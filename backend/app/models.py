"""Pydantic schemas for deterministic synthetic match data."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TeamCode = Literal["A", "B"]
MatchArchetype = Literal["cagey", "thriller", "one_sided", "comeback", "siege"]
TeamStyle = Literal["possession", "counter", "high_press"]
EventType = Literal[
    "pass",
    "shot",
    "tackle",
    "interception",
    "possession_change",
    "pressure",
    "foul",
    "card",
    "goal",
    "substitution",
]
PlayerPosition = Literal["GK", "DF", "MF", "FW"]
StoryKind = Literal[
    "pressing_spell",
    "momentum_swing",
    "red_card_impact",
    "late_drama",
    "hot_streak",
    "big_chance_saved",
    "set_piece_goal",
]

PITCH_LENGTH_METERS = 105.0
PITCH_WIDTH_METERS = 68.0
MATCH_DURATION_SECONDS = 90 * 60
STARTING_LINEUP_SIZE = 11


class Player(BaseModel):
    """A fictional player in a team's matchday squad."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    position: PlayerPosition


class Team(BaseModel):
    """Match metadata and roster for one fictional team."""

    model_config = ConfigDict(extra="forbid")

    code: TeamCode
    name: str = Field(min_length=1)
    home_away: Literal["home", "away"]
    formation: str = Field(min_length=1)
    strength: float = Field(gt=0)
    style: TeamStyle
    pass_length_tendency: float = Field(ge=0, le=1)
    pressing: float = Field(ge=0, le=1)
    directness: float = Field(ge=0, le=1)
    recycling: float = Field(ge=0, le=1)
    roster: list[Player] = Field(
        min_length=STARTING_LINEUP_SIZE, max_length=STARTING_LINEUP_SIZE
    )
    substitutes: list[Player] = Field(min_length=3, max_length=5)
    starting_xi: list[str] = Field(
        min_length=STARTING_LINEUP_SIZE, max_length=STARTING_LINEUP_SIZE
    )

    @model_validator(mode="after")
    def validate_roster(self) -> "Team":
        """Ensure the squad and starting lineup use unique, known players."""
        squad = self.roster + self.substitutes
        squad_ids = [player.id for player in squad]
        if len(squad_ids) != len(set(squad_ids)):
            raise ValueError("player ids must be unique within a team")
        if len(self.starting_xi) != len(set(self.starting_xi)):
            raise ValueError("starting lineup player ids must be unique")
        roster_ids = {player.id for player in self.roster}
        if set(self.starting_xi) != roster_ids:
            raise ValueError("starting lineup must match the 11-player roster")
        return self


class Event(BaseModel):
    """One time-stamped synthetic match event."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    t: float = Field(ge=0, le=MATCH_DURATION_SECONDS)
    minute: int = Field(ge=0, le=90)
    type: EventType
    team: TeamCode
    player: str = Field(min_length=1)
    x: float = Field(ge=0, le=PITCH_LENGTH_METERS)
    y: float = Field(ge=0, le=PITCH_WIDTH_METERS)
    end_x: float | None = Field(default=None, ge=0, le=PITCH_LENGTH_METERS)
    end_y: float | None = Field(default=None, ge=0, le=PITCH_WIDTH_METERS)
    outcome: str = Field(min_length=1)
    under_pressure: bool = False
    pass_difficulty: float | None = Field(default=None, ge=0, le=1)
    ball_speed_kmh: float | None = Field(default=None, ge=0)
    shot_speed_kmh: float | None = Field(default=None, ge=0)
    xg: float | None = Field(default=None, ge=0, le=1)
    key_pass: bool = False
    from_team: TeamCode | None = None
    related_event_id: str | None = None
    related_player: str | None = None
    set_piece: bool = False
    stoppage_seconds: int | None = Field(default=None, ge=0, le=900)


class Issue(BaseModel):
    """A validator finding tied to an event when possible."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    event_id: str | None = None


class StoryMoment(BaseModel):
    """A planted narrative moment with its minute range and evidence ids."""

    model_config = ConfigDict(extra="forbid")

    kind: StoryKind
    minute_start: int = Field(ge=0, le=90)
    minute_end: int = Field(ge=0, le=90)
    team: TeamCode
    event_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_minute_window(self) -> "StoryMoment":
        """Require an ordered minute window."""
        if self.minute_start > self.minute_end:
            raise ValueError("minute_start must not exceed minute_end")
        return self


class TeamTotals(BaseModel):
    """Counts of emitted events credited to a team."""

    model_config = ConfigDict(extra="forbid")

    passes: int = Field(ge=0)
    shots: int = Field(ge=0)
    goals: int = Field(ge=0)
    fouls: int = Field(ge=0)
    cards: int = Field(ge=0)
    tackles: int = Field(ge=0)
    interceptions: int = Field(ge=0)
    pressure_events: int = Field(ge=0)
    substitutions: int = Field(ge=0)
    possession_changes: int = Field(ge=0)
    possessions: int = Field(ge=0)
    possession_seconds: float = Field(ge=0)
    injury_stoppages: int = Field(ge=0)


class Score(BaseModel):
    """Final score for teams A and B."""

    model_config = ConfigDict(extra="forbid")

    team_a: int = Field(ge=0)
    team_b: int = Field(ge=0)


class Match(BaseModel):
    """Complete deterministic match, metadata, event stream, and stories."""

    model_config = ConfigDict(extra="forbid")

    seed: int
    archetype: MatchArchetype
    duration_seconds: int = Field(gt=0)
    team_a: Team
    team_b: Team
    events: list[Event]
    final_score: Score
    team_totals: dict[TeamCode, TeamTotals]
    planted_stories: list[StoryMoment]

    @model_validator(mode="after")
    def validate_team_codes(self) -> "Match":
        """Ensure the two team records and totals are keyed consistently."""
        if self.team_a.code != "A" or self.team_b.code != "B":
            raise ValueError("team_a must use code A and team_b must use code B")
        if set(self.team_totals) != {"A", "B"}:
            raise ValueError("team_totals must contain teams A and B")
        return self
