# Complete Guide: Self-Contained Spotify MCP Server on Google Cloud

## Overview

You're building a **standalone MCP server** that exposes Spotify tools over HTTP, deployable to **Google Cloud Run**, usable by **any MCP-compatible chatbot**.

---

## Architecture

```
┌──────────────────┐         HTTPS (SSE)         ┌─────────────────────────┐
│  Any MCP Client  │ ◄─────────────────────────► │  Cloud Run Service      │
│  (Claude, etc.)  │                             │  spotify-mcp-server     │
└──────────────────┘                             └───────────┬─────────────┘
                                                             │
                                                             ▼
                                                 ┌─────────────────────────┐
                                                 │  Spotify Web API        │
                                                 │  api.spotify.com        │
                                                 └─────────────────────────┘
```

---

## Project Structure

```
spotify-mcp-server/
├── pyproject.toml          # Dependencies & project config
├── Dockerfile              # Cloud Run container
├── README.md
├── .gitignore
├── .env.example            # Template for local dev
└── src/
    └── spotify_mcp/
        ├── __init__.py
        ├── server.py       # FastMCP server with @mcp.tool decorators
        ├── auth.py         # Spotify OAuth token management
        └── client.py       # Spotify Web API wrapper (httpx)
```

---

## File Contents

### 1. pyproject.toml

```toml
[project]
name = "spotify-mcp-server"
version = "0.1.0"
description = "MCP server for Spotify integration, deployable to Cloud Run"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0.0",
    "httpx>=0.27.0",
    "google-cloud-secret-manager>=2.20.0",
    "uvicorn>=0.30.0",
    "starlette>=0.37.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
]

[project.scripts]
spotify-mcp = "spotify_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/spotify_mcp"]

[tool.ruff]
line-length = 88
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

### 2. `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN uv pip install --system -e .

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080
EXPOSE 8080

# Run the MCP server with SSE transport
CMD ["python", "-m", "spotify_mcp.server"]
```

---

### 3. .gitignore

```gitignore
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.env
*.egg-info/
dist/
build/
.pytest_cache/
.ruff_cache/
```

---

### 4. `.env.example`

```bash
# Spotify App Credentials (from developer.spotify.com)
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here

# For single-user: store refresh token directly
# For multi-user: use Firestore/database instead
SPOTIFY_REFRESH_TOKEN=your_refresh_token_here

# Optional: GCP project for Secret Manager
GCP_PROJECT_ID=your-gcp-project
```

---

### 5. `src/spotify_mcp/__init__.py`

```python
"""Spotify MCP Server - A standalone MCP server for Spotify integration."""

__version__ = "0.1.0"
```

---

### 6. `src/spotify_mcp/auth.py`

```python
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
        self.client_secret = client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        self._refresh_token = refresh_token or os.environ.get("SPOTIFY_REFRESH_TOKEN", "")
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
        async with httpx.AsyncClient() as client:
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
```

---

### 7. `src/spotify_mcp/client.py`

```python
"""Spotify Web API client.

Thin async wrapper around the Spotify Web API using httpx.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from .auth import get_access_token, SpotifyAuthError

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

        if not response.content:
            return {}

        return response.json()

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
        return await self.get("/me/playlists", params={"limit": limit, "offset": offset})

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
```

---

### 8. `src/spotify_mcp/server.py`

```python
"""Spotify MCP Server.

FastMCP server exposing Spotify tools via MCP protocol.
Supports SSE transport for Cloud Run deployment.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .client import get_client, SpotifyAPIError
from .auth import SpotifyAuthError

# Create MCP server instance
mcp = FastMCP("spotify")


def _format_track(track: dict) -> str:
    """Format a track for display."""
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    album = track.get("album", {}).get("name", "Unknown Album")
    duration_ms = track.get("duration_ms", 0)
    duration = f"{duration_ms // 60000}:{(duration_ms % 60000) // 1000:02d}"
    return f'"{track.get("name")}" by {artists} ({album}) [{duration}]'


