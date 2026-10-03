"""
Check whether a track's lyrics exist on LRCLIB.

Usage:
    python check_publish.py --artist Superfly --track 花蔭 --duration 228
"""

import argparse
import json
import urllib.parse
import urllib.request


def check(artist: str, track: str, duration: float):
    params = urllib.parse.urlencode({
        "artist_name": artist,
        "track_name": track,
        "duration": duration,
    })
    url = f"https://lrclib.net/api/get?{params}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "lrc-sync/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            record = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"NOT FOUND on LRCLIB: {artist} - {track} ({duration}s)")
            return False
        raise

    synced = record.get("syncedLyrics") or ""
    plain = record.get("plainLyrics") or ""
    print(f"FOUND on LRCLIB (id={record.get('id')}):")
    print(f"  track:    {record.get('trackName')}")
    print(f"  artist:   {record.get('artistName')}")
    print(f"  album:    {record.get('albumName')}")
    print(f"  duration: {record.get('duration')}")
    print(f"  plain lines:  {len(plain.splitlines())}")
    print(f"  synced lines: {len(synced.splitlines())}")
    if synced:
        print("--- first 3 synced lines ---")
        for line in synced.splitlines()[:3]:
            print(f"  {line}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Check LRCLIB for published lyrics.")
    parser.add_argument("--artist", default="Superfly")
    parser.add_argument("--track", default="花蔭")
    parser.add_argument("--duration", type=float, default=228)
    args = parser.parse_args()
    ok = check(args.artist, args.track, args.duration)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
