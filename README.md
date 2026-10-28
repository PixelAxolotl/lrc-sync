# LRC Sync

Sync lyrics with audio to create LRC files using forced alignment (Whisper,
WhisperX, or stable-ts).

## Features

- **Audio file or YouTube URL** as input (auto-download via yt-dlp)
- **Whisper transcription** (faster-whisper) with word-level timestamps
- **Multiple alignment backends** — Whisper (default), WhisperX (wav2vec2
  forced alignment), and stable-ts
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

Optional alignment backends are installed from the repo root (the package is not
published to PyPI, so do not use `pip install lrc-sync[...]`):

```bash
pip install -e .[stable-ts]
# or
pip install -e .[whisperx]
```

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
  - `medium` is the default as the best accuracy-per-second on a Japanese
    benchmark scored against LRCLIB. Use `small` for speed, `large-v3` for the
    highest accuracy if you can wait for it (~4x slower than `medium` on CPU).
- `--language`: Language code (e.g., `en`, `ja`). Auto-detect if omitted
- `--offset`: Time offset in seconds (positive = lyrics appear later)
- `--beam-size`: Whisper beam size. Default: `5`
- `--similarity`: line matching score, `bigram` (default) | `sets` | `both`
- `--method`: alignment backend, `whisper` (default) | `whisperx` | `stable-ts`
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

Benchmarked on the same 5 Japanese tracks (207 lines) used for the model
comparison above, with the `medium` model and the legacy matcher defaults
(`accept_threshold=0.2`, `window_pad=8`). The current 0.4/12 defaults are
benchmarked on the expanded corpus below.

| method | lines within 1s | within 2s | median error |
|---|---|---|---|
| `whisper` (default) | 87.4% | 92.3% | 0.39s |
| `stable-ts` | 90.3% | 95.7% | 0.33s |
| `whisperx` | 34.8% | 45.4% | 2.88s |

`stable-ts` edges out the default on this sample (and on every track), while
`whisperx` is far behind here — its pyannote VAD treats sung vocals as
non-speech on several tracks, leaving too few words to align. WhisperX may
still help on speech-like or well-separated vocal tracks.

The same comparison across all six model sizes (Japanese, 5 tracks, legacy
matcher defaults):

| model | whisper | stable-ts |
|---|---|---|
| `tiny` | 63.8% | 70.1% |
| `base` | 74.9% | 75.9% |
| `small` | 83.6% | 84.5% |
| **`medium`** (default) | **87.4%** | **90.3%** |
| `large-v3-turbo` | 79.7% | 82.1% |
| `large-v3` | 79.2% | 88.4% |

`stable-ts` improves every model size; `large-v3` under stable-ts (88.4%)
nearly matches `medium` stable-ts (90.3%) while `medium` stays ~4× faster.
`whisperx` was only benchmarked on `medium` (34.8%) and is not recommended
on this corpus.

- `whisper` (default): faster-whisper transcription + the fuzzy matcher above.
  Works offline from the local model cache.
- `whisperx`: Whisper transcription followed by wav2vec2 forced alignment.
  Requires the align model
  (`jonatasgrosman/wav2vec2-large-xlsr-53-japanese`, cached locally) and
  pyannote-audio.
- `stable-ts`: stable-ts transcription with word-level timestamps.

Select with `--method` (CLI) or the **Alignment method** dropdown (web UI).
Optional backends are installed from the repo root:

```bash
pip install -e .[whisperx]
# or
pip install -e .[stable-ts]
```

### Check an LRCLIB entry

```bash
python check_publish.py --artist "Artist" --track "Song" --duration 215
```

## API

- `POST /api/jobs` — start an alignment job (file or YouTube URL), returns `{"job_id"}`; accepts an optional `method` field (`whisper`/`whisperx`/`stable-ts`)
- `GET /api/jobs/{id}` — poll `{stage, percent, message, lrc, error}`
- `POST /api/publish` — publish LRC to LRCLIB
- Legacy: `POST /api/align`, `POST /api/youtube`

## Accuracy benchmark

