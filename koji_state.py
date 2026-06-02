"""Koji state and asset loading utilities."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import QLabel

from storage import DIALOGUES_FILE, ROOT_DIR, load_json

STATES: List[str] = [
    "idle",
    "wave",
    "record_ready",
    "collect",
    "success",
    "thinking",
    "writing",
    "happy",
    "confused",
    "angry",
    "sleep",
    "drag",
    "error",
]

ASSET_DIR = ROOT_DIR / "assets" / "koji"
ASSET_EXTENSIONS = ("webp", "gif", "png")
PLACEHOLDER = "🐾\nKoji"


def find_state_asset(state: str) -> Path | None:
    """Return the best matching image for a state, with idle fallback."""
    candidates = [state]
    if state != "idle":
        candidates.append("idle")
    for candidate in candidates:
        for extension in ASSET_EXTENSIONS:
            path = ASSET_DIR / f"{candidate}.{extension}"
            if path.exists():
                return path
    return None


class KojiVisual:
    """Small wrapper that swaps image/gif assets or text placeholder on a label."""

    def __init__(self, label: QLabel, size: QSize) -> None:
        self.label = label
        self.size = size
        self.movie: QMovie | None = None

    def set_state(self, state: str) -> None:
        asset = find_state_asset(state)
        self.movie = None
        self.label.clear()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setFixedSize(self.size)

        if asset is None:
            self.label.setText(PLACEHOLDER)
            self.label.setStyleSheet(
                "QLabel { color: #6b4b35; font-size: 28px; font-weight: 700; "
                "background: rgba(255, 246, 225, 190); border: 2px solid rgba(107,75,53,90); "
                "border-radius: 24px; padding: 8px; }"
            )
            return

        self.label.setStyleSheet("background: transparent;")
        if asset.suffix.lower() == ".gif":
            self.movie = QMovie(str(asset))
            self.movie.setScaledSize(self.size)
            self.label.setMovie(self.movie)
            self.movie.start()
            return

        pixmap = QPixmap(str(asset))
        if pixmap.isNull():
            self.label.setText(PLACEHOLDER)
            return
        self.label.setPixmap(pixmap.scaled(self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


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
    options = dialogues.get(state) or dialogues.get("idle") or [fallback]
    return random.choice(options)
