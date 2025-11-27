"""Spotify OAuth token management.

Handles token refresh and storage. For Cloud Run deployment, tokens are
stored in Google Secret Manager. For local dev, uses environment variables.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


@dataclass
class TokenInfo:
    """Spotify access token with expiration tracking."""

    access_token: str
    expires_at: float  # Unix timestamp
    refresh_token: str
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        # Add 60s buffer before actual expiration
        return time.time() >= (self.expires_at - 60)


class SpotifyAuthError(Exception):
    """Raised when authentication fails."""

    pass


class SpotifyAuth:
    """Manages Spotify OAuth tokens with automatic refresh."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get(
            "SPOTIFY_CLIENT_SECRET", ""
        )
        self._refresh_token = refresh_token or os.environ.get(
            "SPOTIFY_REFRESH_TOKEN", ""
        )
        self._token_info: Optional[TokenInfo] = None

        if not self.client_id or not self.client_secret:
            raise SpotifyAuthError(
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required"
            )

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._token_info and not self._token_info.is_expired:
            return self._token_info.access_token

        if not self._refresh_token:
            raise SpotifyAuthError(
                "No refresh token available. Complete OAuth flow first."
            )

        await self._refresh_access_token()
        return self._token_info.access_token  # type: ignore

    async def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            raise SpotifyAuthError(
                f"Token refresh failed: {response.status_code} - {response.text}"
            )

        data = response.json()
        self._token_info = TokenInfo(
            access_token=data["access_token"],
            expires_at=time.time() + data.get("expires_in", 3600),
            refresh_token=data.get("refresh_token", self._refresh_token),
            scope=data.get("scope", ""),
        )

        # If Spotify returned a new refresh token, update it
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
            # TODO: Persist new refresh token to Secret Manager/DB


# Global auth instance (initialized on first use)
_auth: Optional[SpotifyAuth] = None


def get_auth() -> SpotifyAuth:
    """Get or create the global SpotifyAuth instance."""
    global _auth
    if _auth is None:
        _auth = SpotifyAuth()
    return _auth


async def get_access_token() -> str:
    """Convenience function to get a valid access token."""
    return await get_auth().get_access_token()
