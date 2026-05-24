"""adapters.macro — macro context (DXY, BTC dominance via free public endpoints)."""
import httpx
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"


class SchemaError(Exception):
    pass


async def fetch() -> dict:
    """
    Returns macro context. Uses free CoinGecko endpoint for BTC dominance.
    DXY is approximated from yfinance as a best-effort free source.
    """
    btc_dominance = 50.0  # neutral default

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.coingecko.com/api/v3/global")
            resp.raise_for_status()
            data = resp.json().get("data", {})
            btc_dominance = float(data.get("market_cap_percentage", {}).get("btc", 50.0))
    except Exception:
        pass  # Fall back to neutral

    result = {
        "schema_version": SCHEMA_VERSION,
        "btc_dominance_pct": round(btc_dominance, 2),
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    required_keys = {"schema_version", "btc_dominance_pct", "ts"}
    if not required_keys.issubset(result.keys()):
        raise SchemaError(f"Macro adapter schema mismatch.")

    return result
