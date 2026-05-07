import httpx

_client: httpx.AsyncClient | None = None


def init_http() -> httpx.AsyncClient:
    """Gọi trong lifespan startup. KHÔNG gắn vào app.state —
    APScheduler background job chạy ngoài Request context."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=15,
            limits=httpx.Limits(
                max_keepalive_connections=20, max_connections=100
            ),
        )
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def shared_client() -> httpx.AsyncClient:
    """Mọi clients/coingecko.py, clients/reddit.py ... gọi hàm này."""
    if _client is None:
        raise RuntimeError("HTTP client chưa init — lỗi lifespan order?")
    return _client
