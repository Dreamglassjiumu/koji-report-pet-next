"""Persistent local settings for Koji Report Pet Next."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from storage import SETTINGS_FILE, load_json, save_json

DEFAULT_SETTINGS = {
    "animations_enabled": True,
    "hourly_chime_enabled": True,
    "hourly_chime_start": "09:00",
    "hourly_chime_end": "23:00",
    "hourly_chime_quiet": False,
    "pomodoro_focus_minutes": 25,
    "pomodoro_short_break_minutes": 5,
    "pomodoro_long_break_minutes": 15,
    "attached_windows_follow_koji": True,
    "current_character": "koji",
}


class SettingsManager:
    def __init__(self) -> None:
        self.settings = deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        raw = load_json(SETTINGS_FILE, {})
        self.settings = deepcopy(DEFAULT_SETTINGS)
        if isinstance(raw, dict):
            self.settings.update({key: value for key, value in raw.items() if key in DEFAULT_SETTINGS})
        self.save()

    def save(self) -> None:
        save_json(SETTINGS_FILE, self.settings)

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key in DEFAULT_SETTINGS:
            self.settings[key] = value
            self.save()
