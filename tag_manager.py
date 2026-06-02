"""Editable colorful tag management for Koji notes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List
from uuid import uuid4

from storage import TAGS_FILE, load_json, save_json

UNCATEGORIZED_TAG_ID = "uncategorized"

DEFAULT_TAGS = [
    ("pitch创作", "#f3a65a"),
    ("物件包装", "#f6c177"),
    ("玩法包装", "#ef9fbc"),
    ("资料整理", "#9ccfd8"),
    ("会议总结", "#c4a7e7"),
    ("剧本创作", "#eb6f92"),
    ("角色包装", "#31748f"),
    ("文档处理", "#b7c89f"),
    ("灵感", "#f6d365"),
    ("待确认", "#e0def4"),
    ("Bug/问题", "#f28b82"),
]


@dataclass
class Tag:
    id: str
    name: str
    color: str
    order: int
    is_default: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Tag | None":
        try:
            return cls(
                id=str(data["id"]),
                name=str(data["name"]),
                color=str(data.get("color") or "#f6c177"),
                order=int(data.get("order") or 0),
                is_default=bool(data.get("is_default", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "order": self.order,
            "is_default": self.is_default,
        }


class TagManager:
    def __init__(self) -> None:
        self.tags: List[Tag] = []
        self.load()

    def default_tags(self) -> List[Tag]:
        return [
            Tag(id=f"default-{index}", name=name, color=color, order=index, is_default=True)
            for index, (name, color) in enumerate(DEFAULT_TAGS)
        ]

    def load(self) -> None:
        raw = load_json(TAGS_FILE, None)
        loaded: List[Tag] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    tag = Tag.from_dict(item)
                    if tag is not None:
                        loaded.append(tag)
        self.tags = sorted(loaded or self.default_tags(), key=lambda tag: tag.order)
        if not loaded:
            self.save()

    def save(self) -> None:
        save_json(TAGS_FILE, [tag.to_dict() for tag in self.tags])

    def all_tags(self) -> List[Tag]:
        return list(sorted(self.tags, key=lambda tag: tag.order))

    def get(self, tag_id: str | None) -> Tag | None:
        for tag in self.tags:
            if tag.id == tag_id:
                return tag
        return None

    def name_for(self, tag_id: str | None, fallback: str = "未分类") -> str:
        tag = self.get(tag_id)
        return tag.name if tag is not None else fallback

    def color_for(self, tag_id: str | None, fallback: str = "#f6c177") -> str:
        tag = self.get(tag_id)
        return tag.color if tag is not None else fallback

    def add_tag(self, name: str, color: str = "#f6c177") -> Tag:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Tag 名称不能为空")
        tag = Tag(id=uuid4().hex, name=cleaned, color=color, order=len(self.tags), is_default=False)
        self.tags.append(tag)
        self.save()
        return tag

    def update_tag(self, tag_id: str, name: str, color: str) -> Tag:
        tag = self.get(tag_id)
        if tag is None:
            raise ValueError("这个 Tag 已经不存在了。")
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Tag 名称不能为空")
        tag.name = cleaned
        tag.color = color or tag.color
        self.save()
        return tag

    def delete_tag(self, tag_id: str) -> None:
        self.tags = [tag for tag in self.tags if tag.id != tag_id]
        for index, tag in enumerate(self.tags):
            tag.order = index
        self.save()

    def restore_defaults(self) -> None:
        self.tags = self.default_tags()
        self.save()
