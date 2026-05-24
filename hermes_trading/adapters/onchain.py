"""adapters.onchain — on-chain metrics (Glassnode or free fallback)."""
import os
import httpx
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"


class SchemaError(Exception):
    pass


async def fetch(asset: str = "BTC") -> dict:
    """
    Returns on-chain metrics. Uses Glassnode if GLASSNODE_API_KEY is set,
    otherwise returns a stub with neutral values.
    """
    api_key = os.environ.get("GLASSNODE_API_KEY", "")

    if api_key:
        symbol = asset.split("/")[0].lower()
        url = f"https://api.glassnode.com/v1/metrics/indicators/sopr"
        params = {"a": symbol, "api_key": api_key, "i": "24h", "f": "JSON"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            sopr = float(data[-1]["v"]) if data else 1.0
    else:
        # Free fallback — neutral values
        sopr = 1.0

    result = {
        "schema_version": SCHEMA_VERSION,
        "asset": asset,
        "sopr": sopr,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    required_keys = {"schema_version", "asset", "sopr", "ts"}
    if not required_keys.issubset(result.keys()):
        raise SchemaError(f"Onchain adapter schema mismatch.")

    return result
