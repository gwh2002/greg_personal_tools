#!/usr/bin/env python3
"""Tests for podcast transcript package generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import podcast_transcripts as pt


RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0">
  <channel>
    <title>People Who Plan</title>
    <itunes:author>Modern Operators</itunes:author>
    <item>
      <title>Inside Operator Planning</title>
      <guid>episode-1</guid>
      <pubDate>Wed, 27 May 2026 10:00:00 GMT</pubDate>
      <itunes:duration>3600</itunes:duration>
      <link>https://example.com/episode-1</link>
      <description>First episode.</description>
      <enclosure url="https://cdn.example.com/episode-1.mp3" type="audio/mpeg" />
      <podcast:transcript url="https://example.com/episode-1.txt" type="text/plain" language="en" />
    </item>
    <item>
      <title>Second Planning Episode</title>
      <guid>episode-2</guid>
      <pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate>
      <enclosure url="https://cdn.example.com/episode-2.mp3" type="audio/mpeg" />
    </item>
    <item>
      <title>Third Planning Episode</title>
      <guid>episode-3</guid>
      <pubDate>Mon, 25 May 2026 10:00:00 GMT</pubDate>
      <enclosure url="https://cdn.example.com/episode-3.mp3" type="audio/mpeg" />
    </item>
  </channel>
</rss>
"""


