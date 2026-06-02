"""Daily report record management and template rendering."""
from __future__ import annotations

from collections import defaultdict
import re
from dataclasses import dataclass
from datetime import date, datetime
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

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
FRIDAY_WEEKDAY = 4

WORKDAY_AI_SYSTEM_PROMPT = """你是 Koji，一个文案组日报整理桌宠。你要帮助游戏公司文案策划把零散、口语化、碎片化的工作记录整理成一份可以提交的正式日报。请使用中文输出。

输出格式必须严格为纯文本：

1. 今日工作内容

2. 明日工作内容

3. 近期工作内容

写作要求：
* 根据用户提供的记录进行整理、润色、归纳和适度扩写。
* 目标总长度约 1200～1500 字；素材较少时也尽量写到 800 字以上。
* 可以基于文案策划工作常识进行合理补足，例如资料整理、需求对齐、方案验证、表达优化、问题记录、后续跟进等。
* 不要凭空编造具体项目、具体会议、具体人员、具体结论或已经完成的交付结果。
* “今日工作内容”重点写今天实际推进了什么。
* “明日工作内容”根据今日记录推导明天可以继续做什么。
* “近期工作内容”写未来几天需要持续推进、优化、沉淀或确认的事项。
* 不要输出“今日完成”“进行中”“明日计划”“风险与待确认”等标题。
* 表达要像游戏公司文案策划自己的日报，具体、体面、自然，不要客服腔，不要空话套话。
* 请输出纯文本日报，不要使用 Markdown，不要使用标题符号、加粗符号、项目符号或代码块。标题只能使用“1. 今日工作内容”这种普通编号格式。正文使用自然段，不要使用 Markdown 列表。
"""

FRIDAY_AI_SYSTEM_PROMPT = """你是 Koji，一个文案组日报整理桌宠。今天是周五，你要帮助游戏公司文案策划把本周零散工作记录整理成一份可以提交的周五日报。请使用中文输出。

输出格式必须严格为纯文本：

1. 本周工作内容

2. 下周一工作内容

3. 近期工作内容

写作要求：
* 根据用户提供的记录进行整理、润色、归纳和适度扩写。
* 目标总长度约 1200～1500 字；素材较少时也尽量写到 800 字以上。
* “本周工作内容”要把用户记录包装成一周维度的阶段性推进，包括已完成、已验证、已整理、已沉淀、已发现的问题等。
* “下周一工作内容”要根据本周工作自然推导下周一优先处理的事项。
* “近期工作内容”写后续几天需要持续推进、优化、沟通、验证或沉淀的事项。
* 可以基于文案策划工作常识进行合理补足，例如资料整理、需求对齐、方案验证、表达优化、问题记录、后续跟进等。
* 不要凭空编造具体项目、具体会议、具体人员、具体结论或已经完成的交付结果。
* 不要输出“今日完成”“进行中”“明日计划”“风险与待确认”等标题。
* 表达要像游戏公司文案策划自己的日报，具体、体面、自然，不要客服腔，不要空话套话。
* 请输出纯文本日报，不要使用 Markdown，不要使用标题符号、加粗符号、项目符号或代码块。标题只能使用“1. 本周工作内容”这种普通编号格式。正文使用自然段，不要使用 Markdown 列表。
"""


def clean_ai_report_text(text: str) -> str:
    """Remove common Markdown markers from local AI report output while preserving plain numbered headings."""
    cleaned = str(text or "").replace("```", "")
    cleaned = cleaned.replace("**", "").replace("__", "")
    lines: List[str] = []
    for raw_line in cleaned.splitlines():
        line = re.sub(r"^\s*#{1,6}\s*", "", raw_line)
        line = re.sub(r"^\s*[-*•]+\s+", "", line)
        lines.append(line.rstrip())
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result


def local_report_date(record_date: str | None = None) -> date:
    """Return the local date used by report generation."""
    if not record_date:
        return date.today()
    try:
        return date.fromisoformat(record_date)
    except ValueError:
        return date.today()


def is_friday(record_date: str | None = None) -> bool:
    """Whether the local report date is Friday. Python weekday() uses Friday == 4."""
    return local_report_date(record_date).weekday() == FRIDAY_WEEKDAY


def weekday_name(report_date: date) -> str:
    return WEEKDAY_NAMES[report_date.weekday()]


def report_type_label(report_date: date) -> str:
    return "周五日报" if report_date.weekday() == FRIDAY_WEEKDAY else "普通工作日"


def report_section_titles(record_date: str | None = None) -> List[str]:
    if is_friday(record_date):
        return ["1. 本周工作内容", "2. 下周一工作内容", "3. 近期工作内容"]
    return ["1. 今日工作内容", "2. 明日工作内容", "3. 近期工作内容"]


