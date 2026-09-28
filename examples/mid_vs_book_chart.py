"""Draw docs/mid-vs-book.png: the same strategy backtested with mid-price fills and on the real book."""
import json
from pathlib import Path

import matplotlib.pyplot as plt

from polymarket_backtester import Backtester, RuleStrategy, load_sample

HERE = Path(__file__).parent
spec = json.loads((HERE.parent / "src" / "polymarket_backtester" / "specs" / "late_favorite.json").read_text())
data = load_sample()


def cumulative_return(results):
    invested = pnl = 0.0
    xs, ys = [], []
    for i, m in enumerate(sorted(results.markets, key=lambda r: r.market.end_ts), 1):
        invested += sum(f.notional for f in m.fills if f.action == "BUY")
        pnl += m.pnl
        xs.append(i)
        ys.append(100 * pnl / invested if invested else 0.0)
    return xs, ys


fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
for model, style in (("mid", "--"), ("book", "-")):
    res = Backtester(data, RuleStrategy(spec), fill_model=model).run()
    xs, ys = cumulative_return(res)
    label = "Filled at the mid price (what most backtests do)" if model == "mid" else "Filled by walking the real order book"
    ax.plot(xs, ys, style, linewidth=2.2, label=f"{label}: {ys[-1]:+.1f}%")
ax.set_title(f"Same strategy, same fees and 250 ms latency, two fill models\n{spec['name']} · {len(data.markets())} BTC 15-minute Polymarket markets", fontsize=10)
ax.xaxis.get_major_locator().set_params(integer=True)
ax.set_xlabel("Markets")
ax.set_ylabel("Cumulative return on money invested (%)")
ax.grid(alpha=0.3)
ax.legend(fontsize=8, loc="lower right")
fig.tight_layout()
out = HERE.parent / "docs" / "mid-vs-book.png"
fig.savefig(out)
print("wrote", out)
