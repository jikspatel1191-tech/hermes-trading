"""hermes_trading.reflect — reflection cycle.

Two modes:
  --fallback   deterministic rule-based (Phase 5, before Hermes)
  --hermes     production mode: calls `hermes` subprocess with a prompt
"""
import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hermes_trading.score import score

STATE_DIR = Path(__file__).parent.parent / "state"
STRATEGY_FILE = STATE_DIR / "strategy.yaml"
TRADES_FILE = STATE_DIR / "trades.jsonl"
HYPOTHESES_FILE = STATE_DIR / "hypotheses.jsonl"
HISTORY_DIR = STATE_DIR / "history"
GOAL_FILE = STATE_DIR / "goal.yaml"

HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def save_yaml(path: Path, data: dict):
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_trades() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    trades = []
    with open(TRADES_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades


def bump_version(current: str) -> str:
    try:
        n = int(current.lstrip("v").lstrip("0") or "0")
    except ValueError:
        n = 1
    return f"{n+1:02d}"


def save_history(strategy: dict):
    version = strategy.get("version", "01")
    dest = HISTORY_DIR / f"v{version}.yaml"
    save_yaml(dest, strategy)


def append_hypothesis(hypothesis: dict):
    with open(HYPOTHESES_FILE, "a") as f:
        f.write(json.dumps(hypothesis) + "\n")


def reflect_fallback():
    strategy = load_yaml(STRATEGY_FILE)
    goal = load_yaml(GOAL_FILE)
    trades = load_trades()
    closed = [t for t in trades if t.get("closed")]

    current_score = score(closed, goal)
    target = goal.get("target_return_30d", 0.09)
    max_dd = goal.get("max_drawdown", 0.06)

    # Compute actuals
    import numpy as np
    pnls = np.array([t["pnl_pct"] for t in closed]) if closed else np.array([0.0])
    cumulative_return = float(np.prod(1 + pnls) - 1)

    equity = np.cumprod(1 + pnls)
    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max
    actual_dd = float(np.min(drawdowns))

    # Determine ONE variable to change
    variable_changed = None
    old_value = None
    new_value = None
    reasoning = None

    if cumulative_return < target:
        # Loosen entry threshold by 2 to get more trades
        old_val = float(strategy["entry"]["threshold"])
        new_val = old_val + 2
        strategy["entry"]["threshold"] = new_val
        variable_changed = "entry.threshold"
        old_value = old_val
        new_value = new_val
        reasoning = (
            f"Realised return {cumulative_return*100:.2f}% < target {target*100:.2f}%. "
            f"Loosening entry threshold {old_val} → {new_val} to capture more trades."
        )
    elif abs(actual_dd) > max_dd:
        # Tighten stop loss by 0.2
        old_val = float(strategy.get("stop_loss_pct", 2.0))
        new_val = max(0.2, old_val - 0.2)
        strategy["stop_loss_pct"] = new_val
        variable_changed = "stop_loss_pct"
        old_value = old_val
        new_value = new_val
        reasoning = (
            f"Drawdown {abs(actual_dd)*100:.2f}% > max {max_dd*100:.2f}%. "
            f"Tightening stop_loss_pct {old_val} → {new_val}."
        )
    else:
        # Score is acceptable — small nudge to threshold to keep improving
        old_val = float(strategy["entry"]["threshold"])
        new_val = max(20, old_val - 1)
        strategy["entry"]["threshold"] = new_val
        variable_changed = "entry.threshold"
        old_value = old_val
        new_value = new_val
        reasoning = (
            f"Score {current_score:.3f} acceptable. "
            f"Tightening entry threshold {old_val} → {new_val} for higher-quality entries."
        )

    # Bump version and save history
    old_version = strategy["version"]
    new_version = bump_version(old_version)
    save_history({**strategy, "version": old_version})
    strategy["version"] = new_version
    save_yaml(STRATEGY_FILE, strategy)

    hypothesis = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "fallback",
        "version_from": old_version,
        "version_to": new_version,
        "score_before": current_score,
        "variable_changed": variable_changed,
        "old_value": old_value,
        "new_value": new_value,
        "reasoning": reasoning,
        "one_variable_only": True,
    }
    append_hypothesis(hypothesis)

    print(f"✓ Reflection complete (fallback mode)")
    print(f"  Strategy: v{old_version} → v{new_version}")
    print(f"  Changed : {variable_changed}  {old_value} → {new_value}")
    print(f"  Reason  : {reasoning}")
    print(f"  Score   : {current_score:.3f}")