def report_system_prompt(record_date: str | None = None) -> str:
    return FRIDAY_AI_SYSTEM_PROMPT if is_friday(record_date) else WORKDAY_AI_SYSTEM_PROMPT


@dataclass
class ReportRecord:
    id: str
    date: str
    category: str
    content: str
    time: str

    @classmethod
    def from_dict(cls, data: dict) -> "ReportRecord | None":
        try:
            return cls(
                id=str(data["id"]),
                date=str(data["date"]),
                category=str(data["category"]),
                content=str(data["content"]),
                time=str(data.get("time") or data.get("created_at") or ""),
            )
        except KeyError:
            return None

    def to_dict(self) -> dict:
        return {"id": self.id, "date": self.date, "category": self.category, "content": self.content, "time": self.time}


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
            category=category.strip() or CATEGORIES[0],
            content=cleaned,
            time=datetime.now().strftime("%H:%M"),
        )
        self.records.append(record)
        self.save()
        return record

    def records_for_date(self, record_date: str | None = None) -> List[ReportRecord]:
        target = record_date or date.today().isoformat()
        return [record for record in self.records if record.date == target]

    def get_record(self, record_id: str) -> ReportRecord | None:
        for record in self.records:
            if record.id == record_id:
                return record
        return None

    def update_record(self, record_id: str, category: str, content: str) -> ReportRecord:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("事项内容不能为空")
        record = self.get_record(record_id)
        if record is None:
            raise ValueError("这条记录已经不存在了。")
        record.category = category.strip() or CATEGORIES[0]
        record.content = cleaned
        if not record.time:
            record.time = datetime.now().strftime("%H:%M")
        self.save()
        return record

    def delete_record(self, record_id: str) -> None:
        self.records = [record for record in self.records if record.id != record_id]
        self.save()

    def clear_date(self, record_date: str | None = None) -> None:
        target = record_date or date.today().isoformat()
        self.records = [record for record in self.records if record.date != target]
        self.save()

    def render_template_report(self, record_date: str | None = None) -> str:
        records = self.records_for_date(record_date)
        report_date = local_report_date(record_date)
        target = report_date.isoformat()
        if not records:
            return "素材不足：今天还没有添加日报记录。"

        grouped: Dict[str, List[str]] = defaultdict(list)
        for record in records:
            grouped[record.category].append(record.content)

        titles = report_section_titles(target)
        lines = [f"{target} 日报（{weekday_name(report_date)}）", "", titles[0]]
        ordered_categories = CATEGORIES + [category for category in grouped if category not in CATEGORIES]
        for category in ordered_categories:
            items = grouped.get(category)
            if not items:
                continue
            lines.append(f"\n【{category}】")
            for index, item in enumerate(items, start=1):
                lines.append(f"{index}. {item}")

        if is_friday(target):
            next_day_title = titles[1]
            next_day_text = "- 优先承接本周已推进事项，复查记录中的待优化点，并对下周需要继续跟进的内容做排期和资料补齐。"
        else:
            next_day_title = titles[1]
            next_day_text = "- 继续承接今日已推进事项，补齐资料、优化表达，并及时记录需要对齐或验证的问题。"
        lines.extend(["", next_day_title, next_day_text, "", titles[2], "- 持续沉淀文案资料、整理问题清单，并根据实际反馈推进后续优化。"])
        return "\n".join(lines)

    def ai_material_text(self, record_date: str | None = None) -> str:
        records = self.records_for_date(record_date)
        return "\n".join(
            f"{index}. [{record.category}] {record.time or '--:--'} {record.content}"
            for index, record in enumerate(records, start=1)
        )

    def build_ai_report_messages(self, record_date: str | None = None) -> List[dict]:
        report_date = local_report_date(record_date)
        material = self.ai_material_text(report_date.isoformat())
        friday = report_date.weekday() == FRIDAY_WEEKDAY
        user_prompt = (
            f"当前日期：{report_date.isoformat()}\n"
            f"当前星期：{weekday_name(report_date)}\n"
            f"日报类型：{report_type_label(report_date)}\n\n"
            f"今日记录：\n{material}\n\n"
            "请根据以上记录生成日报。"
        )
        return [
            {"role": "system", "content": FRIDAY_AI_SYSTEM_PROMPT if friday else WORKDAY_AI_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]


def format_record_line(record: ReportRecord) -> str:
    """Render one record for list, clipboard, and export views."""
    return f"[{record.category}] {record.time or '--:--'}  {record.content}"
