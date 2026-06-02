"""Daily report record management and template rendering."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List
from uuid import uuid4

from storage import RECORDS_FILE, load_json, save_json

CATEGORIES = [
    "pitch创作",
    "物件包装",
    "玩法包装",
    "资料整理",
    "会议总结",
    "剧本创作",
    "角色包装",
    "文档处理",
]


@dataclass
class ReportRecord:
    id: str
    date: str
    category: str
    content: str

    @classmethod
    def from_dict(cls, data: dict) -> "ReportRecord | None":
        try:
            return cls(
                id=str(data["id"]),
                date=str(data["date"]),
                category=str(data["category"]),
                content=str(data["content"]),
            )
        except KeyError:
            return None

    def to_dict(self) -> dict:
        return {"id": self.id, "date": self.date, "category": self.category, "content": self.content}


class ReportManager:
    def __init__(self) -> None:
        self.records: List[ReportRecord] = []
        self.load()

    def load(self) -> None:
        raw_records = load_json(RECORDS_FILE, [])
        self.records = []
        if isinstance(raw_records, list):
            for raw in raw_records:
                if isinstance(raw, dict):
                    record = ReportRecord.from_dict(raw)
                    if record is not None:
                        self.records.append(record)

    def save(self) -> None:
        save_json(RECORDS_FILE, [record.to_dict() for record in self.records])

    def add_record(self, category: str, content: str, record_date: str | None = None) -> ReportRecord:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("事项内容不能为空")
        record = ReportRecord(
            id=uuid4().hex,
            date=record_date or date.today().isoformat(),
            category=category if category in CATEGORIES else CATEGORIES[0],
            content=cleaned,
        )
        self.records.append(record)
        self.save()
        return record

    def records_for_date(self, record_date: str | None = None) -> List[ReportRecord]:
        target = record_date or date.today().isoformat()
        return [record for record in self.records if record.date == target]

    def delete_record(self, record_id: str) -> None:
        self.records = [record for record in self.records if record.id != record_id]
        self.save()

    def clear_date(self, record_date: str | None = None) -> None:
        target = record_date or date.today().isoformat()
        self.records = [record for record in self.records if record.date != target]
        self.save()

    def render_template_report(self, record_date: str | None = None) -> str:
        records = self.records_for_date(record_date)
        target = record_date or date.today().isoformat()
        if not records:
            return "素材不足：今天还没有添加日报记录。"

        grouped: Dict[str, List[str]] = defaultdict(list)
        for record in records:
            grouped[record.category].append(record.content)

        lines = [f"{target} 日报", "", "今日完成："]
        for category in CATEGORIES:
            items = grouped.get(category)
            if not items:
                continue
            lines.append(f"\n【{category}】")
            for index, item in enumerate(items, start=1):
                lines.append(f"{index}. {item}")
        lines.extend(["", "明日计划：", "- 继续推进重点事项，及时同步风险与进展。"])
        return "\n".join(lines)

    def ai_material_text(self, record_date: str | None = None) -> str:
        records = self.records_for_date(record_date)
        return "\n".join(f"- {record.category}：{record.content}" for record in records)
