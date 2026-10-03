"""
LRCLIB upload: publish synced lyrics to https://lrclib.net.

API: POST https://lrclib.net/api/publish (no auth required)
"""

import re
from typing import Optional

PUBLISH_URL = "https://lrclib.net/api/publish"
CHALLENGE_URL = "https://lrclib.net/api/request-challenge"
USER_AGENT = "lrc-sync/1.0"


def strip_timestamps(lrc_text: str) -> str:
    """Remove [mm:ss.xx] tags to produce plain lyrics."""
    lines = []
    for line in lrc_text.split("\n"):
        plain = re.sub(r"\[\d{2}:\d{2}\.\d{2}\]", "", line).strip()
        if plain:
            lines.append(plain)
    return "\n".join(lines)


def request_challenge() -> dict:
    """Request a proof-of-work challenge. Returns {"prefix": ..., "target": ...}."""
    import urllib.request
    import json

    req = urllib.request.Request(
        CHALLENGE_URL,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"LRCLIB challenge request failed: {e}")


def solve_challenge(prefix: str, target_hex: str, progress_callback=None) -> str:
    """
    Solve the proof-of-work challenge: find a nonce (decimal string) such that
    SHA256(f"{prefix}{nonce}") <= target (compared as big integers).
    Returns the nonce.
    """
    import hashlib

    target = int(target_hex, 16)
    nonce = 0
    while True:
        digest = hashlib.sha256(f"{prefix}{nonce}".encode("utf-8")).digest()
        if int.from_bytes(digest, "big") <= target:
            return str(nonce)
        nonce += 1
        if progress_callback and nonce % 50000 == 0:
            progress_callback(nonce)


def publish_lrc(
    track_name: str,
    artist_name: str,
    duration: float,
    lrc_text: str,
    album_name: Optional[str] = None,
) -> dict:
    """
    Publish synced lyrics to LRCLIB.

    Args:
        track_name: Title of the track
        artist_name: Track's artist name
        duration: Track duration in seconds
        lrc_text: Synced LRC text
        album_name: Optional album name

    Returns:
        Response JSON from LRCLIB

    Raises:
        ValueError: If required fields are missing
        RuntimeError: If the publish request fails
    """
    import urllib.request
    import json

    if not track_name.strip():
        raise ValueError("Track name is required")
    if not artist_name.strip():
        raise ValueError("Artist name is required")
    if duration <= 0:
        raise ValueError("Duration must be positive")
    if not lrc_text.strip():
        raise ValueError("LRC text is empty")

    payload = {
        "trackName": track_name.strip(),
        "artistName": artist_name.strip(),
        "duration": duration,
        "plainLyrics": strip_timestamps(lrc_text),
        "syncedLyrics": lrc_text,
    }
    # NOTE: albumName is required by the server despite docs marking it
    # optional — always include it (empty string when unknown).
    payload["albumName"] = album_name.strip() if album_name and album_name.strip() else ""

    # LRCLIB requires a proof-of-work publish token (single use, 5-min expiry)
    challenge = request_challenge()
    nonce = solve_challenge(challenge["prefix"], challenge["target"])
    token = f"{challenge['prefix']}:{nonce}"

    req = urllib.request.Request(
        PUBLISH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-Publish-Token": token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8").strip()
            if not body:
                # LRCLIB returns 2xx with an empty body on success
                return {"status": "published", "code": resp.status}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"LRCLIB publish failed: HTTP {e.code} {detail}")
    except Exception as e:
        raise RuntimeError(f"LRCLIB publish failed: {e}")
