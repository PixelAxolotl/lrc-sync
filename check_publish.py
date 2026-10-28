"""
Check whether a track's lyrics exist on LRCLIB.

Usage:
    python check_publish.py --artist Superfly --track 花蔭 --duration 228
"""

import argparse

from logger import log
from lrclib import lookup_record


def check(artist: str, track: str, duration: float):
    try:
        record = lookup_record(artist, track, duration)
    except Exception as e:
        log("ERROR", f"LRCLIB lookup failed: {e}")
        raise
    if not record:
        log("ERROR", f"NOT FOUND on LRCLIB: {artist} - {track} ({duration}s)")
        log("WARN", "Note: new publishes take a while to appear; retry /api/search to confirm visibility.")
        return False

    synced = record.get("syncedLyrics") or ""
    plain = record.get("plainLyrics") or ""
    log("INFO", f"FOUND on LRCLIB (id={record.get('id')}):")
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