def _format_error(e: Exception) -> str:
    """Format an error for the LLM."""
    if isinstance(e, SpotifyAuthError):
        return f"Authentication error: {e}. The Spotify token may need to be refreshed."
    if isinstance(e, SpotifyAPIError):
        return f"Spotify API error ({e.status_code}): {e.message}"
    return f"Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Playback Control Tools
# ─────────────────────────────────────────────────────────────────────────────


@mcp.tool("spotify_get_playback")
async def get_playback() -> str:
    """Get current Spotify playback state including track, device, and progress.

    Use this to see what's currently playing, check if music is paused,
    or find available devices.
    """
    try:
        client = get_client()
        playback = await client.get_current_playback()

        if not playback:
            return "Nothing is currently playing on Spotify."

        device = playback.get("device", {})
        track = playback.get("item", {})
        is_playing = playback.get("is_playing", False)
        progress_ms = playback.get("progress_ms", 0)
        shuffle = playback.get("shuffle_state", False)
        repeat = playback.get("repeat_state", "off")

        status = "Playing" if is_playing else "Paused"
        progress = f"{progress_ms // 60000}:{(progress_ms % 60000) // 1000:02d}"

        lines = [
            f"Status: {status}",
            f"Track: {_format_track(track)}" if track else "Track: None",
            f"Progress: {progress}",
            f"Device: {device.get('name', 'Unknown')} ({device.get('type', 'unknown')})",
            f"Volume: {device.get('volume_percent', 0)}%",
            f"Shuffle: {'On' if shuffle else 'Off'}",
            f"Repeat: {repeat}",
        ]

        return "\n".join(lines)

    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_play")
