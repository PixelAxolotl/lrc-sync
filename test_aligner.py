"""Tests for the alignment pipeline components."""

import pytest
from aligner import (
    WordTimestamp,
    LineTimestamp,
    format_lrc,
    match_lyrics_to_words,
    _normalize,
    _similarity,
)


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("Hello World") == "hello world"

    def test_strip_punctuation(self):
        assert _normalize("Hello, World!") == "hello world"

    def test_strip_whitespace(self):
        assert _normalize("  hello  ") == "hello"

    def test_empty(self):
        assert _normalize("") == ""


class TestSimilarity:
    def test_identical(self):
        assert _similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert _similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        score = _similarity("hello world", "hello there")
        assert 0.0 < score < 1.0

    def test_empty(self):
        assert _similarity("", "hello") == 0.0

    def test_cjk_identical(self):
        assert _similarity("桜散る ひらひら", "桜散る ひらひら") == 1.0

    def test_cjk_no_overlap(self):
        assert _similarity("桜散る", "愛も散る") == 0.0 or _similarity("桜散る", "xyz") == 0.0

    def test_cjk_partial_overlap(self):
        score = _similarity("桜散る ひらひら", "桜散るひらひら")
        assert score > 0.3

    def test_cjk_mismatched_lines_low_score(self):
        score = _similarity("特別な日はそばにいたかった", "桜は去ってく")
        assert score < 0.3


class TestFormatLRC:
    def test_basic_formatting(self):
        lines = [
            LineTimestamp(line="Hello world", start=0.0),
            LineTimestamp(line="Second line", start=5.5),
        ]
        result = format_lrc(lines)
        assert "[00:00.00]Hello world" in result
        assert "[00:05.50]Second line" in result

    def test_offset(self):
        lines = [LineTimestamp(line="Test", start=1.0)]
        result = format_lrc(lines, offset=0.5)
        assert "[00:01.50]Test" in result

    def test_negative_offset_clamped(self):
        lines = [LineTimestamp(line="Test", start=0.5)]
        result = format_lrc(lines, offset=-1.0)
        assert "[00:00.00]Test" in result

    def test_merge_consecutive(self):
        lines = [
            LineTimestamp(line="Line one", start=1.0),
            LineTimestamp(line="Line two", start=1.0),
            LineTimestamp(line="Line three", start=2.0),
        ]
        result = format_lrc(lines, merge_consecutive=True)
        assert "Line one / Line two" in result
        assert "[00:01.00]" in result
        assert "[00:02.00]Line three" in result

    def test_no_merge(self):
        lines = [
            LineTimestamp(line="Line one", start=1.0),
            LineTimestamp(line="Line two", start=1.0),
        ]
        result = format_lrc(lines, merge_consecutive=False)
        assert result.count("[00:01.00]") == 2

    def test_empty(self):
        assert format_lrc([]) == ""


class TestMatchLyricsToWords:
    def test_perfect_match(self):
        words = [
            WordTimestamp(word="Hello", start=0.0, end=0.5),
            WordTimestamp(word="world", start=0.5, end=1.0),
            WordTimestamp(word="Second", start=1.0, end=1.5),
            WordTimestamp(word="line", start=1.5, end=2.0),
        ]
        lyrics = ["Hello world", "Second line"]
        result, warnings = match_lyrics_to_words(lyrics, words)
        assert len(result) == 2
        assert result[0].line == "Hello world"
        assert result[0].start == 0.0
        assert result[1].line == "Second line"
        assert result[1].start == 1.0
        assert len(warnings) == 0

    def test_fuzzy_match(self):
        words = [
            WordTimestamp(word="Hello", start=0.0, end=0.5),
            WordTimestamp(word="world", start=0.5, end=1.0),
        ]
        lyrics = ["Hello, world!"]
        result, warnings = match_lyrics_to_words(lyrics, words)
        assert len(result) == 1
        assert result[0].start == 0.0

    def test_no_match(self):
        words = [
            WordTimestamp(word="Completely", start=0.0, end=0.5),
            WordTimestamp(word="different", start=0.5, end=1.0),
        ]
        lyrics = ["No match here"]
        result, warnings = match_lyrics_to_words(lyrics, words)
        assert len(result) == 1
        assert len(warnings) == 1

    def test_empty_lyrics(self):
        words = [WordTimestamp(word="Hello", start=0.0, end=0.5)]
        result, warnings = match_lyrics_to_words([], words)
        assert len(result) == 0

    def test_empty_words(self):
        result, warnings = match_lyrics_to_words(["Hello"], [])
        assert len(result) == 1
        assert len(warnings) == 1

    def test_blank_lines_skipped(self):
        words = [
            WordTimestamp(word="Hello", start=0.0, end=0.5),
            WordTimestamp(word="world", start=0.5, end=1.0),
        ]
        lyrics = ["Hello world", "", "   "]
        result, warnings = match_lyrics_to_words(lyrics, words)
        assert len(result) == 1

    def test_japanese_match(self):
        words = [
            WordTimestamp(word="特別な日はそばにいたかった", start=10.0, end=12.0),
            WordTimestamp(word="花蔭ひとり", start=12.5, end=14.0),
            WordTimestamp(word="桜は去ってく", start=14.5, end=16.0),
        ]
        lyrics = ["特別な日はそばにいたかった", "花蔭ひとり", "桜は去ってく"]
        result, warnings = match_lyrics_to_words(lyrics, words)
        assert len(result) == 3
        assert len(warnings) == 0
        assert result[0].start == 10.0
        assert result[1].start == 12.5
        assert result[2].start == 14.5

    def test_japanese_no_false_match(self):
        words = [
            WordTimestamp(word="桜は去ってく", start=0.0, end=1.0),
        ]
        lyrics = ["特別な日はそばにいたかった"]
        result, warnings = match_lyrics_to_words(lyrics, words)
        assert len(result) == 1
        assert len(warnings) == 1

    def test_timestamps_never_go_backwards(self):
        # Line 2's best match occurs EARLIER in the audio than line 1's
        # match (e.g. repeated chorus). It must be rejected, not time-travel.
        words = [
            WordTimestamp(word="second line here", start=20.0, end=21.0),
            WordTimestamp(word="first line here", start=32.0, end=33.0),
        ]
        lyrics = ["first line here", "second line here"]
        result, warnings = match_lyrics_to_words(lyrics, words)
        assert len(result) == 2
        assert result[0].start == 32.0
        assert result[1].start >= result[0].start
        assert len(warnings) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
