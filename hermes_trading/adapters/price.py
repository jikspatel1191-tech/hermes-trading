"""adapters.price — fetch current price and recent OHLCV for an asset via ccxt."""
import os
import asyncio
from typing import Any

SCHEMA_VERSION = "1.0"


class SchemaError(Exception):
    pass


async def fetch(asset: str = "BTC/USDT") -> dict:
    """
    Returns:
      {
        "schema_version": "1.0",
        "asset": "BTC/USDT",
        "price": 65432.10,
        "prices_history": [...],   # last 50 closes for RSI
        "ts": "2024-01-01T00:00:00Z"
      }
    """
    import ccxt.async_support as ccxt_async
    from datetime import datetime, timezone

    api_key = os.environ.get("EXCHANGE_API_KEY", "")
    api_secret = os.environ.get("EXCHANGE_API_SECRET", "")

    exchange_kwargs: dict[str, Any] = {"enableRateLimit": True}
    if api_key:
        exchange_kwargs["apiKey"] = api_key
        exchange_kwargs["secret"] = api_secret

    exchange = ccxt_async.binance(exchange_kwargs)

    try:
        ticker = await exchange.fetch_ticker(asset)
        price = float(ticker["last"])

        # Fetch last 50 1m candles for RSI
        ohlcv = await exchange.fetch_ohlcv(asset, timeframe="1m", limit=50)
        closes = [candle[4] for candle in ohlcv]

    finally:
        await exchange.close()

    result = {
        "schema_version": SCHEMA_VERSION,
        "asset": asset,
        "price": price,
        "prices_history": closes,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    # Schema validation
    required_keys = {"schema_version", "asset", "price", "prices_history", "ts"}
    if not required_keys.issubset(result.keys()):
        raise SchemaError(f"Price adapter schema mismatch. Expected keys: {required_keys}")
    if result["schema_version"] != SCHEMA_VERSION:
        raise SchemaError(f"Price adapter schema version mismatch: {result['schema_version']} != {SCHEMA_VERSION}")

    return result
