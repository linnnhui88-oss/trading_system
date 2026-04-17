# -*- coding: utf-8 -*-
"""
Market data service

作用：
1. 统一获取 Binance 行情数据
2. 给仪表盘页面提供：
   - 可选币种列表
   - 当前价格 / 24h统计
   - K线数据
   - 买1-5 / 卖1-5 深度
3. 先以 REST 为主，保证稳定
4. 后续可以在此基础上再扩展 WebSocket 实时推送

设计原则：
- 不直接耦合 order_executor
- 不直接影响现有交易流程
- 请求失败时尽量返回结构化错误，而不是让系统崩溃
"""

import time
from typing import Any, Dict, List, Optional

import requests


class MarketDataService:
    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        timeout: int = 10,
        cache_ttl_seconds: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds

        # 简单内存缓存，减轻前端频繁刷新时的请求压力
        self._cache: Dict[str, Dict[str, Any]] = {}

        # 和 Binance 常用周期保持一致
        self.supported_intervals = [
            "1m", "3m", "5m", "15m", "30m",
            "1h", "2h", "4h", "6h", "12h",
            "1d", "1w"
        ]

    # =========================
    # 对外公开方法
    # =========================

    def get_supported_intervals(self) -> List[str]:
        return list(self.supported_intervals)

    def get_symbols(self, quote_asset: str = "USDT", only_trading: bool = True) -> Dict[str, Any]:
        """
        获取 Binance 可选交易对
        默认只返回 USDT 交易对，避免过多无关币种
        """
        cache_key = f"symbols:{quote_asset}:{only_trading}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return self._success(cached)

        try:
            data = self._request("GET", "/api/v3/exchangeInfo")
            symbols = []

            for item in data.get("symbols", []):
                symbol = item.get("symbol", "")
                status = item.get("status", "")
                item_quote_asset = item.get("quoteAsset", "")

                if quote_asset and item_quote_asset != quote_asset:
                    continue

                if only_trading and status != "TRADING":
                    continue

                symbols.append({
                    "symbol": symbol,
                    "base_asset": item.get("baseAsset", ""),
                    "quote_asset": item_quote_asset,
                    "status": status,
                })

            symbols.sort(key=lambda x: x["symbol"])
            self._set_cache(cache_key, symbols)

            return self._success(symbols)

        except Exception as e:
            return self._error(f"获取币种列表失败: {str(e)}")

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        获取当前价格 + 24h 数据
        """
        symbol = self._normalize_symbol(symbol)
        cache_key = f"ticker:{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return self._success(cached)

        try:
            ticker_24h = self._request("GET", "/api/v3/ticker/24hr", params={"symbol": symbol})
            price_data = self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol})

            result = {
                "symbol": symbol,
                "price": self._safe_float(price_data.get("price")),
                "price_change": self._safe_float(ticker_24h.get("priceChange")),
                "price_change_percent": self._safe_float(ticker_24h.get("priceChangePercent")),
                "weighted_avg_price": self._safe_float(ticker_24h.get("weightedAvgPrice")),
                "high_24h": self._safe_float(ticker_24h.get("highPrice")),
                "low_24h": self._safe_float(ticker_24h.get("lowPrice")),
                "volume_24h": self._safe_float(ticker_24h.get("volume")),
                "quote_volume_24h": self._safe_float(ticker_24h.get("quoteVolume")),
                "open_price": self._safe_float(ticker_24h.get("openPrice")),
                "prev_close_price": self._safe_float(ticker_24h.get("prevClosePrice")),
                "last_qty": self._safe_float(ticker_24h.get("lastQty")),
                "bid_price": self._safe_float(ticker_24h.get("bidPrice")),
                "bid_qty": self._safe_float(ticker_24h.get("bidQty")),
                "ask_price": self._safe_float(ticker_24h.get("askPrice")),
                "ask_qty": self._safe_float(ticker_24h.get("askQty")),
                "open_time": ticker_24h.get("openTime"),
                "close_time": ticker_24h.get("closeTime"),
            }

            self._set_cache(cache_key, result)
            return self._success(result)

        except Exception as e:
            return self._error(f"获取 ticker 失败: {str(e)}")

    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 200) -> Dict[str, Any]:
        """
        获取 K 线数据
        返回适合前端图表使用的结构
        """
        symbol = self._normalize_symbol(symbol)
        interval = self._normalize_interval(interval)

        limit = int(limit)
        if limit <= 0:
            limit = 200
        if limit > 1000:
            limit = 1000

        cache_key = f"klines:{symbol}:{interval}:{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return self._success(cached)

        try:
            rows = self._request("GET", "/api/v3/klines", params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            })

            klines = []
            for row in rows:
                # Binance K线格式：
                # [
                #   0 open time,
                #   1 open,
                #   2 high,
                #   3 low,
                #   4 close,
                #   5 volume,
                #   6 close time,
                #   7 quote asset volume,
                #   8 number of trades,
                #   9 taker buy base asset volume,
                #   10 taker buy quote asset volume,
                #   11 ignore
                # ]
                klines.append({
                    "open_time": row[0],
                    "open": self._safe_float(row[1]),
                    "high": self._safe_float(row[2]),
                    "low": self._safe_float(row[3]),
                    "close": self._safe_float(row[4]),
                    "volume": self._safe_float(row[5]),
                    "close_time": row[6],
                    "quote_asset_volume": self._safe_float(row[7]),
                    "number_of_trades": int(row[8]) if row[8] is not None else 0,
                    "taker_buy_base_asset_volume": self._safe_float(row[9]),
                    "taker_buy_quote_asset_volume": self._safe_float(row[10]),
                })

            result = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
                "items": klines,
            }

            self._set_cache(cache_key, result)
            return self._success(result)

        except Exception as e:
            return self._error(f"获取 K 线失败: {str(e)}")

    def get_depth(self, symbol: str, limit: int = 5) -> Dict[str, Any]:
        """
        获取买卖盘深度
        你当前需求是买1-5 / 卖1-5，所以默认 limit=5
        """
        symbol = self._normalize_symbol(symbol)

        allowed_limits = [5, 10, 20, 50, 100, 500, 1000, 5000]
        if limit not in allowed_limits:
            limit = 5

        cache_key = f"depth:{symbol}:{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return self._success(cached)

        try:
            data = self._request("GET", "/api/v3/depth", params={
                "symbol": symbol,
                "limit": limit
            })

            bids = []
            asks = []

            for price, qty in data.get("bids", []):
                bids.append({
                    "price": self._safe_float(price),
                    "quantity": self._safe_float(qty),
                })

            for price, qty in data.get("asks", []):
                asks.append({
                    "price": self._safe_float(price),
                    "quantity": self._safe_float(qty),
                })

            result = {
                "symbol": symbol,
                "last_update_id": data.get("lastUpdateId"),
                "bids": bids,
                "asks": asks,
            }

            self._set_cache(cache_key, result)
            return self._success(result)

        except Exception as e:
            return self._error(f"获取买卖盘失败: {str(e)}")

    def get_dashboard_snapshot(
        self,
        symbol: str,
        interval: str = "5m",
        kline_limit: int = 200,
        depth_limit: int = 5,
    ) -> Dict[str, Any]:
        """
        给仪表盘页面用的一站式快照接口
        """
        symbol = self._normalize_symbol(symbol)
        interval = self._normalize_interval(interval)

        ticker_result = self.get_ticker(symbol)
        klines_result = self.get_klines(symbol, interval=interval, limit=kline_limit)
        depth_result = self.get_depth(symbol, limit=depth_limit)

        success = (
            ticker_result.get("success", False)
            and klines_result.get("success", False)
            and depth_result.get("success", False)
        )

        if not success:
            errors = []
            if not ticker_result.get("success", False):
                errors.append(ticker_result.get("message", "ticker error"))
            if not klines_result.get("success", False):
                errors.append(klines_result.get("message", "klines error"))
            if not depth_result.get("success", False):
                errors.append(depth_result.get("message", "depth error"))

            return self._error("；".join(errors))

        return self._success({
            "symbol": symbol,
            "interval": interval,
            "ticker": ticker_result["data"],
            "klines": klines_result["data"],
            "depth": depth_result["data"],
        })

    # =========================
    # 内部工具方法
    # =========================

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        response = requests.request(
            method=method.upper(),
            url=url,
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _normalize_symbol(self, symbol: str) -> str:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise ValueError("symbol 不能为空")
        return symbol

    def _normalize_interval(self, interval: str) -> str:
        interval = (interval or "").strip()
        if interval not in self.supported_intervals:
            return "5m"
        return interval

    def _success(self, data: Any) -> Dict[str, Any]:
        return {
            "success": True,
            "data": data,
            "message": "",
        }

    def _error(self, message: str) -> Dict[str, Any]:
        return {
            "success": False,
            "data": None,
            "message": message,
        }

    def _get_cache(self, key: str) -> Optional[Any]:
        item = self._cache.get(key)
        if not item:
            return None

        if time.time() - item["ts"] > self.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None

        return item["data"]

    def _set_cache(self, key: str, data: Any):
        self._cache[key] = {
            "ts": time.time(),
            "data": data,
        }

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default


if __name__ == "__main__":
    """
    手动测试：
    在项目根目录执行：
    python -m trading_core.market_data_service
    """
    service = MarketDataService()

    print("==== 支持的周期 ====")
    print(service.get_supported_intervals())

    print("\n==== 币种列表（前10个） ====")
    symbols_result = service.get_symbols()
    if symbols_result["success"]:
        print(symbols_result["data"][:10])
    else:
        print(symbols_result)

    print("\n==== BTCUSDT ticker ====")
    print(service.get_ticker("BTCUSDT"))

    print("\n==== BTCUSDT 5m K线 ====")
    klines_result = service.get_klines("BTCUSDT", "5m", 5)
    print(klines_result)

    print("\n==== BTCUSDT 深度 ====")
    print(service.get_depth("BTCUSDT", 5))

    print("\n==== Dashboard Snapshot ====")
    print(service.get_dashboard_snapshot("BTCUSDT", "5m", 20, 5))