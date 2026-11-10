# Benchmark v3 — lrc.red ground truth, 30 new tracks (20 ja, 10 en)

Config: stable-ts / `medium` with the README defaults (`similarity_mode=bigram`,
`interpolate_fallback=True`, `accept_threshold=0.4`, `window_pad=12`). No tuning.

Ground truth: lrc.red synced lyrics (`https://lrc.red/s/{ISRC}.lrc`). ISRCs came
from MusicBrainz recording search. Input lyrics: lrc.red's own lines with
timestamps removed, so the input line count equals the reference line count.
Audio: YouTube, chosen by title and duration match (see Method). A line counts
as correct if it lands within 1s of the reference after one constant offset
per track is fitted and removed. Unmatched lines count as errors.

## Summary

| slice | tracks | lines | mean ≤1s | median ≤1s | weighted ≤1s |
|---|---|---|---|---|---|
| ja | 20 | 1,001 | 63.22% | 67.94% | 58.59% |
| en | 10 | 460 | 44.51% | 41.90% | 47.31% |
| all | 30 | 1,461 | 56.98% | 63.12% | — |

Tracks ≥70%: 8. Tracks <30%: 4 (see Caveats).

Context only: benchmark-v2 (LRCLIB ground truth, LRCLIB plain input, different
songs) gave stable-ts medium 69.9% ja / 57.4% en held-out. The ground truth and
inputs differ, so these numbers are not directly comparable.

## Per-track (stable-ts medium)

| id | lang | track | ≤1s | offset | median abs err | lines | YouTube title |
|---|---|---|---|---|---|---|---|
| ja02 | ja | YOASOBI — アイドル | 11.1% | -42.59s | 22.47s | 108 | YOASOBI「アイドル」 (Official Music Video) |
| ja05 | ja | RADWIMPS — すずめ | 69.2% | -0.17s | 0.59s | 26 | RADWIMPS - Suzume feat. Toaka [Official Lyric Video] |
| ja06 | ja | Mrs. GREEN APPLE — ダンスホール | 60.0% | 0.95s | 0.49s | 45 | ダンスホール - Mrs. GREEN APPLE【日本語字幕/歌詞】 |
| ja07 | ja | LiSA — 炎 | 78.4% | 0.16s | 0.37s | 37 | 「Homura (炎) - LiSA」KAN/ENG/ROMAJI LYRICS |
| ja08 | ja | Creepy Nuts — 二度寝 | 67.5% | 0.45s | 0.31s | 83 | 【English Lyric Video】Creepy Nuts - Nidone |
| ja09 | ja | Official髭男dism — パラボラ | 84.4% | 0.43s | 0.27s | 32 | Official髭男dism - パラボラ［Official Video］ |
| ja10 | ja | back number — 水平線 | 79.0% | 0.34s | 0.20s | 38 | Back Number – Suiheisen (水平線) [official music video] |
| ja11 | ja | Mrs. GREEN APPLE — 春愁 | 68.4% | 1.26s | 0.37s | 38 | 春愁 - Mrs. GREEN APPLE 【日本語字幕・歌詞動画】 |
| ja12 | ja | Official髭男dism — Pretender | 61.1% | 0.06s | 0.42s | 54 | Official髭男dism - Pretender［Official Video］ |
| ja13 | ja | RADWIMPS — 前前前世 | 65.1% | 1.96s | 0.28s | 43 | RADWIMPS - Zen Zen Zense / 前前前世 Lyric AMV |
| ja14 | ja | Mrs. GREEN APPLE — ケセラセラ | 48.8% | 0.97s | 1.08s | 41 | ケセラセラ - Mrs. GREEN APPLE【日本語字幕/歌詞】 |
| ja15 | ja | Vaundy — 怪獣の花唄 | 50.0% | 0.20s | 0.95s | 72 | Vaundy - 怪獣の花唄 (Kaijuu No Hanauta) |
| ja16 | ja | YOASOBI — 夜に駆ける | 92.9% | 1.03s | 0.14s | 56 | 夜に駆ける |
| ja17 | ja | back number — 高嶺の花子さん | 69.1% | 5.09s | 0.47s | 42 | 【歌詞付き】高嶺の花子さん - back number |
| ja18 | ja | Official髭男dism — Subtitle | 93.2% | 0.22s | 0.10s | 59 | Official髭男dism - Subtitle [Official Audio] |
| ja19 | ja | Mrs. GREEN APPLE — 青と夏 | 78.7% | 1.28s | 0.35s | 61 | Mrs. GREEN APPLE – 「青と夏」 Official Lyric Video |
| ja20 | ja | King Gnu — 白日 | 79.3% | 1.11s | 0.20s | 82 | King Gnu - 白日 |
| ja22 | ja | 有心論 (ISRC listed as RADWIMPS; video is ZUTOMAYO) | 44.7% | -4.55s | 1.05s | 38 | ずっと真夜中でいいのに。 / ZUTOMAYO - 有心論 [Audio] |
| ja23 | ja | BUMP OF CHICKEN — 天体観測 | 51.4% | -12.66s | 1.00s | 35 | BUMP OF CHICKEN「天体観測」スペシャルMV |
| ja24 | ja | YOASOBI — ハルジオン | 12.1% | -53.00s | 20.20s | 99 | YOASOBI「ハルジオン」Official Music Video |
| en01 | en | Cat Stevens — The Wind | 66.7% | -2.23s | 0.95s | 12 | The Wind |
| en02 | en | Hiatus Kaiyote — Red Room | 7.1% | 0.26s | 61.40s | 42 | Hiatus Kaiyote - 'Red Room' (Official Video) |
| en03 | en | Audien — Message | 9.1% | 6.58s | 37.86s | 11 | Audien - Message (Audio) |
| en05 | en | Billie Eilish — bad guy | 65.6% | 0.08s | 0.30s | 64 | Billie Eilish - bad guy (Audio) |
| en07 | en | a-ha — Take On Me | 34.7% | 0.35s | 8.80s | 49 | a-ha - Take On Me (2023 Remastered) |
| en08 | en | The Weeknd — Blinding Lights | 40.5% | 0.33s | 3.04s | 37 | The Weeknd - Blinding Lights (Official Audio) |
| en09 | en | Harry Styles — As It Was | 41.9% | 0.57s | 3.02s | 43 | Harry Styles - As It Was (Official Audio) |
| en10 | en | Olivia Rodrigo — drivers license | 80.0% | -29.59s | 0.39s | 50 | Olivia Rodrigo - drivers license (Official Video) |
| en11 | en | Billie Eilish — Ocean Eyes | 41.9% | 0.12s | 1.34s | 31 | Billie Eilish - Ocean Eyes (Official Audio) |
| en12 | en | Lewis Capaldi — Someone You Loved | 57.6% | 1.00s | 0.65s | 33 | Lewis Capaldi - Someone You Loved (Official Audio) |