def reflect_hermes():
    strategy = load_yaml(STRATEGY_FILE)
    goal = load_yaml(GOAL_FILE)
    trades = load_trades()
    closed = [t for t in trades if t.get("closed")]
    last_25 = closed[-25:] if len(closed) >= 25 else closed

    current_score = score(closed, goal)

    prompt = f"""You are the reflection engine for a self-improving trading agent.

Current strategy (YAML):
{yaml.dump(strategy, default_flow_style=False)}

Goal:
{yaml.dump(goal, default_flow_style=False)}

Last {len(last_25)} closed trades (JSONL):
{chr(10).join(json.dumps(t) for t in last_25)}

Current score: {current_score:.3f} (range -1 to +1, target > 0)

Your task:
1. Analyse the trades and score.
2. Propose exactly ONE variable in strategy.yaml to change and explain why.
3. Output ONLY valid JSON in this exact format:
{{
  "variable_changed": "entry.threshold",
  "old_value": 30,
  "new_value": 28,
  "reasoning": "RSI entries at 30 are too infrequent given current volatility regime.",
  "confidence": 0.75
}}

Do NOT change more than one variable. Do NOT output anything except the JSON object.
"""

    try:
        result = subprocess.run(
            ["hermes"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()
        # Strip markdown fences if present
        if output.startswith("```"):
            output = "\n".join(output.split("\n")[1:])
        if output.endswith("```"):
            output = "\n".join(output.split("\n")[:-1])
        parsed = json.loads(output.strip())
    except Exception as e:
        print(f"[hermes mode] Hermes call failed: {e}. Falling back to deterministic.")
        return reflect_fallback()

    # Apply the change
    var = parsed["variable_changed"]
    new_val = parsed["new_value"]
    old_val = parsed["old_value"]

    if "." in var:
        parts = var.split(".", 1)
        strategy[parts[0]][parts[1]] = new_val
    else:
        strategy[var] = new_val

    old_version = strategy["version"]
    new_version = bump_version(old_version)
    save_history({**strategy, "version": old_version})
    strategy["version"] = new_version
    save_yaml(STRATEGY_FILE, strategy)

    hypothesis = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "hermes",
        "version_from": old_version,
        "version_to": new_version,
        "score_before": current_score,
        "variable_changed": var,
        "old_value": old_val,
        "new_value": new_val,
        "reasoning": parsed.get("reasoning", ""),
        "confidence": parsed.get("confidence", None),
        "one_variable_only": True,
    }
    append_hypothesis(hypothesis)

    print(f"✓ Reflection complete (hermes mode)")
    print(f"  Strategy: v{old_version} → v{new_version}")
    print(f"  Changed : {var}  {old_val} → {new_val}")
    print(f"  Reason  : {parsed.get('reasoning', '')}")
    print(f"  Score   : {current_score:.3f}")


def main():
    parser = argparse.ArgumentParser(description="Hermes Trading — Reflection Cycle")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fallback", action="store_true", help="Deterministic fallback mode")
    group.add_argument("--hermes", action="store_true", help="Hermes-powered reflection mode")
    args = parser.parse_args()

    if args.fallback:
        reflect_fallback()
    else:
        reflect_hermes()


if __name__ == "__main__":
    main()
