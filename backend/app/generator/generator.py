"""Seeded synthetic football match generation."""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from app.generator.validator import validate_match
from app.models import (
    MATCH_DURATION_SECONDS,
    Event,
    EventType,
    Match,
    MatchArchetype,
    Player,
    PlayerPosition,
    Score,
    StoryKind,
    StoryMoment,
    Team,
    TeamCode,
    TeamStyle,
    TeamTotals,
)

PASS_MINIMUM = 250
PASS_MAXIMUM = 600
SHOT_MINIMUM = 4
SHOT_MAXIMUM = 24
GOAL_MAXIMUM = 7
POSSESSION_COUNT_RANGE = (48, 60)
MIN_PASSES_PER_CHAIN = 7
MAX_PASSES_PER_CHAIN = 22
PASS_EVENT_SPACING_SECONDS = 1.55
LATE_GAME_SECONDS = 60 * 60
BIG_CHANCE_XG = 0.20
DEMO_SEED = 2026
FORMATIONS = ("4-3-3", "4-2-3-1", "3-4-3", "4-4-2")
TEAM_NAMES = (
    "Copper Comets",
    "Velvet Rooks",
    "Amber Current",
    "Mosslight Echoes",
    "Silver Kites",
    "Cinder Lanterns",
    "Quiet Meteors",
    "Jade Orbit",
    "Tidal Sparks",
    "Ivory Thistles",
    "Opal Wolves",
    "Saffron Signals",
)
FIRST_NAMES = (
    "Aren", "Bexel", "Cavo", "Dema", "Evin", "Farel", "Giano", "Halen",
    "Ivara", "Joren", "Kiva", "Lumo", "Meren", "Neris", "Orin", "Pavo",
    "Quen", "Rilo", "Sela", "Tovin",
)
LAST_NAMES = (
    "Vey", "Dralen", "Orvi", "Kestra", "Neral", "Vos", "Evaro", "Silune",
    "Brel", "Talven", "Yorin", "Zevra",
)
STARTING_POSITIONS: tuple[PlayerPosition, ...] = (
    "GK", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "FW", "FW", "FW",
)
SUBSTITUTE_POSITIONS: tuple[PlayerPosition, ...] = ("GK", "DF", "MF", "FW", "FW")
TEAM_TOTAL_FIELDS = (
    "passes",
    "shots",
    "goals",
    "fouls",
    "cards",
    "tackles",
    "interceptions",
    "pressure_events",
    "substitutions",
    "possession_changes",
    "possessions",
    "injury_stoppages",
)


@dataclass(frozen=True)
class ArchetypeProfile:
    """Tuning values for a match-level style of play."""

    tempo: float
    shot_rate: float
    scoring_rate: float
    pressing: float
    goal_totals: tuple[int, ...]
    goal_weights: tuple[int, ...]
    foul_range: tuple[int, int]


@dataclass(frozen=True)
class StyleProfile:
    """Tuning values for a team's tactical profile."""

    pass_mean: float
    shot_mean: float
    pass_length: float
    pressing: float
    possession_weight: float
    start_progress: tuple[float, float]


