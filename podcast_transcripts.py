#!/usr/bin/env python3
"""Build local Markdown transcript packages from podcast and YouTube URLs."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "podcast_transcript_outputs"
USER_AGENT = "podcast-transcripts/1.0"
APPLE_LOOKUP_URL = "https://itunes.apple.com/lookup"

TRANSCRIPT_OFFICIAL_RSS = "official_rss_transcript"
TRANSCRIPT_OFFICIAL_CAPTION = "official_caption"
TRANSCRIPT_YOUTUBE_DIRECT = "youtube_direct_transcript"
TRANSCRIPT_LOCAL_WHISPER = "local_whisper"
TRANSCRIPT_FAILED = "failed"
TRANSCRIPT_DRY_RUN = "dry_run"

FILLER_PHRASES = [
    "um",
    "uh",
    "ah",
    "you know",
    "i mean",
    "i think",
    "i guess",
    "i don't know",
    "i suppose",
    "at least",
    "sort of",
    "kind of",
    "basically",
    "essentially",
    "obviously",
    "honestly",
    "literally",
    "actually",
    "it's like",
    "is like",
    "was like",
    "are like",
    "were like",
    "i'm like",
    "he's like",
    "she's like",
    "they're like",
    "we're like",
    "you're like",
]

FILLER_WORDS = ["like", "just"]

FILLER_PREFIX_RE = re.compile(
    r"^(?:(?:yeah|yes|yep|so|and|but|oh|well|right|okay|ok|no)"
    r"(?:\.\s*|\,\s*|\s+))+",
    re.IGNORECASE,
)


def remove_phrase(text: str, phrase: str) -> str:
    escaped = re.escape(phrase)
    text = re.sub(rf"(?i)^\s*{escaped}(?:\s*,\s*|\s+)", "", text)
    text = re.sub(rf"(?i)\s*,\s*{escaped}\s*,\s*", ", ", text)
    text = re.sub(rf"(?i)\s+{escaped}\s*([,.!?])", r"\1", text)
    text = re.sub(rf"(?i)\s+{escaped}\s+", " ", text)
    text = re.sub(rf"(?i)\s+{escaped}\s*$", "", text)
    return text


def remove_word(text: str, word: str) -> str:
    escaped = re.escape(word)
    text = re.sub(rf"(?i)^\s*{escaped}(?:\s*,\s*|\s+)", "", text)
    text = re.sub(rf"(?i)\s*,\s*{escaped}(?:\s*,\s*|\s+)", ", ", text)
    text = re.sub(rf"(?i)\s+{escaped}\s*,\s*", ", ", text)
    return text


def normalize_disfluency_text(text: str) -> str:
    text = re.sub(r",\s*,", ", ", text)
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"\.\s*,", ".", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,\.\?!])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"^\s*[,.]+\s*", "", text)
    return text.strip()


def disfluency_cleanup(text: str) -> str:
    original = text
    cleaned = text
    for phrase in FILLER_PHRASES:
        cleaned = remove_phrase(cleaned, phrase)
    for word in FILLER_WORDS:
        cleaned = remove_word(cleaned, word)
    cleaned = re.sub(
        r"(?i)\s+like\s+(?!this\b|that\b|these\b|those\b)",
        " ",
        cleaned,
    )
    cleaned = normalize_disfluency_text(cleaned)
    cleaned = FILLER_PREFIX_RE.sub("", cleaned)
    cleaned = normalize_disfluency_text(cleaned)
    if cleaned and original and original[0].isupper() and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


@dataclass
class TranscriptLink:
    url: str
    mime_type: str = ""
    language: str = ""
    rel: str = ""


@dataclass
class Episode:
    show: str
    title: str
    published_date: str = ""
    input_url: str = ""
    feed_url: str = ""
    audio_url: str = ""
    duration: str = ""
    guid: str = ""
    episode_id: str = ""
    description: str = ""
    episode_url: str = ""
    host: str = ""
    transcript_links: list[TranscriptLink] = field(default_factory=list)


@dataclass
class TranscriptResult:
    episode: Episode
    status: str
    transcript_source: str
    confidence: str
    transcript_text: str
    output_path: Path | None = None
    readable_output_path: Path | None = None
    summary_output_path: Path | None = None
    readable_text: str = ""
    summary_text: str = ""
    failure_reason: str = ""
    retry_suggestion: str = ""


@dataclass
class TranscriptSegment:
    timestamp: str
    seconds: int | None
    text: str


class PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        text = " ".join(self.parts)
        text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return html.unescape(text).strip()


def slugify(text: str, max_len: int = 80) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "_", slug).strip("_")
    return (slug[:max_len].strip("_") or "untitled")


def request_bytes(url: str, *, timeout: int = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            return resp.read(), content_type
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc.reason):
            raise
        # Some macOS Python installs do not have a usable local CA bundle.
        # These podcast fetches are public metadata/audio reads and carry no credentials.
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            content_type = resp.headers.get("Content-Type", "")
            return resp.read(), content_type


def request_text(url: str, *, timeout: int = 60) -> tuple[str, str]:
    raw, content_type = request_bytes(url, timeout=timeout)
    charset_match = re.search(r"charset=([^;\s]+)", content_type, flags=re.I)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    return raw.decode(encoding, errors="replace"), content_type


def parse_apple_podcast_url(url: str) -> dict[str, str | None]:
    podcast_id_match = re.search(r"/id(\d+)", url)
    episode_id_match = re.search(r"[?&]i=(\d+)", url)
    if not podcast_id_match:
        raise ValueError(f"Could not extract Apple Podcasts show ID from URL: {url}")
    return {
        "podcast_id": podcast_id_match.group(1),
        "episode_id": episode_id_match.group(1) if episode_id_match else None,
    }


def is_apple_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return "podcasts.apple.com" in host or "itunes.apple.com" in host


def is_youtube_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(domain in host for domain in ("youtube.com", "youtu.be"))


def looks_like_rss_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    return path.endswith((".xml", ".rss")) or "rss" in path or "feed" in path


def extract_youtube_video_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        video_id = parsed.path.strip("/").split("/")[0]
    elif parsed.path == "/watch":
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/"):
        video_id = parsed.path.strip("/").split("/")[1]
    else:
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    if not video_id:
        raise ValueError(f"Could not extract YouTube video ID from URL: {url}")
    return video_id


def fetch_youtube_metadata(url: str) -> dict[str, str]:
    oembed_url = (
        "https://www.youtube.com/oembed?format=json&url="
        + urllib.parse.quote(url, safe="")
    )
    text, _ = request_text(oembed_url, timeout=30)
    data = json.loads(text)
    if not isinstance(data, dict):
        return {}
    return {
        "title": clean_text(str(data.get("title", ""))),
        "author_name": clean_text(str(data.get("author_name", ""))),
    }


def resolve_youtube_url(url: str) -> Episode:
    video_id = extract_youtube_video_id(url)
    title = f"YouTube video {video_id}"
    show = "YouTube"
    try:
        metadata = fetch_youtube_metadata(url)
        title = metadata.get("title") or title
        show = metadata.get("author_name") or show
    except Exception:
        pass
    return Episode(
        show=show,
        title=title,
        input_url=url,
        episode_url=url,
        episode_id=video_id,
        guid=video_id,
    )


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if local_name(child.tag) == name:
            return clean_text(child.text or "")
    return ""


def children_by_local_name(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if local_name(child.tag) == name]


def parse_duration(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if value.isdigit():
        seconds = int(value)
        return format_timestamp(seconds)
    return value


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_timestamp_seconds(value: str) -> int | None:
    parts = value.strip().split(":")
    if not parts or not all(part.replace(".", "", 1).isdigit() for part in parts):
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
    elif len(numbers) == 2:
        hours = 0.0
        minutes, seconds = numbers
    else:
        hours = 0.0
        minutes = 0.0
        seconds = numbers[0]
    return int(hours * 3600 + minutes * 60 + seconds)


def parse_pub_date(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(value)
        return parsed.date().isoformat()
    except Exception:
        pass
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return iso_match.group(1) if iso_match else value


def fetch_apple_lookup(podcast_id: str, *, limit: int = 300) -> dict:
    params = urllib.parse.urlencode(
        {"id": podcast_id, "entity": "podcastEpisode", "limit": str(limit)}
    )
    text, _ = request_text(f"{APPLE_LOOKUP_URL}?{params}", timeout=30)
    data = json.loads(text)
    if not data.get("results"):
        raise ValueError(f"No iTunes lookup results for podcast ID {podcast_id}")
    return data


def apple_lookup_metadata(podcast_id: str) -> tuple[dict, list[dict]]:
    data = fetch_apple_lookup(podcast_id)
    results = data.get("results", [])
    return results[0], results[1:]


def parse_rss_feed(feed_url: str, *, input_url: str = "") -> list[Episode]:
    text, _ = request_text(feed_url, timeout=60)
    return parse_rss_text(text, feed_url=feed_url, input_url=input_url or feed_url)


def parse_rss_text(text: str, *, feed_url: str, input_url: str = "") -> list[Episode]:
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    channel = next((child for child in root.iter() if local_name(child.tag) == "channel"), None)
    if channel is None:
        raise ValueError("Invalid RSS feed: no channel element")

    show = child_text(channel, "title")
    host = child_text(channel, "author") or child_text(channel, "managingEditor")
    episodes: list[Episode] = []
    for item in [child for child in channel if local_name(child.tag) == "item"]:
        title = child_text(item, "title") or "Untitled episode"
        enclosure = next(
            (child for child in item if local_name(child.tag) == "enclosure"),
            None,
        )
        audio_url = urllib.parse.urljoin(feed_url, enclosure.get("url", "")) if enclosure is not None else ""
        transcript_links = [
            TranscriptLink(
                url=urllib.parse.urljoin(feed_url, child.get("url", "")),
                mime_type=child.get("type", ""),
                language=child.get("language", ""),
                rel=child.get("rel", ""),
            )
            for child in children_by_local_name(item, "transcript")
            if child.get("url")
        ]
        duration = ""
        for child in item.iter():
            if local_name(child.tag) == "duration" and child.text:
                duration = parse_duration(child.text)
                break
        episodes.append(
            Episode(
                show=show,
                title=title,
                published_date=parse_pub_date(child_text(item, "pubDate")),
                input_url=input_url or feed_url,
                feed_url=feed_url,
                audio_url=audio_url,
                duration=duration,
                guid=child_text(item, "guid"),
                description=child_text(item, "description"),
                episode_url=urllib.parse.urljoin(feed_url, child_text(item, "link")),
                host=host,
                transcript_links=transcript_links,
            )
        )
    return episodes


def select_latest(
    episodes: list[Episode],
    latest: int | None,
    all_episodes: bool,
    since: str | None = None,
) -> list[Episode]:
    if since:
        episodes = [
            episode
            for episode in episodes
            if episode.published_date and episode.published_date >= since
        ]
    if all_episodes:
        return episodes
    if since and latest is None:
        return episodes
    limit = latest if latest is not None else 5
    return episodes[:limit]


def resolve_apple_url(
    url: str, *, latest: int | None, all_episodes: bool, since: str | None = None
) -> list[Episode]:
    ids = parse_apple_podcast_url(url)
    podcast_info, apple_episodes = apple_lookup_metadata(str(ids["podcast_id"]))
    feed_url = podcast_info.get("feedUrl", "")
    if not feed_url:
        raise ValueError(f"Apple lookup did not return an RSS feed URL for {url}")

    episodes = parse_rss_feed(feed_url, input_url=url)
    for episode in episodes:
        episode.host = episode.host or podcast_info.get("artistName", "")

    episode_id = ids.get("episode_id")
    if episode_id:
        apple_episode = next(
            (item for item in apple_episodes if str(item.get("trackId")) == str(episode_id)),
            None,
        )
        if not apple_episode:
            raise ValueError(f"Apple lookup did not return episode ID {episode_id}")
        apple_title = apple_episode.get("trackName", "")
        matched = match_episode(episodes, apple_title, episode_id=str(episode_id))
        if not matched:
            matched = Episode(
                show=podcast_info.get("collectionName", ""),
                title=apple_title or f"Apple episode {episode_id}",
                published_date=parse_pub_date(apple_episode.get("releaseDate", "")),
                input_url=url,
                feed_url=feed_url,
                audio_url=apple_episode.get("episodeUrl", ""),
                duration=format_timestamp((apple_episode.get("trackTimeMillis") or 0) / 1000),
                episode_id=str(episode_id),
                description=apple_episode.get("description", ""),
                host=podcast_info.get("artistName", ""),
            )
        matched.input_url = url
        matched.episode_id = str(episode_id)
        return [matched]

    return select_latest(episodes, latest, all_episodes, since)


def match_episode(
    episodes: list[Episode], title: str, *, episode_id: str = ""
) -> Episode | None:
    title_norm = normalize_title(title)
    for episode in episodes:
        if normalize_title(episode.title) == title_norm:
            return episode
    if episode_id:
        for episode in episodes:
            if episode_id in episode.guid or episode_id in episode.episode_url:
                return episode
    return None


def normalize_title(title: str) -> str:
    return re.sub(r"\W+", "", title).lower()


def resolve_inputs(
    urls: list[str],
    *,
    latest: int | None,
    all_episodes: bool,
    since: str | None = None,
) -> tuple[list[Episode], list[TranscriptResult]]:
    episodes: list[Episode] = []
    failures: list[TranscriptResult] = []

    for url in urls:
        try:
            if is_apple_url(url):
                episodes.extend(
                    resolve_apple_url(
                        url,
                        latest=latest,
                        all_episodes=all_episodes,
                        since=since,
                    )
                )
            elif is_youtube_url(url):
                episodes.append(resolve_youtube_url(url))
            elif looks_like_rss_url(url):
                rss_episodes = parse_rss_feed(url, input_url=url)
                episodes.extend(select_latest(rss_episodes, latest, all_episodes, since))
            else:
                raise ValueError("Input is not an Apple Podcasts, RSS feed, or YouTube URL")
        except Exception as exc:
            failures.append(
                TranscriptResult(
                    episode=Episode(show="", title=url, input_url=url),
                    status="failed",
                    transcript_source=TRANSCRIPT_FAILED,
                    confidence="low",
                    transcript_text="",
                    failure_reason=str(exc),
                    retry_suggestion="Check that the URL is public and points to Apple Podcasts, an RSS feed, or a YouTube video.",
                )
            )

    return episodes, failures


def read_url_inputs(args: argparse.Namespace) -> list[str]:
    urls = [url.strip() for url in args.urls if url.strip()]
    if args.input_file:
        input_path = Path(args.input_file).expanduser()
        for line in input_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls:
        raise ValueError("Provide at least one URL or --input-file")
    return urls


def choose_batch_slug(urls: list[str], batch_slug: str | None) -> str:
    if batch_slug:
        return slugify(batch_slug)
    if len(urls) == 1 and is_youtube_url(urls[0]):
        try:
            metadata = fetch_youtube_metadata(urls[0])
            if metadata.get("title"):
                return slugify(metadata["title"])
        except Exception:
            pass
    first = urllib.parse.urlparse(urls[0]).path.strip("/").split("/")
    candidate = next((part for part in reversed(first) if part and not part.startswith("id")), "")
    date_prefix = dt.date.today().isoformat().replace("-", ".")
    return f"{date_prefix}_{slugify(candidate or 'podcast_batch')}"


def fetch_transcript_from_link(link: TranscriptLink) -> tuple[str, str]:
    text, content_type = request_text(link.url, timeout=60)
    mime_type = (link.mime_type or content_type).split(";")[0].strip().lower()
    if "json" in mime_type:
        return format_json_transcript(text), TRANSCRIPT_OFFICIAL_RSS
    if "vtt" in mime_type or link.url.lower().endswith(".vtt"):
        return format_vtt_transcript(text), TRANSCRIPT_OFFICIAL_CAPTION
    if "srt" in mime_type or link.url.lower().endswith(".srt"):
        return format_srt_transcript(text), TRANSCRIPT_OFFICIAL_CAPTION
    if "html" in mime_type or link.url.lower().endswith((".html", ".htm")):
        parser = PlainTextHTMLParser()
        parser.feed(text)
        return parser.text(), TRANSCRIPT_OFFICIAL_RSS
    return clean_text(text), TRANSCRIPT_OFFICIAL_RSS


def format_json_transcript(text: str) -> str:
    data = json.loads(text)
    entries: list[str] = []
    if isinstance(data, list):
        iterable = data
    elif isinstance(data, dict):
        iterable = data.get("segments") or data.get("transcript") or data.get("items") or []
        if isinstance(iterable, str):
            return clean_text(iterable)
    else:
        return clean_text(text)

    for item in iterable:
        if isinstance(item, str):
            entries.append(clean_text(item))
        elif isinstance(item, dict):
            start = item.get("start") or item.get("start_time") or item.get("time")
            body = item.get("text") or item.get("body") or item.get("content") or ""
            if body:
                prefix = f"[{format_timestamp(float(start))}] " if isinstance(start, (int, float)) else ""
                entries.append(prefix + clean_text(str(body)))
    return "\n\n".join(entry for entry in entries if entry)


def format_vtt_transcript(text: str) -> str:
    lines: list[str] = []
    timestamp = ""
    body: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.upper() == "WEBVTT" or line.isdigit():
            if timestamp and body:
                lines.append(f"[{timestamp}] {' '.join(body)}")
            timestamp = ""
            body = []
            continue
        if "-->" in line:
            timestamp = line.split("-->", 1)[0].strip()
        elif timestamp:
            body.append(strip_tags(line))
    if timestamp and body:
        lines.append(f"[{timestamp}] {' '.join(body)}")
    return "\n\n".join(lines).strip()


def format_srt_transcript(text: str) -> str:
    return format_vtt_transcript(text.replace(",", "."))


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(text)).strip()


TIMESTAMPED_LINE_RE = re.compile(r"^\[(?P<timestamp>[0-9:.]+)\]\s*(?P<text>.*)$")
SPEAKER_LABEL_RE = re.compile(
    r"(?<!\w)(?P<speaker>[A-Z][A-Za-z'-]*(?:\s+(?:[A-Z][A-Za-z'-]*|\d+)){0,4}):\s*"
)
SUMMARY_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
SUMMARY_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "been",
    "before",
    "being",
    "could",
    "from",
    "have",
    "into",
    "just",
    "like",
    "more",
    "most",
    "much",
    "over",
    "really",
    "should",
    "some",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "very",
    "want",
    "were",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def parse_transcript_segments(transcript_text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    pending: list[str] = []
    pending_timestamp = ""
    pending_seconds: int | None = None

    def flush_pending() -> None:
        nonlocal pending, pending_timestamp, pending_seconds
        body = clean_text(" ".join(pending))
        if body:
            segments.append(
                TranscriptSegment(
                    timestamp=pending_timestamp,
                    seconds=pending_seconds,
                    text=body,
                )
            )
        pending = []
        pending_timestamp = ""
        pending_seconds = None

    for raw_line in transcript_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_pending()
            continue
        match = TIMESTAMPED_LINE_RE.match(line)
        if match:
            flush_pending()
            pending_timestamp = match.group("timestamp")
            pending_seconds = parse_timestamp_seconds(pending_timestamp)
            pending = [match.group("text")]
        else:
            pending.append(line)

    flush_pending()
    return segments


def clean_readable_segment(text: str) -> str:
    cleaned = disfluency_cleanup(text)
    return clean_text(cleaned or text)


def split_speaker_turns(text: str) -> list[str]:
    matches = list(SPEAKER_LABEL_RE.finditer(text))
    if not matches:
        return [text]

    turns: list[str] = []
    first_start = matches[0].start()
    if first_start:
        prefix = text[:first_start].strip()
        if prefix:
            turns.append(prefix)

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        turn = text[match.start() : end].strip()
        if turn:
            turns.append(turn)

    return turns


def starts_with_speaker_label(text: str) -> bool:
    return bool(SPEAKER_LABEL_RE.match(text))


def should_start_new_readable_paragraph(
    current: list[str],
    *,
    current_start_seconds: int | None,
    next_seconds: int | None,
    next_text: str,
    target_words: int,
) -> bool:
    if not current:
        return False
    current_text = " ".join(current)
    current_words = len(current_text.split())
    if current_start_seconds is not None and next_seconds is not None:
        if next_seconds - current_start_seconds >= 180 and current_words >= 80:
            return True
    if current_words >= target_words:
        return True
    if current_words >= 80 and current_text.rstrip().endswith((".", "?", "!")):
        opener = next_text.split(maxsplit=1)[0].lower().strip(",.:;!?") if next_text else ""
        if opener in {"so", "now", "but", "and", "then", "okay", "right"}:
            return True
    return False


def render_readable_transcript_text(
    transcript_text: str,
    *,
    target_words: int = 140,
) -> str:
    segments = parse_transcript_segments(transcript_text)
    if not segments:
        return clean_text(transcript_text)

    paragraphs: list[tuple[str, str]] = []
    current: list[str] = []
    current_timestamp = ""
    current_start_seconds: int | None = None

    def flush_current() -> None:
        nonlocal current, current_timestamp, current_start_seconds
        body = clean_text(" ".join(current))
        if body:
            paragraphs.append((current_timestamp, body))
        current = []
        current_timestamp = ""
        current_start_seconds = None

    for segment in segments:
        text = clean_readable_segment(segment.text)
        if not text:
            continue
        for turn in split_speaker_turns(text):
            if current and starts_with_speaker_label(turn):
                flush_current()
            elif should_start_new_readable_paragraph(
                current,
                current_start_seconds=current_start_seconds,
                next_seconds=segment.seconds,
                next_text=turn,
                target_words=target_words,
            ):
                flush_current()
            if not current:
                current_timestamp = segment.timestamp
                current_start_seconds = segment.seconds
            current.append(turn)

    flush_current()
    return "\n\n".join(
        f"[{timestamp}] {body}" if timestamp else body
        for timestamp, body in paragraphs
    )


def split_summary_sentences(text: str) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    return [
        sentence.strip()
        for sentence in SUMMARY_SENTENCE_RE.split(normalized)
        if sentence.strip()
    ]


def summary_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9'-]{3,}", text.lower())
        if token not in SUMMARY_STOPWORDS
    ]


def render_summary_text(transcript_text: str, *, max_bullets: int = 7) -> str:
    segments = parse_transcript_segments(transcript_text)
    if not segments:
        body = clean_text(transcript_text)
        segments = [TranscriptSegment(timestamp="", seconds=None, text=body)] if body else []
    if not segments:
        return "_No transcript text available to summarize._"

    candidates: list[dict[str, object]] = []
    token_counts: dict[str, int] = {}
    for index, segment in enumerate(segments):
        for sentence in split_summary_sentences(clean_readable_segment(segment.text)):
            words = sentence.split()
            if len(words) < 8:
                continue
            tokens = summary_tokens(sentence)
            if not tokens:
                continue
            for token in tokens:
                token_counts[token] = token_counts.get(token, 0) + 1
            candidates.append(
                {
                    "index": index,
                    "timestamp": segment.timestamp,
                    "sentence": sentence,
                    "tokens": tokens,
                    "word_count": len(words),
                }
            )

    if not candidates:
        fallback = clean_text(" ".join(segment.text for segment in segments))
        return f"- {fallback[:280].rstrip()}"

    scored: list[tuple[float, int, dict[str, object]]] = []
    for position, candidate in enumerate(candidates):
        tokens = candidate["tokens"]
        word_count = int(candidate["word_count"])
        score = sum(token_counts.get(token, 0) for token in tokens) / max(len(tokens), 1)
        if re.search(r"\d|%|\$|million|billion|hours|days|weeks|months", str(candidate["sentence"]), re.I):
            score += 1.5
        if 12 <= word_count <= 32:
            score += 1.0
        if str(candidate["sentence"]).endswith(("?", "!")):
            score -= 0.5
        scored.append((score, -position, candidate))

    selected = [
        candidate
        for _, _, candidate in sorted(scored, reverse=True)[:max_bullets]
    ]
    selected.sort(key=lambda candidate: int(candidate["index"]))

    bullets: list[str] = []
    seen: set[str] = set()
    for candidate in selected:
        sentence = str(candidate["sentence"])
        dedupe_key = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        timestamp = str(candidate["timestamp"])
        prefix = f"[{timestamp}] " if timestamp else ""
        bullets.append(f"- {prefix}{sentence}")

    return "\n".join(bullets) if bullets else "_No summary bullets generated._"


def fetch_youtube_transcript(url: str) -> str:
    video_id = extract_youtube_video_id(url)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError("youtube-transcript-api is not installed") from exc

    api = YouTubeTranscriptApi()
    try:
        entries = [
            {"text": segment.text, "start": segment.start}
            for segment in api.fetch(video_id, languages=["en"])
        ]
    except AttributeError:
        entries = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])

    return render_youtube_transcript_entries(entries)


def render_youtube_transcript_entries(entries: list[dict[str, object]]) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    current_start: float | None = None
    previous_start = 0.0

    def flush_current() -> None:
        nonlocal current, current_start
        if current and current_start is not None:
            paragraphs.append(f"[{format_timestamp(current_start)}] {' '.join(current)}")
        current = []
        current_start = None

    for entry in entries:
        start = float(entry.get("start", 0.0))
        text = clean_text(entry.get("text", ""))
        current_words = len(" ".join(current).split())
        if current and current_start is not None:
            if start - previous_start > 30 or start - current_start >= 180 or current_words >= 120:
                flush_current()
        if text:
            if current_start is None:
                current_start = start
            current.append(text)
        previous_start = start
    flush_current()
    return "\n\n".join(paragraphs)


def download_audio(url: str, output_dir: Path) -> Path:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix or ".mp3"
    output_path = output_dir / f"podcast_audio{suffix}"
    raw, _ = request_bytes(url, timeout=600)
    output_path.write_bytes(raw)
    return output_path


def transcribe_audio_with_whisper(audio_file: Path, *, model_size: str) -> str:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("openai-whisper is not installed") from exc

    model = whisper.load_model(model_size)
    result = model.transcribe(str(audio_file), task="transcribe", language="en", verbose=False)
    segments = result.get("segments") or []
    return "\n\n".join(
        f"[{format_timestamp(float(segment.get('start', 0.0)))}] {clean_text(segment.get('text', ''))}"
        for segment in segments
        if clean_text(segment.get("text", ""))
    )


def generate_transcript(
    episode: Episode, *, dry_run: bool, whisper_model: str
) -> TranscriptResult:
    if dry_run:
        return TranscriptResult(
            episode=episode,
            status="dry_run",
            transcript_source=TRANSCRIPT_DRY_RUN,
            confidence="low",
            transcript_text="Transcript not fetched because --dry-run was used.",
        )

    if is_youtube_url(episode.input_url or episode.episode_url):
        try:
            return TranscriptResult(
                episode=episode,
                status="success",
                transcript_source=TRANSCRIPT_YOUTUBE_DIRECT,
                confidence="high",
                transcript_text=fetch_youtube_transcript(episode.input_url or episode.episode_url),
            )
        except Exception as exc:
            return failure_result(
                episode,
                str(exc),
                "Install youtube-transcript-api or provide an RSS/Apple URL with an audio enclosure.",
            )

    for link in episode.transcript_links:
        try:
            transcript_text, source = fetch_transcript_from_link(link)
            if transcript_text:
                return TranscriptResult(
                    episode=episode,
                    status="success",
                    transcript_source=source,
                    confidence="high",
                    transcript_text=transcript_text,
                )
        except Exception:
            continue

    if not episode.audio_url:
        return failure_result(
            episode,
            "No official transcript link or audio enclosure was found.",
            "Check the RSS feed manually or supply a direct episode/RSS URL.",
        )

    try:
        with tempfile.TemporaryDirectory(prefix="bv_podcast_audio_") as tmp:
            audio_file = download_audio(episode.audio_url, Path(tmp))
            transcript = transcribe_audio_with_whisper(audio_file, model_size=whisper_model)
        return TranscriptResult(
            episode=episode,
            status="success",
            transcript_source=TRANSCRIPT_LOCAL_WHISPER,
            confidence="moderate",
            transcript_text=transcript,
        )
    except Exception as exc:
        return failure_result(
            episode,
            str(exc),
            "Install openai-whisper and ffmpeg, then rerun without --dry-run.",
        )


def failure_result(episode: Episode, reason: str, retry_suggestion: str) -> TranscriptResult:
    return TranscriptResult(
        episode=episode,
        status="failed",
        transcript_source=TRANSCRIPT_FAILED,
        confidence="low",
        transcript_text="",
        failure_reason=reason,
        retry_suggestion=retry_suggestion,
    )


def episode_filename(episode: Episode) -> str:
    date_part = episode.published_date.replace("-", ".") if episode.published_date else "unknown_date"
    return f"{date_part}_{slugify(episode.show, 36)}_{slugify(episode.title, 70)}.md"


def readable_episode_filename(episode: Episode) -> str:
    name = episode_filename(episode)
    return name[:-3] + "_readable.md" if name.endswith(".md") else name + "_readable"


def summary_episode_filename(episode: Episode) -> str:
    name = episode_filename(episode)
    return name[:-3] + "_summary.md" if name.endswith(".md") else name + "_summary"


def yaml_quote(value: str) -> str:
    return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_episode_markdown(result: TranscriptResult) -> str:
    episode = result.episode
    lines = [
        "---",
        f"show: {yaml_quote(episode.show)}",
        f"episode: {yaml_quote(episode.title)}",
        f"published_date: {yaml_quote(episode.published_date)}",
        f"input_url: {yaml_quote(episode.input_url)}",
        f"feed_url: {yaml_quote(episode.feed_url)}",
        f"audio_url: {yaml_quote(episode.audio_url)}",
        f"transcript_source: {yaml_quote(result.transcript_source)}",
        f"confidence: {yaml_quote(result.confidence)}",
        f"status: {yaml_quote(result.status)}",
        f"duration: {yaml_quote(episode.duration)}",
        f"episode_guid: {yaml_quote(episode.guid or episode.episode_id)}",
        "---",
        "",
        f"# {episode.title}",
        "",
        f"- **Show:** {episode.show or 'Unknown'}",
        f"- **Published:** {episode.published_date or 'Unknown'}",
        f"- **Input URL:** {episode.input_url or 'Unknown'}",
        f"- **Feed URL:** {episode.feed_url or 'Unknown'}",
        f"- **Audio URL:** {episode.audio_url or 'Unknown'}",
        f"- **Transcript source:** {result.transcript_source}",
        f"- **Confidence:** {result.confidence}",
        f"- **Status:** {result.status}",
    ]
    if result.failure_reason:
        lines.extend(
            [
                f"- **Failure reason:** {result.failure_reason}",
                f"- **Retry suggestion:** {result.retry_suggestion}",
            ]
        )
    lines.extend(["", "## Transcript", "", result.transcript_text or "_No transcript available._", ""])
    return "\n".join(lines)


def render_readable_episode_markdown(result: TranscriptResult) -> str:
    episode = result.episode
    lines = [
        "---",
        f"show: {yaml_quote(episode.show)}",
        f"episode: {yaml_quote(episode.title)}",
        f"published_date: {yaml_quote(episode.published_date)}",
        f"input_url: {yaml_quote(episode.input_url)}",
        f"feed_url: {yaml_quote(episode.feed_url)}",
        f"audio_url: {yaml_quote(episode.audio_url)}",
        f"transcript_source: {yaml_quote(result.transcript_source)}",
        f"confidence: {yaml_quote(result.confidence)}",
        f"status: {yaml_quote(result.status)}",
        f"duration: {yaml_quote(episode.duration)}",
        f"episode_guid: {yaml_quote(episode.guid or episode.episode_id)}",
        'transcript_view: "readable"',
        "---",
        "",
        f"# {episode.title} - Readable Transcript",
        "",
        f"- **Show:** {episode.show or 'Unknown'}",
        f"- **Published:** {episode.published_date or 'Unknown'}",
        f"- **Input URL:** {episode.input_url or 'Unknown'}",
        f"- **Feed URL:** {episode.feed_url or 'Unknown'}",
        f"- **Audio URL:** {episode.audio_url or 'Unknown'}",
        f"- **Transcript source:** {result.transcript_source}",
        f"- **Confidence:** {result.confidence}",
        f"- **Status:** {result.status}",
        "- **Transcript view:** readable derivative",
        "",
        "## Transcript",
        "",
        result.readable_text or "_No readable transcript available._",
        "",
    ]
    return "\n".join(lines)


def render_summary_episode_markdown(result: TranscriptResult) -> str:
    episode = result.episode
    lines = [
        "---",
        f"show: {yaml_quote(episode.show)}",
        f"episode: {yaml_quote(episode.title)}",
        f"published_date: {yaml_quote(episode.published_date)}",
        f"input_url: {yaml_quote(episode.input_url)}",
        f"feed_url: {yaml_quote(episode.feed_url)}",
        f"audio_url: {yaml_quote(episode.audio_url)}",
        f"transcript_source: {yaml_quote(result.transcript_source)}",
        f"confidence: {yaml_quote(result.confidence)}",
        f"status: {yaml_quote(result.status)}",
        f"duration: {yaml_quote(episode.duration)}",
        f"episode_guid: {yaml_quote(episode.guid or episode.episode_id)}",
        'transcript_view: "summary"',
        "---",
        "",
        f"# {episode.title} - Summary",
        "",
        f"- **Show:** {episode.show or 'Unknown'}",
        f"- **Published:** {episode.published_date or 'Unknown'}",
        f"- **Input URL:** {episode.input_url or 'Unknown'}",
        f"- **Feed URL:** {episode.feed_url or 'Unknown'}",
        f"- **Audio URL:** {episode.audio_url or 'Unknown'}",
        f"- **Transcript source:** {result.transcript_source}",
        f"- **Confidence:** {result.confidence}",
        f"- **Status:** {result.status}",
        "- **Transcript view:** summary",
        "",
        "## Summary",
        "",
        result.summary_text or "_No summary available._",
        "",
    ]
    return "\n".join(lines)


def write_package(
    results: list[TranscriptResult],
    input_urls: list[str],
    output_root: Path,
    batch_slug: str,
    *,
    force: bool,
    readable: bool = False,
    summary: bool = False,
) -> Path:
    batch_dir = output_root / batch_slug
    episodes_dir = batch_dir / "episodes"
    readable_dir = batch_dir / "episodes_readable"
    summaries_dir = batch_dir / "summaries"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    planned_raw_paths: list[tuple[TranscriptResult, Path]] = []
    planned_readable_paths: list[tuple[TranscriptResult, Path]] = []
    planned_summary_paths: list[tuple[TranscriptResult, Path]] = []
    for result in results:
        if result.status in {"success", "dry_run"}:
            path = episodes_dir / episode_filename(result.episode)
            planned_raw_paths.append((result, path))
            if path.exists() and not force:
                raise FileExistsError(f"Refusing to overwrite existing transcript file: {path}")
            if readable and result.status == "success":
                readable_path = readable_dir / readable_episode_filename(result.episode)
                planned_readable_paths.append((result, readable_path))
                if readable_path.exists() and not force:
                    raise FileExistsError(f"Refusing to overwrite existing readable transcript file: {readable_path}")
            if summary and result.status == "success":
                summary_path = summaries_dir / summary_episode_filename(result.episode)
                planned_summary_paths.append((result, summary_path))
                if summary_path.exists() and not force:
                    raise FileExistsError(f"Refusing to overwrite existing summary file: {summary_path}")

    for result, path in planned_raw_paths:
        path.write_text(render_episode_markdown(result), encoding="utf-8")
        result.output_path = path

    if planned_readable_paths:
        readable_dir.mkdir(parents=True, exist_ok=True)
        for result, path in planned_readable_paths:
            result.readable_text = render_readable_transcript_text(result.transcript_text)
            path.write_text(render_readable_episode_markdown(result), encoding="utf-8")
            result.readable_output_path = path

    if planned_summary_paths:
        summaries_dir.mkdir(parents=True, exist_ok=True)
        for result, path in planned_summary_paths:
            result.summary_text = render_summary_text(result.readable_text or result.transcript_text)
            path.write_text(render_summary_episode_markdown(result), encoding="utf-8")
            result.summary_output_path = path

    (batch_dir / "index.md").write_text(render_index(results, input_urls, batch_slug), encoding="utf-8")
    (batch_dir / "combined_transcripts.md").write_text(render_combined(results, batch_slug), encoding="utf-8")
    combined_readable_path = batch_dir / "combined_readable_transcripts.md"
    if planned_readable_paths:
        combined_readable_path.write_text(render_combined_readable(results, batch_slug), encoding="utf-8")
    elif combined_readable_path.exists():
        combined_readable_path.unlink()
    combined_summary_path = batch_dir / "combined_summaries.md"
    if planned_summary_paths:
        combined_summary_path.write_text(render_combined_summaries(results, batch_slug), encoding="utf-8")
    elif combined_summary_path.exists():
        combined_summary_path.unlink()

    failures = [result for result in results if result.status == "failed"]
    failures_path = batch_dir / "failures.md"
    if failures:
        failures_path.write_text(render_failures(failures), encoding="utf-8")
    elif failures_path.exists():
        failures_path.unlink()

    return batch_dir


def render_index(results: list[TranscriptResult], input_urls: list[str], batch_slug: str) -> str:
    has_readable_outputs = any(result.readable_output_path for result in results)
    has_summary_outputs = any(result.summary_output_path for result in results)
    columns = ["Status", "Show", "Episode", "Published", "Source", "Confidence", "File"]
    if has_readable_outputs:
        columns.append("Readable File")
    if has_summary_outputs:
        columns.append("Summary File")
    header = "| " + " | ".join(columns) + " |"
    separator = "|" + "|".join(["---"] * len(columns)) + "|"
    lines = [
        f"# Podcast Transcript Batch: {batch_slug}",
        "",
        "## Inputs",
        "",
    ]
    lines.extend(f"- {url}" for url in input_urls)
    lines.extend(
        [
            "",
            "## Episodes",
            "",
            header,
            separator,
        ]
    )
    for result in results:
        file_link = ""
        if result.output_path:
            file_link = f"[{result.output_path.name}](episodes/{result.output_path.name})"
        readable_link = ""
        if result.readable_output_path:
            readable_link = (
                f"[{result.readable_output_path.name}]"
                f"(episodes_readable/{result.readable_output_path.name})"
            )
        summary_link = ""
        if result.summary_output_path:
            summary_link = (
                f"[{result.summary_output_path.name}]"
                f"(summaries/{result.summary_output_path.name})"
            )
        row = [
            result.status,
            escape_table(result.episode.show),
            escape_table(result.episode.title),
            result.episode.published_date or "Unknown",
            result.transcript_source,
            result.confidence,
            file_link,
        ]
        if has_readable_outputs:
            row.append(readable_link)
        if has_summary_outputs:
            row.append(summary_link)
        lines.append(
            "| "
            + " | ".join(row)
            + " |"
        )

    failures = [result for result in results if result.status == "failed"]
    lines.extend(
        [
            "",
            "## Provenance Notes",
            "",
            "- Official RSS `podcast:transcript` links are preferred before generated transcription.",
            "- Direct YouTube URLs use YouTube transcript extraction only when `youtube-transcript-api` is installed.",
            "- Local generated transcripts use local Whisper from RSS audio enclosures; audio files are temporary and not committed.",
            f"- Failures: {len(failures)}.",
            "",
        ]
    )
    if failures:
        lines.append("See [failures.md](failures.md).")
        lines.append("")
    return "\n".join(lines)


def escape_table(value: str) -> str:
    return (value or "Unknown").replace("|", "\\|").replace("\n", " ")


def render_combined(results: list[TranscriptResult], batch_slug: str) -> str:
    lines = [f"# Combined Podcast Transcripts: {batch_slug}", ""]
    for result in results:
        if result.status not in {"success", "dry_run"}:
            continue
        lines.extend(
            [
                f"## {result.episode.show} - {result.episode.title}",
                "",
                f"- **Published:** {result.episode.published_date or 'Unknown'}",
                f"- **Transcript source:** {result.transcript_source}",
                f"- **Confidence:** {result.confidence}",
                "",
                result.transcript_text or "_No transcript available._",
                "",
            ]
        )
    return "\n".join(lines)


def render_combined_readable(results: list[TranscriptResult], batch_slug: str) -> str:
    lines = [f"# Combined Readable Podcast Transcripts: {batch_slug}", ""]
    for result in results:
        if result.status != "success" or not result.readable_text:
            continue
        lines.extend(
            [
                f"## {result.episode.show} - {result.episode.title}",
                "",
                f"- **Published:** {result.episode.published_date or 'Unknown'}",
                f"- **Transcript source:** {result.transcript_source}",
                f"- **Confidence:** {result.confidence}",
                "- **Transcript view:** readable derivative",
                "",
                result.readable_text,
                "",
            ]
        )
    return "\n".join(lines)


def render_combined_summaries(results: list[TranscriptResult], batch_slug: str) -> str:
    lines = [f"# Combined Podcast Summaries: {batch_slug}", ""]
    for result in results:
        if result.status != "success" or not result.summary_text:
            continue
        lines.extend(
            [
                f"## {result.episode.show} - {result.episode.title}",
                "",
                f"- **Published:** {result.episode.published_date or 'Unknown'}",
                f"- **Transcript source:** {result.transcript_source}",
                f"- **Confidence:** {result.confidence}",
                "",
                result.summary_text,
                "",
            ]
        )
    return "\n".join(lines)


def render_failures(failures: list[TranscriptResult]) -> str:
    lines = [
        "# Podcast Transcript Failures",
        "",
        "| Input | Episode | Reason | Retry suggestion |",
        "|---|---|---|---|",
    ]
    for result in failures:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table(result.episode.input_url),
                    escape_table(result.episode.title),
                    escape_table(result.failure_reason),
                    escape_table(result.retry_suggestion),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a local Markdown transcript package from podcast URLs."
    )
    parser.add_argument("urls", nargs="*", help="Apple Podcasts, RSS feed, or YouTube URLs")
    parser.add_argument("--input-file", help="Plain text file with one URL per line")
    parser.add_argument("--batch-slug", help="Output folder slug under the podcast transcript root")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Output root directory")
    parser.add_argument("--latest", type=int, help="Number of latest episodes for show/RSS inputs")
    parser.add_argument("--since", help="Process show/RSS episodes on or after YYYY-MM-DD")
    parser.add_argument("--all", action="store_true", help="Process all feed episodes")
    parser.add_argument("--dry-run", action="store_true", help="Resolve metadata and write package files without fetching or generating transcripts")
    parser.add_argument("--force", action="store_true", help="Overwrite existing transcript files")
    parser.add_argument(
        "--readable",
        action="store_true",
        help="Also write deterministic readable transcript derivatives without overwriting raw transcripts",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Also write deterministic transcript summaries without requiring an LLM API key",
    )
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Local Whisper model size for generated transcripts",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        input_urls = read_url_inputs(args)
        batch_slug = choose_batch_slug(input_urls, args.batch_slug)
        episodes, failures = resolve_inputs(
            input_urls,
            latest=args.latest,
            all_episodes=args.all,
            since=args.since,
        )
        results = [
            generate_transcript(episode, dry_run=args.dry_run, whisper_model=args.model)
            for episode in episodes
        ]
        results.extend(failures)
        batch_dir = write_package(
            results,
            input_urls,
            Path(args.output_root).expanduser(),
            batch_slug,
            force=args.force,
            readable=args.readable,
            summary=args.summary,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved podcast transcript package to: {batch_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