## Method

1. Candidate songs were taken in order from a hand-written list and kept only if
   MusicBrainz returned an ISRC and lrc.red had synced lyrics for it. The first
   20 JA and 10 EN that passed the checks below were kept. Reserves replaced
   tracks that failed.
2. YouTube search (`artist + title`, with and without "official audio"). Results
   were kept only when the video title contained the track title (Japanese or
   romaji), was not a live/cover/reaction/concert upload, and had a duration
   within 6s (or 15s) of the MusicBrainz length.
3. Five picks were wrong-version and dropped after manual title review: ja01
   (a different video), ja03 (a dance cover), ja21 (a live "First Take" recording),
   en04 (a GRAMMYs performance) and en06 (a Glastonbury live set). Replacements
   came from the reserve list in order. ja04 and ja19 needed a second pass
   (ja04 never found a verified match and was skipped).

## Caveats

- Title and duration matching is a heuristic. Several picks are lyric videos
  or fan videos (e.g. ja13 "Lyric AMV", ja08 "English Lyric Video"). Their
  audio is still the studio track, but this was not verified beyond the title.
- Low scores are not all aligner failures. ja02, ja24, en02 and en03 have large
  fitted offsets or median errors of 20s+. These may be version or timeline
  mismatches that were not investigated, so treat them as unexplained.
- Several runs logged "over 25% of lyric lines did not match", which triggers
  the +1s fallback. That fallback is most likely behind the very low scores.
- ja22's MusicBrainz record listed a different artist. The video matched the
  correct artist (ZUTOMAYO), so the track was kept.
- Each song is one track, one run, one model size. No significance testing.
