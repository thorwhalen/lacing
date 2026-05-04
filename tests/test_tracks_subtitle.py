"""Tests for ``lacing.tracks.subtitle``."""

from __future__ import annotations

import pytest

from lacing import MemoryStore
from lacing.tracks.subtitle import (
    BUILT_IN_BODY_SCHEMAS,
    LINES_TIER,
    SECTIONS_TIER,
    WORDS_TIER,
    SubtitleBuilder,
    SubtitleTrack,
)


@pytest.fixture
def store_with_song():
    store = MemoryStore()
    with SubtitleBuilder(store, asset_id="song/audio.mp3") as b:
        b.section("intro", 0.0, 12.5, title="intro")
        b.section("verse_1", 12.5, 35.0, title="verse 1", energy="medium")
        b.section("chorus", 35.0, 55.0, title="chorus", energy="high")

        b.line(
            "I came down to the river",
            12.5, 16.2,
            section="verse_1",
            line_index=0,
            words=[
                ("I", 12.5, 12.7),
                ("came", 12.7, 13.0, 0.95),
                ("down", 13.0, 13.3, 0.92),
                ("to", 13.3, 13.4),
                ("the", 13.4, 13.6),
                ("river", 13.6, 16.2, 0.88),
            ],
        )
        b.line(
            "to wash my soul",
            16.2, 17.5,
            section="verse_1",
            line_index=1,
        )
        b.line(
            "hold my hand",
            35.0, 37.0,
            section="chorus",
            line_index=2,
        )
    return store


def test_builder_creates_three_tiers(store_with_song):
    names = {t.name for t in store_with_song.tiers()}
    assert {SECTIONS_TIER, LINES_TIER, WORDS_TIER}.issubset(names)


def test_builder_writes_sections_lines_words(store_with_song):
    track = SubtitleTrack(store_with_song, asset_id="song/audio.mp3")
    assert len(track.all_sections()) == 3
    assert len(track.all_lines()) == 3
    assert len(track.all_words()) == 6


def test_lines_in_window(store_with_song):
    track = SubtitleTrack(store_with_song, asset_id="song/audio.mp3")
    inside = track.lines_in(15.0, 17.0)
    texts = [a.body["text"] for a in inside]
    # Both verse lines overlap [15, 17].
    assert "I came down to the river" in texts
    assert "to wash my soul" in texts
    assert "hold my hand" not in texts


def test_words_in_window(store_with_song):
    track = SubtitleTrack(store_with_song, asset_id="song/audio.mp3")
    words = track.words_in(13.0, 13.5)
    texts = [a.body["text"] for a in words]
    assert "down" in texts
    assert "to" in texts
    assert "the" in texts
    # Earlier ones don't overlap.
    assert "I" not in texts


def test_sections_covering(store_with_song):
    track = SubtitleTrack(store_with_song, asset_id="song/audio.mp3")
    at_42 = track.sections_covering(42.0)
    assert len(at_42) == 1
    assert at_42[0].body["label"] == "chorus"

    at_0 = track.sections_covering(0.0)
    assert at_0 and at_0[0].body["label"] == "intro"


def test_word_confidence_round_trips(store_with_song):
    track = SubtitleTrack(store_with_song, asset_id="song/audio.mp3")
    by_text = {a.body["text"]: a for a in track.all_words()}
    assert by_text["came"].body["confidence"] == pytest.approx(0.95)
    assert by_text["river"].body["confidence"] == pytest.approx(0.88)
    # Words inserted without explicit confidence don't get one
    # (None should not be persisted).
    assert "confidence" not in by_text["I"].body


def test_asset_filter_excludes_other_songs():
    store = MemoryStore()
    with SubtitleBuilder(store, asset_id="song-a") as b:
        b.section("intro", 0.0, 5.0)
    with SubtitleBuilder(store, asset_id="song-b") as b:
        b.section("intro", 0.0, 5.0)

    a = SubtitleTrack(store, asset_id="song-a")
    b = SubtitleTrack(store, asset_id="song-b")
    both = SubtitleTrack(store, asset_id=None)
    assert len(a.all_sections()) == 1
    assert len(b.all_sections()) == 1
    assert len(both.all_sections()) == 2


def test_builtin_body_schemas_have_expected_uris():
    expected = {
        "annot://schema/song-section/v1",
        "annot://schema/lyric-line/v1",
        "annot://schema/word/v1",
    }
    assert set(BUILT_IN_BODY_SCHEMAS) == expected


def test_zero_length_intervals_are_widened_by_one_tick():
    """``end_s == start_s`` should not raise — widen to one tick."""
    store = MemoryStore()
    b = SubtitleBuilder(store, asset_id="song")
    receipt = b.section("flash", 5.0, 5.0)  # would otherwise be empty
    assert receipt.tier == SECTIONS_TIER


def test_register_subtitle_schemas_smoke():
    """The optional schema registration should not raise."""
    pytest.importorskip("pydantic")
    from lacing.tracks.subtitle import register_subtitle_schemas

    register_subtitle_schemas()  # idempotent
    register_subtitle_schemas()
