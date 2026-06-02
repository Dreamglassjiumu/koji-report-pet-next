"""Koji Report Pet Next desktop pet application."""
from __future__ import annotations

import math
import os
import random
import sys
from datetime import date
from typing import Callable, Dict

if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QPoint, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai_runtime_manager import AIRuntimeManager, AI_UNAVAILABLE_MESSAGE, READY_MESSAGE, STARTING_MESSAGE, STATUS_LABELS
from chat_manager import ChatManager
from koji_state import STATES, KojiVisual, random_dialogue
from report_manager import CATEGORIES, ReportManager, format_record_line


REPORT_PANEL_STYLESHEET = """
QDialog#reportPanel {
    background: #fff9ef;
}
QLabel#panelTitle {
    color: #4b3324;
    font-size: 24px;
    font-weight: 800;
}
QLabel#panelSubtitle {
    color: #7a5b45;
    font-size: 14px;
}
QLabel#aiNotice {
    color: #8a5a00;
    background: #fff0c2;
    border: 1px solid #f0cf76;
    border-radius: 10px;
    padding: 8px 10px;
}
QComboBox, QLineEdit, QListWidget, QPlainTextEdit {
    color: #3e2b20;
    background: rgba(255, 255, 255, 230);
    border: 1px solid #ead8bf;
    border-radius: 10px;
    padding: 7px 9px;
    selection-background-color: #f0b35c;
}
QListWidget#recordsList, QPlainTextEdit#reportText {
    border: 1px solid #e4ceb0;
}
QPushButton {
    color: #4b3324;
    background: #ffe0a8;
    border: 1px solid #e6ba72;
    border-radius: 10px;
    padding: 8px 10px;
    font-weight: 700;
}
QPushButton:hover {
    background: #ffd28a;
}
QPushButton:pressed {
    background: #f3bd6a;
}
"""


CHAT_UNAVAILABLE_REPLY = "Koji 的本地脑子还没装上，但我可以先负责可爱。等放入 model.gguf 后再来聊。"


