"""Klient for diskmap-agentens HTTP-API."""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from yarl import URL


class DiskmapError(Exception):
    """Agenten svarer ikke eller svarer med feil."""


class DiskmapAuthError(DiskmapError):
    """Feil token."""


class DiskmapClient:
    """Snakker med én agent. Tokenet blir bare her i Home Assistant og sendes aldri videre til nettleseren."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str) -> None:
        self._session = session
        self._base = URL.build(scheme="http", host=host, port=port)
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, path: str, timeout: float = 15, ok: tuple[int, ...] = (200,)) -> Any:
        try:
            async with asyncio.timeout(timeout):
                async with self._session.request(method, self._base.with_path(path), headers=self._headers) as resp:
                    if resp.status == 401:
                        raise DiskmapAuthError("invalid token")
                    if resp.status not in ok:
                        raise DiskmapError(f"{path}: HTTP {resp.status}")
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DiskmapError(f"{path}: {err!r}") from err

    async def info(self) -> dict:
        return await self._request("GET", "/api/info")

    async def summary(self) -> dict:
        return await self._request("GET", "/api/summary")

    async def status(self) -> dict:
        return await self._request("GET", "/api/status")

    async def tree(self) -> dict:
        """Fullt tre, største filer og filtyper (komprimert med gzip underveis)."""
        return await self._request("GET", "/api/tree", timeout=120)

    async def scan(self) -> dict:
        """Starter skanning. 409 betyr at en skanning allerede pågår, og er ikke en feil."""
        return await self._request("POST", "/api/scan", ok=(202, 409))
