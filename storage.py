"""Local JSON storage helpers for Koji Report Pet Next."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
RECORDS_FILE = DATA_DIR / "records.json"
CHAT_HISTORY_FILE = DATA_DIR / "chat_history.json"
DIALOGUES_FILE = DATA_DIR / "koji-dialogues.json"
NOTES_FILE = DATA_DIR / "notes.json"
TAGS_FILE = DATA_DIR / "tags.json"
CATEGORIES_FILE = DATA_DIR / "categories.json"
POMODORO_STATS_FILE = DATA_DIR / "pomodoro_stats.json"
SETTINGS_FILE = DATA_DIR / "settings.json"


def ensure_data_dir() -> None:
    """Create the local data directory when it does not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    """Load JSON safely, returning *default* when missing or malformed."""
    ensure_data_dir()
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    """Write JSON atomically enough for small desktop-app data files."""
    ensure_data_dir()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)
