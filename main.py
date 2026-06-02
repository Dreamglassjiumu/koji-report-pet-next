"""Koji Report Pet Next desktop pet application."""
from __future__ import annotations

import os
import sys
from datetime import date
from typing import Callable, Dict

if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai_runtime_manager import AIRuntimeManager, AI_UNAVAILABLE_MESSAGE
from chat_manager import ChatManager
from koji_state import STATES, KojiVisual, random_dialogue
from report_manager import CATEGORIES, ReportManager


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


class ChatDialog(QDialog):
    def __init__(self, chat_manager: ChatManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chat_manager = chat_manager
        self.setWindowTitle("和 Koji 聊两句")
        self.resize(480, 420)

        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        self.input = QLineEdit()
        self.input.setPlaceholderText("和 Koji 说点什么……")
        send_button = QPushButton("发送")
        send_button.clicked.connect(self.send_message)
        self.input.returnPressed.connect(self.send_message)

        bottom = QHBoxLayout()
        bottom.addWidget(self.input, 1)
        bottom.addWidget(send_button)

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
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.chat_manager.chat(text)
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()


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
        self.resize(780, 680)
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)

        self.title_label = QLabel("Koji 日报面板")
        self.title_label.setObjectName("panelTitle")
        self.subtitle_label = QLabel("Koji 会帮你把零散工作痕迹整理成日报。")
        self.subtitle_label.setObjectName("panelSubtitle")
        self.ai_notice = QLabel("")
        self.ai_notice.setObjectName("aiNotice")
        self.ai_notice.setWordWrap(True)
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
        delete_button = QPushButton("删除记录")
        delete_button.clicked.connect(self.delete_record)
        clear_button = QPushButton("清空今日记录")
        clear_button.clicked.connect(self.clear_today)
        template_button = QPushButton("普通模板整理日报")
        template_button.clicked.connect(self.generate_template)
        ai_button = QPushButton("AI 整理日报")
        ai_button.clicked.connect(self.generate_ai)
        copy_button = QPushButton("复制日报")
        copy_button.clicked.connect(self.copy_report)

        button_row = QHBoxLayout()
        for button in (delete_button, clear_button, template_button, ai_button, copy_button):
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

    def refresh_ai_notice(self) -> None:
        ok, _ = self.ai_runtime.check_files()
        self.ai_notice.setVisible(not ok)
        self.ai_notice.setText(AI_UNAVAILABLE_MESSAGE if not ok else "")

    def refresh_records(self) -> None:
        self.records_list.clear()
        self.record_ids.clear()
        for row, record in enumerate(self.report_manager.records_for_date()):
            self.records_list.addItem(f"[{record.category}] {record.content}")
            self.record_ids[row] = record.id

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
        row = self.records_list.currentRow()
        record_id = self.record_ids.get(row)
        if not record_id:
            QMessageBox.information(self, "Koji", "请先选择一条记录。")
            return
        self.report_manager.delete_record(record_id)
        self.refresh_records()

    def clear_today(self) -> None:
        self.report_manager.clear_date()
        self.refresh_records()
        self.report_text.clear()

    def generate_template(self) -> None:
        report = self.report_manager.render_template_report()
        self.report_text.setPlainText(report)
        self.notify_state("happy" if self.report_manager.records_for_date() else "confused")

    def generate_ai(self) -> None:
        material = self.report_manager.ai_material_text()
        if not material.strip():
            self.report_text.setPlainText("素材不足：请先添加今日记录。")
            self.notify_state("confused")
            return
        self.notify_state("writing")
        ok, check_message = self.ai_runtime.check_files()
        self.refresh_ai_notice()
        if not ok:
            self.report_text.setPlainText(AI_UNAVAILABLE_MESSAGE)
            self.notify_state("confused")
            return
        messages = [
            {"role": "system", "content": "你是专业中文日报助手。请根据素材整理一份简洁、清晰、可编辑的工作日报。"},
            {"role": "user", "content": f"今天的素材如下：\n{material}\n\n请输出日报，包含今日完成和明日计划。"},
        ]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, answer = self.ai_runtime.chat(messages, temperature=0.4, max_tokens=900)
        finally:
            QApplication.restoreOverrideCursor()
        self.report_text.setPlainText(answer if ok else answer)
        self.notify_state("happy" if ok else "error")

    def copy_report(self) -> None:
        text = self.report_text.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "Koji", "还没有可复制的日报内容。")
            return
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "Koji", "日报已复制。")


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
        self.bubble = DialogueBubble()
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(lambda: self.set_state("idle"))

        self.setWindowTitle("Koji Report Pet Next")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.label = QLabel(self)
        self.visual = KojiVisual(self.label, QSize(132, 132))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        self.set_state("idle")
        self.resize(132, 132)

    def set_state(self, state: str) -> None:
        if state not in STATES:
            state = "idle"
        self.current_state = state
        self.visual.set_state(state)
        dialogue = random_dialogue(state)
        self.setToolTip(dialogue)
        self.bubble.show_message(dialogue, self)

    def temporary_state(self, state: str, milliseconds: int = 1800) -> None:
        self.idle_timer.stop()
        self.set_state(state)
        if state != "idle":
            self.idle_timer.start(milliseconds)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.press_position = event.globalPosition().toPoint()
            self.drag_position = self.press_position - self.frameGeometry().topLeft()
            self.was_dragged = False
            self.idle_timer.stop()
            self.set_state("drag")
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.LeftButton and self.drag_position is not None:
            if self.press_position is not None and (event.globalPosition().toPoint() - self.press_position).manhattanLength() > 8:
                self.was_dragged = True
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            should_open = not self.was_dragged
            self.drag_position = None
            self.press_position = None
            self.was_dragged = False
            self.set_state("idle")
            if should_open:
                self.open_report_panel()
        super().mouseReleaseEvent(event)

    def show_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        open_report = QAction("打开日报面板", self)
        open_report.triggered.connect(self.open_report_panel)
        chat = QAction("和 Koji 聊两句", self)
        chat.triggered.connect(self.open_chat_dialog)
        ai_report = QAction("AI 整理日报", self)
        ai_report.triggered.connect(self.ai_report_from_menu)

        menu.addAction(open_report)
        menu.addAction(chat)
        menu.addAction(ai_report)

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
        self.report_panel.raise_()
        self.report_panel.activateWindow()

    def open_chat_dialog(self) -> None:
        self.temporary_state("happy")
        if self.chat_dialog is None:
            self.chat_dialog = ChatDialog(self.chat_manager, self)
        self.chat_dialog.refresh()
        self.chat_dialog.show()
        self.chat_dialog.raise_()
        self.chat_dialog.activateWindow()

    def ai_report_from_menu(self) -> None:
        self.open_report_panel()
        if self.report_panel is not None:
            self.report_panel.generate_ai()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.bubble.close()
        self.ai_runtime.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pet = KojiPet()
    app.aboutToQuit.connect(pet.ai_runtime.shutdown)
    pet.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
