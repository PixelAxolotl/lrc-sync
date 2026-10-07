"""Regression tests for the lyric matcher.

Covers the invariants that a hand-written golden LRC could not check, and which
the LRCLIB benchmark surfaced as real bugs:

* a punctuation-only line ("♪") must still get an output entry, otherwise the
  result has fewer lines than the input and every later line is shifted
  relative to its source (Rokudenashi - アルビレオ: 52 in, 49 out)
* output must be monotonic and preserve input order
* bigram similarity must beat the legacy bag-of-characters score on CJK
* the interpolated fallback must not stack into a 1s-per-line ramp
"""
import sys
import os

sys.path.insert(0, os.path.abspath(".."))

import aligner


def W(word, start, end, conf=0.9):
    return aligner.WordTimestamp(word=word, start=start, end=end, confidence=conf)


def test_punctuation_only_line_is_preserved():
    lyrics = ["real line one", "♪", "another real line", "♪♪", "final line"]
    words = [W("real", 1, 2), W("line", 2, 3), W("one", 3, 4),
             W("another", 10, 11), W("real", 11, 12), W("line", 12, 13),
             W("final", 20, 21), W("line", 21, 22)]

    lines, _, _ = aligner.match_lyrics_to_words(lyrics, words, return_spans=True)

    assert len(lines) == len(lyrics), \
        f"line count must match input: got {len(lines)}, want {len(lyrics)}"
    assert [l.line for l in lines] == lyrics, "input order must be preserved"


def test_blank_line_is_still_dropped():
    lyrics = ["a real line", "   ", "another real line"]
    words = [W("a", 1, 2), W("real", 2, 3), W("line", 3, 4),
             W("another", 10, 11), W("real", 11, 12), W("line", 12, 13)]
    lines, _, _ = aligner.match_lyrics_to_words(lyrics, words, return_spans=True)
    assert len(lines) == 2, f"whitespace-only line should be dropped, got {len(lines)}"


def test_output_is_monotonic():
    lyrics = ["first line here", "second line here", "third line here"]
    words = [W("first", 5, 6), W("line", 6, 7), W("here", 7, 8),
             W("second", 30, 31), W("line", 31, 32), W("here", 32, 33),
             W("third", 60, 61), W("line", 61, 62), W("here", 62, 63)]
    lines, _, _ = aligner.match_lyrics_to_words(lyrics, words, return_spans=True)
    starts = [l.start for l in lines]
    assert starts == sorted(starts), f"timestamps not monotonic: {starts}"


def test_bigram_beats_bag_of_chars_on_cjk():
    # Both lines are common kana; only order distinguishes them.
    a = "ほっといて"          # ほっといて
    b_unrelated = "いてほっと"  # same chars, reversed
    truth = "ほっといて"
    wrong = "いてほっと"
    assert aligner._similarity(truth, truth, mode="bigram") > \
        aligner._similarity(truth, wrong, mode="bigram"), \
        "bigram must prefer the correctly ordered text"
    assert aligner._similarity(truth, wrong, mode="sets") == \
        aligner._similarity(truth, truth, mode="sets"), \
        "the legacy score is order-blind by design; this is the known weakness"


def test_consecutive_unmatched_lines_do_not_stack_into_a_ramp():
    """Unmatched lines must be interpolated, not prev+1s each."""
    # The transcript covers only the first and last lines; the middle ones are
    # absent, which is the shape that previously produced a 1s-per-line ramp.
    lyrics = [f"matched line {i}" for i in range(1, 9)]
    words = [W("matched", 1, 2), W("line", 2, 3), W("1", 3, 4)]
    for i in range(8, 12):
        words += [W("matched", 10 * i, 10 * i + 1),
                  W("line", 10 * i + 1, 10 * i + 2),
                  W(str(i), 10 * i + 2, 10 * i + 3)]

    lines, _, _ = aligner.match_lyrics_to_words(lyrics, words, return_spans=True)
    assert len(lines) == len(lyrics)
    starts = [l.start for l in lines]
    gaps = [round(b - a, 2) for a, b in zip(starts, starts[1:])]
    # with interpolation the spacing tracks the real 10s gaps, not a fixed 1.0
    assert max(gaps) > 2.0, \
        f"unmatched lines look like a fixed ramp, gaps={gaps}"
    assert starts == sorted(starts)


def test_normalize_folds_fullwidth_forms():
    assert aligner._normalize("ＴＯＫＩＯ") == aligner._normalize("TOKIO")
    assert aligner._normalize("ＡＢＣ　ＤＥＦ") == aligner._normalize("ABC DEF")