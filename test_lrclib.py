"""Tests for LRCLIB upload (HTTP mocked — never publishes for real)."""

import io
import json
import pytest
from unittest.mock import patch, MagicMock

from lrclib import strip_timestamps, publish_lrc, solve_challenge, PUBLISH_URL


class TestStripTimestamps:
    def test_removes_tags(self):
        lrc = "[00:01.23]Hello world\n[00:05.50]Second line\n"
        assert strip_timestamps(lrc) == "Hello world\nSecond line"

    def test_empty(self):
        assert strip_timestamps("") == ""


class TestChallenge:
    def test_solve_easy_target(self):
        import hashlib
        target = "00" + "F" * 62
        nonce = solve_challenge("testprefix", target)
        digest = hashlib.sha256(f"testprefix{nonce}".encode()).digest()
        assert int.from_bytes(digest, "big") <= int(target, 16)

    def test_solve_trivial_target(self):
        # Max target: nonce 0 always valid
        nonce = solve_challenge("abc", "F" * 64)
        assert nonce == "0"


class TestPublishLRC:
    def _mock_response(self, obj):
        resp = MagicMock()
        resp.read.return_value = json.dumps(obj).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    def _mock_urlopen(self, m):
        m.side_effect = [
            self._mock_response({"prefix": "p", "target": "F" * 64}),
            self._mock_response({"id": 123}),
        ]

    def test_payload(self):
        lrc = "[00:01.23]Hello world\n"
        with patch("urllib.request.urlopen") as m:
            self._mock_urlopen(m)
            result = publish_lrc("Song", "Artist", 215, lrc, album_name="Album")
            assert result == {"id": 123}
            assert m.call_count == 2
            req = m.call_args[0][0]
            assert req.full_url == PUBLISH_URL
            assert req.get_header("X-publish-token") == "p:0"
            payload = json.loads(req.data.decode("utf-8"))
            assert payload["trackName"] == "Song"
            assert payload["artistName"] == "Artist"
            assert payload["duration"] == 215
            assert payload["albumName"] == "Album"
            assert payload["syncedLyrics"] == lrc
            assert payload["plainLyrics"] == "Hello world"

    def test_empty_body_means_success(self):
        empty = MagicMock()
        empty.read.return_value = b""
        empty.status = 201
        empty.__enter__.return_value = empty
        with patch("urllib.request.urlopen") as m:
            m.side_effect = [
                self._mock_response({"prefix": "p", "target": "F" * 64}),
                empty,
            ]
            result = publish_lrc("Song", "Artist", 215, "[00:01.23]Hi\n")
            assert result["status"] == "published"

    def test_no_album_sends_empty_string(self):
        # Server requires albumName present even when unknown
        with patch("urllib.request.urlopen") as m:
            self._mock_urlopen(m)
            publish_lrc("Song", "Artist", 215, "[00:01.23]Hi\n")
            payload = json.loads(m.call_args[0][0].data.decode("utf-8"))
            assert payload["albumName"] == ""

    def test_missing_track(self):
        with pytest.raises(ValueError):
            publish_lrc("", "Artist", 215, "[00:01.23]Hi\n")

    def test_missing_artist(self):
        with pytest.raises(ValueError):
            publish_lrc("Song", "  ", 215, "[00:01.23]Hi\n")

    def test_bad_duration(self):
        with pytest.raises(ValueError):
            publish_lrc("Song", "Artist", 0, "[00:01.23]Hi\n")

    def test_empty_lrc(self):
        with pytest.raises(ValueError):
            publish_lrc("Song", "Artist", 215, "  \n")

    def test_http_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("403")):
            with pytest.raises(RuntimeError):
                publish_lrc("Song", "Artist", 215, "[00:01.23]Hi\n")