The current defaults were retuned in October 2026 on a 30-track ja/en corpus;
see **Expanded ja/en tuning** below. The tables in this historical section use
the previous defaults (`accept_threshold=0.2`, `window_pad=8`), chosen by
scoring generated LRC timestamps against [LRCLIB](https://lrclib.net) synced
lyrics. They use 5 Japanese tracks (207 lyric lines) drawn from a Spotify
playlist, spanning orchestral pop, avant-garde art pop, josei rock, funk/soul
and post-rock, then validated on a wider 19-track Japanese corpus (813 lines,
one track per artist) to check for overfitting:

| slice | lines | ORIGINAL | TUNED | delta |
|---|---|---|---|---|
| core 5 | 207 | 81.2% | 87.4% | +6.3 |
| validation 14 | 606 | 72.4% | 81.2% | +8.8 |
| **all 19** | **813** | **74.7%** | **82.8%** | **+8.1** |

The tuned matcher improves every slice, and the gain is *larger* on the
held-out 14 tracks than on the 5 used for tuning (+8.8 vs +6.3), so the
change generalizes rather than fitting this sample.

A further run on an expanded 29-track corpus (1384 lines) mixing Japanese
with English/K-pop tracks showed how much the benchmark depends on the
language the model was tuned for: `small` scored 61.2% (tuned) overall, with
the English/K-pop tracks (Taylor Swift, Coldplay, BLACKPINK, …) collapsing
to 4–20% because the Whisper transcripts and the LRCLIB references diverge
on those recordings. That run predates the October 2026 retune; the current
30-track ja/en corpus below is the representative one. Non-Japanese audio is
now benchmarked, but English scores lower than Japanese and a few references
remain version mismatches.

**Method.** Audio is the official YouTube video; input lyrics are LRCLIB's own
`plainLyrics`. One constant offset per track is fitted (maximising inliers, not
mean delta) and subtracted before scoring, so the numbers measure alignment
shape rather than the music video's intro length. A line counts as correct when
it lands within 1s of the reference. Lines the aligner drops, splits or merges
count as errors.

Scores are reproducible with `python temp/bench/readme_bench.py` (see
`temp/bench/RESULTS.md`); re-running after a code change is a valid regression
check. Runtimes are from a cold cache — a warm one reports ~1s per model.

See **Alignment methods** (below) for a comparison of the Whisper / WhisperX /
stable-ts backends on the same tracks.

### Model comparison (5-track Japanese corpus, legacy defaults)

> These numbers use the previous matcher defaults (`accept_threshold=0.2`,
> `window_pad=8`) and are kept as historical context. The shipped defaults are
> now `accept_threshold=0.4`, `window_pad=12`, tuned on the expanded ja/en
> corpus below.

| model | lines within 1s | within 2s | median error | max error | 5-track time |
|---|---|---|---|---|---|
| `tiny` | 63.8% | 77.8% | 0.77s | 17.5s | 1m |
| `base` | 74.9% | 86.5% | 0.62s | 10.5s | 3m |
| `small` | 83.6% | 91.8% | 0.48s | 20.3s | 5m |
| **`medium`** (default) | **87.4%** | **92.3%** | 0.39s | 14.8s | ~4m |
| `large-v3-turbo` | 79.7% | 86.5% | 0.45s | 19.9s | 9m |
| `large-v3` | 79.2% | 85.5% | **0.31s** | 17.4s | 17m |

`medium` scores highest despite `large-v3` being the larger model, and it is
~3x faster. `large-v3` does produce the smallest median error, so it is the
choice if you care about typical rather than worst-case accuracy — but on this
sample it loses more on hard tracks than it gains.

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
interpolating between neighbours. On the earlier Japanese-only 5-track sample
0.4 was worse (79.2% vs 87.4%), so the new default trades a little CJK headroom
for mixed-language robustness.

### Expanded ja/en tuning (30 tracks)

| method | tuning ≤1s | held-out ≤1s | held-out ja | held-out en |
|---|---|---|---|---|
| **`stable-ts`** | **73.14%** | **64.88%** | **69.89%** | **57.39%** |
| `whisper` | 70.21% | 60.88% | 68.97% | 48.80% |

`stable-ts` wins on the held-out batch and is clearly better on English
(+8.6 points). The tuning gain generalizes: +9.2 points on the tuning batch,
+7.4 on the held-out batch. The held-out set was not curated after scoring;
three tracks (FantasticYouth English version, Bruno Mars' *Uptown Funk*, Adele's
*Rolling in the Deep*) remain reference/version mismatches and pull the English
average down. See `temp/bench/v2_final_report.md` for per-track results.

### Old matcher vs tuned matcher, per model (5-track Japanese corpus, legacy defaults)

| model | original | current | delta |
|---|---|---|---|
| `tiny` | 48.8% | 63.8% | **+15.0** |
| `base` | 64.3% | 74.9% | +10.6 |
| `small` | 77.3% | 83.6% | +6.3 |
| `medium` | 80.2% | 87.4% | +7.3 |
| `large-v3-turbo` | 76.3% | 79.7% | +3.4 |
| `large-v3` | 75.4% | 79.2% | +3.9 |

The matching improvements help every model, and help most where the model is
weakest — they raise the floor rather than substitute for a bigger model.

### Caveats

- **5 tracks / 207 lines is a small sample**, and they are not independent
  (four are 2025–26 anime tie-ins). A wider 19-track run put the tuning gain at
  +8.0 points overall, and *larger* on the 14 tracks never used for tuning
  (+8.6 vs +6.3 on these five) — so the change generalizes rather than fitting
  this sample.
- **LRCLIB is machine-generated, not human-verified.** Scoring against it partly
  means reproducing another model's errors. On an earlier attribution pass,
  ~5% of lines sat where our transcript said while LRCLIB said otherwise —
  a reference-side error no aligner can fix.
- **Music-video audio vs the studio master.** Offset removal absorbs a constant
  shift but not a different edit. Every track here is duration-matched, so this
  is controlled rather than proven; expect problems on short versions, live
  recordings, or creditless openings.
- **Japanese only.** All measurements are CJK. The bigram score changes
  non-CJK behaviour and was not tested on English.
- Roughly 24% of lines in a wider run had their text absent from the Whisper
  transcript entirely, which no matching change can recover.
- A previously shipped end-to-end test compared output against a hand-maintained
  golden LRC. It was deleted: it needed the network plus a multi-minute Whisper
  run per model, and its golden file had drifted — it placed one line inside a
  neighbour's time slot, which all six models independently disagreed with by
  ~18s. `test/test_match_invariants.py` now covers the properties that actually
  matter (line-count parity, monotonicity, order preservation, the ramp
  regression) without needing a golden file.
- `--separate-vocals` (Demucs) is **not** recommended as a default: measured
  across these 5 tracks it netted −2.9 points, helping one track (+9.3) and
  hurting four (−1.7 to −12.0) by deleting words it mistook for instruments,
  at ~200s of CPU per track.

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
