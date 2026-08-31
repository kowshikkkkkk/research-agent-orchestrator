import json
import redis

REDIS_URL = "redis://localhost:6379"
CACHE_TTL_SECONDS = 600  # 10 minutes

_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _normalize(query: str) -> str:
    return " ".join(query.strip().lower().split())


def cache_key(query: str) -> str:
    return f"research_cache:{_normalize(query)}"

def get_cached_result(query: str) -> dict | None:
    key = cache_key(query)
    raw = _client.get(key)
    if raw is None:
        return None
    return json.loads(raw)


def set_cached_result(query: str, result: dict) -> None:
    key = cache_key(query)
    _client.setex(key, CACHE_TTL_SECONDS, json.dumps(result))