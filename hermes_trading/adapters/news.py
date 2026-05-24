"""adapters.news — news sentiment (NewsAPI or free fallback)."""
import os
import httpx
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"


class SchemaError(Exception):
    pass


async def fetch(query: str = "Bitcoin") -> dict:
    """
    Returns a simple sentiment score in [-1, +1].
    Uses NewsAPI if NEWS_API_KEY is set, otherwise returns neutral.
    """
    api_key = os.environ.get("NEWS_API_KEY", "")
    sentiment = 0.0

    if api_key:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "pageSize": 10,
            "sortBy": "publishedAt",
            "apiKey": api_key,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

        # Naive sentiment: count positive/negative keywords
        positive_words = {"surge", "rally", "bullish", "gain", "rise", "up", "high", "record", "growth"}
        negative_words = {"crash", "drop", "bearish", "loss", "fall", "down", "low", "fear", "sell"}

        pos = neg = 0
        for article in articles:
            text = (article.get("title", "") + " " + article.get("description", "")).lower()
            pos += sum(1 for w in positive_words if w in text)
            neg += sum(1 for w in negative_words if w in text)

        total = pos + neg
        if total > 0:
            sentiment = (pos - neg) / total

    result = {
        "schema_version": SCHEMA_VERSION,
        "query": query,
        "sentiment": round(sentiment, 4),
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    required_keys = {"schema_version", "query", "sentiment", "ts"}
    if not required_keys.issubset(result.keys()):
        raise SchemaError(f"News adapter schema mismatch.")

    return result
