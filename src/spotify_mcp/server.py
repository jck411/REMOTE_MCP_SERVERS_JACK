"""Spotify MCP Server.

FastMCP server exposing Spotify tools via MCP protocol.
Supports Streamable HTTP transport for Cloud Run deployment.
"""

from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .auth import SpotifyAuthError
from .client import SpotifyAPIError, get_client

# Create MCP server instance
# stateless_http=True and json_response=True are recommended for Cloud Run
# as they allow better scalability in multi-node environments
mcp = FastMCP(
    "spotify",
    stateless_http=True,
    json_response=True,
)


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
                    lines.append(f'  - "{a["name"]}" by {artists} | URI: {a["uri"]}')

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
                    lines.append(f'  - "{p["name"]}" by {owner} | URI: {p["uri"]}')

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
            lines.append(f'- "{p["name"]}" ({track_count} tracks) | URI: {p["uri"]}')

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
        return "Track saved to your library."

    except Exception as e:
        return _format_error(e)


# ─────────────────────────────────────────────────────────────────────────────
# Server Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main():
    """Run the MCP server."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    if transport == "http":
        # For Cloud Run: run with streamable HTTP transport
        # The server listens on host:port/mcp by default
        port = int(os.environ.get("PORT", "8080"))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        # For local development: use stdio
        mcp.run()


if __name__ == "__main__":
    main()