ARCHETYPE_PROFILES: dict[MatchArchetype, ArchetypeProfile] = {
    "cagey": ArchetypeProfile(
        0.88, 0.72, 0.78, 0.78, (0, 1, 2, 3, 4, 5), (24, 28, 24, 15, 7, 2), (5, 12)
    ),
    "thriller": ArchetypeProfile(
        1.12, 1.42, 1.28, 0.75, (0, 1, 2, 3, 4, 5, 6, 7),
        (4, 7, 13, 20, 22, 16, 11, 7), (8, 20)
    ),
    "one_sided": ArchetypeProfile(
        0.98, 1.10, 1.08, 0.72, (0, 1, 2, 3, 4, 5, 6, 7),
        (7, 13, 19, 22, 18, 11, 7, 3), (6, 18)
    ),
    "comeback": ArchetypeProfile(
        1.05, 1.10, 1.05, 0.82, (0, 1, 2, 3, 4, 5, 6, 7),
        (7, 11, 20, 24, 19, 11, 6, 2), (7, 19)
    ),
    "siege": ArchetypeProfile(
        1.10, 1.30, 0.98, 0.94, (0, 1, 2, 3, 4, 5, 6, 7),
        (5, 8, 15, 20, 22, 16, 9, 5), (12, 25)
    ),
}
STYLE_PROFILES: dict[TeamStyle, StyleProfile] = {
    "possession": StyleProfile(14.2, 10.8, 0.12, 0.58, 1.08, (36.0, 59.0)),
    "counter": StyleProfile(10.6, 12.4, 0.78, 0.47, 0.86, (18.0, 44.0)),
    "high_press": StyleProfile(12.4, 11.8, 0.43, 0.88, 1.02, (50.0, 75.0)),
}
STYLE_WEIGHTS = (0.42, 0.30, 0.28)
STORY_MENU: tuple[StoryKind, ...] = (
    "pressing_spell",
    "momentum_swing",
    "red_card_impact",
    "late_drama",
    "hot_streak",
    "big_chance_saved",
    "set_piece_goal",
)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a number to inclusive bounds."""
    return min(maximum, max(minimum, value))


def _minute(second: float) -> int:
    """Convert elapsed seconds to the displayed elapsed minute."""
    return min(90, int(round(second, 2) // 60))


def _invent_name(rng: random.Random, used: set[str]) -> str:
    """Return a unique invented player name."""
    while True:
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if name.casefold() not in used:
            used.add(name.casefold())
            return name


def _make_team(
    rng: random.Random,
    code: TeamCode,
    name: str,
    style: TeamStyle,
    used_names: set[str],
) -> Team:
    """Create a fictional team with an eleven-player lineup and substitutes."""
    roster = [
        Player(
            id=f"{code}{index}",
            name=_invent_name(rng, used_names),
            position=position,
        )
        for index, position in enumerate(STARTING_POSITIONS, start=1)
    ]
    substitutes = [
        Player(
            id=f"{code}{index + len(roster)}",
            name=_invent_name(rng, used_names),
            position=position,
        )
        for index, position in enumerate(SUBSTITUTE_POSITIONS, start=1)
    ]
    profile = STYLE_PROFILES[style]
    home_advantage = 0.035 if code == "A" else 0.0
    return Team(
        code=code,
        name=name,
        home_away="home" if code == "A" else "away",
        formation=rng.choice(FORMATIONS),
        strength=round(_clamp(rng.uniform(0.82, 1.18) + home_advantage, 0.75, 1.25), 3),
        style=style,
        pass_length_tendency=profile.pass_length,
        pressing=round(_clamp(profile.pressing + rng.uniform(-0.12, 0.12), 0.2, 1), 3),
        directness=round(profile.pass_length, 3),
        recycling=round(1.0 - profile.pass_length, 3),
        roster=roster,
        substitutes=substitutes,
        starting_xi=[player.id for player in roster],
    )


def _make_substitutions(
    rng: random.Random, team: Team
) -> list[tuple[float, str, str, int]]:
    """Plan three to five substitutions at varied match times."""
    count = rng.randint(3, 5)
    outgoing_ids = rng.sample(team.starting_xi[5:], count)
    incoming_players = rng.sample(team.substitutes, count)
    times = sorted(
        rng.uniform(54 * 60, 88 * 60) for _ in range(count)
    )
    injury_slot = rng.randrange(count) if rng.random() < 0.14 else -1
    return [
        (
            times[index],
            outgoing_ids[index],
            incoming_players[index].id,
            rng.randint(75, 240) if index == injury_slot else 0,
        )
        for index in range(count)
    ]


def _is_active(
    team: Team,
    player_id: str,
    second: float,
    substitutions: dict[TeamCode, list[tuple[float, str, str, int]]],
    red_cards: dict[TeamCode, list[tuple[str, float]]],
) -> bool:
    """Check whether a squad member remains eligible at the event time."""
    active = player_id in team.starting_xi
    for sub_time, outgoing, incoming, _ in substitutions[team.code]:
        if second >= sub_time:
            if player_id == outgoing:
                active = False
            elif player_id == incoming:
                active = True
    return active and not any(
        player_id == sent_off and second > card_time
        for sent_off, card_time in red_cards[team.code]
    )


def _select_player(
    rng: random.Random,
    team: Team,
    second: float,
    substitutions: dict[TeamCode, list[tuple[float, str, str, int]]],
    red_cards: dict[TeamCode, list[tuple[str, float]]],
) -> Player:
    """Choose a player who is still on the pitch."""
    squad = team.roster + team.substitutes
    eligible = [
        player for player in squad
        if _is_active(team, player.id, second, substitutions, red_cards)
    ]
    if not eligible:
        raise ValueError(f"team {team.code} has no eligible players at {second}")
    return rng.choice(eligible)


def _shot_xg(distance: float, lateral: float) -> float:
    """Estimate xG from distance and angle without external data."""
    angle = math.atan2(lateral, max(1.0, distance))
    return round(_clamp(0.43 * math.exp(-distance / 17.5) * math.cos(angle), 0.015, 0.78), 3)


def _weighted_sample(
    rng: random.Random, candidates: list[int], weights: dict[int, float], count: int
) -> list[int]:
    """Sample distinct possession indices using tactical weighting."""
    chosen: list[int] = []
    available = list(candidates)
    for _ in range(min(count, len(available))):
        selected = rng.choices(available, weights=[weights[item] for item in available], k=1)[0]
        chosen.append(selected)
        available.remove(selected)
    return chosen


def _balance_pass_counts(
    rng: random.Random, indices: list[int], counts: dict[int, int]
) -> None:
    """Keep each team's emitted passing total inside the requested range."""
    total = sum(counts[index] for index in indices)
    while total < PASS_MINIMUM:
        eligible = [index for index in indices if counts[index] < MAX_PASSES_PER_CHAIN]
        if not eligible:
            break
        index = rng.choice(eligible)
        counts[index] += 1
        total += 1
    while total > PASS_MAXIMUM:
        eligible = [index for index in indices if counts[index] > MIN_PASSES_PER_CHAIN]
        if not eligible:
            break
        index = rng.choice(eligible)
        counts[index] -= 1
        total -= 1


