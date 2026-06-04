"""Character companion package discovery and import utilities."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from storage import ROOT_DIR

CHARACTERS_DIR = ROOT_DIR / "assets" / "characters"
CHARACTER_JSON = "character.json"
COMPANION_STATES = [
    "idle",
    "thinking",
    "typing",
    "success",
    "error",
    "sleep",
    "drag",
    "happy",
    "confused",
    "angry",
    "writing",
    "collect",
    "record_ready",
    "wave",
]
COMMON_STATE_ASSETS = [
    "idle",
    "thinking",
    "typing",
    "writing",
    "success",
    "error",
    "sleep",
    "drag",
    "happy",
    "confused",
    "angry",
    "collect",
    "record_ready",
    "wave",
    "idle_01",
    "idle_02",
    "idle_03",
]
ASSET_EXTENSIONS = ("png", "jpg", "jpeg", "webp", "gif")
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True)
class CharacterPackage:
    """Metadata and paths for one desktop companion character."""

    id: str
    name: str
    version: str
    directory: Path
    states: dict[str, str] = field(default_factory=dict)

    def state_asset(self, state: str) -> Path | None:
        """Return the best state image path with idle/avatar fallback."""
        state_names = [state]
        if state != "idle":
            state_names.append("idle")
        for state_name in state_names:
            configured = self.states.get(state_name)
            candidates = [configured] if configured else []
            candidates.extend(f"{state_name}.{extension}" for extension in ASSET_EXTENSIONS)
            for candidate in candidates:
                if not candidate:
                    continue
                path = (self.directory / candidate).resolve()
                if self.directory.resolve() not in path.parents and path != self.directory.resolve():
                    continue
                if path.exists() and path.is_file():
                    return path
        for extension in ASSET_EXTENSIONS:
            avatar = self.directory / f"avatar.{extension}"
            if avatar.exists() and avatar.is_file():
                return avatar
        return None

    def idle_variants(self) -> list[Path]:
        """Return idle_XX image variants for random idle presentation."""
        variants: list[Path] = []
        for extension in ASSET_EXTENSIONS:
            variants.extend(sorted(self.directory.glob(f"idle_*.{extension}")))
        return [path for path in variants if path.is_file()]


class CharacterManager:
    """Scans assets/characters so new companions can be added without code changes."""

    def __init__(self, characters_dir: Path = CHARACTERS_DIR) -> None:
        self.characters_dir = characters_dir
        self.characters: dict[str, CharacterPackage] = {}
        self.refresh()

    def refresh(self) -> list[CharacterPackage]:
        self.characters_dir.mkdir(parents=True, exist_ok=True)
        found: dict[str, CharacterPackage] = {}
        for directory in sorted(path for path in self.characters_dir.iterdir() if path.is_dir()):
            character = self._load_character(directory)
            if character is not None:
                found[character.id] = character
        self.characters = found
        return self.all_characters()

    def all_characters(self) -> list[CharacterPackage]:
        return sorted(self.characters.values(), key=lambda character: character.name.casefold())

    def get(self, character_id: str | None) -> CharacterPackage | None:
        if character_id and character_id in self.characters:
            return self.characters[character_id]
        if "koji" in self.characters:
            return self.characters["koji"]
        characters = self.all_characters()
        return characters[0] if characters else None

    def import_zip(self, zip_path: str | Path) -> CharacterPackage:
        source = Path(zip_path)
        if not source.exists():
            raise ValueError("角色包不存在。")
        with tempfile.TemporaryDirectory(prefix="koji-character-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            with zipfile.ZipFile(source) as archive:
                self._safe_extract(archive, temp_dir)
            package_root = self._find_package_root(temp_dir)
            character = self._load_character(package_root)
            if character is None:
                raise ValueError("角色包缺少有效的 character.json。")
            target_id = sanitize_character_id(character.id or package_root.name)
            target = self.characters_dir / target_id
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(package_root, target)
        self.refresh()
        imported = self.characters.get(target_id)
        if imported is None:
            raise ValueError("角色导入后无法加载，请检查 character.json。")
        return imported

    def _load_character(self, directory: Path) -> CharacterPackage | None:
        metadata_path = directory / CHARACTER_JSON
        if not metadata_path.exists():
            return None
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        character_id = sanitize_character_id(str(data.get("id") or directory.name))
        name = str(data.get("name") or character_id).strip() or character_id
        version = str(data.get("version") or "1.0")
        raw_states = data.get("states", {})
        states = {str(key): str(value) for key, value in raw_states.items()} if isinstance(raw_states, dict) else {}
        return CharacterPackage(character_id, name, version, directory, states)

    def _safe_extract(self, archive: zipfile.ZipFile, destination: Path) -> None:
        destination_resolved = destination.resolve()
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if destination_resolved not in target.parents and target != destination_resolved:
                raise ValueError("角色包包含不安全路径。")
        archive.extractall(destination)

    def _find_package_root(self, extracted_dir: Path) -> Path:
        direct_json = extracted_dir / CHARACTER_JSON
        if direct_json.exists():
            return extracted_dir
        child_dirs = [path for path in extracted_dir.iterdir() if path.is_dir()]
        if len(child_dirs) == 1 and (child_dirs[0] / CHARACTER_JSON).exists():
            return child_dirs[0]
        for path in child_dirs:
            if (path / CHARACTER_JSON).exists():
                return path
        return extracted_dir


def sanitize_character_id(value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("_", value.strip()).strip("._-")
    return cleaned or "character"
