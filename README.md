# LRC Sync

Sync lyrics with audio to create LRC files using Whisper forced alignment.

## Features

- **Audio file or YouTube URL** as input (auto-download via yt-dlp)
- **Whisper transcription** (faster-whisper) with word-level timestamps
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
- `--model` / `-m`: Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`). Default: `small`
- `--language`: Language code (e.g., `en`, `ja`). Auto-detect if omitted
- `--offset`: Time offset in seconds (positive = lyrics appear later)

### Check an LRCLIB entry

```bash
python check_publish.py --artist "Artist" --track "Song" --duration 215
```

## API

- `POST /api/jobs` — start an alignment job (file or YouTube URL), returns `{"job_id"}`
- `GET /api/jobs/{id}` — poll `{stage, percent, message, lrc, error}`
- `POST /api/publish` — publish LRC to LRCLIB
- Legacy: `POST /api/align`, `POST /api/youtube`

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
