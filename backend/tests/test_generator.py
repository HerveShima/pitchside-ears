"""Tests for deterministic synthetic match generation and variety."""

import json
import statistics
from collections.abc import Sequence

import pytest

from app.generator.generator import generate_match
from app.generator.validator import validate_match
from app.models import Event

DEMO_STORY_KINDS = {
    "pressing_spell",
    "momentum_swing",
    "red_card_impact",
    "late_drama",
    "hot_streak",
}


def test_same_seed_produces_identical_json() -> None:
    """A fixed seed must serialize identically across repeated generation."""
    assert generate_match(2026).model_dump_json() == generate_match(2026).model_dump_json()


def test_different_seeds_produce_different_json() -> None:
    """Different seeds must vary teams, tactics, events, or outcomes."""
    assert generate_match(2026).model_dump_json() != generate_match(2027).model_dump_json()


@pytest.mark.parametrize("seed", range(1, 21))
def test_generated_match_passes_validation_and_wide_ranges(seed: int) -> None:
    """Initial seeds stay within the revised broad realism limits."""
    match = generate_match(seed)
    assert validate_match(match) == []
    totals = match.team_totals
    assert 250 <= totals["A"].passes <= 600
    assert 250 <= totals["B"].passes <= 600
    assert 4 <= totals["A"].shots <= 24
    assert 4 <= totals["B"].shots <= 24
    assert 0 <= totals["A"].goals + totals["B"].goals <= 7
    assert 5 <= totals["A"].fouls + totals["B"].fouls <= 25
    assert 0 <= totals["A"].cards + totals["B"].cards <= 7
    assert 3 <= totals["A"].substitutions <= 5
    assert 3 <= totals["B"].substitutions <= 5


def test_seed_2026_keeps_required_stories_and_demo_beats() -> None:
    """The selected demo seed retains all five story beats and key events."""
    match = generate_match(2026)
    stories = {story.kind: story for story in match.planted_stories}
    events_by_id = {event.id: event for event in match.events}

    assert set(stories) == DEMO_STORY_KINDS
    assert all(
        set(story.event_ids).issubset(events_by_id)
        for story in match.planted_stories
    )
    assert any(
        event.type == "shot"
        and event.outcome == "saved"
        and event.xg is not None
        and event.xg >= 0.20
        for event in match.events
    )

    goal_shots = [
        event for event in match.events
        if event.type == "shot" and event.outcome == "goal"
    ]
    assert any(
        sum(
            event.type == "pass"
            and event.team == shot.team
            and last_possession_change(match.events, shot.id).t < event.t < shot.t
            for event in match.events
        ) >= 5
        for shot in goal_shots
    )


def last_possession_change(events: Sequence[Event], event_id: str) -> Event:
    """Find the latest possession boundary before an event."""
    event_index = next(index for index, event in enumerate(events) if event.id == event_id)
    return next(
        event
        for event in reversed(events[:event_index])
        if event.type == "possession_change"
    )


def test_stories_are_causal_and_varied_for_other_seeds() -> None:
    """Seeds outside the demo receive three to five stories with real evidence."""
    for seed in range(1, 21):
        match = generate_match(seed)
        event_ids = {event.id for event in match.events}
        assert 3 <= len(match.planted_stories) <= 5
        assert all(story.event_ids for story in match.planted_stories)
        assert all(
            set(story.event_ids).issubset(event_ids)
            for story in match.planted_stories
        )


def test_distribution_and_validator_over_seeds_1_to_200() -> None:
    """The full acceptance seed range passes and exhibits real match variety."""
    matches = [generate_match(seed) for seed in range(1, 201)]
    for match in matches:
        assert validate_match(match) == []

    goal_totals = [
        match.team_totals["A"].goals + match.team_totals["B"].goals
        for match in matches
    ]
    red_counts = [
        sum(
            event.type == "card" and event.outcome == "red"
            for event in match.events
        )
        for match in matches
    ]
    shot_totals = [
        match.team_totals[code].shots
        for match in matches
        for code in ("A", "B")
    ]
    assert all(
        250 <= match.team_totals[code].passes <= 600
        and 4 <= match.team_totals[code].shots <= 24
        for match in matches
        for code in ("A", "B")
    )
    assert all(0 <= total <= 7 for total in goal_totals)
    assert all(
        5
        <= match.team_totals["A"].fouls + match.team_totals["B"].fouls
        <= 25
        for match in matches
    )
    assert all(
        0 <= match.team_totals["A"].cards + match.team_totals["B"].cards <= 7
        and 3 <= match.team_totals["A"].substitutions <= 5
        and 3 <= match.team_totals["B"].substitutions <= 5
        for match in matches
    )
    assert len(set(goal_totals)) >= 5
    assert statistics.stdev(shot_totals) > 2.0
    assert {0, 1, 2}.issubset(set(red_counts))
    assert red_counts.count(2) >= 1
    assert len({match.archetype for match in matches}) >= 3
    assert any(
        match.team_totals["A"].goals == 0
        and match.team_totals["B"].goals == 0
        for match in matches
    )
    assert any(
        (match.team_totals["A"].goals, match.team_totals["B"].goals) == (4, 3)
        for match in matches
    )


def test_match_json_is_small_and_round_trips() -> None:
    """Generated match JSON is below the demo limit and remains JSON."""
    match = generate_match(2026)
    serialized = match.model_dump_json(indent=2)
    assert len(serialized.encode("utf-8")) < 1_000_000
    assert json.loads(serialized)["seed"] == 2026
