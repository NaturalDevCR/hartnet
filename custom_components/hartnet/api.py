"""Authenticated client for the HartNet app; shares HA's HTTP session."""

from aiohttp import ClientSession, ClientTimeout


class HartNetClient:
    def __init__(self, session: ClientSession, host: str, port: int, token: str):
        self.session = session
        self.base = f"http://{host}:{port}/api"
        self.headers = {"Authorization": f"Bearer {token}"}

    async def request(self, path: str, data: dict | None = None):
        async with self.session.request(
            "GET" if data is None else "POST",
            f"{self.base}/{path}",
            json=data,
            headers=self.headers,
            timeout=ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            return await response.json()