class ChatDialog(QDialog):
    def __init__(self, chat_manager: ChatManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chat_manager = chat_manager
        self.setWindowTitle("和 Koji 聊两句")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(480, 420)

        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        self.history_view.setPlaceholderText("这里会显示你和 Koji 的聊天记录。")
        self.input = QLineEdit()
        self.input.setPlaceholderText("和 Koji 说点什么……")
        send_button = QPushButton("发送")
        send_button.clicked.connect(self.send_message)
        clear_button = QPushButton("清空历史")
        clear_button.clicked.connect(self.clear_history)
        self.input.returnPressed.connect(self.send_message)

        bottom = QHBoxLayout()
        bottom.addWidget(self.input, 1)
        bottom.addWidget(send_button)
        bottom.addWidget(clear_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.history_view, 1)
        layout.addLayout(bottom)
        self.refresh()

    def refresh(self) -> None:
        self.history_view.setPlainText(self.chat_manager.render_history())
        self.history_view.verticalScrollBar().setValue(self.history_view.verticalScrollBar().maximum())

    def send_message(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        parent = self.parent()
        if parent is not None and hasattr(parent, "temporary_state"):
            parent.temporary_state("thinking")  # type: ignore[attr-defined]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, answer = self.chat_manager.chat(text, unavailable_reply=CHAT_UNAVAILABLE_REPLY)
        finally:
            QApplication.restoreOverrideCursor()
        if parent is not None and hasattr(parent, "temporary_state"):
            parent.temporary_state("happy" if ok else "confused")  # type: ignore[attr-defined]
        self.refresh()

    def clear_history(self) -> None:
        self.chat_manager.clear()
        self.refresh()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
        self.hide()


class ReportPanel(QDialog):
    def __init__(
        self,
        report_manager: ReportManager,
        ai_runtime: AIRuntimeManager,
        state_callback: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.report_manager = report_manager
        self.ai_runtime = ai_runtime
        self.state_callback = state_callback
        self.record_ids: Dict[int, str] = {}
        self.setWindowTitle("Koji 日报面板")
        self.resize(860, 760)
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)

        self.title_label = QLabel("Koji 日报面板")
        self.title_label.setObjectName("panelTitle")
        self.subtitle_label = QLabel("Koji 会帮你把零散工作痕迹整理成日报。")
        self.subtitle_label.setObjectName("panelSubtitle")
        self.ai_notice = QLabel("")
        self.ai_notice.setObjectName("aiNotice")
        self.ai_notice.setWordWrap(True)

        self.ai_status_label = QLabel("")
        self.ai_status_label.setObjectName("panelSubtitle")
        restart_ai_button = QPushButton("重启 Koji 脑子")
        restart_ai_button.clicked.connect(self.restart_ai)
        close_ai_button = QPushButton("关闭智能模式")
        close_ai_button.clicked.connect(self.close_ai)
        check_ai_button = QPushButton("检查 AI 状态")
        check_ai_button.clicked.connect(self.check_ai_status)
        self.ai_detail = QLabel("")
        self.ai_detail.setWordWrap(True)
        self.ai_detail.setVisible(False)
        detail_button = QPushButton("显示/隐藏高级信息")
        detail_button.clicked.connect(lambda: self.ai_detail.setVisible(not self.ai_detail.isVisible()))
        ai_status_row = QHBoxLayout()
        ai_status_row.addWidget(self.ai_status_label, 1)
        for button in (restart_ai_button, close_ai_button, check_ai_button, detail_button):
            ai_status_row.addWidget(button)
        self.refresh_ai_notice()

        self.date_label = QLabel(f"日期：{date.today().isoformat()}")
        self.category = QComboBox()
        self.category.addItems(CATEGORIES)
        self.content = QLineEdit()
        self.content.setMinimumHeight(34)
        self.content.setPlaceholderText("输入今天完成的事项……")
        add_button = QPushButton("添加记录")
        add_button.clicked.connect(self.add_record)

        input_row = QHBoxLayout()
        input_row.addWidget(self.category)
        input_row.addWidget(self.content, 1)
        input_row.addWidget(add_button)

        self.records_list = QListWidget()
        self.records_list.setObjectName("recordsList")
        self.records_list.itemDoubleClicked.connect(self.edit_record_item)
        delete_button = QPushButton("删除记录")
        delete_button.clicked.connect(self.delete_record)
        copy_record_button = QPushButton("复制记录")
        copy_record_button.clicked.connect(self.copy_record)
        clear_button = QPushButton("清空今日记录")
        clear_button.clicked.connect(self.clear_today)
        template_button = QPushButton("普通模板整理日报")
        template_button.clicked.connect(self.generate_template)
        ai_button = QPushButton("AI 整理日报")
        ai_button.clicked.connect(self.generate_ai)
        copy_button = QPushButton("复制日报")
        copy_button.clicked.connect(self.copy_report)
        export_txt_button = QPushButton("导出 .txt")
        export_txt_button.clicked.connect(lambda: self.export_records("txt"))
        export_md_button = QPushButton("导出 .md")
        export_md_button.clicked.connect(lambda: self.export_records("md"))

        button_row = QHBoxLayout()
        for button in (delete_button, copy_record_button, clear_button, template_button, ai_button, copy_button, export_txt_button, export_md_button):
            button_row.addWidget(button)

        self.report_text = QPlainTextEdit()
        self.report_text.setObjectName("reportText")
        self.report_text.setPlaceholderText("整理后的日报会显示在这里，可继续编辑。")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.ai_notice)
        layout.addLayout(ai_status_row)
        layout.addWidget(self.ai_detail)
        layout.addWidget(self.date_label)
        layout.addLayout(input_row)
        layout.addWidget(QLabel("今日记录："))
        layout.addWidget(self.records_list, 1)
        layout.addLayout(button_row)
        layout.addWidget(QLabel("日报草稿："))
        layout.addWidget(self.report_text, 2)
        self.refresh_records()

    def notify_state(self, state: str) -> None:
        if self.state_callback is not None:
            self.state_callback(state)

    def show_koji_message(self, message: str) -> None:
        self.ai_notice.setText(message)
        self.ai_notice.setVisible(True)
        parent = self.parent()
        if parent is not None and hasattr(parent, "bubble"):
            parent.bubble.show_message(message, parent)  # type: ignore[attr-defined]

    def refresh_ai_notice(self) -> None:
        status = self.ai_runtime.refresh_status()
        message = self.ai_runtime.status_message()
        self.ai_status_label.setText(f"Koji 智能模式：{STATUS_LABELS.get(status, '未知')}")
        self.ai_notice.setVisible(status.value not in {"ready_to_start", "stopped", "ready"})
        self.ai_notice.setText("" if status.value in {"ready_to_start", "stopped", "ready"} else message)
        port_text = str(self.ai_runtime.port) if self.ai_runtime.port is not None else "未分配"
        self.ai_detail.setText(
            "高级信息：\n"
            f"当前端口：{port_text}\n"
            f"runtime 路径：{self.ai_runtime.server_path}\n"
            f"model 路径：{self.ai_runtime.model_path}\n"
            f"最近错误：{self.ai_runtime.last_error or '无'}"
        )

    def check_ai_status(self) -> None:
        self.refresh_ai_notice()
        self.show_koji_message(self.ai_runtime.status_message())

    def restart_ai(self) -> None:
        self.notify_state("thinking")
        self.show_koji_message(STARTING_MESSAGE)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, message = self.ai_runtime.restart()
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_ai_notice()
        self.notify_state("success" if ok else "error")
        self.show_koji_message(message)

    def close_ai(self) -> None:
        self.ai_runtime.shutdown()
        self.notify_state("sleep")
        self.refresh_ai_notice()
        self.show_koji_message("智能模式已关闭，普通模板日报仍然可用。")

    def refresh_records(self) -> None:
        self.records_list.clear()
        self.record_ids.clear()
        for row, record in enumerate(self.report_manager.records_for_date()):
            item = QListWidgetItem(format_record_line(record))
            item.setData(Qt.UserRole, record.id)
            self.records_list.addItem(item)
            self.record_ids[row] = record.id

    def current_record_id(self) -> str | None:
        item = self.records_list.currentItem()
        if item is not None:
            value = item.data(Qt.UserRole)
            return str(value) if value else None
        return self.record_ids.get(self.records_list.currentRow())

    def edit_record_item(self, item: QListWidgetItem) -> None:
        record_id = item.data(Qt.UserRole)
        if record_id:
            self.edit_record(str(record_id))

    def edit_record(self, record_id: str) -> None:
        record = self.report_manager.get_record(record_id)
        if record is None:
            QMessageBox.information(self, "Koji", "这条记录已经不存在了。")
            self.refresh_records()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("编辑记录")
        dialog.setStyleSheet(self.styleSheet())
        category = QComboBox(dialog)
        category.addItems(CATEGORIES)
        category.setCurrentText(record.category)
        content = QLineEdit(record.content, dialog)
        content.setMinimumHeight(34)
        save_button = QPushButton("保存修改", dialog)
        cancel_button = QPushButton("取消", dialog)
        save_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"时间：{record.time or '--:--'}"))
        layout.addWidget(category)
        layout.addWidget(content)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.report_manager.update_record(record_id, category.currentText(), content.text())
        except ValueError as exc:
            QMessageBox.information(self, "Koji", str(exc))
            return
        self.refresh_records()
        self.notify_state("success")

    def add_record(self) -> None:
        try:
            self.report_manager.add_record(self.category.currentText(), self.content.text())
        except ValueError as exc:
            QMessageBox.information(self, "Koji", str(exc))
            return
        self.content.clear()
        self.refresh_records()
        self.notify_state("collect")

    def delete_record(self) -> None:
        record_id = self.current_record_id()
        if not record_id:
            QMessageBox.information(self, "Koji", "请先选择一条记录。")
            return
        self.report_manager.delete_record(record_id)
        self.refresh_records()

    def copy_record(self) -> None:
        record_id = self.current_record_id()
        if not record_id:
            QMessageBox.information(self, "Koji", "请先选择一条记录。")
            return
        record = self.report_manager.get_record(record_id)
        if record is None:
            QMessageBox.information(self, "Koji", "这条记录已经不存在了。")
            self.refresh_records()
            return
        QGuiApplication.clipboard().setText(format_record_line(record))
        self.notify_state("happy")

    def clear_today(self) -> None:
        if not self.report_manager.records_for_date():
            QMessageBox.information(self, "Koji", "今天还没有记录可清空。")
            return
        reply = QMessageBox.question(self, "Koji", "确定要清空今日记录吗？这一步不能撤回。")
        if reply != QMessageBox.Yes:
            return
        self.report_manager.clear_date()
        self.refresh_records()
        self.report_text.clear()

    def generate_template(self) -> None:
        if not self.report_manager.records_for_date():
            self.report_text.setPlainText("素材不足：请先添加今日记录，Koji 再帮你整理日报。")
            self.notify_state("confused")
            return
        report = self.report_manager.render_template_report()
        self.report_text.setPlainText(report)
        self.notify_state("happy")

    def generate_ai(self) -> None:
        material = self.report_manager.ai_material_text()
        if not material.strip():
            self.notify_state("confused")
            self.show_koji_message("还没有日报素材，先记录一点今天做了什么吧。")
            return
        ok, check_message = self.ai_runtime.check_files()
        self.refresh_ai_notice()
        if not ok:
            self.notify_state("confused")
            self.show_koji_message(check_message)
            return
        self.notify_state("thinking")
        self.show_koji_message(STARTING_MESSAGE)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Koji，一个文案组日报整理桌宠。你帮助游戏公司文案策划把零散记录整理成体面、真实、简洁的中文日报。"
                    "不要编造没有提供的工作内容。不要写成客服腔，不要过度官话。默认输出结构：\n"
                    "一、今日完成\n二、进行中\n三、明日计划\n四、风险与待确认\n"
                    "如果素材不足，请明确提示“素材较少”，但仍基于已有素材整理一版可用日报。"
                ),
            },
            {"role": "user", "content": f"今日记录素材：\n{material}"},
        ]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, answer = self.ai_runtime.chat(messages, temperature=0.4, max_tokens=1000)
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_ai_notice()
        if ok:
            self.report_text.setPlainText(answer)
            self.notify_state("happy")
            self.show_koji_message("日报炼成完毕，去交差吧。")
            return
        self.notify_state("error")
        self.show_koji_message(f"AI 整理日报失败：{answer}\n普通模板日报仍然可用，原始记录不会丢失。")

    def copy_report(self) -> None:
        text = self.report_text.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "Koji", "还没有可复制的日报内容。")
            return
        QGuiApplication.clipboard().setText(text)
        self.notify_state("happy")
        QMessageBox.information(self, "Koji", "日报已复制。")

    def export_records(self, extension: str) -> None:
        records = self.report_manager.records_for_date()
        if not records:
            self.notify_state("confused")
            QMessageBox.information(self, "Koji", "今天还没有记录可导出。")
            return
        extension = "md" if extension == "md" else "txt"
        default_name = f"koji-records-{date.today().isoformat()}.{extension}"
        filter_text = "Markdown 文件 (*.md)" if extension == "md" else "文本文件 (*.txt)"
        path, _ = QFileDialog.getSaveFileName(self, "导出今日记录", default_name, filter_text)
        if not path:
            return
        lines = [f"# {date.today().isoformat()} 今日记录", ""] if extension == "md" else [f"{date.today().isoformat()} 今日记录", ""]
        lines.extend(format_record_line(record) for record in records)
        try:
            with open(path, "w", encoding="utf-8") as file:
                file.write("\n".join(lines))
        except OSError as exc:
            self.notify_state("error")
            QMessageBox.information(self, "Koji", f"导出失败：{exc}")
            return
        self.notify_state("success")
        QMessageBox.information(self, "Koji", "今日记录已导出。")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
        self.hide()


