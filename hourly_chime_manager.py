"""Hourly Koji bubble chime manager."""
from __future__ import annotations

from datetime import datetime, time

from PySide6.QtCore import QObject, QTimer, Signal

CHIME_LINES = {
    9: "开工了，今天的素材从第一条开始。",
    10: "上午已经过去一截了，记录点东西吧。",
    11: "午饭前最后的尊严，写点东西吧。",
    12: "吃饭，日报先放过你五分钟。",
    13: "下午场开始，Koji 也被迫营业。",
    14: "现在记录一条，晚上少痛苦十分钟。",
    15: "三点了，精神状态开始抽象。",
    16: "别等下班前才开始回忆人生。",
    17: "下班前的素材冲刺窗口打开。",
    18: "理论上下班，实际上日报还没写。",
    19: "加班气息出现，Koji 先替你叹口气。",
    20: "今天还没记录的话，就有点抽象了。",
    21: "建议现在生成日报，别深夜考古。",
    22: "夜之日报时间，现在写还来得及。",
    23: "再不写，明天的你会恨今天的你。",
}


class HourlyChimeManager(QObject):
    chime = Signal(str)

    def __init__(self, settings_manager, busy_callback=None, focus_callback=None) -> None:
        super().__init__()
        self.settings_manager = settings_manager
        self.busy_callback = busy_callback
        self.focus_callback = focus_callback
        self.last_key = ""
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.check_now)
        self.timer.start()

    def parse_time(self, value: str, fallback: time) -> time:
        try:
            hour, minute = str(value).split(":", 1)
            return time(max(0, min(23, int(hour))), max(0, min(59, int(minute))))
        except (TypeError, ValueError):
            return fallback

    def enabled(self) -> bool:
        return bool(self.settings_manager.get("hourly_chime_enabled", True))

    def in_work_hours(self, now: datetime) -> bool:
        start = self.parse_time(self.settings_manager.get("hourly_chime_start", "09:00"), time(9, 0))
        end = self.parse_time(self.settings_manager.get("hourly_chime_end", "23:00"), time(23, 0))
        current = now.time().replace(second=0, microsecond=0)
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def check_now(self) -> None:
        now = datetime.now()
        if not self.enabled() or now.minute != 0 or not self.in_work_hours(now):
            return
        key = f"{now.date().isoformat()}-{now.hour}"
        if key == self.last_key:
            return
        if self.busy_callback is not None and self.busy_callback():
            return
        self.last_key = key
        in_focus = bool(self.focus_callback() if self.focus_callback is not None else False)
        if in_focus or bool(self.settings_manager.get("hourly_chime_quiet", False)):
            self.chime.emit(f"{now.hour:02d}:00 到了，记得留一条素材。")
        else:
            self.chime.emit(CHIME_LINES.get(now.hour, "整点到了，Koji 提醒你留一点日报素材。"))
