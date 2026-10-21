"""Rank synthetic seeds by deterministic demo-drama criteria."""

from collections.abc import Sequence

from app.generator.generator import DEMO_SEED, generate_match
from app.models import Event, Match

FIRST_CANDIDATE_SEED = 1
LAST_CANDIDATE_SEED = 300
REQUIRED_DEMO_STORIES = {
    "pressing_spell",
    "momentum_swing",
    "red_card_impact",
    "late_drama",
    "hot_streak",
}
POINTS_PER_REQUIRED_STORY = 20
POINTS_PER_DEMO_BEAT = 20


def _goal_buildups(match: Match) -> list[tuple[Event, Event, list[Event]]]:
    """Return goal shots preceded by at least five passes in their possession."""
    results: list[tuple[Event, Event, list[Event]]] = []
    events: Sequence[Event] = match.events
    for index, goal_shot in enumerate(events):
        if goal_shot.type != "shot" or goal_shot.outcome != "goal":
            continue
        possession_start = next(
            (
                cursor
                for cursor in range(index - 1, -1, -1)
                if events[cursor].type == "possession_change"
            ),
            None,
        )
        if possession_start is None:
            continue
        passes = [
            event
            for event in events[possession_start + 1 : index]
            if event.type == "pass" and event.team == goal_shot.team
        ]
        goal_event = next(
            (
                event
                for event in events[index + 1 :]
                if event.type == "goal"
                and event.related_event_id == goal_shot.id
            ),
            None,
        )
        if goal_event is not None and len(passes) >= 5:
            results.append((goal_shot, goal_event, passes))
    return results


def demo_drama_score(match: Match) -> tuple[int, dict[str, object]]:
    """Score demo suitability and return reproducible evidence details."""
    stories = {story.kind: story for story in match.planted_stories}
    total_goals = match.final_score.team_a + match.final_score.team_b
    goal_events = [event for event in match.events if event.type == "goal"]
    late_goals = [event for event in goal_events if event.minute > 80]
    red_cards = [
        event
        for event in match.events
        if event.type == "card" and event.outcome.casefold() == "red"
    ]
    saved_big_chances = [
        event
        for event in match.events
        if event.type == "shot"
        and event.outcome.casefold() == "saved"
        and event.xg is not None
        and event.xg >= 0.2
    ]
    buildups = _goal_buildups(match)

    story_points = len(REQUIRED_DEMO_STORIES & set(stories)) * POINTS_PER_REQUIRED_STORY
    beat_points = 0
    beat_points += POINTS_PER_DEMO_BEAT if 2 <= total_goals <= 4 else 0
    beat_points += POINTS_PER_DEMO_BEAT if late_goals else 0
    beat_points += POINTS_PER_DEMO_BEAT if red_cards else 0
    beat_points += POINTS_PER_DEMO_BEAT if saved_big_chances else 0
    beat_points += POINTS_PER_DEMO_BEAT if buildups else 0
    details: dict[str, object] = {
        "stories": {
            kind: story.minute_start
            for kind, story in stories.items()
        },
        "late_goal_minutes": [event.minute for event in late_goals],
        "red_card_minutes": [event.minute for event in red_cards],
        "saved_big_chance_minutes": [event.minute for event in saved_big_chances],
        "buildup_goal_minutes": [shot.minute for shot, _, _ in buildups],
        "buildup_pass_counts": [len(passes) for _, _, passes in buildups],
        "scoreline": (match.final_score.team_a, match.final_score.team_b),
    }
    return story_points + beat_points, details


def main() -> None:
    """Generate seeds 1–300 and print the ten strongest demo candidates."""
    candidates: list[tuple[int, int, Match, dict[str, object]]] = []
    for seed in range(FIRST_CANDIDATE_SEED, LAST_CANDIDATE_SEED + 1):
        match = generate_match(seed)
        score, details = demo_drama_score(match)
        candidates.append((score, seed, match, details))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    print(f"Demo-drama ranking ({FIRST_CANDIDATE_SEED}-{LAST_CANDIDATE_SEED})")
    print("Rank Seed Scoreline Archetype Score Story minutes / key beats")
    for rank, (score, seed, match, details) in enumerate(candidates[:10], start=1):
        story_minutes = ", ".join(
            f"{kind}@{minute}"
            for kind, minute in sorted(details["stories"].items())
        )
        scoreline = details["scoreline"]
        late_minutes = details["late_goal_minutes"]
        saved_minutes = details["saved_big_chance_minutes"]
        buildup_minutes = details["buildup_goal_minutes"]
        print(
            f"{rank:>2} {seed:>4} {scoreline[0]}-{scoreline[1]} "
            f"{match.archetype:<10} {score:>3} "
            f"stories=[{story_minutes}] late={late_minutes} "
            f"saved_big={saved_minutes} buildup={buildup_minutes}"
        )
    print(f"Default demo seed remains {DEMO_SEED}; no selection was applied.")


if __name__ == "__main__":
    main()