class DialogueBubble(QWidget):
    """Small auto-hiding speech bubble displayed beside the Koji pet."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "QLabel { color: #4b3324; background: rgba(255, 250, 238, 235); "
            "border: 1px solid rgba(188, 139, 74, 150); border-radius: 14px; "
            "padding: 10px 12px; font-size: 13px; }"
        )
        self.label.setMaximumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def show_message(self, message: str, anchor: QWidget, milliseconds: int = 3200) -> None:
        self.label.setText(message)
        self.adjustSize()
        self._move_near(anchor)
        self.show()
        self.raise_()
        self.hide_timer.start(milliseconds)

    def follow(self, anchor: QWidget) -> None:
        if self.isVisible():
            self._move_near(anchor)

    def _move_near(self, anchor: QWidget) -> None:
        anchor_rect = anchor.frameGeometry()
        x = anchor_rect.right() + 10
        y = anchor_rect.top() + 10
        screen = QGuiApplication.screenAt(anchor_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if x + self.width() > available.right():
                x = anchor_rect.left() - self.width() - 10
            if y + self.height() > available.bottom():
                y = available.bottom() - self.height() - 8
            x = max(available.left() + 8, x)
            y = max(available.top() + 8, y)
        self.move(x, y)


class KojiPet(QWidget):
    PET_SIZE = QSize(152, 152)
    VISUAL_SIZE = QSize(132, 132)
    BREATH_AMPLITUDE = 4
    RANDOM_IDLE_STATES = ("wave", "thinking", "happy", "sleep")
    RANDOM_IDLE_MIN_MS = 20_000
    RANDOM_IDLE_MAX_MS = 40_000

    def __init__(self) -> None:
        super().__init__()
        self.ai_runtime = AIRuntimeManager()
        self.report_manager = ReportManager()
        self.chat_manager = ChatManager(self.ai_runtime)
        self.report_panel: ReportPanel | None = None
        self.chat_dialog: ChatDialog | None = None
        self.drag_position: QPoint | None = None
        self.press_position: QPoint | None = None
        self.was_dragged = False
        self.current_state = "idle"
        self.animations_enabled = True
        self.is_dragging = False
        self.breath_offset = 0
        self.drag_offset = 0
        self.bounce_offset = 0
        self.bounce_scale = 1.0
        self.base_label_pos = QPoint(
            (self.PET_SIZE.width() - self.VISUAL_SIZE.width()) // 2,
            (self.PET_SIZE.height() - self.VISUAL_SIZE.height()) // 2,
        )
        self.bubble = DialogueBubble()
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(lambda: self.set_state("idle"))

        self.breath_animation = QVariantAnimation(self)
        self.breath_animation.setStartValue(0.0)
        self.breath_animation.setEndValue(1.0)
        self.breath_animation.setDuration(2400)
        self.breath_animation.setLoopCount(-1)
        self.breath_animation.valueChanged.connect(self.update_breath_frame)

        self.bounce_animation = QVariantAnimation(self)
        self.bounce_animation.setStartValue(0.0)
        self.bounce_animation.setEndValue(1.0)
        self.bounce_animation.setDuration(320)
        self.bounce_animation.valueChanged.connect(self.update_bounce_frame)
        self.bounce_animation.finished.connect(self.finish_bounce)

        self.drag_wobble_timer = QTimer(self)
        self.drag_wobble_timer.setInterval(120)
        self.drag_wobble_timer.timeout.connect(self.update_drag_wobble)

        self.random_idle_timer = QTimer(self)
        self.random_idle_timer.setSingleShot(True)
        self.random_idle_timer.timeout.connect(self.trigger_random_idle_activity)

        self.setWindowTitle("Koji Report Pet Next")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.label = QLabel(self)
        self.visual = KojiVisual(self.label, self.VISUAL_SIZE)
        self.setFixedSize(self.PET_SIZE)
        self.apply_visual_transform()
        self.set_state("idle")
        self.start_idle_motion()
        self.schedule_random_idle_activity()

    def mark_user_interaction(self) -> None:
        self.schedule_random_idle_activity()

    def set_state(self, state: str, show_dialogue: bool = True) -> None:
        if state not in STATES:
            state = "idle"
        previous_state = self.current_state
        self.current_state = state
        self.visual.set_state(state)
        self.apply_visual_transform()
        if show_dialogue:
            dialogue = random_dialogue(state)
            self.setToolTip(dialogue)
            self.bubble.show_message(dialogue, self)
        self.sync_animation_state()
        if state != previous_state and state in {"collect", "success", "happy", "confused", "error", "writing"}:
            self.play_state_bounce()

    def temporary_state(self, state: str, milliseconds: int = 1800) -> None:
        self.mark_user_interaction()
        self.idle_timer.stop()
        self.set_state(state)
        if state != "idle":
            self.idle_timer.start(milliseconds)

    def start_idle_motion(self) -> None:
        if self.animations_enabled and self.current_state == "idle" and not self.is_dragging:
            if self.breath_animation.state() != QAbstractAnimation.State.Running:
                self.breath_animation.start()
        else:
            self.stop_idle_motion(reset=self.current_state != "idle" or self.is_dragging or not self.animations_enabled)

    def stop_idle_motion(self, reset: bool = True) -> None:
        if self.breath_animation.state() != QAbstractAnimation.State.Stopped:
            self.breath_animation.stop()
        if reset:
            self.breath_offset = 0
            self.apply_visual_transform()

    def sync_animation_state(self) -> None:
        self.start_idle_motion()
        if self.animations_enabled and self.current_state == "idle" and not self.is_dragging:
            self.schedule_random_idle_activity()
        else:
            self.random_idle_timer.stop()

    def update_breath_frame(self, value: object) -> None:
        if not self.animations_enabled or self.current_state != "idle" or self.is_dragging:
            return
        progress = float(value)
        self.breath_offset = round(math.sin(progress * math.tau) * self.BREATH_AMPLITUDE)
        self.apply_visual_transform()

    def play_state_bounce(self) -> None:
        if not self.animations_enabled:
            return
        self.bounce_animation.stop()
        self.bounce_animation.start()

    def update_bounce_frame(self, value: object) -> None:
        progress = float(value)
        impulse = math.sin(progress * math.pi)
        self.bounce_scale = 1.0 + 0.06 * impulse
        self.bounce_offset = round(-7 * impulse)
        self.apply_visual_transform()

    def finish_bounce(self) -> None:
        self.bounce_scale = 1.0
        self.bounce_offset = 0
        self.apply_visual_transform()

    def update_drag_wobble(self) -> None:
        if not self.animations_enabled or not self.is_dragging:
            self.drag_offset = 0
        else:
            self.drag_offset = -self.drag_offset if self.drag_offset else 3
        self.apply_visual_transform()

    def apply_visual_transform(self) -> None:
        width = max(1, round(self.VISUAL_SIZE.width() * self.bounce_scale))
        height = max(1, round(self.VISUAL_SIZE.height() * self.bounce_scale))
        x = self.base_label_pos.x() + self.drag_offset - (width - self.VISUAL_SIZE.width()) // 2
        y = self.base_label_pos.y() + self.breath_offset + self.bounce_offset - (height - self.VISUAL_SIZE.height()) // 2
        self.label.setGeometry(x, y, width, height)

    def schedule_random_idle_activity(self) -> None:
        self.random_idle_timer.stop()
        if not self.animations_enabled or self.current_state != "idle" or self.is_dragging:
            return
        self.random_idle_timer.start(random.randint(self.RANDOM_IDLE_MIN_MS, self.RANDOM_IDLE_MAX_MS))

    def report_panel_is_busy(self) -> bool:
        if self.chat_dialog is not None and self.chat_dialog.isVisible():
            return True
        if self.report_panel is None or not self.report_panel.isVisible():
            return False
        return self.report_panel.content.hasFocus() or self.report_panel.report_text.hasFocus()

    def trigger_random_idle_activity(self) -> None:
        if not self.animations_enabled or self.current_state != "idle" or self.is_dragging or self.report_panel_is_busy():
            self.schedule_random_idle_activity()
            return
        state = random.choice(self.RANDOM_IDLE_STATES)
        duration = random.randint(2_000, 4_000)
        self.temporary_state(state, duration)

    def toggle_animations(self) -> None:
        self.animations_enabled = not self.animations_enabled
        if self.animations_enabled:
            self.sync_animation_state()
        else:
            self.breath_animation.stop()
            self.bounce_animation.stop()
            self.drag_wobble_timer.stop()
            self.random_idle_timer.stop()
            self.breath_offset = 0
            self.drag_offset = 0
            self.bounce_offset = 0
            self.bounce_scale = 1.0
            self.apply_visual_transform()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.mark_user_interaction()
            self.press_position = event.globalPosition().toPoint()
            self.drag_position = self.press_position - self.frameGeometry().topLeft()
            self.was_dragged = False
            self.is_dragging = True
            self.idle_timer.stop()
            self.stop_idle_motion()
            self.set_state("drag", show_dialogue=False)
            if self.animations_enabled:
                self.drag_wobble_timer.start()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.LeftButton and self.drag_position is not None:
            if self.press_position is not None and (event.globalPosition().toPoint() - self.press_position).manhattanLength() > 8:
                self.was_dragged = True
            self.move(event.globalPosition().toPoint() - self.drag_position)
            self.bubble.follow(self)
            self.position_report_panel()
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.mark_user_interaction()
            did_drag = self.was_dragged
            should_open = not did_drag
            self.drag_position = None
            self.press_position = None
            self.was_dragged = False
            self.is_dragging = False
            self.drag_wobble_timer.stop()
            self.drag_offset = 0
            self.apply_visual_transform()
            self.set_state("idle", show_dialogue=not did_drag)
            if did_drag:
                self.bubble.show_message(random_dialogue("drag"), self)
            if should_open:
                self.open_report_panel()
        super().mouseReleaseEvent(event)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        self.bubble.follow(self)
        self.position_report_panel()
        super().moveEvent(event)

    def show_context_menu(self, position: QPoint) -> None:
        self.mark_user_interaction()
        menu = QMenu(self)
        open_report = QAction("打开日报面板", self)
        open_report.triggered.connect(self.open_report_panel)
        chat = QAction("和 Koji 聊两句", self)
        chat.triggered.connect(self.open_chat_dialog)
        ai_report = QAction("AI 整理日报", self)
        ai_report.triggered.connect(self.ai_report_from_menu)
        animation_action = QAction("关闭动画" if self.animations_enabled else "开启动画", self)
        animation_action.triggered.connect(self.toggle_animations)

        menu.addAction(open_report)
        menu.addAction(chat)
        menu.addAction(ai_report)
        menu.addSeparator()
        menu.addAction(animation_action)

        state_menu = menu.addMenu("状态测试")
        for state in STATES:
            state_action = QAction(state, self)
            state_action.triggered.connect(lambda checked=False, selected_state=state: self.temporary_state(selected_state, 2600))
            state_menu.addAction(state_action)

        menu.addSeparator()
        quit_action = QAction("退出", self)
        app = QApplication.instance()
        if app is not None:
            quit_action.triggered.connect(app.quit)
        menu.addAction(quit_action)
        menu.exec(self.mapToGlobal(position))

    def open_report_panel(self) -> None:
        self.temporary_state("wave")
        if self.report_panel is None:
            self.report_panel = ReportPanel(self.report_manager, self.ai_runtime, self.temporary_state, self)
        self.report_panel.refresh_ai_notice()
        self.report_panel.refresh_records()
        self.report_panel.show()
        self.position_report_panel(force=True)
        self.report_panel.raise_()
        self.report_panel.activateWindow()

    def open_chat_dialog(self) -> None:
        self.temporary_state("happy")
        if self.chat_dialog is None:
            self.chat_dialog = ChatDialog(self.chat_manager, self)
        self.chat_dialog.refresh()
        self.chat_dialog.show()
        self.position_chat_dialog()
        self.chat_dialog.raise_()
        self.chat_dialog.activateWindow()


    def position_report_panel(self, force: bool = False) -> None:
        if self.report_panel is None or not self.report_panel.isVisible():
            return
        pet_rect = self.frameGeometry()
        panel_size = self.report_panel.frameGeometry().size() if force else self.report_panel.size()
        screen = QGuiApplication.screenAt(pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        gap = 16
        right_x = pet_rect.right() + gap
        left_x = pet_rect.left() - panel_size.width() - gap
        if right_x + panel_size.width() <= available.right():
            x = right_x
        elif left_x >= available.left():
            x = left_x
        else:
            # Last-resort clamp still keeps Koji visible by preferring the less-overlapping side.
            x = max(available.left(), min(right_x, available.right() - panel_size.width()))
        y = pet_rect.top()
        if y + panel_size.height() > available.bottom():
            y = available.bottom() - panel_size.height()
        y = max(available.top(), y)
        self.report_panel.move(x, y)

    def position_chat_dialog(self) -> None:
        if self.chat_dialog is None or not self.chat_dialog.isVisible():
            return
        pet_rect = self.frameGeometry()
        screen = QGuiApplication.screenAt(pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        gap = 16
        x = pet_rect.right() + gap
        if x + self.chat_dialog.width() > available.right():
            x = pet_rect.left() - self.chat_dialog.width() - gap
        y = max(available.top(), min(pet_rect.top(), available.bottom() - self.chat_dialog.height()))
        self.chat_dialog.move(max(available.left(), x), y)

    def ai_report_from_menu(self) -> None:
        self.open_report_panel()
        if self.report_panel is not None:
            self.report_panel.generate_ai()

    def shutdown(self) -> None:
        for timer in (self.idle_timer, self.drag_wobble_timer, self.random_idle_timer):
            timer.stop()
        self.breath_animation.stop()
        self.bounce_animation.stop()
        self.bubble.close()
        self.ai_runtime.shutdown()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pet = KojiPet()
    app.aboutToQuit.connect(pet.shutdown)
    pet.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
