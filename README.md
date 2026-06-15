# Greg Personal Tools

Small personal utilities and agent workflows.

## Tools

- `podcast_transcripts.py`: create local Markdown transcript packages from Apple Podcasts, RSS feed, and direct YouTube URLs.
- `babysit-pr/`: shareable agent skill for taking a GitHub pull request through automated review follow-through to a human merge handoff.

## Podcast Transcripts

Create local Markdown transcript packages from Apple Podcasts, RSS feed, and direct YouTube URLs.

## What It Does

- Uses official RSS `podcast:transcript` links when available.
- Uses direct YouTube transcripts for YouTube URLs when available.
- Falls back to local Whisper transcription from RSS audio enclosures.
- Writes raw transcripts, optional readable derivatives, optional extractive summaries, a batch index, combined transcript files, and failure notes.
- Does not require an LLM API key.

## Setup

```bash
git clone https://github.com/gwh2002/greg_personal_tools.git
cd greg_personal_tools
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

Whisper audio fallback requires `ffmpeg`:

```bash
brew install ffmpeg
```

On Linux, install `ffmpeg` with your system package manager.

## Quick Start

```bash
python3 podcast_transcripts.py \
  --readable \
  --summary \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

```bash
python3 podcast_transcripts.py \
  --batch-slug people-who-plan \
  --latest 5 \
  --readable \
  "https://podcasts.apple.com/ca/podcast/people-who-plan-inside-the-minds-of-modern-operators/id1886794877"
```

Outputs are written by default to:

```text
podcast_transcript_outputs/<batch_slug>/
```

Each successful run writes:

- `index.md`
- `combined_transcripts.md`
- `episodes/*.md`
- `episodes_readable/*.md` when `--readable` is passed
- `summaries/*.md` when `--summary` is passed
- `combined_readable_transcripts.md` when `--readable` is passed
- `combined_summaries.md` when `--summary` is passed
- `failures.md` when one or more URLs fail

## Common Commands

```bash
# Show help
python3 podcast_transcripts.py --help

# Metadata-only dry run
python3 podcast_transcripts.py --dry-run --batch-slug test-batch "https://example.com/feed.xml"

# Process every episode in a feed
python3 podcast_transcripts.py --all --batch-slug full-feed "https://example.com/feed.xml"

# Process episodes after a date
python3 podcast_transcripts.py --since 2026-04-01 --batch-slug recent "https://example.com/feed.xml"

# Use a custom output folder
python3 podcast_transcripts.py --output-root ./outputs --batch-slug batch-name "https://example.com/feed.xml"

# Re-run and overwrite existing outputs
python3 podcast_transcripts.py --force --batch-slug batch-name "https://example.com/feed.xml"
```

You can also install the console command:

```bash
python3 -m pip install -e .
podcast-transcripts --help
```

## Input Types

- Apple Podcasts show URL: processes the latest 5 episodes by default.
- Apple Podcasts episode URL: processes the single episode.
- RSS feed URL: processes the latest 5 feed items by default.
- Direct YouTube URL: processes the single video.
- Text file of URLs: use `--input-file /path/to/urls.txt`.

## Validation

```bash
python3 -m unittest discover -s . -p 'test_*.py'
```

## Archive

The older personal-tools repo contents were moved to `oct_2025/` so the repo root can focus on this utility.
