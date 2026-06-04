"""Companion state and character-aware asset loading utilities."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import QLabel

from character_manager import CharacterPackage, COMPANION_STATES
from storage import DIALOGUES_FILE, load_json

STATES: List[str] = list(COMPANION_STATES)
STATE_ALIASES = {
    "wave": "idle",
    "record_ready": "idle",
    "collect": "thinking",
    "writing": "typing",
    "happy": "success",
    "confused": "error",
    "angry": "error",
    "drag": "idle",
}
PLACEHOLDER_STYLESHEET = (
    "QLabel { color: #6b4b35; font-size: 28px; font-weight: 700; "
    "background: rgba(255, 246, 225, 190); border: 2px solid rgba(107,75,53,90); "
    "border-radius: 24px; padding: 8px; }"
)


def normalize_state(state: str) -> str:
    normalized = STATE_ALIASES.get(state, state)
    return normalized if normalized in STATES else "idle"


class KojiVisual:
    """Swaps character images/gifs by companion state with safe fallback."""

    def __init__(self, label: QLabel, size: QSize, character: CharacterPackage | None = None) -> None:
        self.label = label
        self.size = size
        self.character = character
        self.current_state = "idle"
        self.movie: QMovie | None = None

    def set_character(self, character: CharacterPackage | None) -> None:
        self.character = character
        self.set_state(self.current_state)

    def set_state(self, state: str) -> None:
        self.current_state = normalize_state(state)
        asset = self._asset_for_state(self.current_state)
        self._show_asset(asset)

    def show_random_idle_variant(self) -> bool:
        if self.character is None:
            return False
        variants = self.character.idle_variants()
        if not variants:
            self.set_state("idle")
            return False
        self.current_state = "idle"
        self._show_asset(random.choice(variants))
        return True

    def _asset_for_state(self, state: str) -> Path | None:
        if self.character is None:
            return None
        return self.character.state_asset(state)

    def _show_asset(self, asset: Path | None) -> None:
        self.movie = None
        self.label.clear()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(1, 1)
        self.label.setMaximumSize(16777215, 16777215)
        self.label.resize(self.size)
        self.label.setScaledContents(False)

        if asset is None:
            self._show_placeholder()
            return

        self.label.setStyleSheet("background: transparent;")
        if asset.suffix.lower() == ".gif":
            self.movie = QMovie(str(asset))
            if not self.movie.isValid():
                self._show_placeholder()
                return
            self.movie.setScaledSize(self.size)
            self.label.setMovie(self.movie)
            self.movie.start()
            return

        pixmap = QPixmap(str(asset))
        if pixmap.isNull():
            self._show_placeholder()
            return
        self.label.setScaledContents(True)
        self.label.setPixmap(pixmap.scaled(self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _show_placeholder(self) -> None:
        name = self.character.name if self.character is not None else "Koji"
        self.label.setText(f"🐱\n{name}")
        self.label.setStyleSheet(PLACEHOLDER_STYLESHEET)


def load_dialogues() -> Dict[str, List[str]]:
    data = load_json(DIALOGUES_FILE, {})
    if not isinstance(data, dict):
        return {}
    normalized: Dict[str, List[str]] = {}
    for key, value in data.items():
        if isinstance(value, list):
            normalized[key] = [str(item) for item in value]
    return normalized


def random_dialogue(state: str, fallback: str = "Koji 在这里陪你整理今天。") -> str:
    dialogues = load_dialogues()
    normalized_state = normalize_state(state)
    options = dialogues.get(normalized_state) or dialogues.get(state) or dialogues.get("idle") or [fallback]
    return random.choice(options)
