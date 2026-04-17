# -*- coding: utf-8 -*-
"""
AI model registry

作用：
1. 统一定义系统支持的 AI 大模型
2. 为设置页、策略页提供标准模型列表
3. 统一每个模型的显示名称、提供商、默认模型名、是否需要 base_url 等元信息

注意：
- 这个文件只做“注册表”，不做任何 API 调用
- 这个文件本身不会影响现有交易逻辑
- 后续 settings 页面、strategy 页面、llm_service 都会依赖这里
"""

from copy import deepcopy


AI_MODELS = {
    "gpt": {
        "provider_key": "gpt",
        "label": "OpenAI GPT",
        "provider_name": "OpenAI",
        "default_model_name": "gpt-4o-mini",
        "supports_custom_base_url": True,
        "requires_api_key": True,
        "description": "OpenAI GPT 系列模型，适合通用分析和结构化输出。",
        "sort_order": 1,
    },
    "gemini": {
        "provider_key": "gemini",
        "label": "Google Gemini",
        "provider_name": "Google",
        "default_model_name": "gemini-1.5-pro",
        "supports_custom_base_url": False,
        "requires_api_key": True,
        "description": "Google Gemini 系列模型，适合文本分析与多模态扩展。",
        "sort_order": 2,
    },
    "claude": {
        "provider_key": "claude",
        "label": "Anthropic Claude",
        "provider_name": "Anthropic",
        "default_model_name": "claude-3-5-sonnet-20241022",
        "supports_custom_base_url": False,
        "requires_api_key": True,
        "description": "Anthropic Claude 系列模型，适合长文本分析与稳健判断。",
        "sort_order": 3,
    },
    "qwen": {
        "provider_key": "qwen",
        "label": "阿里千问",
        "provider_name": "Alibaba Cloud",
        "default_model_name": "qwen-plus",
        "supports_custom_base_url": True,
        "requires_api_key": True,
        "description": "阿里千问系列模型，适合中文场景和通用推理。",
        "sort_order": 4,
    },
    "kimi": {
        "provider_key": "kimi",
        "label": "Kimi",
        "provider_name": "Moonshot AI",
        "default_model_name": "moonshot-v1-8k",
        "supports_custom_base_url": True,
        "requires_api_key": True,
        "description": "Kimi 模型，适合中文长文本理解与分析。",
        "sort_order": 5,
    },
    "deepseek": {
        "provider_key": "deepseek",
        "label": "DeepSeek",
        "provider_name": "DeepSeek",
        "default_model_name": "deepseek-chat",
        "supports_custom_base_url": True,
        "requires_api_key": True,
        "description": "DeepSeek 模型，适合推理和代码分析，也可用于交易信号辅助判断。",
        "sort_order": 6,
    },
}


def get_all_ai_models():
    """
    返回全部 AI 模型定义，按 sort_order 排序
    """
    models = [deepcopy(item) for item in AI_MODELS.values()]
    models.sort(key=lambda x: x.get("sort_order", 999))
    return models


def get_ai_model(provider_key: str):
    """
    根据 provider_key 获取单个模型定义
    """
    if not provider_key:
        return None
    model = AI_MODELS.get(provider_key)
    return deepcopy(model) if model else None


def is_supported_ai_model(provider_key: str) -> bool:
    """
    判断是否是系统支持的模型
    """
    return provider_key in AI_MODELS


def get_ai_model_choices():
    """
    返回适合前端下拉框使用的轻量列表
    """
    choices = []
    for item in get_all_ai_models():
        choices.append({
            "provider_key": item["provider_key"],
            "label": item["label"],
            "provider_name": item["provider_name"],
            "default_model_name": item["default_model_name"],
        })
    return choices


def build_default_provider_config(provider_key: str):
    """
    生成某个模型的默认配置骨架
    后续数据库初始化、设置页新建配置时可直接使用
    """
    model = get_ai_model(provider_key)
    if not model:
        raise ValueError(f"Unsupported AI provider: {provider_key}")

    return {
        "provider_key": model["provider_key"],
        "label": model["label"],
        "provider_name": model["provider_name"],
        "api_key": "",
        "base_url": "",
        "model_name": model["default_model_name"],
        "is_enabled": False,
        "configured": False,
        "selectable": False,
    }