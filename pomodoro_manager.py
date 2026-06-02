"""Pomodoro timer state and local statistics."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict

from PySide6.QtCore import QObject, QTimer, Signal

from storage import POMODORO_STATS_FILE, load_json, save_json

PHASE_FOCUS = "focus"
PHASE_SHORT_BREAK = "short_break"
PHASE_LONG_BREAK = "long_break"
PHASE_LABELS = {PHASE_FOCUS: "专注", PHASE_SHORT_BREAK: "短休息", PHASE_LONG_BREAK: "长休息", "stopped": "未开始"}


class PomodoroManager(QObject):
    tick = Signal()
    phase_changed = Signal(str)
    focus_completed = Signal()

    def __init__(self, settings_manager) -> None:
        super().__init__()
        self.settings_manager = settings_manager
        self.phase = "stopped"
        self.remaining_seconds = int(self.focus_minutes * 60)
        self.running = False
        self.completed_today = 0
        self.stats: Dict = {}
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.load_stats()

    @property
    def focus_minutes(self) -> int:
        return max(1, int(self.settings_manager.get("pomodoro_focus_minutes", 25)))

    @property
    def short_break_minutes(self) -> int:
        return max(1, int(self.settings_manager.get("pomodoro_short_break_minutes", 5)))

    @property
    def long_break_minutes(self) -> int:
        return max(1, int(self.settings_manager.get("pomodoro_long_break_minutes", 15)))

    def today_key(self) -> str:
        return date.today().isoformat()

    def load_stats(self) -> None:
        raw = load_json(POMODORO_STATS_FILE, {})
        self.stats = raw if isinstance(raw, dict) else {}
        today = self.stats.get(self.today_key(), {}) if isinstance(self.stats.get(self.today_key(), {}), dict) else {}
        self.completed_today = int(today.get("completed_count", 0) or 0)

    def save_stats(self) -> None:
        today = self.stats.setdefault(self.today_key(), {"completed_count": 0, "completed_at": [], "phase_records": []})
        today["completed_count"] = self.completed_today
        save_json(POMODORO_STATS_FILE, self.stats)

    def _record_phase(self, phase: str, event: str) -> None:
        today = self.stats.setdefault(self.today_key(), {"completed_count": 0, "completed_at": [], "phase_records": []})
        today.setdefault("phase_records", []).append({"phase": phase, "event": event, "time": datetime.now().isoformat(timespec="seconds")})
        self.save_stats()

    def _set_phase(self, phase: str, seconds: int) -> None:
        self.phase = phase
        self.remaining_seconds = max(0, seconds)
        self._record_phase(phase, "start")
        self.phase_changed.emit(phase)
        self.tick.emit()

    def start(self) -> None:
        self._set_phase(PHASE_FOCUS, self.focus_minutes * 60)
        self.running = True
        self.timer.start()

    def pause(self) -> None:
        if self.running:
            self.running = False
            self.timer.stop()
            self._record_phase(self.phase, "pause")
            self.tick.emit()

    def resume(self) -> None:
        if self.phase != "stopped" and not self.running:
            self.running = True
            self.timer.start()
            self._record_phase(self.phase, "resume")
            self.tick.emit()

    def toggle_pause(self) -> None:
        self.pause() if self.running else self.resume()

    def stop(self) -> None:
        self.timer.stop()
        self.running = False
        self._record_phase(self.phase, "stop")
        self.phase = "stopped"
        self.remaining_seconds = self.focus_minutes * 60
        self.phase_changed.emit(self.phase)
        self.tick.emit()

    def skip(self) -> None:
        self._finish_phase()

    def reset_count(self) -> None:
        self.completed_today = 0
        self.save_stats()
        self.tick.emit()

    def apply_settings(self) -> None:
        if self.phase == "stopped":
            self.remaining_seconds = self.focus_minutes * 60
            self.tick.emit()

    def _tick(self) -> None:
        if not self.running:
            return
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self._finish_phase()
        else:
            self.tick.emit()

    def _finish_phase(self) -> None:
        previous = self.phase
        self._record_phase(previous, "finish")
        if previous == PHASE_FOCUS:
            self.completed_today += 1
            today = self.stats.setdefault(self.today_key(), {"completed_count": 0, "completed_at": [], "phase_records": []})
            today.setdefault("completed_at", []).append(datetime.now().isoformat(timespec="seconds"))
            self.save_stats()
            self.focus_completed.emit()
            if self.completed_today % 4 == 0:
                self._set_phase(PHASE_LONG_BREAK, self.long_break_minutes * 60)
            else:
                self._set_phase(PHASE_SHORT_BREAK, self.short_break_minutes * 60)
        else:
            self._set_phase(PHASE_FOCUS, self.focus_minutes * 60)
        self.running = True
        self.timer.start()

    def formatted_remaining(self) -> str:
        minutes, seconds = divmod(max(0, self.remaining_seconds), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def phase_label(self) -> str:
        return PHASE_LABELS.get(self.phase, self.phase)
