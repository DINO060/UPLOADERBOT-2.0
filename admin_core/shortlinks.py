"""
ADMIN CORE - Short Links
========================
Int\u00e9gration de plusieurs APIs de raccourcissement de liens.
Support: shorte.st, gplinks, shrinkme, linkvertise, urlshortx, etc.
"""

import logging
import aiohttp
from typing import Optional, Dict, Any
from urllib.parse import quote

from .config import AdminConfig

logger = logging.getLogger("admin_core.shortlinks")


class ShortLinkManager:
    """
    Gestionnaire des liens courts.

    Providers support\u00e9s:
        - shorte.st
        - gplinks
        - shrinkme
        - linkvertise
        - urlshortx
        - ouo.io
        - exe.io
        - Custom (API g\u00e9n\u00e9rique)
    """

    def __init__(self, config: AdminConfig):
        self.config = config
        self.api_key = config.shortlink_api_key
        self.provider = config.shortlink_provider.lower()

    async def shorten(self, url: str) -> Optional[str]:
        """
        Raccourcit une URL en utilisant le provider configur\u00e9.

        Args:
            url: URL \u00e0 raccourcir

        Returns:
            URL raccourcie ou None en cas d'erreur
        """
        if not self.config.shortlink_enabled:
            return url

        if not self.api_key:
            logger.warning("Shortlink API key not configured")
            return url

        try:
            if self.provider == "shorte.st":
                return await self._shorten_shortest(url)
            elif self.provider == "gplinks":
                return await self._shorten_gplinks(url)
            elif self.provider == "shrinkme":
                return await self._shorten_shrinkme(url)
            elif self.provider == "linkvertise":
                return await self._shorten_linkvertise(url)
            elif self.provider == "urlshortx":
                return await self._shorten_urlshortx(url)
            elif self.provider == "ouo.io":
                return await self._shorten_ouo(url)
            elif self.provider == "exe.io":
                return await self._shorten_exe(url)
            else:
                logger.warning(f"Unknown shortlink provider: {self.provider}")
                return url

        except Exception as e:
            logger.error(f"Error shortening URL with {self.provider}: {e}")
            return url

    # ==================== PROVIDERS ====================

    async def _shorten_shortest(self, url: str) -> Optional[str]:
        """Shorte.st API"""
        api_url = "https://api.shorte.st/v1/data/url"

        async with aiohttp.ClientSession() as session:
            headers = {"public-api-token": self.api_key}
            data = {"urlToShorten": url}

            async with session.put(api_url, headers=headers, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("status") == "ok":
                        return result.get("shortenedUrl")

        return None

    async def _shorten_gplinks(self, url: str) -> Optional[str]:
        """GPLinks API"""
        api_url = f"https://gplinks.co/api?api={self.api_key}&url={quote(url)}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("status") == "success":
                        return result.get("shortenedUrl")

        return None

    async def _shorten_shrinkme(self, url: str) -> Optional[str]:
        """ShrinkMe API"""
        api_url = f"https://shrinkme.io/api?api={self.api_key}&url={quote(url)}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("status") == "success":
                        return result.get("shortenedUrl")

        return None

    async def _shorten_linkvertise(self, url: str) -> Optional[str]:
        """Linkvertise API"""
        api_url = "https://publisher.linkvertise.com/api/v1/redirect/link/new"

        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {"url": url}

            async with session.post(api_url, headers=headers, json=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("data", {}).get("link")

        return None

    async def _shorten_urlshortx(self, url: str) -> Optional[str]:
        """URLShortX API"""
        api_url = f"https://urlshortx.com/api?api={self.api_key}&url={quote(url)}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("status") == "success":
                        return result.get("shortenedUrl")

        return None

    async def _shorten_ouo(self, url: str) -> Optional[str]:
        """Ouo.io API"""
        api_url = f"https://ouo.io/api/{self.api_key}?s={quote(url)}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    return await resp.text()

        return None

    async def _shorten_exe(self, url: str) -> Optional[str]:
        """Exe.io API"""
        api_url = f"https://exe.io/api?api={self.api_key}&url={quote(url)}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("status") == "success":
                        return result.get("shortenedUrl")

        return None

    # ==================== UTILITIES ====================

    async def shorten_multiple(self, urls: list) -> Dict[str, str]:
        """
        Raccourcit plusieurs URLs.

        Args:
            urls: Liste d'URLs

        Returns:
            Dict {original_url: shortened_url}
        """
        result = {}
        for url in urls:
            shortened = await self.shorten(url)
            result[url] = shortened or url
        return result

    def is_enabled(self) -> bool:
        """V\u00e9rifie si le shortlink est activ\u00e9 et configur\u00e9."""
        return self.config.shortlink_enabled and bool(self.api_key)

    @staticmethod
    def get_supported_providers() -> list:
        """Retourne la liste des providers support\u00e9s."""
        return [
            "shorte.st",
            "gplinks",
            "shrinkme",
            "linkvertise",
            "urlshortx",
            "ouo.io",
            "exe.io"
        ]


async def shorten_url(
    url: str,
    api_key: str,
    provider: str = "shorte.st"
) -> Optional[str]:
    """
    Fonction utilitaire pour raccourcir une URL sans manager.

    Args:
        url: URL \u00e0 raccourcir
        api_key: Cl\u00e9 API
        provider: Nom du provider

    Returns:
        URL raccourcie ou originale en cas d'erreur
    """
    from .config import AdminConfig

    temp_config = AdminConfig(
        shortlink_enabled=True,
        shortlink_api_key=api_key,
        shortlink_provider=provider
    )

    manager = ShortLinkManager(temp_config)
    return await manager.shorten(url)
