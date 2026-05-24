"""hermes_trading.run — entrypoint."""
import argparse
import asyncio
import os
from pathlib import Path

import yaml
from rich.console import Console

console = Console()

STATE_DIR = Path(__file__).parent.parent / "state"
GOAL_FILE = STATE_DIR / "goal.yaml"
STRATEGY_FILE = STATE_DIR / "strategy.yaml"

# Default content — overridden by env vars GOAL_YAML and STRATEGY_YAML
DEFAULT_GOAL = """asset: "BTC/USDT"
target_return_30d: 0.09
max_drawdown: 0.06
min_sharpe: 1.2
failure_below: -0.04
reflection_every: 5
one_variable_only: true
"""

DEFAULT_STRATEGY = """version: "01"
entry:
  indicator: rsi
  threshold: 30
  direction: long
stop_loss_pct: 2.0
position_size_r: 0.5
"""


def seed_state_files():
    """Write state files from env vars or defaults if they don't exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "history").mkdir(parents=True, exist_ok=True)

    if not GOAL_FILE.exists():
        content = os.environ.get("GOAL_YAML", DEFAULT_GOAL)
        GOAL_FILE.write_text(content)
        console.print(f"[yellow]Seeded goal.yaml from {'env' if 'GOAL_YAML' in os.environ else 'defaults'}[/yellow]")

    if not STRATEGY_FILE.exists():
        content = os.environ.get("STRATEGY_YAML", DEFAULT_STRATEGY)
        STRATEGY_FILE.write_text(content)
        console.print(f"[yellow]Seeded strategy.yaml from {'env' if 'STRATEGY_YAML' in os.environ else 'defaults'}[/yellow]")


def load_goal() -> dict:
    seed_state_files()
    with open(GOAL_FILE) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Hermes Trading Worker")
    parser.add_argument("--asset", type=str, default=None, help="Override asset from goal.yaml")
    args = parser.parse_args()

    goal = load_goal()
    asset = args.asset or goal["asset"]

    mode = os.environ.get("HERMES_TRADING_MODE", "paper")
    console.print(f"[bold green]Booting hermes-trading worker[/bold green]")
    console.print(f"  Asset : {asset}")
    console.print(f"  Mode  : {mode}")
    console.print(f"  Goal  : +{goal['target_return_30d']*100:.0f}% / 30d  |  max DD {goal['max_drawdown']*100:.0f}%  |  min Sharpe {goal['min_sharpe']}")

    from hermes_trading.loop import run_loop
    asyncio.run(run_loop(asset=asset, goal=goal, mode=mode))


if __name__ == "__main__":
    main()
