# -*- coding: utf-8 -*-
"""
LLM service

作用：
1. 统一管理不同 AI 大模型的调用入口
2. 根据 provider_key 自动读取数据库配置
3. 对上层暴露统一 analyze_trade(...) 方法
4. 在未安装对应 SDK 或接口异常时，返回结构化失败结果，而不是让系统崩溃

当前设计原则：
- 先保证系统稳定，不强依赖所有 SDK 都必须安装
- 如果某个模型 SDK 未安装，返回明确错误信息
- 如果模型未配置 / 未启用，也返回结构化结果
- 后续 strategy_engine_adapter 可以安全接入本文件

支持的 provider_key：
- gpt
- gemini
- claude
- qwen
- kimi
- deepseek
"""

import json
from typing import Any, Dict, Optional

from trading_core.ai_provider_config_manager import AIProviderConfigManager
from trading_core.ai_model_registry import is_supported_ai_model


class BaseLLMClient:
    def __init__(self, provider_config: Dict[str, Any]):
        self.provider_config = provider_config

    def analyze_trade(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses must implement analyze_trade")


class OpenAICompatibleClient(BaseLLMClient):
    """
    兼容 OpenAI 风格接口的客户端
    可用于：
    - OpenAI GPT
    - 部分兼容 OpenAI API 的第三方服务（如某些 DeepSeek / Qwen / Kimi 接入方式）
    """

    def analyze_trade(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        api_key = self.provider_config.get("api_key", "").strip()
        base_url = self.provider_config.get("base_url", "").strip()
        model_name = self.provider_config.get("model_name", "").strip()

        if not api_key:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message="API Key 未配置"
            )

        try:
            from openai import OpenAI
        except Exception:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message="未安装 openai SDK，请先安装：pip install openai"
            )

        try:
            if base_url:
                client = OpenAI(api_key=api_key, base_url=base_url)
            else:
                client = OpenAI(api_key=api_key)

            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )

            content = completion.choices[0].message.content if completion.choices else ""
            return parse_model_response(
                provider_key=self.provider_config.get("provider_key", ""),
                raw_content=content
            )

        except Exception as e:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message=f"模型调用失败: {str(e)}"
            )


class GeminiClient(BaseLLMClient):
    def analyze_trade(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        api_key = self.provider_config.get("api_key", "").strip()
        model_name = self.provider_config.get("model_name", "").strip()

        if not api_key:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message="API Key 未配置"
            )

        try:
            import google.generativeai as genai
        except Exception:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message="未安装 google-generativeai SDK，请先安装：pip install google-generativeai"
            )

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name=model_name)

            prompt = f"{system_prompt}\n\n{user_prompt}"
            response = model.generate_content(prompt)
            content = getattr(response, "text", "") or ""

            return parse_model_response(
                provider_key=self.provider_config.get("provider_key", ""),
                raw_content=content
            )

        except Exception as e:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message=f"模型调用失败: {str(e)}"
            )


class ClaudeClient(BaseLLMClient):
    def analyze_trade(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        api_key = self.provider_config.get("api_key", "").strip()
        model_name = self.provider_config.get("model_name", "").strip()

        if not api_key:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message="API Key 未配置"
            )

        try:
            import anthropic
        except Exception:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message="未安装 anthropic SDK，请先安装：pip install anthropic"
            )

        try:
            client = anthropic.Anthropic(api_key=api_key)

            message = client.messages.create(
                model=model_name,
                max_tokens=1000,
                temperature=0.2,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
            )

            content = ""
            if getattr(message, "content", None):
                parts = []
                for item in message.content:
                    text_val = getattr(item, "text", "")
                    if text_val:
                        parts.append(text_val)
                content = "\n".join(parts)

            return parse_model_response(
                provider_key=self.provider_config.get("provider_key", ""),
                raw_content=content
            )

        except Exception as e:
            return build_error_result(
                provider_key=self.provider_config.get("provider_key", ""),
                message=f"模型调用失败: {str(e)}"
            )


def build_trade_decision_prompts(signal_payload: Dict[str, Any]) -> Dict[str, str]:
    """
    给不同模型统一生成提示词
    要求模型必须返回 JSON
    """
    system_prompt = """
你是一个加密货币量化交易风控分析助手。
你的任务不是解释市场，而是根据输入的策略信号与行情摘要，输出严格 JSON 决策。

你必须只返回 JSON，不要返回 markdown，不要返回解释，不要返回代码块。
JSON 格式必须为：
{
  "decision": "EXECUTE" | "SKIP" | "REDUCE",
  "confidence": 0.0,
  "risk_level": "low" | "medium" | "high",
  "reason": "简洁说明"
}

规则：
1. confidence 必须是 0 到 1 之间的小数
2. 如果信号不明确、波动异常、风险过高，优先输出 SKIP
3. 如果可以执行但建议降低仓位，输出 REDUCE
4. 不要输出任何额外字段
""".strip()

    user_prompt = (
        "请根据以下交易信号和上下文做决策：\n"
        f"{json.dumps(signal_payload, ensure_ascii=False, indent=2)}"
    )

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt
    }


