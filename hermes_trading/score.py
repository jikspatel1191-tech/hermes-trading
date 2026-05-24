"""hermes_trading.score — score trades against goal.yaml, returns float in [-1, +1]."""
import numpy as np


def score(trades: list[dict], goal: dict) -> float:
    """
    Composite score in [-1, +1]:
      - realised return vs target
      - max drawdown vs limit
      - Sharpe vs minimum
    """
    closed = [t for t in trades if t.get("closed") and "pnl_pct" in t]
    if not closed:
        return 0.0

    pnls = np.array([t["pnl_pct"] for t in closed])

    # --- Return component ---
    cumulative_return = float(np.prod(1 + pnls) - 1)
    target = goal.get("target_return_30d", 0.09)
    return_score = np.clip(cumulative_return / target, -1.0, 1.0)

    # --- Drawdown component ---
    equity = np.cumprod(1 + pnls)
    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max
    max_dd = float(np.min(drawdowns))  # most negative
    max_dd_limit = goal.get("max_drawdown", 0.06)
    if max_dd_limit == 0:
        dd_score = 0.0
    else:
        dd_score = np.clip(1.0 + (max_dd / max_dd_limit), -1.0, 1.0)

    # --- Sharpe component ---
    min_sharpe = goal.get("min_sharpe", 1.2)
    if len(pnls) < 2 or np.std(pnls) == 0:
        sharpe = 0.0
    else:
        sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(252))
    sharpe_score = np.clip(sharpe / max(min_sharpe, 0.01), -1.0, 1.0)

    # --- Composite (equal weight) ---
    composite = (return_score + dd_score + sharpe_score) / 3.0

    # Floor: steeply negative below failure threshold
    failure_below = goal.get("failure_below", -0.04)
    if cumulative_return < failure_below:
        composite = min(composite, -0.5)

    return float(np.clip(composite, -1.0, 1.0))