async def play(
    query: Optional[str] = None,
    uri: Optional[str] = None,
    device_id: Optional[str] = None,
) -> str:
    """Start or resume Spotify playback.

    If query is provided, searches for and plays the best match.
    If uri is provided (spotify:track:xxx), plays that specific item.
    If neither, resumes current playback.
    """
    try:
        client = get_client()

        if query:
            # Search and play
            results = await client.search(query, types=["track"], limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if not tracks:
                return f"No tracks found for '{query}'."
            track = tracks[0]
            await client.play(device_id=device_id, uris=[track["uri"]])
            return f"Now playing: {_format_track(track)}"

        elif uri:
            # Play specific URI
            if uri.startswith("spotify:track:"):
                await client.play(device_id=device_id, uris=[uri])
            else:
                await client.play(device_id=device_id, context_uri=uri)
            return f"Started playing: {uri}"

        else:
            # Resume playback
            await client.play(device_id=device_id)
            return "Resumed playback."

    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_pause")
async def pause() -> str:
    """Pause Spotify playback."""
    try:
        client = get_client()
        await client.pause()
        return "Playback paused."
    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_next")
async def next_track() -> str:
    """Skip to the next track."""
    try:
        client = get_client()
        await client.skip_to_next()
        return "Skipped to next track."
    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_previous")
async def previous_track() -> str:
    """Skip to the previous track."""
    try:
        client = get_client()
        await client.skip_to_previous()
        return "Skipped to previous track."
    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_volume")
async def set_volume(volume: int) -> str:
    """Set playback volume (0-100)."""
    try:
        client = get_client()
        clamped = max(0, min(100, volume))
        await client.set_volume(clamped)
        return f"Volume set to {clamped}%."
    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_shuffle")
async def set_shuffle(enabled: bool) -> str:
    """Enable or disable shuffle mode."""
    try:
        client = get_client()
        await client.set_shuffle(enabled)
        return f"Shuffle {'enabled' if enabled else 'disabled'}."
    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_repeat")
async def set_repeat(mode: str = "off") -> str:
    """Set repeat mode: 'track', 'context' (album/playlist), or 'off'."""
    try:
        client = get_client()
        if mode not in ("track", "context", "off"):
            return "Invalid mode. Use 'track', 'context', or 'off'."
        await client.set_repeat(mode)
        return f"Repeat mode set to '{mode}'."
    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_queue_add")
async def add_to_queue(query: Optional[str] = None, uri: Optional[str] = None) -> str:
    """Add a track to the playback queue.

    Provide either a search query or a Spotify URI.
    """
    try:
        client = get_client()

        if query:
            results = await client.search(query, types=["track"], limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if not tracks:
                return f"No tracks found for '{query}'."
            track = tracks[0]
            await client.add_to_queue(track["uri"])
            return f"Added to queue: {_format_track(track)}"

        elif uri:
            await client.add_to_queue(uri)
            return f"Added to queue: {uri}"

        else:
            return "Provide either 'query' or 'uri' to add to queue."

    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_queue")
async def get_queue() -> str:
    """Get the current playback queue."""
    try:
        client = get_client()
        queue = await client.get_queue()

        currently_playing = queue.get("currently_playing")
        upcoming = queue.get("queue", [])

        lines = []
        if currently_playing:
            lines.append(f"Now playing: {_format_track(currently_playing)}")
        else:
            lines.append("Nothing currently playing.")

        if upcoming:
            lines.append(f"\nUp next ({len(upcoming)} tracks):")
            for i, track in enumerate(upcoming[:10], 1):
                lines.append(f"  {i}. {_format_track(track)}")
            if len(upcoming) > 10:
                lines.append(f"  ... and {len(upcoming) - 10} more")
        else:
            lines.append("Queue is empty.")

        return "\n".join(lines)

    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_devices")
async def get_devices() -> str:
    """List available Spotify playback devices."""
    try:
        client = get_client()
        result = await client.get_devices()
        devices = result.get("devices", [])

        if not devices:
            return "No active Spotify devices found. Open Spotify on a device first."

        lines = ["Available devices:"]
        for d in devices:
            active = " [ACTIVE]" if d.get("is_active") else ""
            lines.append(
                f"- {d.get('name')} ({d.get('type')}){active} "
                f"Volume: {d.get('volume_percent')}% | ID: {d.get('id')}"
            )

        return "\n".join(lines)

    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_transfer")
async def transfer_playback(device_id: str, play: bool = True) -> str:
    """Transfer playback to another device.

    Use spotify_devices to find device IDs.
    """
    try:
        client = get_client()
        await client.transfer_playback(device_id, play=play)
        return f"Playback transferred to device {device_id}."
    except Exception as e:
        return _format_error(e)


# ─────────────────────────────────────────────────────────────────────────────
# Search & Browse Tools
# ─────────────────────────────────────────────────────────────────────────────


@mcp.tool("spotify_search")
async def search(
    query: str,
    types: str = "track",
    limit: int = 10,
) -> str:
    """Search Spotify for tracks, albums, artists, or playlists.

    types: comma-separated list like "track,album,artist,playlist"
    """
    try:
        client = get_client()
        type_list = [t.strip() for t in types.split(",")]
        results = await client.search(query, types=type_list, limit=limit)

        lines = [f"Search results for '{query}':"]

        if "tracks" in results:
            tracks = results["tracks"].get("items", [])
            if tracks:
                lines.append(f"\nTracks ({len(tracks)}):")
                for t in tracks[:limit]:
                    lines.append(f"  - {_format_track(t)} | URI: {t['uri']}")

        if "albums" in results:
            albums = results["albums"].get("items", [])
            if albums:
                lines.append(f"\nAlbums ({len(albums)}):")
                for a in albums[:limit]:
                    artists = ", ".join(art["name"] for art in a.get("artists", []))
                    lines.append(f"  - \"{a['name']}\" by {artists} | URI: {a['uri']}")

        if "artists" in results:
            artists = results["artists"].get("items", [])
            if artists:
                lines.append(f"\nArtists ({len(artists)}):")
                for a in artists[:limit]:
                    followers = a.get("followers", {}).get("total", 0)
                    lines.append(
                        f"  - {a['name']} ({followers:,} followers) | URI: {a['uri']}"
                    )

        if "playlists" in results:
            playlists = results["playlists"].get("items", [])
            if playlists:
                lines.append(f"\nPlaylists ({len(playlists)}):")
                for p in playlists[:limit]:
                    owner = p.get("owner", {}).get("display_name", "Unknown")
                    lines.append(
                        f"  - \"{p['name']}\" by {owner} | URI: {p['uri']}"
                    )

        return "\n".join(lines)

    except Exception as e:
        return _format_error(e)


# ─────────────────────────────────────────────────────────────────────────────
# Library & Playlists
# ─────────────────────────────────────────────────────────────────────────────


@mcp.tool("spotify_my_playlists")
async def my_playlists(limit: int = 20) -> str:
    """Get the user's playlists."""
    try:
        client = get_client()
        result = await client.get_my_playlists(limit=limit)
        playlists = result.get("items", [])

        if not playlists:
            return "You have no playlists."

        lines = [f"Your playlists ({len(playlists)}):"]
        for p in playlists:
            track_count = p.get("tracks", {}).get("total", 0)
            lines.append(
                f"- \"{p['name']}\" ({track_count} tracks) | URI: {p['uri']}"
            )

        return "\n".join(lines)

    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_recently_played")
async def recently_played(limit: int = 20) -> str:
    """Get recently played tracks."""
    try:
        client = get_client()
        result = await client.get_recently_played(limit=limit)
        items = result.get("items", [])

        if not items:
            return "No recently played tracks."

        lines = ["Recently played:"]
        for item in items:
            track = item.get("track", {})
            played_at = item.get("played_at", "")[:10]  # Just the date
            lines.append(f"- {_format_track(track)} (played {played_at})")

        return "\n".join(lines)

    except Exception as e:
        return _format_error(e)


@mcp.tool("spotify_like_track")
async def like_track(uri: Optional[str] = None) -> str:
    """Save the current track (or specified track) to your library.

    If uri is not provided, likes the currently playing track.
    """
    try:
        client = get_client()

        if uri:
            track_id = uri.replace("spotify:track:", "")
        else:
            playback = await client.get_current_playback()
            if not playback or not playback.get("item"):
                return "Nothing is currently playing."
            track_id = playback["item"]["id"]

        await client.save_tracks([track_id])
        return f"Track saved to your library."

    except Exception as e:
        return _format_error(e)


# ─────────────────────────────────────────────────────────────────────────────
# Server Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main():
    """Run the MCP server."""
    # Use SSE transport for HTTP-based communication (Cloud Run compatible)
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    if transport == "sse":
        # For Cloud Run: run with SSE over HTTP
        mcp.run(transport="sse")
    else:
        # For local development: use stdio
        mcp.run()


if __name__ == "__main__":
    main()
```

---

## Deployment Steps

### 1. Create Spotify App

1. Go to https://developer.spotify.com/dashboard
2. Create a new app
3. Note your **Client ID** and **Client Secret**
4. Add redirect URI: `http://localhost:8888/callback` (for initial token)
5. Required scopes:
   ```
   user-read-playback-state
   user-modify-playback-state
   user-read-currently-playing
   user-read-recently-played
   user-library-read
   user-library-modify
   playlist-read-private
   playlist-modify-public
   playlist-modify-private
   ```

### 2. Get Initial Refresh Token

Create a one-time script to get the refresh token:

```python
# get_token.py (run locally once)
import httpx
import webbrowser
from urllib.parse import urlencode

CLIENT_ID = "your_client_id"
REDIRECT_URI = "http://localhost:8888/callback"
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing user-read-recently-played user-library-read user-library-modify playlist-read-private playlist-modify-public playlist-modify-private"

auth_url = "https://accounts.spotify.com/authorize?" + urlencode({
    "client_id": CLIENT_ID,
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPES,
})

print(f"Open this URL:\n{auth_url}")
webbrowser.open(auth_url)
code = input("Paste the 'code' from the redirect URL: ")

# Exchange code for tokens
response = httpx.post(
    "https://accounts.spotify.com/api/token",
    data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    },
    auth=(CLIENT_ID, "your_client_secret"),
)
print(response.json())
# Save the refresh_token!
```

### 3. Set Up Google Cloud

```bash
# Create project
gcloud projects create spotify-mcp-server
gcloud config set project spotify-mcp-server

# Enable APIs
gcloud services enable \
    run.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com

# Store secrets
echo -n "your_client_id" | gcloud secrets create SPOTIFY_CLIENT_ID --data-file=-
echo -n "your_client_secret" | gcloud secrets create SPOTIFY_CLIENT_SECRET --data-file=-
echo -n "your_refresh_token" | gcloud secrets create SPOTIFY_REFRESH_TOKEN --data-file=-
```

### 4. Deploy to Cloud Run

```bash
gcloud run deploy spotify-mcp \
    --source . \
    --region us-central1 \
    --allow-unauthenticated \
    --set-env-vars="MCP_TRANSPORT=sse" \
    --set-secrets="SPOTIFY_CLIENT_ID=SPOTIFY_CLIENT_ID:latest,SPOTIFY_CLIENT_SECRET=SPOTIFY_CLIENT_SECRET:latest,SPOTIFY_REFRESH_TOKEN=SPOTIFY_REFRESH_TOKEN:latest" \
    --memory 512Mi \
    --timeout 300 \
    --min-instances 0 \
    --max-instances 10
```

### 5. Connect from Any MCP Client

```json
{
  "mcpServers": {
    "spotify": {
      "transport": "sse",
      "url": "https://spotify-mcp-xxxxx-uc.a.run.app/sse"
    }
  }
}
```

---

## Local Development

```bash
# Create venv
python -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"

# Set env vars
export SPOTIFY_CLIENT_ID="xxx"
export SPOTIFY_CLIENT_SECRET="xxx"
export SPOTIFY_REFRESH_TOKEN="xxx"

# Run (stdio mode for local testing)
python -m spotify_mcp.server

# Or test with SSE locally
MCP_TRANSPORT=sse python -m spotify_mcp.server
```

---

## Security Considerations

| Concern | Recommendation |
|---------|----------------|
| **API Access** | Use Cloud Run IAM or add API key validation |
| **Token Storage** | Use Secret Manager (single user) or Firestore (multi-user) |
| **HTTPS** | Cloud Run provides this automatically |
| **Rate Limits** | Spotify has rate limits; add caching if needed |

---

## Additional Tools You May Want to Add

```python
# Ideas for additional tools:

@mcp.tool("spotify_play_album")
async def play_album(album_name: str, artist: str = "") -> str:
    """Play a specific album."""
    ...

@mcp.tool("spotify_play_playlist")
async def play_playlist(playlist_name: str) -> str:
    """Play one of the user's playlists by name."""
    ...

@mcp.tool("spotify_create_playlist")
async def create_playlist(name: str, description: str = "") -> str:
    """Create a new playlist."""
    ...

@mcp.tool("spotify_add_to_playlist")
async def add_to_playlist(playlist_id: str, track_uri: str) -> str:
    """Add a track to a playlist."""
    ...

@mcp.tool("spotify_get_recommendations")
async def get_recommendations(seed_tracks: str, limit: int = 20) -> str:
    """Get track recommendations based on seed tracks."""
    ...
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `401 Unauthorized` | Refresh token expired; re-run OAuth flow |
| `403 Forbidden` | Missing scopes; check app settings in Spotify Dashboard |
| `No active device` | Open Spotify app on a device first |
| `Rate limited` | Add exponential backoff or caching |
| `Cloud Run timeout` | Increase `--timeout` setting |

---

## References

- [Spotify Web API Docs](https://developer.spotify.com/documentation/web-api)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP Docs](https://gofastmcp.com)
- [Cloud Run Docs](https://cloud.google.com/run/docs)