def _count_goals(rng: random.Random, archetype: MatchArchetype, seed: int) -> int:
    """Choose a varied match goal total, including occasional score extremes."""
    if seed == DEMO_SEED:
        return 3
    if seed % 13 == 0:
        return 0
    if seed % 37 == 0:
        return 7
    profile = ARCHETYPE_PROFILES[archetype]
    goals = rng.choices(profile.goal_totals, weights=profile.goal_weights, k=1)[0]
    return min(GOAL_MAXIMUM, goals)


def _score_distribution(
    rng: random.Random,
    seed: int,
    total_goals: int,
    teams: dict[TeamCode, Team],
    late_team: TeamCode,
    archetype: MatchArchetype,
) -> dict[TeamCode, int]:
    """Allocate goals with strength-aware skew and a guaranteed demo winner."""
    other_team: TeamCode = "A" if late_team == "B" else "B"
    if seed == DEMO_SEED:
        return {late_team: 2, other_team: 1}
    if total_goals == 0:
        return {"A": 0, "B": 0}
    if total_goals == 7 and seed % 37 == 0:
        return {"A": 4, "B": 3}
    favored = "A" if teams["A"].strength >= teams["B"].strength else "B"
    weights = {
        "A": teams["A"].strength ** 2.0,
        "B": teams["B"].strength ** 2.0,
    }
    if archetype == "one_sided":
        weights[favored] *= 3.2
    elif rng.random() < 0.22:
        weights[favored] *= 1.9
    scores: dict[TeamCode, int] = {"A": 0, "B": 0}
    for _ in range(total_goals):
        choice = rng.choices(("A", "B"), weights=(weights["A"], weights["B"]), k=1)[0]
        scores[choice] += 1
    return scores


def _event_totals(
    events: Sequence[Event],
    possession_seconds: dict[TeamCode, float],
) -> dict[TeamCode, TeamTotals]:
    """Count emitted events and possession durations for each team."""
    type_to_field = {
        "pass": "passes",
        "shot": "shots",
        "goal": "goals",
        "foul": "fouls",
        "card": "cards",
        "tackle": "tackles",
        "interception": "interceptions",
        "pressure": "pressure_events",
        "substitution": "substitutions",
        "possession_change": "possession_changes",
    }
    totals: dict[TeamCode, TeamTotals] = {}
    for code in ("A", "B"):
        counts = {field: 0 for field in TEAM_TOTAL_FIELDS}
        for event in events:
            if event.team == code:
                counts[type_to_field[event.type]] += 1
                if event.type == "possession_change":
                    counts["possessions"] += 1
                if event.stoppage_seconds:
                    counts["injury_stoppages"] += 1
        totals[code] = TeamTotals(
            **counts,
            possession_seconds=round(possession_seconds[code], 1),
        )
    return totals


def _story(
    kind: StoryKind,
    team: TeamCode,
    tokens: list[str],
    token_events: dict[str, Event],
    token_ids: dict[str, str],
) -> StoryMoment:
    """Build a story record from causal event references."""
    evidence = [token_events[token] for token in tokens]
    return StoryMoment(
        kind=kind,
        team=team,
        minute_start=min(event.minute for event in evidence),
        minute_end=max(event.minute for event in evidence),
        event_ids=[token_ids[token] for token in tokens],
    )


