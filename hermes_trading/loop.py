"""hermes_trading.loop — 24/7 async reliability loop."""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from rich.console import Console

from hermes_trading.score import score
from hermes_trading.adapters.price import fetch as fetch_price

console = Console()

STATE_DIR = Path(__file__).parent.parent / "state"
TRADES_FILE = STATE_DIR / "trades.jsonl"
STRATEGY_FILE = STATE_DIR / "strategy.yaml"
HEARTBEAT_FILE = STATE_DIR / "heartbeat.json"
GOAL_FILE = STATE_DIR / "goal.yaml"

MAX_CONSECUTIVE_FAILURES = 5
RETRY_ATTEMPTS = 3
LOOP_INTERVAL_SECONDS = 60


def load_strategy() -> dict:
    with open(STRATEGY_FILE) as f:
        return yaml.safe_load(f)


def load_goal() -> dict:
    with open(GOAL_FILE) as f:
        return yaml.safe_load(f)


def write_heartbeat(status: str, extra: dict = None):
    data = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": status,
        **(extra or {}),
    }
    HEARTBEAT_FILE.write_text(json.dumps(data))


def append_trade(trade: dict):
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(trade) + "\n")


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


async def fetch_with_retry(fetch_fn, retries=RETRY_ATTEMPTS) -> dict:
    delay = 2
    last_exc = None
    for attempt in range(retries):
        try:
            return await fetch_fn()
        except Exception as e:
            last_exc = e
            console.print(f"[yellow]Adapter retry {attempt+1}/{retries}: {e}[/yellow]")
            await asyncio.sleep(delay)
            delay *= 2
    raise last_exc


def compute_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    import numpy as np
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def evaluate_entry(strategy: dict, market_data: dict) -> bool:
    entry = strategy.get("entry", {})
    indicator = entry.get("indicator", "rsi")
    threshold = float(entry.get("threshold", 30))
    direction = entry.get("direction", "long")

    if indicator == "rsi":
        rsi_val = market_data.get("rsi", 50.0)
        if direction == "long":
            return rsi_val < threshold
        else:
            return rsi_val > threshold
    return False


async def run_loop(asset: str, goal: dict, mode: str):
    consecutive_failures = 0
    open_trade = None

    console.print(f"[cyan]Loop started. Polling every {LOOP_INTERVAL_SECONDS}s.[/cyan]")

    while True:
        try:
            strategy = load_strategy()

            # Fetch price data
            price_data = await fetch_with_retry(lambda: fetch_price(asset))
            current_price = price_data["price"]
            prices_history = price_data.get("prices_history", [current_price])
            rsi_val = compute_rsi(prices_history)

            market_data = {
                "price": current_price,
                "rsi": rsi_val,
                "asset": asset,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

            console.print(
                f"[dim]{market_data['ts']}[/dim]  "
                f"[bold]{asset}[/bold] ${current_price:,.2f}  "
                f"RSI={rsi_val:.1f}"
            )

            # Manage open trade
            if open_trade is not None:
                entry_price = open_trade["entry_price"]
                stop_loss_pct = float(strategy.get("stop_loss_pct", 2.0)) / 100
                direction = open_trade["direction"]

                if direction == "long":
                    pnl_pct = (current_price - entry_price) / entry_price
                    hit_stop = pnl_pct <= -stop_loss_pct
                else:
                    pnl_pct = (entry_price - current_price) / entry_price
                    hit_stop = pnl_pct <= -stop_loss_pct

                # Close after 5 minutes (5 loops) or stop loss
                open_trade["bars_open"] = open_trade.get("bars_open", 0) + 1
                should_close = hit_stop or open_trade["bars_open"] >= 5

                if should_close:
                    closed_trade = {
                        **open_trade,
                        "exit_price": current_price,
                        "exit_ts": market_data["ts"],
                        "pnl_pct": pnl_pct,
                        "closed": True,
                        "stop_hit": hit_stop,
                        "strategy_version": strategy.get("version", "01"),
                    }
                    append_trade(closed_trade)
                    console.print(
                        f"[{'green' if pnl_pct > 0 else 'red'}]"
                        f"CLOSED {direction.upper()} @ ${current_price:,.2f}  "
                        f"PnL={pnl_pct*100:+.2f}%[/]"
                    )
                    open_trade = None

                    # Check reflection trigger
                    trades = load_trades()
                    closed = [t for t in trades if t.get("closed")]
                    if len(closed) % goal.get("reflection_every", 5) == 0 and len(closed) > 0:
                        console.print(f"[bold yellow]Reflection trigger: {len(closed)} closed trades.[/bold yellow]")

            # Check entry
            if open_trade is None and mode == "paper":
                if evaluate_entry(strategy, market_data):
                    size = float(strategy.get("position_size_r", 0.5))
                    open_trade = {
                        "asset": asset,
                        "entry_price": current_price,
                        "entry_ts": market_data["ts"],
                        "direction": strategy["entry"].get("direction", "long"),
                        "size_r": size,
                        "closed": False,
                        "bars_open": 0,
                        "strategy_version": strategy.get("version", "01"),
                    }
                    console.print(
                        f"[bold green]OPEN {open_trade['direction'].upper()} "
                        f"@ ${current_price:,.2f}  size={size}R[/bold green]"
                    )

            write_heartbeat("ok", {"price": current_price, "rsi": rsi_val, "open_trade": open_trade is not None})
            consecutive_failures = 0

        except Exception as e:
            consecutive_failures += 1
            console.print(f"[bold red]Loop error ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}[/bold red]")
            write_heartbeat("error", {"error": str(e), "consecutive_failures": consecutive_failures})

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                console.print("[bold red]Circuit breaker tripped — too many consecutive failures. Exiting.[/bold red]")
                raise SystemExit(1)

        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
