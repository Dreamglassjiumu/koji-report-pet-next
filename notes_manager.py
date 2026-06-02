"""Sticky note persistence for Koji Report Pet Next."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List
from uuid import uuid4

from storage import NOTES_FILE, load_json, save_json


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Note:
    id: str
    title: str
    content: str
    tag_id: str | None
    color: str
    x: int
    y: int
    width: int
    height: int
    pinned: bool
    created_at: str
    updated_at: str
    visible: bool

    @classmethod
    def from_dict(cls, data: dict) -> "Note | None":
        try:
            return cls(
                id=str(data["id"]),
                title=str(data.get("title") or "随手记"),
                content=str(data.get("content") or ""),
                tag_id=str(data.get("tag_id")) if data.get("tag_id") else None,
                color=str(data.get("color") or "#fff4c2"),
                x=int(data.get("x", 240)),
                y=int(data.get("y", 180)),
                width=max(220, int(data.get("width", 280))),
                height=max(180, int(data.get("height", 260))),
                pinned=bool(data.get("pinned", True)),
                created_at=str(data.get("created_at") or now_text()),
                updated_at=str(data.get("updated_at") or now_text()),
                visible=bool(data.get("visible", True)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "tag_id": self.tag_id,
            "color": self.color,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "pinned": self.pinned,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "visible": self.visible,
        }


class NotesManager:
    def __init__(self) -> None:
        self.notes: List[Note] = []
        self.load()

    def load(self) -> None:
        raw = load_json(NOTES_FILE, [])
        self.notes = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    note = Note.from_dict(item)
                    if note is not None:
                        self.notes.append(note)

    def save(self) -> None:
        save_json(NOTES_FILE, [note.to_dict() for note in self.notes])

    def all_notes(self) -> List[Note]:
        return sorted(self.notes, key=lambda note: note.updated_at, reverse=True)

    def get(self, note_id: str) -> Note | None:
        for note in self.notes:
            if note.id == note_id:
                return note
        return None

    def create_note(self, tag_id: str | None = None, color: str = "#fff4c2", x: int = 240, y: int = 180) -> Note:
        timestamp = now_text()
        note = Note(uuid4().hex, "随手记", "", tag_id, color, x, y, 280, 260, True, timestamp, timestamp, True)
        self.notes.append(note)
        self.save()
        return note

    def touch(self, note: Note) -> None:
        note.updated_at = now_text()
        self.save()

    def delete(self, note_id: str) -> None:
        self.notes = [note for note in self.notes if note.id != note_id]
        self.save()

    def reassign_deleted_tag(self, tag_id: str) -> None:
        changed = False
        for note in self.notes:
            if note.tag_id == tag_id:
                note.tag_id = None
                changed = True
        if changed:
            self.save()
