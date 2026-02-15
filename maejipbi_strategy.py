"""Whale accumulation (매집비) strategy demo implementation.

This module is intentionally API-agnostic. It defines a tiny interface-like wrapper
(`KiwoomLikeAPI`) and a strategy class (`MaejipBiStrategy`) that can be wired to
PyKiwoom/KOA wrappers in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Protocol


class KiwoomLikeAPI(Protocol):
    """Minimal protocol required by `MaejipBiStrategy`.

    You can adapt a real Kiwoom OpenAPI wrapper to this protocol.
    """

    def get_total_listed_shares(self, stock_code: str) -> int:
        """Return the total listed shares for a stock code."""

    def get_broker_daily_data(self, stock_code: str, lookback_days: int) -> list[dict]:
        """Return per-day broker/investor trading records.

        Expected dict keys:
        - buy_volume: int
        - sell_volume: int
        - close: float
        """

    def get_daily_closes(self, stock_code: str, lookback_days: int) -> list[float]:
        """Return daily close prices (oldest -> newest)."""


@dataclass
class StrategyMetrics:
    floating_shares: int
    net_buy_volume: int
    maejip_ratio_pct: float
    buy_strength: float
    current_price: float
    ma20: float


class MaejipBiStrategy:
    """Implementation of 매집비(Accumulation Ratio) based signal generation."""

    def __init__(
        self,
        api: KiwoomLikeAPI,
        lookback_days: int = 20,
        target_ratio: float = 5.0,
        buy_strength_threshold: float = 3.0,
    ) -> None:
        self.api = api
        self.lookback_days = lookback_days
        self.target_ratio = target_ratio
        self.buy_strength_threshold = buy_strength_threshold

    def get_major_shareholder_shares(self, stock_code: str, total_shares: int) -> int:
        """Placeholder logic.

        In a real deployment, replace this with a DART/증권사 데이터 결합 로직.
        """
        _ = stock_code
        # Default assumption from the specification: floating = total * 0.6.
        return int(total_shares * 0.4)

    @staticmethod
    def _safe_div(num: float, den: float) -> float:
        if den == 0:
            return 0.0
        return num / den

    @staticmethod
    def _moving_average(values: Iterable[float]) -> float:
        vals = list(values)
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def calculate_metrics(self, stock_code: str) -> StrategyMetrics:
        total_shares = self.api.get_total_listed_shares(stock_code)
        major_holder_shares = self.get_major_shareholder_shares(stock_code, total_shares)
        floating_shares = max(total_shares - major_holder_shares, 1)

        rows = self.api.get_broker_daily_data(stock_code, self.lookback_days)
        total_buy = sum(int(row.get("buy_volume", 0)) for row in rows)
        total_sell = sum(int(row.get("sell_volume", 0)) for row in rows)
        net_buy_volume = total_buy - total_sell

        maejip_ratio_pct = self._safe_div(net_buy_volume, floating_shares) * 100.0
        buy_strength = self._safe_div(total_buy, total_sell)

        closes = self.api.get_daily_closes(stock_code, max(self.lookback_days, 20))
        current_price = closes[-1] if closes else 0.0
        ma20 = self._moving_average(closes[-20:]) if closes else 0.0

        return StrategyMetrics(
            floating_shares=floating_shares,
            net_buy_volume=net_buy_volume,
            maejip_ratio_pct=maejip_ratio_pct,
            buy_strength=buy_strength,
            current_price=current_price,
            ma20=ma20,
        )

    def generate_buy_signal(self, stock_code: str) -> tuple[bool, StrategyMetrics]:
        metrics = self.calculate_metrics(stock_code)
        signal = (
            metrics.maejip_ratio_pct >= self.target_ratio
            and metrics.buy_strength >= self.buy_strength_threshold
            and metrics.current_price > metrics.ma20
        )
        return signal, metrics

    def generate_sell_signal(self, current_price: float, average_entry_price: float) -> bool:
        """Simple stop-loss: sell when price drops below 95% of avg entry."""
        if average_entry_price <= 0:
            return False
        return current_price < average_entry_price * 0.95


class MockKiwoomAPI:
    """Demonstration API wrapper for local testing/examples."""

    def __init__(
        self,
        total_shares: int,
        broker_rows: List[dict],
        closes: List[float],
    ) -> None:
        self._total_shares = total_shares
        self._broker_rows = broker_rows
        self._closes = closes

    def get_total_listed_shares(self, stock_code: str) -> int:
        _ = stock_code
        return self._total_shares

    def get_broker_daily_data(self, stock_code: str, lookback_days: int) -> list[dict]:
        _ = stock_code
        return self._broker_rows[-lookback_days:]

    def get_daily_closes(self, stock_code: str, lookback_days: int) -> list[float]:
        _ = stock_code
        return self._closes[-lookback_days:]


if __name__ == "__main__":
    mock_api = MockKiwoomAPI(
        total_shares=100_000_000,
        broker_rows=[
            {"buy_volume": 3_000_000, "sell_volume": 1_000_000, "close": 10200},
            {"buy_volume": 2_800_000, "sell_volume": 900_000, "close": 10300},
            {"buy_volume": 3_200_000, "sell_volume": 1_000_000, "close": 10450},
            {"buy_volume": 2_900_000, "sell_volume": 1_100_000, "close": 10500},
            {"buy_volume": 3_100_000, "sell_volume": 1_000_000, "close": 10650},
        ],
        closes=[9800, 9850, 9920, 10020, 10100, 10250, 10320, 10410, 10500, 10650,
                10720, 10680, 10750, 10810, 10900, 10980, 11020, 11100, 11200, 11350],
    )

    strategy = MaejipBiStrategy(mock_api, lookback_days=5, target_ratio=5.0)
    buy_signal, metrics = strategy.generate_buy_signal("005930")

    print("BUY SIGNAL:", buy_signal)
    print(metrics)
