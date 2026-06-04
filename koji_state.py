"""Companion state and character-aware cached asset loading utilities."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import QLabel

from character_manager import ASSET_EXTENSIONS, COMMON_STATE_ASSETS, COMPANION_STATES, CharacterPackage
from storage import DIALOGUES_FILE, load_json

STATES: List[str] = list(COMPANION_STATES)
STATE_ALIASES = {
    "writing": "writing",
    "happy": "happy",
    "confused": "confused",
    "angry": "angry",
    "drag": "drag",
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
    """Swaps character images/gifs by companion state using per-character caches."""

    def __init__(self, label: QLabel, size: QSize, character: CharacterPackage | None = None) -> None:
        self.label = label
        self.size = size
        self.character: CharacterPackage | None = None
        self.current_state = "idle"
        self.current_asset: Path | None = None
        self.movie: QMovie | None = None
        self.asset_cache: dict[str, Path | None] = {}
        self.pixmap_cache: dict[Path, QPixmap] = {}
        self.movie_cache: dict[Path, QMovie] = {}
        self.idle_variant_cache: list[Path] = []
        self.set_character(character)

    def set_character(self, character: CharacterPackage | None) -> None:
        self._stop_current_movie()
        self.character = character
        self.current_asset = None
        self.asset_cache.clear()
        self.pixmap_cache.clear()
        self.movie_cache.clear()
        self.idle_variant_cache.clear()
        self.preload_character_assets()
        self.set_state(self.current_state, force=True)

    def preload_character_assets(self) -> None:
        if self.character is None:
            return
        state_names = set(COMMON_STATE_ASSETS) | set(self.character.states.keys()) | set(STATES)
        for state_name in sorted(state_names):
            asset = self._resolve_asset_for_state(state_name)
            self.asset_cache[state_name] = asset
            if asset is not None:
                self._preload_asset(asset)
        self.idle_variant_cache = self._resolve_idle_variants()
        for asset in self.idle_variant_cache:
            self._preload_asset(asset)
        fallback = self._resolve_avatar_asset()
        self.asset_cache["avatar"] = fallback
        if fallback is not None:
            self._preload_asset(fallback)

    def set_state(self, state: str, force: bool = False) -> None:
        state = normalize_state(state)
        if not force and state == self.current_state:
            return
        self.current_state = state
        asset = self._asset_for_state(state)
        if not force and asset == self.current_asset:
            return
        self._show_asset(asset)

    def show_random_idle_variant(self) -> bool:
        if self.character is None or not self.idle_variant_cache:
            self.set_state("idle")
            return False
        self.current_state = "idle"
        self._show_asset(random.choice(self.idle_variant_cache))
        return True

    def _asset_for_state(self, state: str) -> Path | None:
        if self.character is None:
            return None
        asset = self.asset_cache.get(state)
        if asset is not None:
            return asset
        if state != "idle":
            idle = self.asset_cache.get("idle")
            if idle is not None:
                return idle
        avatar = self.asset_cache.get("avatar")
        return avatar if avatar is not None else None

    def _resolve_asset_for_state(self, state: str) -> Path | None:
        if self.character is None:
            return None
        state = str(state)
        state_names = [state]
        if state != "idle":
            state_names.append("idle")
        for state_name in state_names:
            configured = self.character.states.get(state_name)
            candidates = [configured] if configured else []
            candidates.extend(f"{state_name}.{extension}" for extension in ASSET_EXTENSIONS)
            for candidate in candidates:
                path = self._safe_character_path(candidate)
                if path is not None and path.exists() and path.is_file():
                    return path
        return self._resolve_avatar_asset()

    def _resolve_avatar_asset(self) -> Path | None:
        if self.character is None:
            return None
        for extension in ASSET_EXTENSIONS:
            path = self.character.directory / f"avatar.{extension}"
            if path.exists() and path.is_file():
                return path
        return None

    def _resolve_idle_variants(self) -> list[Path]:
        if self.character is None:
            return []
        variants: list[Path] = []
        for stem in ("idle_01", "idle_02", "idle_03"):
            for extension in ASSET_EXTENSIONS:
                path = self.character.directory / f"{stem}.{extension}"
                if path.exists() and path.is_file():
                    variants.append(path)
        # Keep compatibility with imported packages that use idle_04+.
        for extension in ASSET_EXTENSIONS:
            variants.extend(path for path in sorted(self.character.directory.glob(f"idle_*.{extension}")) if path.is_file())
        unique: list[Path] = []
        seen: set[Path] = set()
        for path in variants:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(resolved)
        return unique

    def _safe_character_path(self, candidate: str | None) -> Path | None:
        if self.character is None or not candidate:
            return None
        path = (self.character.directory / candidate).resolve()
        root = self.character.directory.resolve()
        if root not in path.parents and path != root:
            return None
        if path.suffix.lower().lstrip(".") not in ASSET_EXTENSIONS:
            return None
        return path

    def _preload_asset(self, asset: Path) -> None:
        if asset.suffix.lower() == ".gif":
            if asset not in self.movie_cache:
                movie = QMovie(str(asset))
                if movie.isValid():
                    movie.setScaledSize(self.size)
                    self.movie_cache[asset] = movie
            return
        if asset not in self.pixmap_cache:
            pixmap = QPixmap(str(asset))
            if not pixmap.isNull():
                self.pixmap_cache[asset] = pixmap.scaled(self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _show_asset(self, asset: Path | None) -> None:
        self._stop_current_movie()
        self.current_asset = asset
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
            movie = self.movie_cache.get(asset)
            if movie is None or not movie.isValid():
                self._show_placeholder()
                return
            movie.stop()
            movie.jumpToFrame(0)
            movie.setScaledSize(self.size)
            self.movie = movie
            self.label.setMovie(movie)
            movie.start()
            return

        pixmap = self.pixmap_cache.get(asset)
        if pixmap is None or pixmap.isNull():
            self._show_placeholder()
            return
        self.label.setScaledContents(True)
        self.label.setPixmap(pixmap)

    def _stop_current_movie(self) -> None:
        if self.movie is not None:
            self.movie.stop()
            self.movie = None

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
