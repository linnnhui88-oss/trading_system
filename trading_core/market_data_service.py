# -*- coding: utf-8 -*-
"""Market data service for dashboard market/ticker/kline/depth/liquidation panels."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

import requests


class MarketDataService:
    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        futures_base_url: str = "https://fapi.binance.com",
        timeout: int = 10,
        cache_ttl_seconds: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.futures_base_url = futures_base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.supported_intervals = [
            "1m", "3m", "5m", "15m", "30m",
            "1h", "2h", "4h", "6h", "12h",
            "1d", "1w",
        ]

    def get_supported_intervals(self) -> List[str]:
        return list(self.supported_intervals)

    def get_symbols(self, quote_asset: str = "USDT", only_trading: bool = True) -> Dict[str, Any]:
        cache_key = f"symbols:{quote_asset}:{only_trading}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return self._success(cached)

        try:
            data = self._request("GET", "/api/v3/exchangeInfo")
            rows = []
            for item in data.get("symbols", []):
                status = item.get("status", "")
                item_quote_asset = item.get("quoteAsset", "")
                if quote_asset and item_quote_asset != quote_asset:
                    continue
                if only_trading and status != "TRADING":
                    continue
                rows.append(
                    {
                        "symbol": item.get("symbol", ""),
                        "base_asset": item.get("baseAsset", ""),
                        "quote_asset": item_quote_asset,
                        "status": status,
                    }
                )
            rows.sort(key=lambda x: x["symbol"])
            self._set_cache(cache_key, rows)
            return self._success(rows)
        except Exception as e:
            return self._error(f"failed to get symbols: {e}")

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
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
            return self._error(f"failed to get ticker: {e}")

    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 200) -> Dict[str, Any]:
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
            rows = self._request(
                "GET",
                "/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            klines = []
            for row in rows:
                klines.append(
                    {
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
                    }
                )
            result = {"symbol": symbol, "interval": interval, "limit": limit, "items": klines}
            self._set_cache(cache_key, result)
            return self._success(result)
        except Exception as e:
            return self._error(f"failed to get klines: {e}")

    def get_depth(self, symbol: str, limit: int = 5) -> Dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        allowed_limits = [5, 10, 20, 50, 100, 500, 1000, 5000]
        if limit not in allowed_limits:
            limit = 5

        cache_key = f"depth:{symbol}:{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return self._success(cached)

        try:
            data = self._request("GET", "/api/v3/depth", params={"symbol": symbol, "limit": limit})
            bids = [{"price": self._safe_float(p), "quantity": self._safe_float(q)} for p, q in data.get("bids", [])]
            asks = [{"price": self._safe_float(p), "quantity": self._safe_float(q)} for p, q in data.get("asks", [])]
            result = {
                "symbol": symbol,
                "last_update_id": data.get("lastUpdateId"),
                "bids": bids,
                "asks": asks,
            }
            self._set_cache(cache_key, result)
            return self._success(result)
        except Exception as e:
            return self._error(f"failed to get depth: {e}")

    def get_dashboard_snapshot(
        self,
        symbol: str,
        interval: str = "5m",
        kline_limit: int = 200,
        depth_limit: int = 5,
    ) -> Dict[str, Any]:
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
            return self._error("; ".join(errors))

        return self._success(
            {
                "symbol": symbol,
                "interval": interval,
                "ticker": ticker_result["data"],
                "klines": klines_result["data"],
                "depth": depth_result["data"],
            }
        )
    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        base = self.futures_base_url if path.startswith("/fapi/") else self.base_url
        url = f"{base}{path}"
        response = requests.request(method=method.upper(), url=url, params=params or {}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _fetch_open_interest(self, symbol: str) -> Dict[str, Any]:
        try:
            data = self._request("GET", "/fapi/v1/openInterest", params={"symbol": symbol})
            return {
                "open_interest": self._safe_float(data.get("openInterest")),
                "symbol": data.get("symbol", symbol),
                "time": data.get("time"),
                "success": True,
            }
        except Exception:
            return {"open_interest": 0.0, "symbol": symbol, "time": None, "success": False}

    def _normalize_symbol(self, symbol: str) -> str:
        value = (symbol or "").strip().upper().replace("/", "")
        if not value:
            raise ValueError("symbol must not be empty")
        return value

    def _normalize_interval(self, interval: str) -> str:
        value = (interval or "").strip()
        if value not in self.supported_intervals:
            return "5m"
        return value

    def _success(self, data: Any) -> Dict[str, Any]:
        return {"success": True, "data": data, "message": ""}

    def _error(self, message: str) -> Dict[str, Any]:
        return {"success": False, "data": None, "message": message}

    def _get_cache(self, key: str) -> Optional[Any]:
        item = self._cache.get(key)
        if not item:
            return None
        if time.time() - item["ts"] > self.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        return item["data"]

    def _set_cache(self, key: str, data: Any):
        self._cache[key] = {"ts": time.time(), "data": data}

    @staticmethod
    def _calc_volatility(klines: List[Dict[str, Any]]) -> float:
        if not klines or len(klines) < 3:
            return 0.003
        returns = []
        prev_close = None
        for row in klines:
            close_px = MarketDataService._safe_float(row.get("close"))
            if prev_close and prev_close > 0 and close_px > 0:
                returns.append((close_px - prev_close) / prev_close)
            prev_close = close_px
        if not returns:
            return 0.003
        mean = sum(returns) / len(returns)
        var = sum((x - mean) ** 2 for x in returns) / max(1, len(returns) - 1)
        return max(0.0015, min(0.05, math.sqrt(max(var, 0.0))))

    @staticmethod
    def _calc_long_short_bias(klines: List[Dict[str, Any]]) -> float:
        if not klines:
            return 0.0
        down = 0.0
        up = 0.0
        for row in klines[-48:]:
            o = MarketDataService._safe_float(row.get("open"))
            c = MarketDataService._safe_float(row.get("close"))
            if o <= 0:
                continue
            if c < o:
                down += (o - c) / o
            elif c > o:
                up += (c - o) / o
        total = up + down
        if total <= 1e-9:
            return 0.0
        return max(-0.35, min(0.35, (down - up) / total))

    @staticmethod
    def _build_cumulative_curve(points: List[Dict[str, Any]], current_price: float) -> List[Dict[str, Any]]:
        below = [p for p in points if p.get("price", 0.0) <= current_price]
        above = [p for p in points if p.get("price", 0.0) >= current_price]
        below = sorted(below, key=lambda x: x.get("price", 0.0), reverse=True)
        above = sorted(above, key=lambda x: x.get("price", 0.0))

        long_acc = 0.0
        short_acc = 0.0
        curve: List[Dict[str, Any]] = []
        for row in below:
            long_acc += MarketDataService._safe_float(row.get("long_value"))
            curve.append({"price": row.get("price"), "cum_long": round(long_acc, 2), "cum_short": 0.0})
        for row in above:
            short_acc += MarketDataService._safe_float(row.get("short_value"))
            curve.append({"price": row.get("price"), "cum_long": 0.0, "cum_short": round(short_acc, 2)})
        return sorted(curve, key=lambda x: x.get("price", 0.0))

    @staticmethod
    def _find_largest_shock(klines: List[Dict[str, Any]]) -> tuple[int, float]:
        largest_idx = -1
        largest_score = 0.0
        for idx, row in enumerate(klines):
            o = MarketDataService._safe_float(row.get("open"))
            c = MarketDataService._safe_float(row.get("close"))
            qv = MarketDataService._safe_float(row.get("quote_asset_volume"))
            if o <= 0 or qv <= 0:
                continue
            move = abs(c - o) / o
            score = move * math.log10(qv + 10.0)
            if score > largest_score:
                largest_score = score
                largest_idx = idx
        return largest_idx, largest_score

    @staticmethod
    def _format_usd(value: float) -> str:
        v = abs(float(value or 0.0))
        if v >= 1e9:
            return f"${value / 1e9:.2f}B"
        if v >= 1e6:
            return f"${value / 1e6:.2f}M"
        if v >= 1e3:
            return f"${value / 1e3:.2f}K"
        return f"${value:.2f}"

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default


if __name__ == "__main__":
    service = MarketDataService()
    print(service.get_dashboard_snapshot("BTCUSDT", "5m", 20, 5))
