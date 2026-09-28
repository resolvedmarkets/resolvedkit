"""A strategy in Python: buy UP when its book shows 3x more bid depth than ask depth."""
from polymarket_backtester import UP, Backtester, Strategy, load_sample


class DepthImbalance(Strategy):
    def on_book(self, ctx, book):
        if book.side != UP or ctx.state.get("entered") or not book.two_sided:
            return
        bid_depth = sum(l.size * l.price for l in book.bids[:5])
        ask_depth = sum(l.size * l.price for l in book.asks[:5])
        if 60 < ctx.seconds_to_end < 600 and bid_depth > 3 * ask_depth:
            ctx.buy(UP, usd=100, max_price=book.best_ask + 0.02)
            ctx.state["entered"] = True


results = Backtester(load_sample(), DepthImbalance(), latency_ms=250).run()
for k, v in results.summary().items():
    print(f"{k:<22} {v}")
