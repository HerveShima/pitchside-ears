"""Validation rules for generated match data."""

from collections import Counter

from app.models import Event, Issue, Match, TeamCode

MAX_PITCH_X = 105.0
MAX_PITCH_Y = 68.0
MAX_EVENT_SPEED_KMH = 130.0
TEAM_EVENT_TOTAL_FIELDS = {
    "passes": "pass",
    "shots": "shot",
    "goals": "goal",
    "fouls": "foul",
    "cards": "card",
    "tackles": "tackle",
    "interceptions": "interception",
    "pressure_events": "pressure",
    "substitutions": "substitution",
    "possession_changes": "possession_change",
    "possessions": "possession_change",
}


def _event_minute(event: Event) -> int:
    """Return the expected displayed minute for an elapsed event time."""
    return min(90, int(event.t // 60))


def _check_player_rosters(
    match: Match, issues: list[Issue], team_rosters: dict[TeamCode, set[str]]
) -> None:
    """Check roster exclusivity and each event's player references."""
    team_a_players = match.team_a.roster + match.team_a.substitutes
    team_b_players = match.team_b.roster + match.team_b.substitutes
    team_a_ids = {player.id for player in team_a_players}
    team_b_ids = {player.id for player in team_b_players}
    team_a_names = {player.name.casefold() for player in team_a_players}
    team_b_names = {player.name.casefold() for player in team_b_players}
    if team_a_ids & team_b_ids or team_a_names & team_b_names:
        issues.append(
            Issue(
                code="player_on_both_teams",
                severity="error",
                message="a player identity appears in both team rosters",
            )
        )
    for event in match.events:
        for player_id in (event.player, event.related_player):
            if player_id is not None and player_id not in team_rosters[event.team]:
                issues.append(
                    Issue(
                        code="unknown_player",
                        severity="error",
                        message=f"player {player_id!r} is not on team {event.team}'s roster",
                        event_id=event.id,
                    )
                )


def _check_player_removals(match: Match, issues: list[Issue]) -> None:
    """Reject events involving a player after a red card or substitution off."""
    removals: dict[tuple[TeamCode, str], tuple[float, str]] = {}
    for event in match.events:
        if event.type == "card" and event.outcome.casefold() == "red":
            removals[(event.team, event.player)] = (event.t, "red card")
        if event.type == "substitution":
            removals[(event.team, event.player)] = (event.t, "substitution off")
    for event in match.events:
        participants = (event.player, event.related_player)
        for player_id in participants:
            if player_id is None:
                continue
            removal = removals.get((event.team, player_id))
            if removal is None:
                continue
            removal_time, reason = removal
            is_removal_event = (
                event.type == "substitution" and event.player == player_id
            ) or (
                event.type == "card"
                and event.outcome.casefold() == "red"
                and event.player == player_id
            )
            if event.t > removal_time and not is_removal_event:
                issues.append(
                    Issue(
                        code=(
                            "player_after_red_card"
                            if reason == "red card"
                            else "player_after_substitution"
                        ),
                        severity="error",
                        message=f"player {player_id!r} appears after {reason}",
                        event_id=event.id,
                    )
                )


def _check_goals_and_score(match: Match, issues: list[Issue]) -> None:
    """Check shot-goal links and compare the final score with goal events."""
    event_by_id = {event.id: event for event in match.events}
    goals_by_shot: Counter[str] = Counter()
    for event in match.events:
        if event.type == "goal":
            shot = event_by_id.get(event.related_event_id or "")
            if (
                shot is None
                or shot.type != "shot"
                or shot.outcome.casefold() != "goal"
                or shot.team != event.team
            ):
                issues.append(
                    Issue(
                        code="goal_event_mismatch",
                        severity="error",
                        message="goal event must reference a goal-outcome shot for the same team",
                        event_id=event.id,
                    )
                )
            elif event.related_event_id is not None:
                goals_by_shot[event.related_event_id] += 1
    for event in match.events:
        if event.type == "shot" and event.outcome.casefold() == "goal":
            if goals_by_shot[event.id] != 1:
                issues.append(
                    Issue(
                        code="goal_event_mismatch",
                        severity="error",
                        message="a goal-outcome shot must have exactly one linked goal event",
                        event_id=event.id,
                    )
                )
    goals_a = sum(event.type == "goal" and event.team == "A" for event in match.events)
    goals_b = sum(event.type == "goal" and event.team == "B" for event in match.events)
    if match.final_score.team_a != goals_a or match.final_score.team_b != goals_b:
        issues.append(
            Issue(
                code="final_score_mismatch",
                severity="error",
                message="final score does not match the emitted goal events",
            )
        )


def _check_possession_changes(match: Match, issues: list[Issue]) -> None:
    """Check possession changes alternate from the current team."""
    active_team: TeamCode | None = None
    for event in match.events:
        if event.type != "possession_change":
            continue
        if event.from_team is None or event.from_team == event.team:
            issues.append(
                Issue(
                    code="possession_change_invalid",
                    severity="error",
                    message="possession change must name a different previous team",
                    event_id=event.id,
                )
            )
            continue
        if active_team is not None and event.from_team != active_team:
            issues.append(
                Issue(
                    code="possession_change_invalid",
                    severity="error",
                    message="possession change previous team does not match current possession",
                    event_id=event.id,
                )
            )
        active_team = event.team


def _check_totals(match: Match, issues: list[Issue]) -> None:
    """Compare every recorded per-team count with emitted event counts."""
    for code in ("A", "B"):
        totals = match.team_totals.get(code)
        if totals is None:
            issues.append(
                Issue(
                    code="team_totals_mismatch",
                    severity="error",
                    message=f"team {code} is missing totals",
                )
            )
            continue
        team_events = [event for event in match.events if event.team == code]
        for field, event_type in TEAM_EVENT_TOTAL_FIELDS.items():
            actual = sum(event.type == event_type for event in team_events)
            if field == "possessions":
                actual = sum(event.type == "possession_change" for event in team_events)
            if getattr(totals, field) != actual:
                issues.append(
                    Issue(
                        code="team_totals_mismatch",
                        severity="error",
                        message=f"team {code} {field} total does not match emitted events",
                    )
                )
        actual_injuries = sum(
            event.stoppage_seconds is not None for event in team_events
        )
        if totals.injury_stoppages != actual_injuries:
            issues.append(
                Issue(
                    code="team_totals_mismatch",
                    severity="error",
                    message=f"team {code} injury stoppage total does not match emitted events",
                )
            )
    possession_seconds = sum(
        match.team_totals[code].possession_seconds for code in ("A", "B")
    )
    if abs(possession_seconds - match.duration_seconds) > 0.3:
        issues.append(
            Issue(
                code="team_totals_mismatch",
                severity="error",
                message="team possession seconds must sum to match duration",
            )
        )


def _check_story_causality(match: Match, issues: list[Issue]) -> None:
    """Ensure planted stories reference the event pattern they describe."""
    events_by_id = {event.id: event for event in match.events}
    for story in match.planted_stories:
        evidence = [
            events_by_id[event_id]
            for event_id in story.event_ids
            if event_id in events_by_id
        ]
        issue_event_id = story.event_ids[0] if story.event_ids else None
        valid = True
        if story.kind == "pressing_spell":
            valid = sum(
                event.type == "pressure" and event.team == story.team
                for event in evidence
            ) >= 2
        elif story.kind == "momentum_swing":
            goals = [event for event in evidence if event.type == "goal"]
            valid = any(
                event.type == "pressure"
                and any(
                    event.team != goal.team and event.t > goal.t
                    for goal in goals
                )
                for event in evidence
            )
        elif story.kind == "red_card_impact":
            red_cards = [
                event
                for event in evidence
                if event.type == "card"
                and event.outcome.casefold() == "red"
                and event.team == story.team
            ]
            valid = any(
                event.t > red.t
                and event.team != red.team
                and event.type in {"pressure", "goal"}
                for event in evidence
                for red in red_cards
            )
        elif story.kind == "late_drama":
            valid = any(
                event.type == "goal"
                and event.team == story.team
                and event.minute > 80
                for event in evidence
            )
        elif story.kind == "hot_streak":
            passes = [event for event in evidence if event.type == "pass"]
            valid = (
                len(passes) >= 3
                and len({event.player for event in passes}) == 1
                and max(event.t for event in passes) - min(event.t for event in passes)
                <= 5 * 60
            )
        elif story.kind == "big_chance_saved":
            valid = any(
                event.type == "shot"
                and event.team == story.team
                and event.outcome.casefold() == "saved"
                and event.xg is not None
                and event.xg >= 0.2
                for event in evidence
            )
        elif story.kind == "set_piece_goal":
            set_piece_shots = {
                event.id
                for event in evidence
                if event.type == "shot"
                and event.outcome.casefold() == "goal"
                and event.set_piece
            }
            valid = any(
                event.type == "goal"
                and event.team == story.team
                and event.related_event_id in set_piece_shots
                for event in evidence
            )
        if not valid:
            issues.append(
                Issue(
                    code="story_evidence_invalid",
                    severity="error",
                    message=f"story {story.kind!r} lacks matching causal event evidence",
                    event_id=issue_event_id,
                )
            )


def validate_match(match: Match) -> list[Issue]:
    """Return all detectable schema and consistency issues in a match."""
    issues: list[Issue] = []
    seen_ids: set[str] = set()
    previous_time: float | None = None
    for event in match.events:
        if event.id in seen_ids:
            issues.append(
                Issue(
                    code="duplicate_event_id",
                    severity="error",
                    message=f"event id {event.id!r} is not unique",
                    event_id=event.id,
                )
            )
        seen_ids.add(event.id)
        if previous_time is not None and event.t < previous_time:
            issues.append(
                Issue(
                    code="event_time_decreasing",
                    severity="error",
                    message="event times must be non-decreasing",
                    event_id=event.id,
                )
            )
        previous_time = event.t
        if event.minute != _event_minute(event):
            issues.append(
                Issue(
                    code="minute_inconsistent",
                    severity="error",
                    message="event minute is inconsistent with elapsed seconds",
                    event_id=event.id,
                )
            )
        for coordinate, value, upper_bound in (
            ("x", event.x, MAX_PITCH_X),
            ("end_x", event.end_x, MAX_PITCH_X),
            ("y", event.y, MAX_PITCH_Y),
            ("end_y", event.end_y, MAX_PITCH_Y),
        ):
            if value is not None and not 0 <= value <= upper_bound:
                issues.append(
                    Issue(
                        code="coordinate_out_of_bounds",
                        severity="error",
                        message=f"{coordinate} coordinate is outside the pitch",
                        event_id=event.id,
                    )
                )
        for speed_name, speed in (
            ("ball_speed_kmh", event.ball_speed_kmh),
            ("shot_speed_kmh", event.shot_speed_kmh),
        ):
            if speed is not None and not 0 <= speed < MAX_EVENT_SPEED_KMH:
                issues.append(
                    Issue(
                        code=(
                            "ball_speed_implausible"
                            if speed_name == "ball_speed_kmh"
                            else "shot_speed_implausible"
                        ),
                        severity="error",
                        message=f"{speed_name} must be below {MAX_EVENT_SPEED_KMH} km/h",
                        event_id=event.id,
                    )
                )
        if event.type == "shot" and (
            event.xg is None or event.shot_speed_kmh is None
        ):
            issues.append(
                Issue(
                    code="shot_metadata_missing",
                    severity="error",
                    message="shots must include xG and shot speed",
                    event_id=event.id,
                )
            )
        if event.type == "pass" and (
            event.pass_difficulty is None or event.ball_speed_kmh is None
        ):
            issues.append(
                Issue(
                    code="pass_metadata_missing",
                    severity="error",
                    message="passes must include difficulty and ball speed",
                    event_id=event.id,
                )
            )

    rosters: dict[TeamCode, set[str]] = {
        "A": {
            player.id
            for player in match.team_a.roster + match.team_a.substitutes
        },
        "B": {
            player.id
            for player in match.team_b.roster + match.team_b.substitutes
        },
    }
    _check_player_rosters(match, issues, rosters)
    _check_player_removals(match, issues)
    _check_goals_and_score(match, issues)
    _check_possession_changes(match, issues)
    _check_totals(match, issues)

    event_ids = {event.id for event in match.events}
    for story in match.planted_stories:
        for event_id in story.event_ids:
            if event_id not in event_ids:
                issues.append(
                    Issue(
                        code="story_event_missing",
                        severity="error",
                        message=f"story {story.kind!r} references missing event {event_id!r}",
                        event_id=event_id,
                    )
                )
    _check_story_causality(match, issues)
    return issues
