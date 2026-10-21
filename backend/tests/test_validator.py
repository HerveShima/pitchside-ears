"""Corruption tests for match validation rules."""

from collections.abc import Callable

import pytest

from app.generator.generator import generate_match
from app.generator.validator import validate_match
from app.models import Match


def _replace_event(match: Match, index: int, **changes: object) -> Match:
    """Return a match copy with one event changed."""
    events = list(match.events)
    events[index] = events[index].model_copy(update=changes)
    return match.model_copy(update={"events": events})


def _has_code(match: Match, code: str) -> bool:
    """Check whether validation reports a specified issue code."""
    return any(issue.code == code for issue in validate_match(match))


def _first_index(match: Match, event_type: str) -> int:
    """Find the first event index of a requested type."""
    return next(index for index, event in enumerate(match.events) if event.type == event_type)


def test_out_of_bounds_coordinate_is_reported() -> None:
    """Coordinates beyond the pitch produce a coordinate finding."""
    match = generate_match(17)
    corrupted = _replace_event(match, _first_index(match, "pass"), x=106.0)
    assert _has_code(corrupted, "coordinate_out_of_bounds")


def test_impossible_ball_speed_is_reported() -> None:
    """Ball speeds at or above 130 km/h are rejected."""
    match = generate_match(17)
    pass_index = _first_index(match, "pass")
    corrupted = _replace_event(match, pass_index, ball_speed_kmh=140.0)
    assert _has_code(corrupted, "ball_speed_implausible")


def test_decreasing_event_time_is_reported() -> None:
    """A later list entry earlier in time produces a monotonicity finding."""
    match = generate_match(17)
    events = list(match.events)
    events[1] = events[1].model_copy(update={"t": events[0].t - 1.0})
    corrupted = match.model_copy(update={"events": events})
    assert _has_code(corrupted, "event_time_decreasing")


def test_unknown_player_is_reported() -> None:
    """An event player absent from the team's roster is rejected."""
    match = generate_match(17)
    corrupted = _replace_event(match, _first_index(match, "pass"), player="Z99")
    assert _has_code(corrupted, "unknown_player")


def test_event_after_red_card_is_reported() -> None:
    """A sent-off player's later involvement is rejected."""
    match = generate_match(2026)
    red_card = next(
        event
        for event in match.events
        if event.type == "card" and event.outcome == "red"
    )
    later_index = next(
        index
        for index, event in enumerate(match.events)
        if event.team == red_card.team
        and event.t > red_card.t
        and event.type not in {"substitution"}
    )
    corrupted = _replace_event(
        match, later_index, player=red_card.player
    )
    assert _has_code(corrupted, "player_after_red_card")


def test_wrong_final_score_is_reported() -> None:
    """Final score inconsistent with emitted goals is rejected."""
    match = generate_match(17)
    corrupted = match.model_copy(
        update={
            "final_score": match.final_score.model_copy(
                update={"team_a": match.final_score.team_a + 1}
            )
        }
    )
    assert _has_code(corrupted, "final_score_mismatch")


def test_duplicate_event_id_is_reported() -> None:
    """Repeated event identifiers are rejected."""
    match = generate_match(17)
    events = list(match.events)
    events[1] = events[1].model_copy(update={"id": events[0].id})
    corrupted = match.model_copy(update={"events": events})
    assert _has_code(corrupted, "duplicate_event_id")


@pytest.mark.parametrize(
    ("corrupt", "expected_code"),
    [
        (
            lambda match: _replace_event(
                match, _first_index(match, "shot"), shot_speed_kmh=130.0
            ),
            "shot_speed_implausible",
        ),
    ],
)
def test_shot_speed_boundary_is_validated(
    corrupt: Callable[[Match], Match], expected_code: str
) -> None:
    """Shot speed must remain strictly below the configured upper bound."""
    assert _has_code(corrupt(generate_match(18)), expected_code)
