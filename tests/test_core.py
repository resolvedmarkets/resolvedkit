import pytest

from polymarket_backtester import DOWN, UP, Backtester, Book, Level, Market, RuleStrategy, Strategy, taker_fee
from polymarket_backtester.fills import walk_buy, walk_sell

ASKS = (Level(0.50, 100), Level(0.52, 100), Level(0.60, 1000))
BIDS = (Level(0.48, 50), Level(0.45, 100))


def test_walk_buy_spends_across_levels():
    w = walk_buy(ASKS, usd=80)
    # 100 @ 0.50 = $50, then $30 / 0.52 = 57.69 shares
    assert w.legs[0] == Level(0.50, 100)
    assert w.cost == pytest.approx(80)
    assert w.shares == pytest.approx(100 + 30 / 0.52)
    assert w.avg_price == pytest.approx(80 / (100 + 30 / 0.52))
    assert not w.depth_limited


def test_walk_buy_respects_price_limit_and_flags_it():
    w = walk_buy(ASKS, usd=500, max_price=0.52)
    assert w.shares == pytest.approx(200)
    assert w.depth_limited


def test_walk_buy_empty_book():
    w = walk_buy((), usd=10)
    assert w.shares == 0 and w.depth_limited


def test_walk_sell_partial_when_book_is_thin():
    w = walk_sell(BIDS, shares=500)
    assert w.shares == pytest.approx(150)
    assert w.depth_limited


def test_fee_matches_polymarket_crypto_table():
    # docs.polymarket.com/trading/fees: 100 shares at $0.50 on crypto = $1.75, at $0.10 = $0.63
    assert taker_fee(100, 0.50, 0.07) == pytest.approx(1.75)
    assert round(taker_fee(100, 0.10, 0.07), 2) == 0.63


def test_fee_is_charged_per_level():
    w = walk_buy(ASKS, usd=80)
    expected = 100 * 0.07 * 0.5 * 0.5 + (30 / 0.52) * 0.07 * 0.52 * 0.48
    assert w.fee(0.07) == pytest.approx(expected, abs=1e-5)


def book(ts, side, bid, ask, size=1000):
    return Book(ts, side, (Level(bid, size),) if bid else (), (Level(ask, size),) if ask else ())


class ListSource:
    def __init__(self, market, books):
        self.m, self.b = market, books

    def markets(self):
        return [self.m]

    def books(self, market_id):
        return self.b


MARKET = Market("0xabc", "BTC up?", "crypto", end_ts=10_000, payout=(1.0, 0.0))


class BuyUpOnce(Strategy):
    def on_book(self, ctx, b):
        if not ctx.state.get("done"):
            ctx.buy(UP, 100)
            ctx.state["done"] = True


def test_latency_fills_on_a_later_book_and_settles_at_payout():
    books = [book(0, UP, 0.49, 0.50), book(100, UP, 0.59, 0.60), book(300, UP, 0.69, 0.70)]
    res = Backtester(ListSource(MARKET, books), BuyUpOnce(), latency_ms=250).run()
    fill = res.markets[0].fills[0]
    assert fill.ts == 300 and fill.avg_price == pytest.approx(0.70)  # first book >= 0 + 250 ms
    shares = 100 / 0.70
    assert res.markets[0].settlement == pytest.approx(shares * 1.0)
    assert res.pnl == pytest.approx(shares - 100 - taker_fee(shares, 0.70, 0.07), abs=1e-4)


def test_placeholder_book_is_rejected():
    books = [book(0, UP, 0.01, 0.99), book(500, UP, 0.01, 0.99)]
    res = Backtester(ListSource(MARKET, books), BuyUpOnce(), latency_ms=100).run()
    assert not res.markets[0].fills
    assert res.rejections == {"placeholder_book": 1}


def test_mid_fill_model_is_better_than_book():
    books = [book(0, UP, 0.40, 0.50), book(1000, UP, 0.40, 0.50)]
    mid = Backtester(ListSource(MARKET, books), BuyUpOnce(), latency_ms=0, fill_model="mid").run()
    real = Backtester(ListSource(MARKET, books), BuyUpOnce(), latency_ms=0).run()
    assert mid.markets[0].fills[0].avg_price == pytest.approx(0.45)
    assert real.markets[0].fills[0].avg_price == pytest.approx(0.50)
    assert mid.pnl > real.pnl


def test_rule_strategy_enters_favorite_and_takes_profit():
    spec = {"entry": {"side": "favorite", "seconds_before_end": 5, "min_price": 0.5, "max_price": 0.9, "usd": 50},
            "exit": {"take_profit": 0.05}}
    books = [
        book(1_000, UP, 0.60, 0.61), book(1_000, DOWN, 0.38, 0.39),  # 9 s left: too early
        book(6_000, UP, 0.60, 0.61), book(6_000, DOWN, 0.38, 0.39),  # 4 s left: enter UP
        book(6_500, UP, 0.60, 0.61),                                  # fill at 0.61
        book(7_000, UP, 0.70, 0.71),                                  # bid 0.70 >= 0.66: sell
        book(7_500, UP, 0.70, 0.71),                                  # sell fills
    ]
    res = Backtester(ListSource(MARKET, books), RuleStrategy(spec), latency_ms=250).run()
    fills = res.markets[0].fills
    assert [f.action for f in fills] == ["BUY", "SELL"]
    assert fills[0].avg_price == pytest.approx(0.61) and fills[1].avg_price == pytest.approx(0.70)
    assert res.markets[0].settlement == pytest.approx(0)


def test_rule_spec_validation():
    with pytest.raises(ValueError):
        RuleStrategy({"entry": {"side": "yes", "seconds_before_end": 10, "usd": 1}})
