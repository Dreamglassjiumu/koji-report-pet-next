"""Collectible unlock data for Koji's collection cabinet."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

from storage import COLLECTIBLES_FILE, ROOT_DIR, load_json, save_json

COLLECTIBLES_DIR = ROOT_DIR / "assets" / "collectibles"

OLD_WATCH = "old_watch"
TICKET = "ticket"
STAR_MAP = "star_map"
ALL_COLLECTIBLE_IDS = [OLD_WATCH, TICKET, STAR_MAP]


@dataclass(frozen=True)
class Collectible:
    id: str
    name: str
    description: str
    icon: str


@dataclass(frozen=True)
class UnlockResult:
    unlocked: bool
    collectible: Collectible | None = None


class CollectionManager:
    """Persist unlocked collectibles and lightweight collection stats."""

    def __init__(self, collectibles_dir: Path = COLLECTIBLES_DIR) -> None:
        self.collectibles_dir = collectibles_dir
        self.data: dict = {}
        self.load()
        self._normalize()
        self.save()

    def load(self) -> None:
        raw = load_json(COLLECTIBLES_FILE, {"unlocked": []})
        self.data = raw if isinstance(raw, dict) else {"unlocked": []}

    def save(self) -> None:
        save_json(COLLECTIBLES_FILE, self.data)

    def _normalize(self) -> None:
        unlocked = self.data.get("unlocked", [])
        if not isinstance(unlocked, list):
            unlocked = []
        self.data["unlocked"] = [str(item) for item in unlocked if str(item) in ALL_COLLECTIBLE_IDS]
        stats = self.data.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        stats.setdefault("chat_success_count", 0)
        stats.setdefault("generated_report_count", 0)
        stats.setdefault("login_streak", 0)
        stats.setdefault("last_login_date", "")
        self.data["stats"] = stats

    def unlocked_ids(self) -> List[str]:
        return list(self.data.get("unlocked", []))

    def is_unlocked(self, collectible_id: str) -> bool:
        return collectible_id in self.unlocked_ids()

    def stats(self) -> dict:
        return self.data.setdefault("stats", {})

    def all_collectibles(self) -> List[Collectible]:
        return [item for item in (self.load_collectible(item_id) for item_id in ALL_COLLECTIBLE_IDS) if item is not None]

    def load_collectible(self, collectible_id: str) -> Collectible | None:
        path = self.collectibles_dir / f"{collectible_id}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return Collectible(
            id=str(raw.get("id") or collectible_id),
            name=str(raw.get("name") or collectible_id),
            description=str(raw.get("description") or ""),
            icon=str(raw.get("icon") or ""),
        )

    def unlock(self, collectible_id: str) -> UnlockResult:
        if collectible_id not in ALL_COLLECTIBLE_IDS or self.is_unlocked(collectible_id):
            return UnlockResult(False)
        self.data.setdefault("unlocked", []).append(collectible_id)
        self.save()
        return UnlockResult(True, self.load_collectible(collectible_id))

    def record_report_generated(self) -> UnlockResult:
        stats = self.stats()
        stats["generated_report_count"] = int(stats.get("generated_report_count", 0) or 0) + 1
        self.save()
        return self.unlock(OLD_WATCH) if stats["generated_report_count"] == 1 else UnlockResult(False)

    def record_chat_success(self) -> UnlockResult:
        stats = self.stats()
        stats["chat_success_count"] = int(stats.get("chat_success_count", 0) or 0) + 1
        self.save()
        if stats["chat_success_count"] >= 100:
            return self.unlock(STAR_MAP)
        return UnlockResult(False)

    def record_login(self, today: date | None = None) -> UnlockResult:
        today = today or date.today()
        today_text = today.isoformat()
        stats = self.stats()
        last_text = str(stats.get("last_login_date") or "")
        if last_text == today_text:
            return UnlockResult(False)
        try:
            last_date = date.fromisoformat(last_text) if last_text else None
        except ValueError:
            last_date = None
        if last_date == today - timedelta(days=1):
            stats["login_streak"] = int(stats.get("login_streak", 0) or 0) + 1
        else:
            stats["login_streak"] = 1
        stats["last_login_date"] = today_text
        self.save()
        if int(stats["login_streak"]) >= 3:
            return self.unlock(TICKET)
        return UnlockResult(False)
