"""
LRCLIB upload: publish synced lyrics to https://lrclib.net.

API: POST https://lrclib.net/api/publish (no auth required)
"""

import re
from typing import Optional

PUBLISH_URL = "https://lrclib.net/api/publish"
CHALLENGE_URL = "https://lrclib.net/api/request-challenge"
SEARCH_URL = "https://lrclib.net/api/search"
GET_URL = "https://lrclib.net/api/get"
USER_AGENT = "lrc-sync/1.0"

_MAX_ATTEMPTS = 5
_BACKOFF_BASE = 1.0


def _urlopen_with_retries(req, timeout=30, action="request"):
    """Open a URL, retrying transient network failures with exponential backoff."""
    import time
    import urllib.error
    import urllib.request

    last_err = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError:
            # HTTP error responses (4xx/5xx) are not transient connection issues
            raise
        except Exception as e:
            last_err = e
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_BASE * (2 ** attempt))
    raise RuntimeError(
        f"LRCLIB {action} failed after {_MAX_ATTEMPTS} attempts: {last_err}"
    )


def strip_timestamps(lrc_text: str) -> str:
    """Remove [mm:ss.xx] tags to produce plain lyrics."""
    lines = []
    for line in lrc_text.split("\n"):
        plain = re.sub(r"\[\d{2}:\d{2}\.\d{2}\]", "", line).strip()
        if plain:
            lines.append(plain)
    return "\n".join(lines)


def validate_lrc(lrc_text: str) -> dict:
    """Check per-line first [mm:ss.xx] tag for duplicates and time-order."""
    duplicates, out_of_order = [], []
    prev, max_so_far = None, None
    for i, line in enumerate(lrc_text.split("\n"), 1):
        m = re.search(r"\[(\d{2}):(\d{2})\.(\d{2})\]", line)
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 100
        if prev is not None and t == prev:
            duplicates.append(i)
        elif max_so_far is not None and t < max_so_far:
            out_of_order.append(i)
        prev = t
        max_so_far = t if max_so_far is None else max(max_so_far, t)
    return {"duplicates": duplicates, "out_of_order": out_of_order}


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
        with _urlopen_with_retries(req, action="challenge request") as resp:
            return json.loads(resp.read().decode("utf-8"))
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"LRCLIB challenge request failed: {e}")


def solve_challenge(prefix: str, target_hex: str, progress_callback=None) -> str:
    """
    Solve the proof-of-work challenge: find a nonce (decimal string) such that
    SHA256(f"{prefix}{nonce}") <= target (compared as big integers).
    Returns the nonce.
    """
    import hashlib
    import time

    target = int(target_hex, 16)
    start = time.monotonic()
    nonce = 0
    while True:
        digest = hashlib.sha256(f"{prefix}{nonce}".encode("utf-8")).digest()
        if int.from_bytes(digest, "big") <= target:
            return str(nonce)
        nonce += 1
        if progress_callback and nonce % 50000 == 0:
            elapsed = time.monotonic() - start
            hps = nonce / elapsed if elapsed > 0 else 0
            try:
                progress_callback(nonce, hps)
            except TypeError:
                progress_callback(nonce)


def publish_lrc(
    track_name: str,
    artist_name: str,
    duration: float,
    lrc_text: str,
    album_name: Optional[str] = None,
    progress_callback=None,
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
    nonce = solve_challenge(challenge["prefix"], challenge["target"],
                            progress_callback=progress_callback)
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
        with _urlopen_with_retries(req, action="publish") as resp:
            body = resp.read().decode("utf-8").strip()
            if not body:
                # LRCLIB returns 2xx with an empty body on success, but that
                # only means accepted — verify the record is actually visible.
                try:
                    record = lookup_record(track_name, artist_name, duration)
                except RuntimeError:
                    record = None
                if record and record.get("id") is not None:
                    return {"status": "published", "id": record.get("id"), "code": resp.status}
                return {"status": "submitted", "id": None,
                        "reason": "not-yet-visible", "code": resp.status}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"LRCLIB publish failed: HTTP {e.code} {detail}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"LRCLIB publish failed: {e}")


def search_records(artist_name: str, track_name: str) -> list:
    """
    Search LRCLIB for matching tracks. Returns the raw result list as-is.
    """
    import urllib.request
    import urllib.parse
    import json

    params = urllib.parse.urlencode({
        "artist_name": artist_name.strip(),
        "track_name": track_name.strip(),
    })
    req = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with _urlopen_with_retries(req, action="search") as resp:
            return json.loads(resp.read().decode("utf-8"))
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"LRCLIB search failed: {e}")


def lookup_record(artist_name: str, track_name: str, duration: float) -> Optional[dict]:
    """
    Fetch a track's LRCLIB record (used to resolve the id after publishing).
    Returns the record dict, or None if not found.
    """
    import urllib.request
    import urllib.parse
    import json

    params = urllib.parse.urlencode({
        "artist_name": artist_name.strip(),
        "track_name": track_name.strip(),
        "duration": duration,
    })
    req = urllib.request.Request(
        f"{GET_URL}?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with _urlopen_with_retries(req, action="lookup") as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"LRCLIB lookup failed: HTTP {e.code}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"LRCLIB lookup failed: {e}")


def get_by_id(record_id) -> Optional[dict]:
    """
    Fetch a track's LRCLIB record by id. Returns the record, or None if not found.
    """
    import urllib.request
    import urllib.parse
    import json

    urls = (
        f"{GET_URL}/{record_id}",
        f"{GET_URL}?{urllib.parse.urlencode({'id': record_id})}",
    )
    for url in urls:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with _urlopen_with_retries(req, action="lookup") as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise RuntimeError(f"LRCLIB lookup failed: HTTP {e.code}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"LRCLIB lookup failed: {e}")
    return None
