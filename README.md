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

### Desktop window

Install the dependencies, then run:

```bash
python desktop.py
```

This opens the existing interface in one native application window instead of
an external browser. On Windows, `run_desktop.bat` is a convenient launcher.

To build a standalone Windows application folder, install PyInstaller and run
`build_desktop.bat`. The resulting executable is
`dist\LrcSync\LrcSync.exe`. Whisper models are downloaded on first use and are
not bundled into the executable because they are large.

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
  - `medium` is the default as the best accuracy-per-second on a Japanese
    benchmark scored against LRCLIB. Use `small` for speed, `large-v3` for the
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

`stable-ts` is the default. The expanded 30-track ja/en benchmark below
compares `stable-ts` and `whisper` at `medium`; `stable-ts` wins on the held-out
batch (64.9% vs 60.9% within 1s) and is clearly better on English.

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

The defaults were retuned in October 2026 on a 30-track corpus mixing Japanese
and English: 15 tuning tracks (752 lines) and 15 held-out tracks (726 lines,
all different songs). Audio is the official YouTube video; input lyrics are
LRCLIB's own `plainLyrics`; ground truth is LRCLIB `syncedLyrics`. One constant
offset per track is fitted (maximising inliers, not mean delta) and subtracted
before scoring, so the numbers measure alignment shape rather than the music
video's intro length. A line counts as correct when it lands within 1s of the
reference. Dropped, split or merged lines count as errors.

The selected global matcher config is `similarity_mode=bigram`,
`interpolate_fallback=True`, `accept_threshold=0.4`, `window_pad=12`.
Stable-ts medium scores 73.1% on the tuning batch and 64.9% on the held-out
batch; whisper medium scores 70.2% and 60.9%. Full per-track results:
[docs/benchmark-v2.md](docs/benchmark-v2.md).

### Matching parameters (`medium`, expanded 30-track corpus)

Defaults were retuned in October 2026 on a 15-track ja/en tuning batch
(10 Japanese + 5 English, 752 lines) and validated on a disjoint 15-track
ja/en batch (726 lines). With stable-ts medium the selected config scored
**73.1%** on the tuning batch and **64.9%** on the held-out batch.

| parameter | best | worst | spread |
|---|---|---|---|
| `similarity_mode` | **`bigram` 73.1%** | `sets` 56.1% | **17.0** |
| `accept_threshold` | **0.4 → 73.1%** | 0.1 → 64.9% | 8.3 |
| `window_pad` (internal) | 12 → 73.1% | 5/8 → 68.6% | 4.5 |
| `interpolate_fallback` | on → 73.1% | off → 72.7% | 0.4 |

Character-bigram F1 still dominates everything else combined. On the mixed
corpus a higher threshold helps: low-confidence English matches are worse than
interpolating between neighbours, so 0.4 wins by preventing weak matches from
being accepted.

### Expanded ja/en tuning (30 tracks)

Tuning batch: 752 lines (10 ja + 5 en). Held-out comparison batch: 726 lines
(10 ja + 5 en, all different tracks).

| method | tuning ≤1s | held-out ≤1s | held-out ja | held-out en |
|---|---|---|---|---|
| **`stable-ts`** | **73.14%** | **64.88%** | **69.89%** | **57.39%** |
| `whisper` | 70.21% | 60.88% | 68.97% | 48.80% |

`stable-ts` wins on the held-out batch and is clearly better on English
(+8.6 points). The tuning gain generalizes: +9.2 points on the tuning batch,
+7.4 on the held-out batch. The held-out set was not curated after scoring;
three tracks (FantasticYouth English version, Bruno Mars' *Uptown Funk*, Adele's
*Rolling in the Deep*) remain reference/version mismatches and pull the English
average down. Full per-track breakdown: [docs/benchmark-v2.md](docs/benchmark-v2.md).

### Caveats

- **LRCLIB is machine-generated, not human-verified.** Scoring against it partly
  means reproducing another model's errors. Some lines sit where our transcript
  says while LRCLIB says otherwise — a reference-side error no aligner can fix.
- **Music-video audio vs the studio master.** Offset removal absorbs a constant
  shift but not a different edit. Expect problems on short versions, live
  recordings, or creditless openings; a few English tracks in this corpus are
  known version mismatches.
- **English is harder than Japanese.** Held-out accuracy is 57.4% for English
  vs 69.9% for Japanese with stable-ts medium. English transcripts and LRCLIB
  references diverge more, especially on live/lyric-video uploads.
- Roughly 24% of lines in a wider run had their text absent from the Whisper
  transcript entirely, which no matching change can recover.
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
