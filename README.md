# LRC Sync

Sync lyrics with audio to create LRC files using forced alignment (stable-ts
or Whisper).

## Features

- **Audio file or YouTube URL** as input (auto-download via yt-dlp)
- **Whisper transcription** (faster-whisper) with word-level timestamps
- **Multiple alignment backends** — stable-ts (default) and Whisper
- **Fuzzy lyric alignment**, including character-level matching for Japanese/Chinese/Korean
- **Web UI** with live progress bar (download → transcribe → match)
- **Publish to [LRCLIB](https://lrclib.net)** (handles its proof-of-work challenge automatically)
- **CLI** for scripting

## Requirements

- Python 3.10+
- ffmpeg (for audio conversion) — place a build in the project folder
  (e.g. from https://www.gyan.dev/ffmpeg/builds/) or install it on PATH

## Installation

```bash
pip install -r requirements.txt
```

`stable-ts` is a required dependency and is installed by
`requirements.txt`; no extra step is needed.

## Usage

### Web UI

```bash
python server.py
```

Opens http://127.0.0.1:8000 in your browser automatically
(`--no-browser` to skip).

1. Upload an audio file **or** paste a YouTube URL
2. Enter lyrics, pick a model, click Generate LRC (progress bar included)
3. Download the `.lrc`, or fill in song/artist/duration and Upload to LRCLIB

### CLI

```bash
# From a local file
python cli.py --audio song.mp3 --lyrics lyrics.txt --output song.lrc

# From YouTube
python cli.py --youtube "https://www.youtube.com/watch?v=..." --lyrics lyrics.txt

# Publish the result to LRCLIB
python cli.py --audio song.mp3 --lyrics lyrics.txt \
    --publish --track "Song" --artist "Artist" --duration 215
```

Options:
- `--model` / `-m`: Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`, plus English-only `tiny.en`, `base.en`, `small.en`, `medium.en`). Default: `medium`
  - Disclaimer: `.en` models are English-only — they transcribe non-English lyrics/audio poorly. Use a multilingual model for ja/zh/ko/etc.
  - `medium` is the default. Use `small` for speed, `large-v3` for the
    highest accuracy if you can wait for it (~4x slower than `medium` on CPU).
- `--language`: Language code (e.g., `en`, `ja`). Auto-detect if omitted
- `--offset`: Time offset in seconds (positive = lyrics appear later)
- `--beam-size`: Whisper beam size. Default: `5`
- `--similarity`: line matching score, `bigram` (default) | `sets` | `both`
- `--method`: alignment backend, `stable-ts` (default) | `whisper`
- `--accept-threshold`: minimum score to accept a line. Default: `0.4`
- `--no-interpolate`: place unmatched lines at previous+1s instead of
  interpolating between matched neighbours

Matching notes: the default `bigram` score is order-sensitive, which matters a
lot for CJK — the older `sets` score is a bag of characters, so a short line of
common kana matches almost anything. Lines scoring below `--accept-threshold`
are placed by interpolating between their nearest matched neighbours, which
avoids the old compounding "previous line + 1s" ramp. Pass `--similarity sets
--no-interpolate` to restore the previous behaviour.

### Alignment methods

`stable-ts` is the default. Only `stable-ts` was measured in the v3 benchmark
below; the `whisper` backend's last comparison (v2, different ground truth) is
in [docs/benchmark-v2.md](docs/benchmark-v2.md).

- `stable-ts` (default): stable-ts transcription with word-level timestamps.
- `whisper`: faster-whisper transcription + the fuzzy matcher above. Works
  offline from the local model cache.

Select with `--method` (CLI) or the **Alignment method** dropdown (web UI).

### Check an LRCLIB entry

```bash
python check_publish.py --artist "Artist" --track "Song" --duration 215
```

## API

- `POST /api/jobs` — start an alignment job (file or YouTube URL), returns `{"job_id"}`; accepts an optional `method` field (`stable-ts`/`whisper`)
- `GET /api/jobs/{id}` — poll `{stage, percent, message, lrc, error}`
- `POST /api/publish` — publish LRC to LRCLIB
- Legacy: `POST /api/align`, `POST /api/youtube`

## Accuracy benchmark

Latest run (v3): 30 new tracks, 20 Japanese and 10 English, stable-ts with
`medium` and the defaults above. Ground truth is lrc.red synced lyrics. Input
lyrics are lrc.red's own plain lines. Audio comes from YouTube. One constant
offset per track is fitted and removed before scoring. A line counts as correct
within 1s of the reference. Unmatched or dropped lines count as errors.

| slice | tracks | lines | mean ≤1s | median ≤1s | weighted ≤1s |
|---|---|---|---|---|---|
| Japanese | 20 | 1,001 | 63.2% | 67.9% | 58.6% |
| English | 10 | 460 | 44.5% | 41.9% | 47.3% |
| All | 30 | 1,461 | 57.0% | 63.1% | — |

Per-track results, YouTube sources and method: [docs/benchmark-v3.md](docs/benchmark-v3.md).

Two things to keep in mind:

- **Results are not comparable to earlier runs.** v2 used LRCLIB as ground
  truth and LRCLIB plain lyrics as input, on different songs. Its numbers
  (stable-ts medium: 69.9% Japanese, 57.4% English held-out) are in
  [docs/benchmark-v2.md](docs/benchmark-v2.md).
- **The v3 result is noisy.** Several tracks scored below 15% with large
  fitted offsets or 20s+ median errors. These are not yet explained (see the
  caveats in the v3 doc). Treat the per-track numbers as indicative.

### Matching parameters

The defaults used here (`similarity_mode=bigram`, `interpolate_fallback=True`,
`accept_threshold=0.4`, `window_pad=12`) were chosen on the v2 tuning corpus
(LRCLIB ground truth). The full sweep is in
[docs/benchmark-v2.md](docs/benchmark-v2.md). v3 did not re-tune them.

### Caveats

- **Ground truth is machine-generated.** lrc.red lyrics are timed by a
  tool, not by hand. Scoring against them partly means reproducing that
  tool's errors.
- **Music-video audio vs the studio master.** Offset removal absorbs a constant
  shift but not a different edit. Expect problems on short versions, live
  recordings, creditless openings, and lyric-video or fan-edit uploads.
- **Audio selection is heuristic.** v3 matched YouTube videos by title and
  duration, then hand-removed wrong versions (covers, live takes, and
  reaction videos). A few wrong-version picks may remain.
- **English is harder than Japanese** in both v2 and v3 (44.5% vs 63.2% mean
  in v3).
- Roughly 24% of lines in a wider v2 run had their text absent from the
  Whisper transcript entirely, which no matching change can recover.
- `test/test_match_invariants.py` covers line-count parity, monotonicity, order
  preservation and the ramp regression without needing a golden LRC file.
- `--separate-vocals` (Demucs) is **not** recommended as a default: it can
  delete words it mistakes for instruments, at ~200s of CPU per track.

## How it works

1. YouTube URL? Download audio-only via yt-dlp
2. Audio converted to 16kHz mono WAV via ffmpeg
3. faster-whisper transcribes with word-level timestamps (VAD off — it deletes sung vocals)
4. Fuzzy matcher aligns lyric lines to word timestamps (CJK-aware)
5. Post-processing: offset adjustment + merging + monotonic timestamps
6. Output as standard LRC format

## Supported Audio Formats

MP3, WAV, FLAC, M4A, OGG, and anything ffmpeg supports.

## License

MIT
