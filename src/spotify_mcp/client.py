"""Spotify Web API client.

Thin async wrapper around the Spotify Web API using httpx.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .auth import get_access_token

SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class SpotifyAPIError(Exception):
    """Raised when a Spotify API call fails."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Spotify API error {status_code}: {message}")


class SpotifyClient:
    """Async client for Spotify Web API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to Spotify API."""
        token = await get_access_token()
        url = f"{SPOTIFY_API_BASE}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )

        if response.status_code == 204:
            return {}

        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("error", {}).get("message", response.text)
            except Exception:
                message = response.text
            raise SpotifyAPIError(response.status_code, message)

        if not response.content or not response.text.strip():
            return {}

        # Try to parse JSON, but some endpoints return non-JSON on success
        try:
            return response.json()
        except Exception:
            # Non-JSON response (e.g., player control endpoints return plain text)
            return {}

    async def get(
        self, endpoint: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        return await self._request("GET", endpoint, params=params)

    async def post(
        self,
        endpoint: str,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._request("POST", endpoint, params=params, json_body=json_body)

    async def put(
        self,
        endpoint: str,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._request("PUT", endpoint, params=params, json_body=json_body)

    async def delete(
        self, endpoint: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        return await self._request("DELETE", endpoint, params=params)

    # ─────────────────────────────────────────────────────────────────
    # Player / Playback
    # ─────────────────────────────────────────────────────────────────

    async def get_current_playback(self) -> dict[str, Any]:
        """Get the current playback state."""
        return await self.get("/me/player")

    async def get_currently_playing(self) -> dict[str, Any]:
        """Get the currently playing track."""
        return await self.get("/me/player/currently-playing")

    async def play(
        self,
        device_id: Optional[str] = None,
        context_uri: Optional[str] = None,
        uris: Optional[list[str]] = None,
        offset: Optional[dict[str, Any]] = None,
        position_ms: Optional[int] = None,
    ) -> dict[str, Any]:
        """Start or resume playback."""
        params = {"device_id": device_id} if device_id else None
        body: dict[str, Any] = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        if offset:
            body["offset"] = offset
        if position_ms is not None:
            body["position_ms"] = position_ms
        return await self.put("/me/player/play", json_body=body or None, params=params)

    async def pause(self, device_id: Optional[str] = None) -> dict[str, Any]:
        """Pause playback."""
        params = {"device_id": device_id} if device_id else None
        return await self.put("/me/player/pause", params=params)

    async def skip_to_next(self, device_id: Optional[str] = None) -> dict[str, Any]:
        """Skip to next track."""
        params = {"device_id": device_id} if device_id else None
        return await self.post("/me/player/next", params=params)

    async def skip_to_previous(self, device_id: Optional[str] = None) -> dict[str, Any]:
        """Skip to previous track."""
        params = {"device_id": device_id} if device_id else None
        return await self.post("/me/player/previous", params=params)

    async def seek(
        self, position_ms: int, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Seek to position in current track."""
        params: dict[str, Any] = {"position_ms": position_ms}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/seek", params=params)

    async def set_volume(
        self, volume_percent: int, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Set playback volume (0-100)."""
        params: dict[str, Any] = {"volume_percent": max(0, min(100, volume_percent))}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/volume", params=params)

    async def set_shuffle(
        self, state: bool, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Set shuffle mode."""
        params: dict[str, Any] = {"state": str(state).lower()}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/shuffle", params=params)

    async def set_repeat(
        self, state: str, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Set repeat mode: 'track', 'context', or 'off'."""
        params: dict[str, Any] = {"state": state}
        if device_id:
            params["device_id"] = device_id
        return await self.put("/me/player/repeat", params=params)

    async def get_devices(self) -> dict[str, Any]:
        """Get available playback devices."""
        return await self.get("/me/player/devices")

    async def transfer_playback(
        self, device_id: str, play: bool = False
    ) -> dict[str, Any]:
        """Transfer playback to another device."""
        return await self.put(
            "/me/player", json_body={"device_ids": [device_id], "play": play}
        )

    async def add_to_queue(
        self, uri: str, device_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Add a track to the playback queue."""
        params: dict[str, Any] = {"uri": uri}
        if device_id:
            params["device_id"] = device_id
        return await self.post("/me/player/queue", params=params)

    async def get_queue(self) -> dict[str, Any]:
        """Get the user's playback queue."""
        return await self.get("/me/player/queue")

    # ─────────────────────────────────────────────────────────────────
    # Search
    # ─────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        types: list[str] = ["track"],
        limit: int = 20,
        offset: int = 0,
        market: Optional[str] = None,
    ) -> dict[str, Any]:
        """Search for tracks, albums, artists, playlists, etc."""
        params: dict[str, Any] = {
            "q": query,
            "type": ",".join(types),
            "limit": min(50, max(1, limit)),
            "offset": offset,
        }
        if market:
            params["market"] = market
        return await self.get("/search", params=params)

    # ─────────────────────────────────────────────────────────────────
    # Tracks & Albums
    # ─────────────────────────────────────────────────────────────────

    async def get_track(self, track_id: str) -> dict[str, Any]:
        """Get track details."""
        return await self.get(f"/tracks/{track_id}")

    async def get_album(self, album_id: str) -> dict[str, Any]:
        """Get album details."""
        return await self.get(f"/albums/{album_id}")

    async def get_album_tracks(
        self, album_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get album tracks."""
        return await self.get(
            f"/albums/{album_id}/tracks", params={"limit": limit, "offset": offset}
        )

    # ─────────────────────────────────────────────────────────────────
    # Artists
    # ─────────────────────────────────────────────────────────────────

    async def get_artist(self, artist_id: str) -> dict[str, Any]:
        """Get artist details."""
        return await self.get(f"/artists/{artist_id}")

    async def get_artist_top_tracks(
        self, artist_id: str, market: str = "US"
    ) -> dict[str, Any]:
        """Get artist's top tracks."""
        return await self.get(
            f"/artists/{artist_id}/top-tracks", params={"market": market}
        )

    async def get_artist_albums(
        self,
        artist_id: str,
        include_groups: str = "album,single",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get artist's albums."""
        return await self.get(
            f"/artists/{artist_id}/albums",
            params={"include_groups": include_groups, "limit": limit},
        )

    # ─────────────────────────────────────────────────────────────────
    # Playlists
    # ─────────────────────────────────────────────────────────────────

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Get playlist details."""
        return await self.get(f"/playlists/{playlist_id}")

    async def get_playlist_tracks(
        self, playlist_id: str, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """Get playlist tracks."""
        return await self.get(
            f"/playlists/{playlist_id}/tracks",
            params={"limit": limit, "offset": offset},
        )

    async def get_my_playlists(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get current user's playlists."""
        return await self.get(
            "/me/playlists", params={"limit": limit, "offset": offset}
        )

    async def create_playlist(
        self,
        user_id: str,
        name: str,
        public: bool = False,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new playlist."""
        return await self.post(
            f"/users/{user_id}/playlists",
            json_body={"name": name, "public": public, "description": description},
        )

    async def add_tracks_to_playlist(
        self, playlist_id: str, uris: list[str], position: Optional[int] = None
    ) -> dict[str, Any]:
        """Add tracks to a playlist."""
        body: dict[str, Any] = {"uris": uris}
        if position is not None:
            body["position"] = position
        return await self.post(f"/playlists/{playlist_id}/tracks", json_body=body)

    # ─────────────────────────────────────────────────────────────────
    # User Profile & Library
    # ─────────────────────────────────────────────────────────────────

    async def get_me(self) -> dict[str, Any]:
        """Get current user's profile."""
        return await self.get("/me")

    async def get_saved_tracks(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get user's saved/liked tracks."""
        return await self.get("/me/tracks", params={"limit": limit, "offset": offset})

    async def save_tracks(self, track_ids: list[str]) -> dict[str, Any]:
        """Save tracks to user's library."""
        return await self.put("/me/tracks", json_body={"ids": track_ids})

    async def remove_saved_tracks(self, track_ids: list[str]) -> dict[str, Any]:
        """Remove tracks from user's library."""
        return await self.delete("/me/tracks", params={"ids": ",".join(track_ids)})

    async def get_recently_played(self, limit: int = 50) -> dict[str, Any]:
        """Get recently played tracks."""
        return await self.get("/me/player/recently-played", params={"limit": limit})


# Global client instance
_client: Optional[SpotifyClient] = None


def get_client() -> SpotifyClient:
    """Get or create the global SpotifyClient instance."""
    global _client
    if _client is None:
        _client = SpotifyClient()
    return _client
