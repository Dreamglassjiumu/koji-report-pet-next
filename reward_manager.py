"""Local upgrade reward CG and memory album management."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from character_manager import CharacterPackage
from storage import DATA_DIR, ROOT_DIR, load_json, save_json

REWARD_UNLOCKS_FILE = DATA_DIR / "reward_unlocks.json"
DEFAULT_REWARD_TITLE = "升级奖励"
DEFAULT_REWARD_SUBTITLE = "关系又近了一步。"
DEFAULT_REWARD_DESCRIPTION = "恭喜升级，解锁新的纪念奖励图。"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class LevelReward:
    """One configured level reward for a character."""

    character_id: str
    character_name: str
    level: int
    image: str
    title: str = DEFAULT_REWARD_TITLE
    subtitle: str = DEFAULT_REWARD_SUBTITLE
    description: str = DEFAULT_REWARD_DESCRIPTION
    rewards_dir: Path | None = None

    @property
    def image_path(self) -> Path | None:
        if self.rewards_dir is None or not self.image:
            return None
        path = (self.rewards_dir / self.image).resolve()
        try:
            if self.rewards_dir.resolve() not in path.parents and path != self.rewards_dir.resolve():
                return None
        except OSError:
            return None
        if path.exists() and path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            return path
        return None


class RewardManager:
    """Loads per-character reward definitions and persists local unlock records."""

    def __init__(self, unlocks_file: Path = REWARD_UNLOCKS_FILE) -> None:
        self.unlocks_file = unlocks_file
        self.unlocks: dict[str, dict[str, Any]] = {}
        self.load()
        self.ensure_default_koji_rewards()
        self.save()

    def load(self) -> None:
        raw = load_json(self.unlocks_file, {})
        self.unlocks = raw if isinstance(raw, dict) else {}

    def save(self) -> None:
        save_json(self.unlocks_file, self.unlocks)

    def ensure_default_koji_rewards(self) -> None:
        rewards_dir = ROOT_DIR / "assets" / "characters" / "koji" / "rewards"
        rewards_json = rewards_dir / "rewards.json"
        if rewards_json.exists():
            return
        rewards_dir.mkdir(parents=True, exist_ok=True)
        save_json(
            rewards_json,
            {
                "level_rewards": [
                    {
                        "level": 2,
                        "image": "lv2.png",
                        "title": "初次靠近",
                        "subtitle": "Koji 对你露出了更放松的笑容。",
                        "description": "恭喜升级到 Lv2，解锁纪念奖励图。",
                    },
                    {
                        "level": 3,
                        "image": "lv3.png",
                        "title": "熟悉的陪伴",
                        "subtitle": "你们的关系又近了一步。",
                        "description": "恭喜升级到 Lv3，解锁纪念奖励图。",
                    },
                    {
                        "level": 5,
                        "image": "lv5.png",
                        "title": "特别纪念",
                        "subtitle": "这是只属于你们的回忆。",
                        "description": "恭喜升级到 Lv5，解锁特别奖励图。",
                    },
                ]
            },
        )

    def configured_rewards(self, character: CharacterPackage | None) -> list[LevelReward]:
        if character is None:
            return []
        rewards_dir = character.directory / "rewards"
        rewards_json = rewards_dir / "rewards.json"
        raw = load_json(rewards_json, {})
        if not isinstance(raw, dict):
            return []
        entries = raw.get("level_rewards", [])
        if not isinstance(entries, list):
            return []
        rewards: list[LevelReward] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                level = int(entry.get("level", 0) or 0)
            except (TypeError, ValueError):
                continue
            if level <= 0:
                continue
            rewards.append(
                LevelReward(
                    character_id=character.id,
                    character_name=character.name,
                    level=level,
                    image=str(entry.get("image") or ""),
                    title=str(entry.get("title") or DEFAULT_REWARD_TITLE),
                    subtitle=str(entry.get("subtitle") or DEFAULT_REWARD_SUBTITLE),
                    description=str(entry.get("description") or DEFAULT_REWARD_DESCRIPTION),
                    rewards_dir=rewards_dir,
                )
            )
        return sorted(rewards, key=lambda reward: reward.level)

    def reward_for_level(self, character: CharacterPackage | None, level: int) -> LevelReward | None:
        for reward in self.configured_rewards(character):
            if reward.level == level:
                return reward
        return None

    def character_data(self, character_id: str | None) -> dict[str, Any]:
        safe_id = str(character_id or "koji")
        data = self.unlocks.get(safe_id)
        if not isinstance(data, dict):
            data = {"unlocked": {}}
            self.unlocks[safe_id] = data
        if not isinstance(data.get("unlocked"), dict):
            data["unlocked"] = {}
        return data

    def is_unlocked(self, character_id: str | None, level: int) -> bool:
        return str(level) in self.character_data(character_id).get("unlocked", {})

    def unlock_reward(self, reward: LevelReward) -> bool:
        if self.is_unlocked(reward.character_id, reward.level):
            return False
        data = self.character_data(reward.character_id)
        data["unlocked"][str(reward.level)] = {
            "level": reward.level,
            "unlocked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "title": reward.title,
            "subtitle": reward.subtitle,
            "description": reward.description,
            "image": reward.image,
        }
        self.save()
        return True

    def unlocked_record(self, character_id: str | None, level: int) -> dict[str, Any] | None:
        record = self.character_data(character_id).get("unlocked", {}).get(str(level))
        return record if isinstance(record, dict) else None