class PodcastTranscriptTests(unittest.TestCase):
    def test_parse_apple_podcast_url(self) -> None:
        parsed = pt.parse_apple_podcast_url(
            "https://podcasts.apple.com/ca/podcast/show-name/id1886794877?i=1001234567890"
        )

        self.assertEqual("1886794877", parsed["podcast_id"])
        self.assertEqual("1001234567890", parsed["episode_id"])

    def test_parse_rss_text_discovers_transcript_links(self) -> None:
        episodes = pt.parse_rss_text(
            RSS_FIXTURE,
            feed_url="https://example.com/feed.xml",
            input_url="https://example.com/feed.xml",
        )

        self.assertEqual(3, len(episodes))
        self.assertEqual("People Who Plan", episodes[0].show)
        self.assertEqual("Inside Operator Planning", episodes[0].title)
        self.assertEqual("2026-05-27", episodes[0].published_date)
        self.assertEqual("1:00:00", episodes[0].duration)
        self.assertEqual("https://example.com/episode-1.txt", episodes[0].transcript_links[0].url)

    def test_select_latest_defaults_to_five_and_supports_latest_n(self) -> None:
        episodes = [
            pt.Episode(show="Show", title=f"Episode {index}", published_date=f"2026-05-2{index}")
            for index in range(7)
        ]

        self.assertEqual(5, len(pt.select_latest(episodes, latest=None, all_episodes=False)))
        self.assertEqual(2, len(pt.select_latest(episodes, latest=2, all_episodes=False)))
        self.assertEqual(7, len(pt.select_latest(episodes, latest=2, all_episodes=True)))
        self.assertEqual(
            ["Episode 4", "Episode 5", "Episode 6"],
            [
                episode.title
                for episode in pt.select_latest(
                    episodes,
                    latest=None,
                    all_episodes=False,
                    since="2026-05-24",
                )
            ],
        )

    def test_episode_filename_uses_date_show_and_episode_slugs(self) -> None:
        episode = pt.Episode(
            show="People Who Plan",
            title="Inside the Minds of Modern Operators!",
            published_date="2026-05-27",
        )

        self.assertEqual(
            "2026.05.27_people_who_plan_inside_the_minds_of_modern_operators.md",
            pt.episode_filename(episode),
        )

    def test_write_package_outputs_index_combined_episode_and_failures(self) -> None:
        success = pt.TranscriptResult(
            episode=pt.Episode(
                show="People Who Plan",
                title="Inside Operator Planning",
                published_date="2026-05-27",
                input_url="https://example.com/feed.xml",
                feed_url="https://example.com/feed.xml",
                audio_url="https://cdn.example.com/episode-1.mp3",
            ),
            status="success",
            transcript_source=pt.TRANSCRIPT_OFFICIAL_RSS,
            confidence="high",
            transcript_text="[0:00] Operators plan carefully.",
        )
        failure = pt.failure_result(
            pt.Episode(show="", title="https://bad.example.com", input_url="https://bad.example.com"),
            "Unsupported URL",
            "Use Apple Podcasts, RSS, or YouTube.",
        )

        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = pt.write_package(
                [success, failure],
                ["https://example.com/feed.xml", "https://bad.example.com"],
                Path(tmp),
                "operator-podcasts",
                force=False,
            )

            self.assertTrue((batch_dir / "index.md").exists())
            self.assertTrue((batch_dir / "combined_transcripts.md").exists())
            self.assertTrue((batch_dir / "failures.md").exists())
            episode_files = list((batch_dir / "episodes").glob("*.md"))
            self.assertEqual(1, len(episode_files))
            self.assertIn("Operators plan carefully", (batch_dir / "combined_transcripts.md").read_text())

    def test_readable_transcript_paragraphizes_timestamped_segments(self) -> None:
        raw = "\n\n".join(
            [
                "[0:00] Um, welcome to the show.",
                "[0:04] You know, we are talking about planning.",
                "[0:08] It matters because operators need context.",
                "[3:15] So, now we move to the second topic.",
            ]
        )

        readable = pt.render_readable_transcript_text(raw, target_words=10)

        self.assertIn("[0:00] Welcome to the show. We are talking about planning.", readable)
        self.assertIn("[3:15] Now we move to the second topic.", readable)
        self.assertNotIn("[0:04]", readable)
        self.assertNotIn("Um,", readable)

    def test_readable_transcript_breaks_on_new_speaker_labels(self) -> None:
        raw = "\n\n".join(
            [
                "[0:00] Chris Heagle: Support comes from a sponsor. Krista Tippett: I'm Krista Tippett. Latanya Sweeney: It is wonderful to be here.",
                "[0:45] Krista Tippett: Let's start with your early life.",
            ]
        )

        readable = pt.render_readable_transcript_text(raw, target_words=140)

        self.assertIn(
            "[0:00] Chris Heagle: Support comes from a sponsor.\n\n"
            "[0:00] Krista Tippett: I'm Krista Tippett.\n\n"
            "[0:00] Latanya Sweeney: It is wonderful to be here.\n\n"
            "[0:45] Krista Tippett: Let's start with your early life.",
            readable,
        )

    def test_readable_transcript_breaks_on_short_and_numbered_speaker_labels(self) -> None:
        raw = "\n\n".join(
            [
                "[0:00] Host: Welcome to the episode. Guest: Thanks for having me.",
                "[0:15] Speaker 1: Let's compare the files. Chris: The pattern is clear.",
            ]
        )

        readable = pt.render_readable_transcript_text(raw, target_words=140)

        self.assertIn(
            "[0:00] Host: Welcome to the episode.\n\n"
            "[0:00] Guest: Thanks for having me.\n\n"
            "[0:15] Speaker 1: Let's compare the files.\n\n"
            "[0:15] Chris: The pattern is clear.",
            readable,
        )

    def test_youtube_transcript_entries_keep_chunk_start_timestamps(self) -> None:
        entries = [
            {"text": "Welcome to the show.", "start": 0.0},
            {"text": "We are talking about planning.", "start": 4.0},
            {"text": "This is still the first section.", "start": 8.0},
            {"text": "Now we are in the next section.", "start": 190.0},
        ]

        transcript = pt.render_youtube_transcript_entries(entries)

        self.assertIn("[0:00] Welcome to the show.", transcript)
        self.assertIn("[3:10] Now we are in the next section.", transcript)
        self.assertNotIn("[0:08] Welcome to the show.", transcript)

    def test_resolve_youtube_url_uses_oembed_title_metadata(self) -> None:
        with patch.object(
            pt,
            "fetch_youtube_metadata",
            return_value={
                "title": "The Ralph Wiggum Loop from 1st principles",
                "author_name": "Geoffrey Huntley",
            },
        ):
            episode = pt.resolve_youtube_url("https://www.youtube.com/watch?v=4Nna09dG_c0")

        self.assertEqual("Geoffrey Huntley", episode.show)
        self.assertEqual("The Ralph Wiggum Loop from 1st principles", episode.title)
        self.assertEqual("4Nna09dG_c0", episode.episode_id)
        self.assertEqual("4Nna09dG_c0", episode.guid)

    def test_choose_batch_slug_uses_youtube_title_when_available(self) -> None:
        with patch.object(
            pt,
            "fetch_youtube_metadata",
            return_value={
                "title": "The Ralph Wiggum Loop from 1st principles",
                "author_name": "Geoffrey Huntley",
            },
        ):
            slug = pt.choose_batch_slug(["https://www.youtube.com/watch?v=4Nna09dG_c0"], None)

        self.assertEqual("the_ralph_wiggum_loop_from_1st_principles", slug)

    def test_write_package_can_emit_readable_derivatives_without_overwriting_raw(self) -> None:
        success = pt.TranscriptResult(
            episode=pt.Episode(
                show="People Who Plan",
                title="Inside Operator Planning",
                published_date="2026-05-27",
                input_url="https://example.com/feed.xml",
                feed_url="https://example.com/feed.xml",
                audio_url="https://cdn.example.com/episode-1.mp3",
                duration="30:00",
                guid="episode-1",
            ),
            status="success",
            transcript_source=pt.TRANSCRIPT_LOCAL_WHISPER,
            confidence="moderate",
            transcript_text="[0:00] Um, operators plan carefully.\n\n[0:05] They keep the details.",
        )

        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = pt.write_package(
                [success],
                ["https://example.com/feed.xml"],
                Path(tmp),
                "operator-podcasts",
                force=False,
                readable=True,
            )

            raw_files = list((batch_dir / "episodes").glob("*.md"))
            readable_files = list((batch_dir / "episodes_readable").glob("*.md"))
            self.assertEqual(1, len(raw_files))
            self.assertEqual(1, len(readable_files))
            self.assertTrue((batch_dir / "combined_readable_transcripts.md").exists())

            raw_text = raw_files[0].read_text()
            readable_text = readable_files[0].read_text()
            index_text = (batch_dir / "index.md").read_text()

            self.assertIn("[0:00] Um, operators plan carefully.", raw_text)
            self.assertIn('transcript_view: "readable"', readable_text)
            self.assertIn("episode_guid: \"episode-1\"", readable_text)
            self.assertIn("[0:00] Operators plan carefully. They keep the details.", readable_text)
            self.assertIn("episodes_readable/", index_text)

            with self.assertRaises(FileExistsError):
                pt.write_package(
                    [success],
                    ["https://example.com/feed.xml"],
                    Path(tmp),
                    "operator-podcasts",
                    force=False,
                    readable=True,
                )

    def test_summary_text_selects_timestamped_bullets(self) -> None:
        raw = "\n\n".join(
            [
                "[0:00] Welcome to the show and thanks for joining us today.",
                "[0:30] Operators need planning systems because capacity, inventory, and staffing decisions compound across teams.",
                "[1:15] A good weekly review names the decision owner, the current blocker, and the next dated commitment.",
                "[2:00] The team compared 12 customer calls and found the same onboarding confusion in 9 of them.",
            ]
        )

        summary = pt.render_summary_text(raw, max_bullets=3)

        self.assertIn("- [0:30]", summary)
        self.assertIn("planning systems", summary)
        self.assertIn("12 customer calls", summary)

    def test_write_package_can_emit_summaries_without_overwriting_raw(self) -> None:
        success = pt.TranscriptResult(
            episode=pt.Episode(
                show="People Who Plan",
                title="Inside Operator Planning",
                published_date="2026-05-27",
                input_url="https://www.youtube.com/watch?v=abc123",
                duration="30:00",
                guid="youtube-abc123",
            ),
            status="success",
            transcript_source=pt.TRANSCRIPT_YOUTUBE_DIRECT,
            confidence="high",
            transcript_text=(
                "[0:00] Operators need planning systems because capacity and staffing decisions compound.\n\n"
                "[0:45] The team reviewed 12 customer calls and found onboarding confusion in 9 of them."
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = pt.write_package(
                [success],
                ["https://www.youtube.com/watch?v=abc123"],
                Path(tmp),
                "youtube-summary-test",
                force=False,
                summary=True,
            )

            summary_files = list((batch_dir / "summaries").glob("*.md"))
            self.assertEqual(1, len(summary_files))
            self.assertTrue((batch_dir / "combined_summaries.md").exists())

            summary_text = summary_files[0].read_text()
            index_text = (batch_dir / "index.md").read_text()

            self.assertIn('transcript_view: "summary"', summary_text)
            self.assertIn("## Summary", summary_text)
            self.assertIn("summaries/", index_text)

            with self.assertRaises(FileExistsError):
                pt.write_package(
                    [success],
                    ["https://www.youtube.com/watch?v=abc123"],
                    Path(tmp),
                    "youtube-summary-test",
                    force=False,
                    summary=True,
                )

    def test_dry_run_smoke_does_not_fetch_transcripts(self) -> None:
        episode = pt.Episode(show="Show", title="Episode", input_url="https://example.com/feed.xml")

        with patch.object(pt, "fetch_transcript_from_link") as fetch_transcript:
            result = pt.generate_transcript(episode, dry_run=True, whisper_model="base")

        fetch_transcript.assert_not_called()
        self.assertEqual("dry_run", result.status)
        self.assertEqual(pt.TRANSCRIPT_DRY_RUN, result.transcript_source)


if __name__ == "__main__":
    unittest.main()
