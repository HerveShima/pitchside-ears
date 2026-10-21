"""Generate and report the seeded Phase 1 demonstration match."""

from pathlib import Path

from app.generator.generator import generate_match
from app.generator.validator import validate_match

MAX_DEMO_BYTES = 1_000_000


def main() -> None:
    """Generate seed 2026, validate it, and write the demo JSON."""
    match = generate_match(2026)
    issues = validate_match(match)
    data_directory = Path(__file__).resolve().parents[2] / "data"
    data_directory.mkdir(parents=True, exist_ok=True)
    output_path = data_directory / "demo_match.json"
    serialized = match.model_dump_json(indent=2) + "\n"
    output_path.write_text(serialized, encoding="utf-8")
    size_bytes = output_path.stat().st_size
    summary = (
        f"Seed {match.seed} ({match.archetype}) | "
        f"{match.team_a.name} [{match.team_a.style}] {match.final_score.team_a}"
        f"-{match.final_score.team_b} {match.team_b.name}\n"
        f"Team B style: {match.team_b.style}\n"
        f"Shots A/B: {match.team_totals['A'].shots}/{match.team_totals['B'].shots}"
        f" | Passes A/B: {match.team_totals['A'].passes}/"
        f"{match.team_totals['B'].passes}\n"
        f"Cards A/B: {match.team_totals['A'].cards}/"
        f"{match.team_totals['B'].cards} | Fouls: "
        f"{match.team_totals['A'].fouls + match.team_totals['B'].fouls}\n"
        f"Subs A/B: {match.team_totals['A'].substitutions}/"
        f"{match.team_totals['B'].substitutions} | Injury stoppages: "
        f"{match.team_totals['A'].injury_stoppages + match.team_totals['B'].injury_stoppages}\n"
        f"Stories: {', '.join(story.kind for story in match.planted_stories)}\n"
        f"Issues: {len(issues)} | Demo JSON: {size_bytes:,} bytes"
    )
    print(summary)
    if issues:
        for issue in issues:
            print(f"{issue.severity.upper()} {issue.code}: {issue.message}")
        raise SystemExit(1)
    if size_bytes >= MAX_DEMO_BYTES:
        raise SystemExit(f"demo JSON exceeds {MAX_DEMO_BYTES:,} bytes")


if __name__ == "__main__":
    main()
