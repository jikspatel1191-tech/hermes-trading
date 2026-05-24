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


def load_goal() -> dict:
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
