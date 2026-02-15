from maejipbi_strategy import MaejipBiStrategy, MockKiwoomAPI


def test_buy_signal_true_when_all_conditions_met():
    api = MockKiwoomAPI(
        total_shares=100_000_000,
        broker_rows=[
            {"buy_volume": 3_000_000, "sell_volume": 1_000_000, "close": 10100},
            {"buy_volume": 3_000_000, "sell_volume": 1_000_000, "close": 10200},
            {"buy_volume": 3_000_000, "sell_volume": 1_000_000, "close": 10300},
            {"buy_volume": 3_000_000, "sell_volume": 1_000_000, "close": 10400},
            {"buy_volume": 3_000_000, "sell_volume": 1_000_000, "close": 10500},
        ],
        closes=list(range(10000, 10020)),
    )
    strategy = MaejipBiStrategy(api, lookback_days=5, target_ratio=5.0)

    signal, metrics = strategy.generate_buy_signal("TEST")

    assert signal is True
    assert metrics.maejip_ratio_pct > 5.0
    assert metrics.buy_strength == 3.0


def test_sell_signal_triggers_on_5pct_drop():
    api = MockKiwoomAPI(total_shares=10, broker_rows=[], closes=[])
    strategy = MaejipBiStrategy(api)
    assert strategy.generate_sell_signal(current_price=94.9, average_entry_price=100.0) is True
    assert strategy.generate_sell_signal(current_price=95.0, average_entry_price=100.0) is False
