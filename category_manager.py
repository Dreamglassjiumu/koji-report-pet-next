"""Editable work category management for Koji report records."""
from __future__ import annotations

from typing import List

from storage import CATEGORIES_FILE, load_json, save_json

DEFAULT_CATEGORIES = [
    "pitch创作",
    "物件包装",
    "玩法包装",
    "资料整理",
    "会议总结",
    "剧本创作",
    "角色包装",
    "文档处理",
    "流程优化",
    "需求对齐",
]

UNCATEGORIZED = "未分类"


def normalized_category_name(name: str) -> str:
    """Trim user input for category names."""
    return str(name or "").strip()


class CategoryManager:
    """Persist and validate user-editable report categories."""

    def __init__(self) -> None:
        self.categories: List[str] = []
        self.load()

    def load(self) -> None:
        raw = load_json(CATEGORIES_FILE, None)
        loaded: List[str] = []
        if isinstance(raw, dict) and isinstance(raw.get("categories"), list):
            loaded = [normalized_category_name(item) for item in raw["categories"]]
        elif isinstance(raw, list):
            loaded = [normalized_category_name(item) for item in raw]

        self.categories = self._dedupe_preserve_order(loaded or DEFAULT_CATEGORIES)
        changed = False
        for default in DEFAULT_CATEGORIES:
            if default not in self.categories:
                self.categories.append(default)
                changed = True
        if raw is None or changed:
            self.save()

    def save(self) -> None:
        save_json(CATEGORIES_FILE, {"categories": self.categories})

    def all_categories(self) -> List[str]:
        return list(self.categories)

    def add_category(self, name: str) -> str:
        cleaned = normalized_category_name(name)
        if not cleaned:
            raise ValueError("分类名称不能为空。")
        if cleaned in self.categories:
            raise ValueError("这个分类已经存在了。")
        self.categories.append(cleaned)
        self.save()
        return cleaned

    def rename_category(self, old_name: str, new_name: str) -> tuple[str, str]:
        old_cleaned = normalized_category_name(old_name)
        new_cleaned = normalized_category_name(new_name)
        if not old_cleaned or old_cleaned not in self.categories:
            raise ValueError("请选择要重命名的分类。")
        if not new_cleaned:
            raise ValueError("分类名称不能为空。")
        if new_cleaned != old_cleaned and new_cleaned in self.categories:
            raise ValueError("这个分类已经存在了。")
        index = self.categories.index(old_cleaned)
        self.categories[index] = new_cleaned
        self.save()
        return old_cleaned, new_cleaned

    def delete_category(self, name: str) -> str:
        cleaned = normalized_category_name(name)
        if not cleaned or cleaned not in self.categories:
            raise ValueError("请选择要删除的分类。")
        self.categories = [category for category in self.categories if category != cleaned]
        self.save()
        return cleaned

    def restore_defaults(self) -> None:
        self.categories = list(DEFAULT_CATEGORIES)
        self.save()

    @staticmethod
    def _dedupe_preserve_order(items: List[str]) -> List[str]:
        result: List[str] = []
        for item in items:
            if item and item not in result:
                result.append(item)
        return result or list(DEFAULT_CATEGORIES)