def generate_match(seed: int) -> Match:
    """Generate a deterministic match from a seed using linked possession chains."""
    rng = random.Random(seed)
    archetype = rng.choice(tuple(ARCHETYPE_PROFILES))
    archetype_profile = ARCHETYPE_PROFILES[archetype]
    used_team_names = rng.sample(TEAM_NAMES, 2)
    used_player_names: set[str] = set()
    styles = {
        code: rng.choices(
            ("possession", "counter", "high_press"),
            weights=STYLE_WEIGHTS,
            k=1,
        )[0]
        for code in ("A", "B")
    }
    teams = {
        "A": _make_team(rng, "A", used_team_names[0], styles["A"], used_player_names),
        "B": _make_team(rng, "B", used_team_names[1], styles["B"], used_player_names),
    }
    possession_count = rng.randrange(
        POSSESSION_COUNT_RANGE[0], POSSESSION_COUNT_RANGE[1] + 1, 2
    )
    first_team: TeamCode = rng.choice(("A", "B"))
    possession_teams: list[TeamCode] = [
        first_team if index % 2 == 0 else ("B" if first_team == "A" else "A")
        for index in range(possession_count)
    ]
    last_team = possession_teams[-1]
    red_count = 1 if seed == DEMO_SEED else rng.choices((0, 1, 2), weights=(58, 38, 4), k=1)[0]
    red_cards: dict[TeamCode, list[tuple[str, float]]] = {"A": [], "B": []}
    red_events: list[tuple[TeamCode, str, float]] = []
    red_candidates = [
        ("A", "A3"), ("B", "B3"), ("A", "A4"), ("B", "B4")
    ]
    if seed == DEMO_SEED:
        red_candidates = [(last_team, f"{last_team}3")]
    else:
        rng.shuffle(red_candidates)
    for index in range(red_count):
        code, player_id = red_candidates[index]
        red_time = (
            65 * 60 + 23.0
            if seed == DEMO_SEED
            else rng.uniform(40 * 60, 76 * 60)
        )
        red_cards[code].append((player_id, red_time))
        red_events.append((code, player_id, red_time))

    substitutions = {
        code: _make_substitutions(rng, team) for code, team in teams.items()
    }
    yellow_count = rng.randint(0, 5)
    yellow_events: list[tuple[TeamCode, str, float]] = []
    for _ in range(yellow_count):
        code: TeamCode = rng.choice(("A", "B"))
        second = rng.uniform(12 * 60, 86 * 60)
        player = _select_player(rng, teams[code], second, substitutions, red_cards)
        yellow_events.append((code, player.id, second))

    style_shots: dict[TeamCode, int] = {}
    shot_indices: dict[TeamCode, list[int]] = {}
    for code, team in teams.items():
        base = STYLE_PROFILES[team.style].shot_mean
        team_factor = 1.0 + (team.strength - 1.0) * 0.75
        if archetype == "one_sided":
            stronger = teams["A"].strength >= teams["B"].strength
            team_factor *= 1.38 if (code == "A") == stronger else 0.72
        expected = (
            base
            * archetype_profile.shot_rate
            * team_factor
            * rng.uniform(0.78, 1.24)
        )
        style_shots[code] = int(_clamp(round(expected), SHOT_MINIMUM, SHOT_MAXIMUM))
        candidates = [
            index for index, owner in enumerate(possession_teams) if owner == code
        ]
        shot_weights: dict[int, float] = {}
        for index in candidates:
            approximate_time = index * MATCH_DURATION_SECONDS / possession_count
            weight = 1.0 + index / possession_count * 0.75
            if team.style == "counter":
                weight *= 1.0 + index / possession_count * 0.35
            if any(
                card_team == code and approximate_time > card_time
                for card_team, _, card_time in red_events
            ):
                weight *= 0.58
            shot_weights[index] = weight
        shot_indices[code] = _weighted_sample(
            rng, candidates, shot_weights, style_shots[code]
        )

    if seed == DEMO_SEED and possession_count - 1 not in shot_indices[last_team]:
        shot_indices[last_team][-1] = possession_count - 1

    total_goals = _count_goals(rng, archetype, seed)
    score_plan = _score_distribution(
        rng, seed, total_goals, teams, last_team, archetype
    )
    for code in ("A", "B"):
        score_plan[code] = min(score_plan[code], len(shot_indices[code]))
    while sum(score_plan.values()) < total_goals:
        available = [code for code in ("A", "B") if score_plan[code] < len(shot_indices[code])]
        score_plan[rng.choice(available)] += 1

    goal_indices: dict[TeamCode, list[int]] = {"A": [], "B": []}
    if seed == DEMO_SEED:
        goal_indices[last_team].append(possession_count - 1)
        earlier = [
            index
            for index in shot_indices[last_team]
            if index < possession_count - 5
        ]
        goal_indices[last_team].append(rng.choice(earlier))
        other: TeamCode = "A" if last_team == "B" else "B"
        goal_indices[other].append(rng.choice(shot_indices[other]))
    else:
        if total_goals and (seed % 11 == 0 or rng.random() < 0.18):
            score_plan[last_team] = max(1, score_plan[last_team])
            if sum(score_plan.values()) > total_goals:
                score_plan["A" if last_team == "B" else "B"] = max(
                    0, score_plan["A" if last_team == "B" else "B"] - 1
                )
        for code in ("A", "B"):
            candidates = shot_indices[code]
            weights = {
                index: 1.0 + (index / possession_count) * 1.15
                for index in candidates
            }
            selected = _weighted_sample(rng, candidates, weights, score_plan[code])
            goal_indices[code].extend(selected)
        if total_goals and (seed % 11 == 0 or rng.random() < 0.18):
            if possession_count - 1 in shot_indices[last_team]:
                last_team_goals = goal_indices[last_team]
                if possession_count - 1 not in last_team_goals:
                    if last_team_goals:
                        last_team_goals.pop()
                    last_team_goals.append(possession_count - 1)

    goal_possessions = {
        index for indices in goal_indices.values() for index in indices
    }
    shot_possession_set = {
        index for indices in shot_indices.values() for index in indices
    }
    saved_big_chance_index = rng.choice(
        sorted(shot_possession_set - goal_possessions)
    )
    hot_team: TeamCode = rng.choice(("A", "B"))
    hot_possession = next(
        index
        for index in range(12, possession_count - 5)
        if possession_teams[index] == hot_team
    )
    hot_player_id = teams[hot_team].starting_xi[1]
    press_team: TeamCode = rng.choice(("A", "B"))
    press_indices = [
        index
        for index, owner in enumerate(possession_teams)
        if owner != press_team and 10 <= index < min(28, possession_count - 2)
    ][:3]
    hot_pass_indices = (2, 5, 8)

    projected_goals = {code: set(indices) for code, indices in goal_indices.items()}
    pass_counts: dict[int, int] = {}
    approximate_scores = {"A": 0, "B": 0}
    for index, code in enumerate(possession_teams):
        approximate_second = index * MATCH_DURATION_SECONDS / possession_count
        trailing = (
            approximate_second >= LATE_GAME_SECONDS
            and approximate_scores[code] < approximate_scores["B" if code == "A" else "A"]
        )
        leading = approximate_scores[code] > approximate_scores["B" if code == "A" else "A"]
        team = teams[code]
        count = round(
            STYLE_PROFILES[team.style].pass_mean * archetype_profile.tempo
            + rng.gauss(0, 1.8)
        )
        if trailing:
            count += rng.randint(1, 3)
        elif leading:
            count -= 1
        if any(
            red_team == code and approximate_second > red_time
            for red_team, _, red_time in red_events
        ):
            count -= 2
        elif any(
            red_team != code and approximate_second > red_time
            for red_team, _, red_time in red_events
        ):
            count += 1
        if index == hot_possession:
            count = max(count, 9)
        pass_counts[index] = int(
            _clamp(count, MIN_PASSES_PER_CHAIN, MAX_PASSES_PER_CHAIN)
        )
        if index in projected_goals[code]:
            approximate_scores[code] += 1
    for code in ("A", "B"):
        team_possessions = [
            index for index, owner in enumerate(possession_teams) if owner == code
        ]
        _balance_pass_counts(rng, team_possessions, pass_counts)

    foul_min, foul_max = archetype_profile.foul_range
    foul_count = rng.randint(foul_min, foul_max)
    foul_plan: dict[int, list[str]] = {index: [] for index in range(possession_count)}
    for foul_number in range(foul_count):
        index = rng.randrange(possession_count)
        foul_plan[index].append(f"foul-{foul_number + 1}")

    events: list[Event] = []
    draft_counter = 0

    def add_event(
        second: float,
        event_type: EventType,
        team: TeamCode,
        player: str,
        x: float,
        y: float,
        outcome: str,
        *,
        under_pressure: bool = False,
        end_x: float | None = None,
        end_y: float | None = None,
        pass_difficulty: float | None = None,
        ball_speed_kmh: float | None = None,
        shot_speed_kmh: float | None = None,
        xg: float | None = None,
        key_pass: bool = False,
        from_team: TeamCode | None = None,
        related_event_id: str | None = None,
        related_player: str | None = None,
        set_piece: bool = False,
        stoppage_seconds: int | None = None,
    ) -> str:
        nonlocal draft_counter
        draft_counter += 1
        token = f"draft-{draft_counter:05d}"
        events.append(
            Event(
                id=token,
                t=round(second, 2),
                minute=_minute(second),
                type=event_type,
                team=team,
                player=player,
                x=round(x, 2),
                y=round(y, 2),
                end_x=round(end_x, 2) if end_x is not None else None,
                end_y=round(end_y, 2) if end_y is not None else None,
                outcome=outcome,
                under_pressure=under_pressure,
                pass_difficulty=pass_difficulty,
                ball_speed_kmh=ball_speed_kmh,
                shot_speed_kmh=shot_speed_kmh,
                xg=xg,
                key_pass=key_pass,
                from_team=from_team,
                related_event_id=related_event_id,
                related_player=related_player,
                set_piece=set_piece,
                stoppage_seconds=stoppage_seconds,
            )
        )
        return token

    story_tokens: dict[StoryKind, list[str]] = {
        kind: [] for kind in STORY_MENU
    }
    red_tokens: list[str] = []
    for code, player_id, second in red_events:
        red_tokens.append(
            add_event(
                second,
                "card",
                code,
                player_id,
                52.5,
                34.0,
                "red",
                under_pressure=True,
            )
        )
    for code, player_id, second in yellow_events:
        add_event(
            second,
            "card",
            code,
            player_id,
            rng.uniform(10, 95),
            rng.uniform(5, 63),
            "yellow",
            under_pressure=True,
        )
    for code, team in teams.items():
        for second, outgoing, incoming, stoppage in substitutions[code]:
            outgoing_player = next(
                player for player in team.roster if player.id == outgoing
            )
            add_event(
                second,
                "substitution",
                code,
                outgoing_player.id,
                52.5,
                34.0,
                "injury_stoppage" if stoppage else "player_off",
                related_player=incoming,
                stoppage_seconds=stoppage or None,
            )

    shot_tokens: dict[int, str] = {}
    goal_tokens: dict[int, str] = {}
    saved_big_chance_token: str | None = None
    set_piece_goal_tokens: list[str] = []
    hot_tokens: list[str] = []
    press_tokens: list[str] = []
    momentum_tokens: list[str] = []
    red_impact_tokens: list[str] = list(red_tokens)
    possession_weight: dict[TeamCode, float] = {"A": 0.0, "B": 0.0}
    slot_seconds = MATCH_DURATION_SECONDS / possession_count
    set_piece_goal_index: int | None = None
    scored_indices = [index for index in goal_possessions]
    if scored_indices and seed != DEMO_SEED and rng.random() < 0.16:
        set_piece_goal_index = rng.choice(scored_indices)

    score = {"A": 0, "B": 0}
    for index, code in enumerate(possession_teams):
        team = teams[code]
        opponent_code: TeamCode = "A" if code == "B" else "B"
        opponent = teams[opponent_code]
        start_second = index * slot_seconds + 1.0
        chain_end = start_second + min(
            slot_seconds * 0.65,
            (pass_counts[index] + 4) * PASS_EVENT_SPACING_SECONDS,
        )
        trailing = (
            start_second >= LATE_GAME_SECONDS
            and score[code] < score[opponent_code]
        )
        leading = score[code] > score[opponent_code]
        profile = STYLE_PROFILES[team.style]
        progress = rng.uniform(*profile.start_progress)
        if trailing:
            progress = min(82.0, progress + 8.0)
        elif leading:
            progress = max(10.0, progress - 8.0)
        if any(
            red_team == code and start_second > red_time
            for red_team, _, red_time in red_events
        ):
            progress = max(8.0, progress - 5.0)
        x = progress if code == "A" else 105.0 - progress
        y = rng.uniform(5.0, 63.0)
        receiver = _select_player(
            rng, team, start_second, substitutions, red_cards
        )
        previous_code: TeamCode = (
            "B" if code == "A" else "A"
        )
        add_event(
            start_second,
            "possession_change",
            code,
            receiver.id,
            x,
            y,
            "kickoff" if index == 0 else "won",
            from_team=previous_code,
        )
        share_weight = 1.0 + pass_counts[index] / 10.0
        if any(
            red_team == code and start_second > red_time
            for red_team, _, red_time in red_events
        ):
            share_weight *= 0.68
        possession_weight[code] += share_weight

        hot_player = (
            next(player for player in team.roster if player.id == hot_player_id)
            if code == hot_team
            else None
        )
        for pass_index in range(pass_counts[index]):
            second = start_second + 1.0 + pass_index * PASS_EVENT_SPACING_SECONDS
            long_pass = rng.random() < team.pass_length_tendency
            if long_pass:
                distance_forward = rng.uniform(10.0, 23.0)
                lateral_change = rng.uniform(-11.0, 11.0)
            else:
                distance_forward = rng.uniform(1.0, 7.0)
                lateral_change = rng.uniform(-7.0, 7.0)
            if leading:
                distance_forward *= 0.72
            elif trailing and second >= LATE_GAME_SECONDS:
                distance_forward *= 1.25
            if rng.random() < team.recycling:
                distance_forward *= -rng.uniform(0.12, 0.55)
            direction = 1.0 if code == "A" else -1.0
            end_x = _clamp(x + direction * distance_forward, 1.0, 104.0)
            end_y = _clamp(y + lateral_change, 1.0, 67.0)
            distance = math.hypot(end_x - x, end_y - y)
            under_pressure = rng.random() < min(
                0.72,
                archetype_profile.pressing * 0.24 + opponent.pressing * 0.32,
            )
            passer = (
                hot_player
                if index == hot_possession
                and pass_index in hot_pass_indices
                and hot_player is not None
                else _select_player(
                    rng, team, second, substitutions, red_cards
                )
            )
            pass_token = add_event(
                second,
                "pass",
                code,
                passer.id,
                x,
                y,
                "complete",
                under_pressure=under_pressure,
                end_x=end_x,
                end_y=end_y,
                pass_difficulty=round(
                    _clamp(0.08 + distance / 34.0 + (0.18 if under_pressure else 0), 0.03, 0.99),
                    3,
                ),
                ball_speed_kmh=round(
                    _clamp(34.0 + distance * 1.18 + rng.uniform(0, 16), 20, 115),
                    1,
                ),
                key_pass=(index in shot_possession_set and pass_index >= pass_counts[index] - 2)
                or rng.random() < 0.025,
            )
            if index == hot_possession and pass_index in hot_pass_indices:
                hot_tokens.append(pass_token)

            planted_press = index in press_indices and pass_index in (2, 5, 8)
            red_press = any(
                red_team == code and start_second > red_time
                for red_team, _, red_time in red_events
            ) and index % 2 == 0 and pass_index == 3
            random_press = rng.random() < profile.pressing * 0.045
            if planted_press or red_press or random_press:
                pressing_team_code = (
                    press_team
                    if planted_press
                    else opponent_code
                )
                pressing_team = teams[pressing_team_code]
                pressure_player = _select_player(
                    rng,
                    pressing_team,
                    second + 0.04,
                    substitutions,
                    red_cards,
                )
                pressure_token = add_event(
                    second + 0.04,
                    "pressure",
                    pressing_team_code,
                    pressure_player.id,
                    end_x,
                    end_y,
                    "closed_down",
                    under_pressure=True,
                )
                if planted_press:
                    press_tokens.append(pressure_token)
                if red_press:
                    red_impact_tokens.append(pressure_token)
            x, y = end_x, end_y

        if index in shot_possession_set:
            goal_x = 105.0 if code == "A" else 0.0
            big_chance = index == saved_big_chance_index
            if big_chance:
                shot_progress = rng.uniform(88.0, 94.0)
                shot_y = rng.uniform(30.5, 37.5)
            else:
                shot_progress = rng.uniform(78.0, 99.0)
                shot_y = _clamp(y + rng.uniform(-7.0, 7.0), 2.0, 66.0)
            shot_x = shot_progress if code == "A" else 105.0 - shot_progress
            distance = math.hypot(goal_x - shot_x, 34.0 - shot_y)
            xg = _shot_xg(distance, abs(34.0 - shot_y))
            if big_chance:
                xg = max(xg, BIG_CHANCE_XG)
            shot_second = min(
                chain_end - 0.3,
                start_second + (pass_counts[index] + 2) * PASS_EVENT_SPACING_SECONDS,
            )
            shooter = _select_player(
                rng, team, shot_second, substitutions, red_cards
            )
            is_goal = index in goal_possessions
            if is_goal:
                outcome = "goal"
            elif big_chance:
                outcome = "saved"
            else:
                save_chance = 0.38 * archetype_profile.scoring_rate
                outcome = rng.choices(
                    ("saved", "miss", "blocked"),
                    weights=(save_chance, 0.40, max(0.05, 0.60 - save_chance)),
                    k=1,
                )[0]
            set_piece = index == set_piece_goal_index
            shot_token = add_event(
                shot_second,
                "shot",
                code,
                shooter.id,
                shot_x,
                shot_y,
                outcome,
                under_pressure=rng.random() < (0.36 if not trailing else 0.48),
                end_x=goal_x,
                end_y=34.0,
                shot_speed_kmh=round(
                    _clamp(79.0 + (25.0 - distance) * 0.78 + rng.uniform(-9, 10), 48, 118),
                    1,
                ),
                xg=xg,
                set_piece=set_piece,
            )
            shot_tokens[index] = shot_token
            if big_chance:
                saved_big_chance_token = shot_token
            if is_goal:
                goal_token = add_event(
                    shot_second + 0.12,
                    "goal",
                    code,
                    shooter.id,
                    goal_x,
                    34.0,
                    "scored",
                    related_event_id=shot_token,
                    set_piece=set_piece,
                )
                goal_tokens[index] = goal_token
                score[code] += 1
                if set_piece:
                    set_piece_goal_tokens.extend((shot_token, goal_token))

        if foul_plan[index]:
            for foul_index in range(len(foul_plan[index])):
                foul_second = min(
                    chain_end - 0.1,
                    start_second + (pass_counts[index] + 2 + foul_index * 0.12)
                    * PASS_EVENT_SPACING_SECONDS,
                )
                offender = _select_player(
                    rng, team, foul_second, substitutions, red_cards
                )
                add_event(
                    foul_second,
                    "foul",
                    code,
                    offender.id,
                    x,
                    y,
                    "contact",
                    under_pressure=True,
                )
        elif index not in shot_possession_set and rng.random() < 0.74:
            defender = _select_player(
                rng,
                opponent,
                chain_end - 0.15,
                substitutions,
                red_cards,
            )
            tackle_type: EventType = rng.choice(("tackle", "interception"))
            add_event(
                chain_end - 0.15,
                tackle_type,
                opponent_code,
                defender.id,
                x,
                y,
                "won",
            )

    all_goal_tokens = list(goal_tokens.items())
    if all_goal_tokens:
        _, goal_token = min(all_goal_tokens, key=lambda item: item[0])
        goal_event = next(event for event in events if event.id == goal_token)
        response_team: TeamCode = "A" if goal_event.team == "B" else "B"
        response_second = goal_event.t + 5.0
        response_player = _select_player(
            rng, teams[response_team], response_second, substitutions, red_cards
        )
        momentum_tokens = [
            goal_token,
            add_event(
                response_second,
                "pressure",
                response_team,
                response_player.id,
                goal_event.x,
                goal_event.y,
                "momentum_response",
                under_pressure=True,
            ),
        ]

    for code, player_id, red_second in red_events:
        response_index = next(
            (
                index
                for index, owner in enumerate(possession_teams)
                if owner == code and index * slot_seconds > red_second
            ),
            None,
        )
        if response_index is None:
            continue
        pressure_team_code: TeamCode = "A" if code == "B" else "B"
        response_second = response_index * slot_seconds + 12.0
        pressure_player = _select_player(
            rng,
            teams[pressure_team_code],
            response_second,
            substitutions,
            red_cards,
        )
        red_impact_tokens.append(
            add_event(
                response_second,
                "pressure",
                pressure_team_code,
                pressure_player.id,
                52.5,
                34.0,
                "numerical_advantage",
                under_pressure=True,
            )
        )

    token_ids: dict[str, str] = {}
    token_events: dict[str, Event] = {}
    ordered = sorted(enumerate(events), key=lambda pair: (pair[1].t, pair[0]))
    for event_number, (_, event) in enumerate(ordered, start=1):
        token_ids[event.id] = f"e{event_number:04d}"
    final_events: list[Event] = []
    for _, event in ordered:
        final_event = event.model_copy(
            update={
                "id": token_ids[event.id],
                "related_event_id": (
                    token_ids.get(event.related_event_id)
                    if event.related_event_id is not None
                    else None
                ),
            }
        )
        final_events.append(final_event)
        token_events[event.id] = final_event

    stories: list[StoryMoment] = []
    if press_tokens:
        stories.append(_story("pressing_spell", press_team, press_tokens, token_events, token_ids))
    if momentum_tokens:
        momentum_goal = token_events[momentum_tokens[0]]
        stories.append(
            _story(
                "momentum_swing",
                momentum_goal.team,
                momentum_tokens,
                token_events,
                token_ids,
            )
        )
    if red_tokens and len(red_impact_tokens) > len(red_tokens):
        stories.append(
            _story("red_card_impact", red_events[0][0], red_impact_tokens, token_events, token_ids)
        )
    late_goal = next(
        (
            (index, token)
            for index, token in goal_tokens.items()
            if token_events[token].minute > 80
        ),
        None,
    )
    if late_goal is not None:
        late_index, late_goal_token = late_goal
        stories.append(
            _story(
                "late_drama",
                possession_teams[late_index],
                [shot_tokens[late_index], late_goal_token],
                token_events,
                token_ids,
            )
        )
    if hot_tokens:
        stories.append(_story("hot_streak", hot_team, hot_tokens, token_events, token_ids))
    if saved_big_chance_token is not None:
        big_chance = token_events[saved_big_chance_token]
        stories.append(
            _story(
                "big_chance_saved",
                big_chance.team,
                [saved_big_chance_token],
                token_events,
                token_ids,
            )
        )
    if set_piece_goal_tokens:
        set_piece_shot = token_events[set_piece_goal_tokens[0]]
        stories.append(
            _story(
                "set_piece_goal",
                set_piece_shot.team,
                set_piece_goal_tokens,
                token_events,
                token_ids,
            )
        )

    if seed == DEMO_SEED:
        required = {
            "pressing_spell",
            "momentum_swing",
            "red_card_impact",
            "late_drama",
            "hot_streak",
        }
        stories = [story for story in stories if story.kind in required]
    else:
        rng.shuffle(stories)
        stories = stories[: rng.randint(3, min(5, len(stories)))]
        stories.sort(key=lambda story: (story.minute_start, story.kind))

    possession_denominator = sum(possession_weight.values())
    possession_seconds = {
        code: MATCH_DURATION_SECONDS * possession_weight[code] / possession_denominator
        for code in ("A", "B")
    }
    totals = _event_totals(final_events, possession_seconds)
    final_score = Score(
        team_a=sum(
            event.type == "goal" and event.team == "A" for event in final_events
        ),
        team_b=sum(
            event.type == "goal" and event.team == "B" for event in final_events
        ),
    )
    match = Match(
        seed=seed,
        archetype=archetype,
        duration_seconds=MATCH_DURATION_SECONDS,
        team_a=teams["A"],
        team_b=teams["B"],
        events=final_events,
        final_score=final_score,
        team_totals=totals,
        planted_stories=stories,
    )
    issues = validate_match(match)
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(f"generated match failed validation: {details}")
    return match
