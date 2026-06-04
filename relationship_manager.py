"""Relationship growth data for Koji companion characters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from storage import RELATIONSHIP_FILE, load_json, save_json

MAX_LEVEL = 5
LEVEL_NAMES = {
    1: "陌生",
    2: "认识",
    3: "熟悉",
    4: "搭档",
    5: "挚友",
}
LEVEL_THRESHOLDS = {
    1: 50,
    2: 150,
    3: 300,
    4: 600,
}

EXP_REPORT_SUCCESS = 5
EXP_CHAT_SUCCESS = 1
EXP_POMODORO_DONE = 3
EXP_DAILY_CHECK_IN = 2
EXP_CHARACTER_IMPORT = 10


@dataclass(frozen=True)
class RelationshipChange:
    """Result of adding relationship experience."""

    character_id: str
    level: int
    exp: int
    leveled_up: bool = False
    previous_level: int | None = None

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "未知")


class RelationshipManager:
    """Persist per-character relationship level and experience."""

    def __init__(self) -> None:
        self.relationships: Dict[str, dict] = {}
        self.load()
        self.ensure_character("koji")
        self.save()

    def load(self) -> None:
        raw = load_json(RELATIONSHIP_FILE, {})
        self.relationships = raw if isinstance(raw, dict) else {}

    def save(self) -> None:
        save_json(RELATIONSHIP_FILE, self.relationships)

    def ensure_character(self, character_id: str | None) -> dict:
        safe_id = str(character_id or "koji")
        raw = self.relationships.get(safe_id)
        if not isinstance(raw, dict):
            raw = {"level": 1, "exp": 0}
            self.relationships[safe_id] = raw
        raw["level"] = min(MAX_LEVEL, max(1, int(raw.get("level", 1) or 1)))
        raw["exp"] = max(0, int(raw.get("exp", 0) or 0))
        if raw["level"] >= MAX_LEVEL:
            raw["exp"] = 0
        return raw

    def get(self, character_id: str | None) -> Tuple[int, int]:
        data = self.ensure_character(character_id)
        return int(data["level"]), int(data["exp"])

    def add_exp(self, character_id: str | None, amount: int) -> RelationshipChange:
        safe_id = str(character_id or "koji")
        data = self.ensure_character(safe_id)
        previous_level = int(data["level"])
        level = previous_level
        exp = int(data["exp"]) + max(0, int(amount))
        leveled_up = False
        while level < MAX_LEVEL and exp >= LEVEL_THRESHOLDS[level]:
            exp -= LEVEL_THRESHOLDS[level]
            level += 1
            leveled_up = True
        if level >= MAX_LEVEL:
            exp = 0
        data["level"] = level
        data["exp"] = exp
        self.save()
        return RelationshipChange(safe_id, level, exp, leveled_up, previous_level if leveled_up else None)

    def progress_text(self, character_id: str | None) -> str:
        level, exp = self.get(character_id)
        if level >= MAX_LEVEL:
            return "MAX"
        return f"{exp} / {LEVEL_THRESHOLDS[level]}"

    def level_label(self, character_id: str | None) -> str:
        level, _exp = self.get(character_id)
        return f"Lv{level} {LEVEL_NAMES.get(level, '未知')}"