def parse_model_response(provider_key: str, raw_content: str) -> Dict[str, Any]:
    """
    尝试把模型输出解析为标准结构
    如果模型没有严格按 JSON 返回，则尽量降级处理
    """
    raw_content = (raw_content or "").strip()

    if not raw_content:
        return build_error_result(provider_key, "模型返回为空")

    # 优先直接解析 JSON
    try:
        parsed = json.loads(raw_content)
        return normalize_decision_result(provider_key, parsed, raw_content)
    except Exception:
        pass

    # 尝试提取 markdown 代码块内的 JSON
    cleaned = raw_content.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(cleaned)
        return normalize_decision_result(provider_key, parsed, raw_content)
    except Exception:
        pass

    # 降级为失败结果
    return build_error_result(
        provider_key=provider_key,
        message=f"模型返回格式无法解析为 JSON: {raw_content[:300]}"
    )


def normalize_decision_result(provider_key: str, parsed: Dict[str, Any], raw_content: str) -> Dict[str, Any]:
    decision = str(parsed.get("decision", "SKIP")).strip().upper()
    if decision not in {"EXECUTE", "SKIP", "REDUCE"}:
        decision = "SKIP"

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except Exception:
        confidence = 0.0

    if confidence < 0:
        confidence = 0.0
    if confidence > 1:
        confidence = 1.0

    risk_level = str(parsed.get("risk_level", "medium")).strip().lower()
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "medium"

    reason = str(parsed.get("reason", "")).strip()
    if not reason:
        reason = "模型未提供原因"

    return {
        "success": True,
        "provider_key": provider_key,
        "decision": decision,
        "confidence": confidence,
        "risk_level": risk_level,
        "reason": reason,
        "raw_content": raw_content,
        "error": None,
    }


def build_error_result(provider_key: str, message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "provider_key": provider_key,
        "decision": "SKIP",
        "confidence": 0.0,
        "risk_level": "high",
        "reason": message,
        "raw_content": "",
        "error": message,
    }


class LLMService:
    def __init__(self, db_path: str = "trading_system.db"):
        self.config_manager = AIProviderConfigManager(db_path=db_path)

    def get_provider_config(self, provider_key: str) -> Optional[Dict[str, Any]]:
        return self.config_manager.get_provider_config(provider_key)

    def is_provider_selectable(self, provider_key: str) -> bool:
        config = self.get_provider_config(provider_key)
        return bool(config and config.get("selectable"))

    def create_client(self, provider_key: str) -> BaseLLMClient:
        if not is_supported_ai_model(provider_key):
            raise ValueError(f"Unsupported AI provider: {provider_key}")

        provider_config = self.get_provider_config(provider_key)
        if not provider_config:
            raise ValueError(f"Provider config not found: {provider_key}")

        if not provider_config.get("configured"):
            raise ValueError(f"Provider API key not configured: {provider_key}")

        if not provider_config.get("is_enabled"):
            raise ValueError(f"Provider is disabled: {provider_key}")

        if provider_key in {"gpt", "qwen", "kimi", "deepseek"}:
            return OpenAICompatibleClient(provider_config)

        if provider_key == "gemini":
            return GeminiClient(provider_config)

        if provider_key == "claude":
            return ClaudeClient(provider_config)

        raise ValueError(f"No client implementation for provider: {provider_key}")

    def analyze_trade(self, provider_key: str, signal_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        对上层暴露的统一交易分析方法
        """
        if not provider_key:
            return build_error_result(provider_key="", message="未指定 AI 模型")

        if not is_supported_ai_model(provider_key):
            return build_error_result(provider_key=provider_key, message="不支持的 AI 模型")

        provider_config = self.get_provider_config(provider_key)
        if not provider_config:
            return build_error_result(provider_key=provider_key, message="未找到模型配置")

        if not provider_config.get("configured"):
            return build_error_result(provider_key=provider_key, message="模型 API Key 未配置")

        if not provider_config.get("is_enabled"):
            return build_error_result(provider_key=provider_key, message="模型已禁用")

        prompts = build_trade_decision_prompts(signal_payload)

        try:
            client = self.create_client(provider_key)
            return client.analyze_trade(
                system_prompt=prompts["system_prompt"],
                user_prompt=prompts["user_prompt"]
            )
        except Exception as e:
            return build_error_result(
                provider_key=provider_key,
                message=f"创建模型客户端失败: {str(e)}"
            )


if __name__ == "__main__":
    """
    手动测试：
    在项目根目录执行：
    python -m trading_core.llm_service
    """
    service = LLMService()

    demo_signal = {
        "symbol": "BTCUSDT",
        "interval": "5m",
        "signal": "BUY",
        "strategy_name": "MA99_MTF",
        "price": 68234.5,
        "indicators": {
            "ma99": 67900.0,
            "volume_ratio": 1.8,
            "rsi": 61.2
        },
        "risk_context": {
            "global_auto_trading": False,
            "max_daily_loss_pct": 5
        }
    }

    print("===== 可用模型状态 =====")
    for item in service.config_manager.list_models_with_status():
        print(item)

    print("\n===== 示例分析（需要先在数据库配置有效 API）=====")
    result = service.analyze_trade("gpt", demo_signal)
    print(json.dumps(result, ensure_ascii=False, indent=2))