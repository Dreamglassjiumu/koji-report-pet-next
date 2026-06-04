"""Koji Report Pet Next desktop pet application."""
from __future__ import annotations

import math
import os
import random
import sys
import zipfile
from datetime import date
from typing import Callable, Dict

if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, QSize, Qt, QThread, QTime, QTimer, QUrl, Signal, QVariantAnimation
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ai_runtime_manager import AIRuntimeManager, AI_UNAVAILABLE_MESSAGE, READY_MESSAGE, STARTING_MESSAGE, STATUS_LABELS
from category_manager import CategoryManager
from collection_manager import CollectionManager, UnlockResult
from character_manager import CharacterManager
from chat_manager import ChatManager
from koji_state import STATES, KojiVisual, normalize_state, random_dialogue
from report_manager import ReportManager, clean_ai_report_text, format_record_line
from relationship_manager import (
    EXP_CHARACTER_IMPORT,
    EXP_CHAT_SUCCESS,
    EXP_DAILY_CHECK_IN,
    EXP_POMODORO_DONE,
    EXP_REPORT_SUCCESS,
    LEVEL_THRESHOLDS,
    RelationshipChange,
    RelationshipManager,
)
from hourly_chime_manager import HourlyChimeManager
from notes_manager import Note, NotesManager
from pomodoro_manager import PHASE_FOCUS, PomodoroManager
from settings_manager import SettingsManager
from tag_manager import TagManager


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

QFrame#moduleCard, QFrame#characterCard, QFrame#workspaceCard {
    background: rgba(255, 250, 238, 238);
    border: 1px solid #ead8bf;
    border-radius: 18px;
}
QFrame#moduleCard:hover, QFrame#characterCard:hover, QFrame#workspaceCard:hover {
    border-color: #e7c28b;
}
QLabel#sectionTitle {
    color: #5c3b25;
    font-size: 16px;
    font-weight: 800;
}
QLabel#miniMeta {
    color: #8a6a52;
    font-size: 12px;
}
QProgressBar {
    color: #5c3b25;
    background: #f6e7d1;
    border: 1px solid #e5c79f;
    border-radius: 8px;
    height: 14px;
    text-align: center;
    font-weight: 700;
}
QProgressBar::chunk {
    background: #f0b35c;
    border-radius: 7px;
}
QToolButton#accordionHeader {
    color: #4b3324;
    background: #fff0cf;
    border: 1px solid #ead8bf;
    border-radius: 12px;
    padding: 9px 10px;
    font-size: 14px;
    font-weight: 800;
    text-align: left;
}
QToolButton#accordionHeader:hover {
    background: #ffe6b8;
}
QPushButton#toolbarButton {
    padding: 8px 12px;
}
"""


CHAT_UNAVAILABLE_REPLY = "Koji 的本地脑子还没装好，现在只能装可爱。等 model.gguf 放进去后，我再认真陪你聊。"


class FunctionWorker(QObject):
    finished = Signal(object)

    def __init__(self, function: Callable[[], object]) -> None:
        super().__init__()
        self.function = function

    def run(self) -> None:
        try:
            self.finished.emit(self.function())
        except Exception as exc:  # noqa: BLE001 - show friendly UI errors instead of crashing Qt.
            self.finished.emit((False, f"Koji 执行任务时打结了：{exc}"))


def run_in_qthread(owner: QObject, function: Callable[[], object], callback: Callable[[object], None]) -> QThread:
    thread = QThread(owner)
    worker = FunctionWorker(function)
    thread.worker = worker  # type: ignore[attr-defined]
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(callback)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread


class ChatInput(QPlainTextEdit):
    """Multi-line chat input: Enter sends, Shift+Enter inserts a line break."""

    def __init__(self, send_callback: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.send_callback = send_callback
        self.setFixedHeight(72)
        self.setPlaceholderText("和 Koji 说点什么……Enter 发送，Shift+Enter 换行")

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.send_callback()
            event.accept()
            return
        super().keyPressEvent(event)


class ChatMessageBubble(QWidget):
    def __init__(self, role: str, content: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        is_user = role == "user"
        name = "你" if is_user else "Koji"

        name_label = QLabel(name)
        name_label.setStyleSheet("QLabel { color: #8a6a52; font-size: 12px; font-weight: 700; }")
        bubble = QLabel(content)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble.setMaximumWidth(330)
        bubble.setStyleSheet(
            "QLabel { color: #3e2b20; border-radius: 14px; padding: 9px 11px; "
            + ("background: #e8f0f2; border: 1px solid #c7dadd;" if is_user else "background: #fff0cf; border: 1px solid #e9c98f;")
            + " }"
        )

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(3)
        stack.addWidget(name_label, 0, Qt.AlignRight if is_user else Qt.AlignLeft)
        stack.addWidget(bubble, 0, Qt.AlignRight if is_user else Qt.AlignLeft)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        if is_user:
            row.addStretch(1)
            row.addLayout(stack)
        else:
            row.addLayout(stack)
            row.addStretch(1)


class ChatDialog(QDialog):
    def __init__(
        self,
        chat_manager: ChatManager,
        success_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.chat_manager = chat_manager
        self.success_callback = success_callback
        self.setWindowTitle("和 Koji 聊两句")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(500, 520)

        title = QLabel("和 Koji 聊两句")
        title.setObjectName("panelTitle")
        hint = QLabel("Koji 可以闲聊，也可以帮你把乱七八糟的工作想法捋顺。")
        hint.setObjectName("panelSubtitle")
        hint.setWordWrap(True)

        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)

        self.history_view = QScrollArea()
        self.history_view.setWidgetResizable(True)
        self.history_view.setWidget(self.messages_widget)
        self.history_view.setObjectName("chatScroll")
        self.history_view.setStyleSheet(
            "QScrollArea#chatScroll { background: rgba(255, 250, 238, 210); border: 1px solid #ead8bf; border-radius: 14px; }"
            "QScrollArea#chatScroll QWidget { background: transparent; }"
        )
        self.typing_label = QLabel("Koji 正在憋话……")
        self.typing_label.setObjectName("panelSubtitle")
        self.typing_label.setVisible(False)

        self.input = ChatInput(self.send_message)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.send_message)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_message)
        clear_button = QPushButton("清空历史")
        clear_button.setStyleSheet("QPushButton { color: #7a5b45; background: #fff4dc; border-color: #ead8bf; font-weight: 500; }")
        clear_button.clicked.connect(self.clear_history)

        bottom = QHBoxLayout()
        bottom.addWidget(self.input, 1)
        bottom.addWidget(self.send_button)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(clear_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.history_view, 1)
        layout.addWidget(self.typing_label)
        layout.addLayout(bottom)
        self.refresh()

    def refresh(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self.chat_manager.history:
            self.messages_layout.insertWidget(0, ChatMessageBubble("assistant", "可以闲聊，也可以把工作脑内垃圾倒给我。我会努力不嘲笑你，たぶん。"))
        else:
            for item in self.chat_manager.history[-30:]:
                role = item.get("role", "assistant")
                content = str(item.get("content", "")).strip()
                if role in {"user", "assistant"} and content:
                    self.messages_layout.insertWidget(self.messages_layout.count() - 1, ChatMessageBubble(role, content))
        QTimer.singleShot(0, self.scroll_to_bottom)

    def scroll_to_bottom(self) -> None:
        bar = self.history_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def send_message(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or not self.send_button.isEnabled():
            return
        self.input.clear()
        self.send_button.setEnabled(False)
        self.send_button.setText("Koji 正在憋话……")
        self.typing_label.setVisible(True)
        self.cancel_button.setEnabled(True)
        parent = self.parent()
        if parent is not None and hasattr(parent, "temporary_state"):
            parent.temporary_state("thinking", 900)  # type: ignore[attr-defined]
            QTimer.singleShot(900, lambda: parent.temporary_state("typing", 60_000) if not self.send_button.isEnabled() else None)  # type: ignore[attr-defined]
        self.chat_thread = run_in_qthread(
            self,
            lambda: self.chat_manager.chat(text, unavailable_reply=CHAT_UNAVAILABLE_REPLY),
            self.finish_message,
        )

    def finish_message(self, result: object) -> None:
        ok = False
        if isinstance(result, tuple) and result:
            ok = bool(result[0])
        self.send_button.setEnabled(True)
        self.send_button.setText("发送")
        self.cancel_button.setEnabled(False)
        self.typing_label.setVisible(False)
        parent = self.parent()
        if parent is not None and hasattr(parent, "temporary_state"):
            parent.temporary_state("success" if ok else "error", 3000 if ok else 5000)  # type: ignore[attr-defined]
        if ok and self.success_callback is not None:
            self.success_callback()
        self.refresh()

    def cancel_message(self) -> None:
        self.chat_manager.ai_runtime.cancel_generation()
        self.send_button.setEnabled(True)
        self.send_button.setText("发送")
        self.cancel_button.setEnabled(False)
        self.typing_label.setVisible(False)
        parent = self.parent()
        if parent is not None and hasattr(parent, "temporary_state"):
            parent.temporary_state("error", 5000)  # type: ignore[attr-defined]

    def clear_history(self) -> None:
        self.chat_manager.clear()
        self.refresh()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
        self.hide()


class CategoryManageDialog(QDialog):
    def __init__(self, category_manager: CategoryManager, report_manager: ReportManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.category_manager = category_manager
        self.report_manager = report_manager
        self.setWindowTitle("分类管理")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(430, 420)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.rename_selected())
        add_button = QPushButton("新增分类")
        add_button.clicked.connect(self.add_category)
        rename_button = QPushButton("重命名")
        rename_button.clicked.connect(self.rename_selected)
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self.delete_selected)
        restore_button = QPushButton("恢复默认")
        restore_button.clicked.connect(self.restore_defaults)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        row = QHBoxLayout()
        for button in (add_button, rename_button, delete_button, restore_button, close_button):
            row.addWidget(button)
        layout = QVBoxLayout(self)
        tip = QLabel("日报分类：双击可重命名。删除分类不会删除已有记录；已记录内容会保留原分类文本。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list_widget.clear()
        for category in self.category_manager.all_categories():
            item = QListWidgetItem(category)
            item.setData(Qt.UserRole, category)
            self.list_widget.addItem(item)

    def selected_category(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def add_category(self) -> None:
        name, ok = QInputDialog.getText(self, "新增分类", "分类名称：")
        if not ok:
            return
        try:
            self.category_manager.add_category(name)
        except ValueError as exc:
            QMessageBox.information(self, "Koji", str(exc))
        self.refresh()

    def rename_selected(self) -> None:
        old_name = self.selected_category()
        if not old_name:
            return
        name, ok = QInputDialog.getText(self, "重命名分类", "分类名称：", text=old_name)
        if not ok:
            return
        try:
            old_cleaned, new_cleaned = self.category_manager.rename_category(old_name, name)
            if self.report_manager is not None:
                self.report_manager.rename_category_in_records(old_cleaned, new_cleaned)
        except ValueError as exc:
            QMessageBox.information(self, "Koji", str(exc))
        self.refresh()

    def delete_selected(self) -> None:
        category = self.selected_category()
        if not category:
            return
        if QMessageBox.question(self, "Koji", f"确定删除分类「{category}」吗？已有记录不会被删除，会保留原分类文本。") != QMessageBox.Yes:
            return
        try:
            self.category_manager.delete_category(category)
        except ValueError as exc:
            QMessageBox.information(self, "Koji", str(exc))
        self.refresh()

    def restore_defaults(self) -> None:
        if QMessageBox.question(self, "Koji", "确定恢复默认分类吗？自定义分类会被替换，但已有记录不会被删除。") != QMessageBox.Yes:
            return
        self.category_manager.restore_defaults()
        self.refresh()




class CollapsibleSection(QWidget):
    """Small accordion section used by the workspace side panel."""

    def __init__(self, title: str, content: QWidget, expanded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.content = content
        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("accordionHeader")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.clicked.connect(self.set_expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setText(("▼ " if expanded else "▶ ") + self.title)
        self.content.setVisible(expanded)


class CharacterCard(QFrame):
    """Always-visible companion identity and relationship summary."""

    def __init__(self, relationship_manager: RelationshipManager, collection_manager: CollectionManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.relationship_manager = relationship_manager
        self.collection_manager = collection_manager
        self.setObjectName("characterCard")

        self.avatar = QLabel("Koji")
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setFixedSize(116, 116)
        self.avatar.setStyleSheet("QLabel { background: #fff0cf; border: 1px solid #ead0a0; border-radius: 58px; color: #8a5a00; font-weight: 900; }")
        self.name_label = QLabel("Koji")
        self.name_label.setObjectName("panelTitle")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.level_label = QLabel("Lv1 陌生")
        self.level_label.setStyleSheet("QLabel { color: #5c3b25; font-size: 18px; font-weight: 900; }")
        self.level_label.setAlignment(Qt.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.exp_label = QLabel("0 / 50")
        self.exp_label.setObjectName("miniMeta")
        self.exp_label.setAlignment(Qt.AlignCenter)
        self.collection_label = QLabel("收藏：0 / 0")
        self.collection_label.setObjectName("miniMeta")
        self.collection_label.setAlignment(Qt.AlignCenter)
        self.tip_label = QLabel("下一次日报、聊天或番茄钟都会让信任慢慢增长。")
        self.tip_label.setObjectName("panelSubtitle")
        self.tip_label.setWordWrap(True)
        self.tip_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self.avatar, 0, Qt.AlignHCenter)
        layout.addWidget(self.name_label)
        layout.addWidget(self.level_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.exp_label)
        layout.addWidget(self.collection_label)
        layout.addWidget(self.tip_label)
        layout.addStretch(1)

    def refresh(self, character) -> None:
        character_id = getattr(character, "id", "koji")
        character_name = getattr(character, "name", "Koji")
        self.name_label.setText(character_name)
        self.avatar.setText(character_name[:8])
        asset_path = character.state_asset("idle") if character is not None else None
        if asset_path is not None:
            pixmap = QPixmap(str(asset_path))
            if not pixmap.isNull():
                self.avatar.setPixmap(pixmap.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.avatar.setPixmap(QPixmap())
        else:
            self.avatar.setPixmap(QPixmap())
        self.level_label.setText(self.relationship_manager.level_label(character_id))
        level, exp = self.relationship_manager.get(character_id)
        if level >= 5:
            self.progress.setValue(100)
            self.exp_label.setText("MAX")
            self.tip_label.setText("已经是最可靠的工作搭档了。")
        else:
            threshold = LEVEL_THRESHOLDS[level]
            self.progress.setValue(int(exp / threshold * 100) if threshold else 0)
            self.exp_label.setText(f"{exp} / {threshold}")
            remaining = max(0, threshold - exp)
            self.tip_label.setText(f"距离下一等级还差 {remaining} 经验。")
        total = len(self.collection_manager.all_collectibles())
        self.collection_label.setText(f"收藏：{len(self.collection_manager.unlocked_ids())} / {total}")


class CollectionCabinetWidget(QFrame):
    """Inline collection cabinet for the workspace function center."""

    def __init__(self, collection_manager: CollectionManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.collection_manager = collection_manager
        self.setObjectName("moduleCard")
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(lambda _current, _previous: self.refresh_detail())
        self.name_label = QLabel("？？？")
        self.name_label.setObjectName("sectionTitle")
        self.icon_label = QLabel("图标：？？？")
        self.icon_label.setObjectName("miniMeta")
        self.description_label = QLabel("选择收藏品查看详情。")
        self.description_label.setObjectName("panelSubtitle")
        self.description_label.setWordWrap(True)

        detail = QVBoxLayout()
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(6)
        detail.addWidget(self.name_label)
        detail.addWidget(self.icon_label)
        detail.addWidget(self.description_label)
        detail.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("已获得收藏品会显示真实信息，未获得保持神秘。"))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(detail)
        self.refresh()

    def refresh(self) -> None:
        current_id = self.list_widget.currentItem().data(Qt.UserRole) if self.list_widget.currentItem() else None
        self.list_widget.clear()
        selected_row = 0
        for row, collectible in enumerate(self.collection_manager.all_collectibles()):
            unlocked = self.collection_manager.is_unlocked(collectible.id)
            label = f"{collectible.icon} {collectible.name}" if unlocked and collectible.icon else collectible.name if unlocked else "？？？"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, collectible.id)
            self.list_widget.addItem(item)
            if collectible.id == current_id:
                selected_row = row
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(selected_row)
        self.refresh_detail()

    def refresh_detail(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            self.name_label.setText("？？？")
            self.icon_label.setText("图标：？？？")
            self.description_label.setText("暂无收藏品。")
            return
        collectible_id = str(item.data(Qt.UserRole) or "")
        collectible = self.collection_manager.load_collectible(collectible_id)
        if collectible is None or not self.collection_manager.is_unlocked(collectible_id):
            self.name_label.setText("？？？")
            self.icon_label.setText("图标：？？？")
            self.description_label.setText("尚未获得。")
            return
        self.name_label.setText(collectible.name)
        self.icon_label.setText(f"图标：{collectible.icon or '无'}")
        self.description_label.setText(collectible.description)


class ReportPanel(QDialog):
    def __init__(
        self,
        report_manager: ReportManager,
        ai_runtime: AIRuntimeManager,
        category_manager: CategoryManager,
        tag_manager: TagManager,
        notes_manager: NotesManager,
        relationship_manager: RelationshipManager,
        collection_manager: CollectionManager,
        state_callback: Callable[[str], None] | None = None,
        report_success_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.report_manager = report_manager
        self.ai_runtime = ai_runtime
        self.category_manager = category_manager
        self.tag_manager = tag_manager
        self.notes_manager = notes_manager
        self.relationship_manager = relationship_manager
        self.collection_manager = collection_manager
        self.state_callback = state_callback
        self.report_success_callback = report_success_callback
        self.record_ids: Dict[int, str] = {}
        self.setWindowTitle("Koji 日报面板")
        self.resize(1180, 780)
        self.setMinimumSize(980, 640)
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)

        self.title_label = QLabel("Koji 日报面板")
        self.title_label.setObjectName("panelTitle")
        self.subtitle_label = QLabel(f"当前角色：{self.current_character_name()} · 日期：{date.today().isoformat()}")
        self.subtitle_label.setObjectName("panelSubtitle")
        self.ai_notice = QLabel("")
        self.ai_notice.setObjectName("aiNotice")
        self.ai_notice.setWordWrap(True)

        self.ai_status_label = QLabel("")
        self.ai_status_label.setObjectName("panelSubtitle")
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self.update_model_description)
        self.model_description = QLabel("")
        self.model_description.setObjectName("panelSubtitle")
        self.model_description.setWordWrap(True)
        self.switch_model_button = QPushButton("切换模型")
        self.switch_model_button.clicked.connect(self.switch_model)
        open_models_button = QPushButton("模型文件夹")
        open_models_button.clicked.connect(self.open_models_folder)
        refresh_models_button = QPushButton("刷新模型")
        refresh_models_button.clicked.connect(self.refresh_model_list)
        restart_ai_button = QPushButton("重启 Koji 脑子")
        restart_ai_button.clicked.connect(self.restart_ai)
        close_ai_button = QPushButton("关闭智能模式")
        close_ai_button.clicked.connect(self.close_ai)
        check_ai_button = QPushButton("检查 AI 状态")
        check_ai_button.clicked.connect(self.check_ai_status)
        self.ai_detail = QLabel("")
        self.ai_detail.setWordWrap(True)
        self.ai_detail.setVisible(False)
        detail_button = QPushButton("高级信息")
        detail_button.clicked.connect(lambda: self.ai_detail.setVisible(not self.ai_detail.isVisible()))

        self.character_card = CharacterCard(self.relationship_manager, self.collection_manager)
        self.character_card.setMinimumWidth(210)
        self.character_card.setMaximumWidth(260)

        self.date_label = QLabel(f"今日工作 · {date.today().isoformat()}")
        self.date_label.setObjectName("sectionTitle")
        self.category = QComboBox()
        self.refresh_category_combo()
        manage_category_button = QPushButton("分类")
        manage_category_button.clicked.connect(self.open_category_manager)
        self.content = QLineEdit()
        self.content.setMinimumHeight(34)
        self.content.setPlaceholderText("输入今天完成的事项……")
        add_button = QPushButton("添加记录")
        add_button.clicked.connect(self.add_record)

        input_row = QHBoxLayout()
        input_row.addWidget(self.category)
        input_row.addWidget(manage_category_button)
        input_row.addWidget(self.content, 1)
        input_row.addWidget(add_button)

        self.records_list = QListWidget()
        self.records_list.setObjectName("recordsList")
        self.records_list.itemDoubleClicked.connect(self.edit_record_item)
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self.delete_record)
        copy_record_button = QPushButton("复制记录")
        copy_record_button.clicked.connect(self.copy_record)
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.clear_today)
        template_button = QPushButton("普通整理")
        template_button.clicked.connect(self.generate_template)
        self.ai_button = QPushButton("AI 整理")
        self.ai_button.clicked.connect(self.generate_ai)
        self.cancel_ai_button = QPushButton("取消生成")
        self.cancel_ai_button.setEnabled(False)
        self.cancel_ai_button.clicked.connect(self.cancel_ai_generation)
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(self.copy_report)
        export_txt_button = QPushButton("导出 TXT")
        export_txt_button.clicked.connect(lambda: self.export_records("txt"))
        export_md_button = QPushButton("导出 MD")
        export_md_button.clicked.connect(lambda: self.export_records("md"))

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        for button in (self.ai_button, template_button, copy_button, export_txt_button, export_md_button, copy_record_button, delete_button, clear_button, self.cancel_ai_button):
            button.setObjectName("toolbarButton")
            button_row.addWidget(button)
        button_row.addStretch(1)

        self.report_text = QPlainTextEdit()
        self.report_text.setObjectName("reportText")
        self.report_text.setPlaceholderText("整理后的日报会显示在这里，可继续编辑。")

        workspace_card = QFrame()
        workspace_card.setObjectName("workspaceCard")
        workspace = QVBoxLayout(workspace_card)
        workspace.setContentsMargins(16, 16, 16, 16)
        workspace.setSpacing(10)
        workspace.addWidget(self.date_label)
        workspace.addLayout(input_row)
        workspace.addWidget(QLabel("今日记录："))
        workspace.addWidget(self.records_list, 3)
        workspace.addLayout(button_row)
        workspace.addWidget(QLabel("日报草稿："))
        workspace.addWidget(self.report_text, 4)

        self.collection_widget = CollectionCabinetWidget(self.collection_manager)
        tag_panel = self.create_button_panel("便签 Tag 入口", [("打开 Tag 管理", self.open_tag_manager), ("打开便签列表", self.call_parent_open_notes)])
        category_panel = self.create_button_panel("日报分类入口", [("打开分类管理", self.open_category_manager)])
        ai_panel = self.create_ai_settings_panel(open_models_button, refresh_models_button, restart_ai_button, close_ai_button, check_ai_button, detail_button)
        system_panel = self.create_system_panel()

        function_scroll_body = QWidget()
        function_layout = QVBoxLayout(function_scroll_body)
        function_layout.setContentsMargins(0, 0, 0, 0)
        function_layout.setSpacing(10)
        function_layout.addWidget(CollapsibleSection("收藏柜", self.collection_widget, True))
        function_layout.addWidget(CollapsibleSection("Tag 管理", tag_panel, False))
        function_layout.addWidget(CollapsibleSection("分类管理", category_panel, False))
        function_layout.addWidget(CollapsibleSection("AI 设置", ai_panel, False))
        function_layout.addWidget(CollapsibleSection("系统设置", system_panel, False))
        function_layout.addStretch(1)

        function_scroll = QScrollArea()
        function_scroll.setWidgetResizable(True)
        function_scroll.setWidget(function_scroll_body)
        function_scroll.setFrameShape(QFrame.NoFrame)
        function_scroll.setMinimumWidth(260)
        function_scroll.setMaximumWidth(320)
        function_scroll.setStyleSheet("QScrollArea { background: transparent; }")

        header = QHBoxLayout()
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.subtitle_label)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.character_card, 0)
        body.addWidget(workspace_card, 1)
        body.addWidget(function_scroll, 0)
        body.setStretch(0, 1)
        body.setStretch(1, 4)
        body.setStretch(2, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(self.ai_notice)
        layout.addLayout(body, 1)

        self.refresh_model_list()
        self.refresh_ai_notice()
        self.refresh_records()
        self.refresh_character_card()


    def parent_pet(self):
        parent = self.parent()
        return parent if parent is not None else None

    def current_character(self):
        parent = self.parent_pet()
        return getattr(parent, "current_character", None)

    def current_character_name(self) -> str:
        character = self.current_character()
        return getattr(character, "name", "Koji") or "Koji"

    def refresh_character_card(self) -> None:
        self.subtitle_label.setText(f"当前角色：{self.current_character_name()} · 日期：{date.today().isoformat()}")
        self.character_card.refresh(self.current_character())
        if hasattr(self, "collection_widget"):
            self.collection_widget.refresh()

    def create_button_panel(self, hint: str, buttons: list[tuple[str, Callable[[], None]]]) -> QFrame:
        panel = QFrame()
        panel.setObjectName("moduleCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        label = QLabel(hint)
        label.setObjectName("panelSubtitle")
        label.setWordWrap(True)
        layout.addWidget(label)
        for title, callback in buttons:
            button = QPushButton(title)
            button.clicked.connect(callback)
            layout.addWidget(button)
        return panel

    def create_ai_settings_panel(self, open_models_button: QPushButton, refresh_models_button: QPushButton, restart_ai_button: QPushButton, close_ai_button: QPushButton, check_ai_button: QPushButton, detail_button: QPushButton) -> QFrame:
        panel = QFrame()
        panel.setObjectName("moduleCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("当前模型"))
        layout.addWidget(self.model_combo)
        layout.addWidget(self.switch_model_button)
        row = QHBoxLayout()
        row.addWidget(open_models_button)
        row.addWidget(refresh_models_button)
        layout.addLayout(row)
        layout.addWidget(self.model_description)
        layout.addWidget(self.ai_status_label)
        for button in (restart_ai_button, close_ai_button, check_ai_button, detail_button):
            layout.addWidget(button)
        layout.addWidget(self.ai_detail)
        return panel

    def create_system_panel(self) -> QFrame:
        callbacks = [
            ("和 Koji 聊两句", self.call_parent_chat),
            ("新建便签", self.call_parent_create_note),
            ("打开便签列表", self.call_parent_open_notes),
            ("开始番茄钟", self.call_parent_start_pomodoro),
            ("暂停/继续番茄钟", self.call_parent_toggle_pomodoro),
            ("停止番茄钟", self.call_parent_stop_pomodoro),
            ("系统设置", self.call_parent_settings),
            ("切换动画", self.call_parent_toggle_animations),
        ]
        return self.create_button_panel("常用系统功能入口；右键菜单保留，但这里可直接打开。", callbacks)

    def call_parent_method(self, method_name: str) -> None:
        parent = self.parent_pet()
        method = getattr(parent, method_name, None)
        if callable(method):
            method()

    def call_parent_chat(self) -> None:
        self.call_parent_method("open_chat_dialog")

    def call_parent_create_note(self) -> None:
        self.call_parent_method("create_note")

    def call_parent_open_notes(self) -> None:
        self.call_parent_method("open_notes_list")

    def call_parent_start_pomodoro(self) -> None:
        self.call_parent_method("start_pomodoro")

    def call_parent_toggle_pomodoro(self) -> None:
        parent = self.parent_pet()
        pomodoro = getattr(parent, "pomodoro_manager", None)
        if pomodoro is not None and hasattr(pomodoro, "toggle_pause"):
            pomodoro.toggle_pause()

    def call_parent_stop_pomodoro(self) -> None:
        self.call_parent_method("stop_pomodoro")

    def call_parent_settings(self) -> None:
        self.call_parent_method("open_settings_dialog")

    def call_parent_toggle_animations(self) -> None:
        self.call_parent_method("toggle_animations")

    def open_tag_manager(self) -> None:
        dialog = TagManageDialog(self.tag_manager, self.notes_manager, self)
        dialog.exec()



    def refresh_category_combo(self) -> None:
        current = self.category.currentText() if hasattr(self, "category") else ""
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems(self.category_manager.all_categories())
        if current:
            index = self.category.findText(current)
            if index >= 0:
                self.category.setCurrentIndex(index)
        self.category.blockSignals(False)

    def open_category_manager(self) -> None:
        dialog = CategoryManageDialog(self.category_manager, self.report_manager, self)
        dialog.exec()
        self.refresh_category_combo()
        self.refresh_records()

    def refresh_model_list(self) -> None:
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        current = self.ai_runtime.get_current_model()
        current_key = (current or {}).get("file") or (current or {}).get("id")
        for model in self.ai_runtime.list_models():
            self.model_combo.addItem(model.get("name") or model.get("file") or "未命名模型", model)
            if model.get("file") == current_key or model.get("id") == current_key:
                self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
        self.model_combo.blockSignals(False)
        self.update_model_description()
        self.refresh_ai_notice()

    def selected_model(self) -> dict | None:
        data = self.model_combo.currentData()
        return data if isinstance(data, dict) else None

    def update_model_description(self) -> None:
        model = self.selected_model() or self.ai_runtime.get_current_model()
        if not model:
            self.model_description.setText("未检测到可用 GGUF 模型。旧结构可继续使用 ai-runtime/model.gguf；多模型请放入 ai-runtime/models/。")
            return
        description = model.get("description") or "本地 GGUF 模型"
        name_and_file = f"{description}\n文件：{model.get('file', '未知')}"
        is_quality = any(keyword in (model.get("name", "") + model.get("file", "") + description).lower() for keyword in ("高质量", "8b"))
        if is_quality:
            name_and_file += "\n高质量模型生成较慢，可能需要 1～3 分钟，Koji 不是死了，是在憋大的。"
        self.model_description.setText(name_and_file)

    def open_models_folder(self) -> None:
        self.ai_runtime.models_dir.mkdir(parents=True, exist_ok=True)
        if self.ai_runtime.legacy_model_path.exists() and not self.ai_runtime._scan_model_files():
            self.show_koji_message("你也可以把多个模型放入 ai-runtime/models/，然后在 Koji 里切换。")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ai_runtime.models_dir)))

    def switch_model(self) -> None:
        model = self.selected_model()
        if not model:
            self.show_koji_message("还没有可切换的模型，请先把 GGUF 放进 ai-runtime/models/。")
            return
        if self.ai_runtime.is_generating():
            reply = QMessageBox.question(
                self,
                "Koji",
                "Koji 正在生成内容，切换模型需要先停止当前任务。",
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return
            self.cancel_ai_generation(show_message=False)
            self.ai_runtime.cancel_generation()
        self.notify_state("thinking")
        self.show_koji_message("Koji 正在换脑子……")
        selected = model.get("id") or model.get("file") or ""

        def task() -> tuple[bool, str]:
            ok, message = self.ai_runtime.set_current_model(selected)
            if not ok:
                return ok, message
            if self.ai_runtime.process is not None and self.ai_runtime.process.poll() is None:
                return self.ai_runtime.restart_with_current_model()
            return True, "模型切好了，Koji 换了个脑子。"

        self.switch_thread = run_in_qthread(self, task, self.finish_switch_model)

    def finish_switch_model(self, result: object) -> None:
        ok, message = result if isinstance(result, tuple) and len(result) >= 2 else (False, "模型切换失败。")
        self.refresh_model_list()
        self.refresh_ai_notice()
        self.notify_state("success" if ok else "error")
        self.show_koji_message("模型切好了，Koji 换了个脑子。" if ok else f"切换模型失败：{message}")

    def notify_state(self, state: str) -> None:
        if self.state_callback is not None:
            duration = 3000 if normalize_state(state) == "success" else 5000 if normalize_state(state) == "error" else 1800
            self.state_callback(state, duration)

    def show_koji_message(self, message: str) -> None:
        self.ai_notice.setText(message)
        self.ai_notice.setVisible(True)
        parent = self.parent()
        if parent is not None and hasattr(parent, "bubble"):
            parent.bubble.show_message(message, parent)  # type: ignore[attr-defined]

    def notify_report_success(self) -> None:
        if self.report_success_callback is not None:
            self.report_success_callback()

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
            f"model 路径：{self.ai_runtime.get_current_model_path() or self.ai_runtime.model_path}\n"
            f"最近错误：{self.ai_runtime.last_error or '无'}"
        )

    def check_ai_status(self) -> None:
        self.refresh_ai_notice()
        self.show_koji_message(self.ai_runtime.status_message())

    def restart_ai(self) -> None:
        self.notify_state("thinking")
        self.show_koji_message(STARTING_MESSAGE)
        self.restart_thread = run_in_qthread(self, self.ai_runtime.restart_with_current_model, self.finish_restart_ai)

    def finish_restart_ai(self, result: object) -> None:
        ok, message = result if isinstance(result, tuple) and len(result) >= 2 else (False, "Koji 脑子重启失败。")
        self.refresh_ai_notice()
        self.notify_state("success" if ok else "error")
        self.show_koji_message(str(message))

    def close_ai(self) -> None:
        self.cancel_ai_generation(show_message=False)
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
        category.addItems(self.category_manager.all_categories())
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
        report = self.report_manager.render_template_report(categories=self.category_manager.all_categories())
        self.report_text.setPlainText(report)
        self.notify_state("happy")
        self.notify_report_success()

    def generate_ai(self) -> None:
        if not self.ai_button.isEnabled():
            return
        material = self.report_manager.ai_material_text()
        self.ai_record_count = len(self.report_manager.records_for_date())
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
        self.ai_generation_cancelled = False
        self.ai_button.setText("生成中...")
        self.ai_button.setEnabled(False)
        self.cancel_ai_button.setEnabled(True)
        self.notify_state("thinking")
        QTimer.singleShot(900, lambda: self.notify_state("typing") if not self.ai_button.isEnabled() else None)
        self.show_koji_message("Koji 正在认真憋日报，高质量模型可能需要 1～3 分钟。")
        self.ai_wait_60_timer = QTimer.singleShot(60000, self.show_ai_wait_60_message)
        self.ai_wait_180_timer = QTimer.singleShot(180000, self.show_ai_wait_180_message)
        messages = self.report_manager.build_ai_report_messages()
        self.ai_report_thread = run_in_qthread(
            self,
            lambda: self.ai_runtime.chat(messages, temperature=0.45, top_p=0.9, max_tokens=2600),
            self.finish_ai_generation,
        )

    def show_ai_wait_60_message(self) -> None:
        if not self.ai_button.isEnabled():
            self.show_koji_message("模型比较大，Koji 还在写，别急。")

    def show_ai_wait_180_message(self) -> None:
        if not self.ai_button.isEnabled():
            self.show_koji_message("这颗脑子有点沉，建议稍后再试或切换轻量模型。")

    def cancel_ai_generation(self, show_message: bool = True) -> None:
        if self.ai_button.isEnabled() and not self.ai_runtime.is_generating():
            return
        self.ai_generation_cancelled = True
        self.ai_runtime.cancel_generation()
        self.ai_button.setText("AI 整理日报")
        self.ai_button.setEnabled(True)
        self.cancel_ai_button.setEnabled(False)
        if show_message:
            self.notify_state("confused")
            self.show_koji_message("这次先不憋了，素材还在。")

    def finish_ai_generation(self, result: object) -> None:
        if getattr(self, "ai_generation_cancelled", False):
            return
        self.ai_button.setText("AI 整理日报")
        self.ai_button.setEnabled(True)
        self.cancel_ai_button.setEnabled(False)
        self.refresh_ai_notice()
        ok, answer = result if isinstance(result, tuple) and len(result) >= 2 else (False, "本地 AI 返回了未知结果。")
        if ok:
            self.report_text.setPlainText(clean_ai_report_text(str(answer)))
            self.notify_state("success")
            self.show_koji_message("日报炼成完毕，去交差吧。")
            self.notify_report_success()
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
        gap = 12
        screen = QGuiApplication.screenAt(anchor_rect.center()) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None

        right_top = QPoint(anchor_rect.right() + gap, anchor_rect.top() - max(0, self.height() // 3))
        left_top = QPoint(anchor_rect.left() - self.width() - gap, anchor_rect.top() - max(0, self.height() // 3))
        right_bottom = QPoint(anchor_rect.right() + gap, anchor_rect.bottom() - self.height())
        candidates = (right_top, left_top, right_bottom)

        x, y = right_top.x(), right_top.y()
        if available is not None:
            for candidate in candidates:
                if (
                    candidate.x() >= available.left() + 8
                    and candidate.x() + self.width() <= available.right() - 8
                    and candidate.y() >= available.top() + 8
                    and candidate.y() + self.height() <= available.bottom() - 8
                ):
                    x, y = candidate.x(), candidate.y()
                    break
            else:
                x = max(available.left() + 8, min(x, available.right() - self.width() - 8))
                y = max(available.top() + 8, min(y, available.bottom() - self.height() - 8))
        self.move(x, y)

class PomodoroWindow(QDialog):
    def __init__(self, manager: PomodoroManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Koji 番茄钟")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(320, 220)

        self.phase_label = QLabel()
        self.phase_label.setObjectName("panelSubtitle")
        self.time_label = QLabel()
        self.time_label.setStyleSheet("font-size: 42px; font-weight: 900; color: #4b3324;")
        self.count_label = QLabel()
        self.count_label.setObjectName("panelSubtitle")

        start_button = QPushButton("开始")
        start_button.clicked.connect(self.manager.start)
        pause_button = QPushButton("暂停/继续")
        pause_button.clicked.connect(self.manager.toggle_pause)
        stop_button = QPushButton("停止")
        stop_button.clicked.connect(self.manager.stop)
        skip_button = QPushButton("跳过")
        skip_button.clicked.connect(self.manager.skip)
        reset_button = QPushButton("重置计数")
        reset_button.clicked.connect(self.manager.reset_count)

        row = QHBoxLayout()
        for button in (start_button, pause_button, stop_button, skip_button, reset_button):
            row.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("番茄钟状态"))
        layout.addWidget(self.phase_label)
        layout.addWidget(self.time_label)
        layout.addWidget(self.count_label)
        layout.addLayout(row)
        self.manager.tick.connect(self.refresh)
        self.manager.phase_changed.connect(lambda _phase: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        running = "运行中" if self.manager.running else "已暂停" if self.manager.phase != "stopped" else "未开始"
        self.phase_label.setText(f"当前阶段：{self.manager.phase_label()}（{running}）")
        self.time_label.setText(self.manager.formatted_remaining())
        self.count_label.setText(f"今日已完成番茄数：{self.manager.completed_today}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
        self.hide()


class TagManageDialog(QDialog):
    def __init__(self, tag_manager: TagManager, notes_manager: NotesManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tag_manager = tag_manager
        self.notes_manager = notes_manager
        self.setWindowTitle("Tag 管理")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(430, 420)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.rename_selected())
        add_button = QPushButton("新增 Tag")
        add_button.clicked.connect(self.add_tag)
        rename_button = QPushButton("重命名")
        rename_button.clicked.connect(self.rename_selected)
        color_button = QPushButton("修改颜色")
        color_button.clicked.connect(self.change_color)
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self.delete_selected)
        restore_button = QPushButton("恢复默认")
        restore_button.clicked.connect(self.restore_defaults)
        row = QHBoxLayout()
        for button in (add_button, rename_button, color_button, delete_button, restore_button):
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("便签 Tag：双击可重命名，删除后便签会变为未分类。"))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list_widget.clear()
        for tag in self.tag_manager.all_tags():
            item = QListWidgetItem(f"{tag.name}  {tag.color}")
            item.setData(Qt.UserRole, tag.id)
            item.setBackground(QColor(tag.color))
            self.list_widget.addItem(item)

    def selected_tag_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def add_tag(self) -> None:
        name, ok = QInputDialog.getText(self, "新增 Tag", "Tag 名称：")
        if not ok or not name.strip():
            return
        color = QColorDialog.getColor(QColor("#f6c177"), self, "选择 Tag 颜色")
        try:
            self.tag_manager.add_tag(name, color.name() if color.isValid() else "#f6c177")
        except ValueError as exc:
            QMessageBox.information(self, "Koji", str(exc))
        self.refresh()

    def rename_selected(self) -> None:
        tag_id = self.selected_tag_id()
        tag = self.tag_manager.get(tag_id) if tag_id else None
        if tag is None:
            return
        name, ok = QInputDialog.getText(self, "重命名 Tag", "Tag 名称：", text=tag.name)
        if not ok:
            return
        try:
            self.tag_manager.update_tag(tag.id, name, tag.color)
        except ValueError as exc:
            QMessageBox.information(self, "Koji", str(exc))
        self.refresh()

    def change_color(self) -> None:
        tag_id = self.selected_tag_id()
        tag = self.tag_manager.get(tag_id) if tag_id else None
        if tag is None:
            return
        color = QColorDialog.getColor(QColor(tag.color), self, "选择 Tag 颜色")
        if color.isValid():
            self.tag_manager.update_tag(tag.id, tag.name, color.name())
            self.refresh()

    def delete_selected(self) -> None:
        tag_id = self.selected_tag_id()
        if not tag_id:
            return
        if QMessageBox.question(self, "Koji", "删除 Tag 不会删除便签，已使用便签会改为未分类。确定删除吗？") != QMessageBox.Yes:
            return
        self.tag_manager.delete_tag(tag_id)
        if self.notes_manager is not None:
            self.notes_manager.reassign_deleted_tag(tag_id)
        self.refresh()

    def restore_defaults(self) -> None:
        if QMessageBox.question(self, "Koji", "确定恢复默认 Tag 吗？自定义 Tag 会被替换。") != QMessageBox.Yes:
            return
        self.tag_manager.restore_defaults()
        self.refresh()


class SettingsDialog(QDialog):
    def __init__(self, settings_manager: SettingsManager, pomodoro: PomodoroManager, tag_manager: TagManager, notes_manager: NotesManager, character_manager: CharacterManager, relationship_manager: RelationshipManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.pomodoro = pomodoro
        self.tag_manager = tag_manager
        self.notes_manager = notes_manager
        self.character_manager = character_manager
        self.relationship_manager = relationship_manager
        self.setWindowTitle("Koji 设置")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(460, 420)
        self.animations = QCheckBox("开启动画")
        self.animations.setChecked(bool(settings_manager.get("animations_enabled", True)))
        self.chime = QCheckBox("开启整点报时")
        self.chime.setChecked(bool(settings_manager.get("hourly_chime_enabled", True)))
        self.quiet = QCheckBox("整点少打扰模式")
        self.quiet.setChecked(bool(settings_manager.get("hourly_chime_quiet", False)))
        self.start_time = QTimeEdit(QTime.fromString(str(settings_manager.get("hourly_chime_start", "09:00")), "HH:mm"))
        self.start_time.setDisplayFormat("HH:mm")
        self.end_time = QTimeEdit(QTime.fromString(str(settings_manager.get("hourly_chime_end", "23:00")), "HH:mm"))
        self.end_time.setDisplayFormat("HH:mm")
        self.focus = QSpinBox(); self.focus.setRange(1, 180); self.focus.setValue(int(settings_manager.get("pomodoro_focus_minutes", 25)))
        self.short_break = QSpinBox(); self.short_break.setRange(1, 60); self.short_break.setValue(int(settings_manager.get("pomodoro_short_break_minutes", 5)))
        self.long_break = QSpinBox(); self.long_break.setRange(1, 120); self.long_break.setValue(int(settings_manager.get("pomodoro_long_break_minutes", 15)))
        self.character_combo = QComboBox()
        self.refresh_character_combo()
        self.character_combo.currentIndexChanged.connect(self.change_character)
        import_character_button = QPushButton("导入角色")
        import_character_button.clicked.connect(self.import_character)
        tag_button = QPushButton("打开 Tag 管理")
        tag_button.clicked.connect(self.open_tags)
        save_button = QPushButton("保存设置")
        save_button.clicked.connect(self.save_settings)
        form = QFormLayout()
        form.addRow(self.animations)
        form.addRow(self.chime)
        form.addRow("报时开始", self.start_time)
        form.addRow("报时结束", self.end_time)
        form.addRow(self.quiet)
        form.addRow("专注分钟", self.focus)
        form.addRow("短休息分钟", self.short_break)
        form.addRow("长休息分钟", self.long_break)
        character_row = QHBoxLayout()
        character_row.addWidget(self.character_combo, 1)
        character_row.addWidget(import_character_button)
        form.addRow("当前角色", character_row)
        form.addRow("Tag", tag_button)
        form.addRow("本地 AI", QLabel("运行器优先：ai-runtime/koboldcpp.exe\n模型：ai-runtime/model.gguf 或 ai-runtime/models/*.gguf\n所有数据仅保存在本地 data/ 目录。"))
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(save_button)

    def refresh_character_combo(self) -> None:
        current_id = str(self.settings_manager.get("current_character", "koji"))
        self.character_manager.refresh()
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        selected_index = 0
        for index, character in enumerate(self.character_manager.all_characters()):
            self.character_combo.addItem(character.name, character.id)
            if character.id == current_id:
                selected_index = index
        if self.character_combo.count() > 0:
            self.character_combo.setCurrentIndex(selected_index)
        self.character_combo.blockSignals(False)

    def change_character(self) -> None:
        character_id = self.character_combo.currentData()
        if not character_id:
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "select_character"):
            parent.select_character(str(character_id))  # type: ignore[attr-defined]

    def import_character(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入角色", "", "角色包 (*.zip)")
        if not path:
            return
        try:
            character = self.character_manager.import_zip(path)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            QMessageBox.information(self, "Koji", f"导入失败：{exc}")
            return
        self.refresh_character_combo()
        index = self.character_combo.findData(character.id)
        if index >= 0:
            self.character_combo.setCurrentIndex(index)
        parent = self.parent()
        if parent is not None and hasattr(parent, "select_character"):
            parent.select_character(character.id)  # type: ignore[attr-defined]
        if parent is not None and hasattr(parent, "award_relationship_exp"):
            parent.award_relationship_exp(EXP_CHARACTER_IMPORT)  # type: ignore[attr-defined]
        QMessageBox.information(self, "Koji", f"已导入角色：{character.name}")

    def open_tags(self) -> None:
        dialog = TagManageDialog(self.tag_manager, self.notes_manager, self)
        dialog.exec()

    def save_settings(self) -> None:
        self.settings_manager.set("animations_enabled", self.animations.isChecked())
        self.settings_manager.set("hourly_chime_enabled", self.chime.isChecked())
        self.settings_manager.set("hourly_chime_quiet", self.quiet.isChecked())
        self.settings_manager.set("hourly_chime_start", self.start_time.time().toString("HH:mm"))
        self.settings_manager.set("hourly_chime_end", self.end_time.time().toString("HH:mm"))
        self.settings_manager.set("pomodoro_focus_minutes", self.focus.value())
        self.settings_manager.set("pomodoro_short_break_minutes", self.short_break.value())
        self.settings_manager.set("pomodoro_long_break_minutes", self.long_break.value())
        self.pomodoro.apply_settings()
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_animations_enabled"):
            parent.set_animations_enabled(self.animations.isChecked())  # type: ignore[attr-defined]
        QMessageBox.information(self, "Koji", "设置已保存。")


class NoteCardWindow(QDialog):
    def __init__(self, note: Note, notes_manager: NotesManager, tag_manager: TagManager, to_report_callback: Callable[[Note], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.note = note
        self.notes_manager = notes_manager
        self.tag_manager = tag_manager
        self.to_report_callback = to_report_callback
        self.setWindowTitle(note.title or "随手记")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        flags = Qt.Window | Qt.Tool
        if note.pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.resize(note.width, note.height)
        self.move(note.x, note.y)
        self.color_bar = QLabel()
        self.color_bar.setFixedHeight(8)
        self.title_edit = QLineEdit(note.title)
        self.content_edit = QPlainTextEdit(note.content)
        self.tag_combo = QComboBox()
        self.refresh_tags()
        self.pin_button = QPushButton("取消置顶" if note.pinned else "置顶")
        self.pin_button.clicked.connect(self.toggle_pin)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self.delete_note)
        to_report_button = QPushButton("转为日报记录")
        to_report_button.clicked.connect(self.to_report)
        self.title_edit.textChanged.connect(self.save_from_widgets)
        self.content_edit.textChanged.connect(self.save_from_widgets)
        self.tag_combo.currentIndexChanged.connect(self.save_from_widgets)
        row = QHBoxLayout()
        for button in (self.pin_button, to_report_button, delete_button, close_button):
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.color_bar)
        layout.addWidget(self.title_edit)
        layout.addWidget(self.tag_combo)
        layout.addWidget(self.content_edit, 1)
        layout.addLayout(row)
        self.apply_color()

    def refresh_tags(self) -> None:
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("未分类", None)
        for tag in self.tag_manager.all_tags():
            self.tag_combo.addItem(tag.name, tag.id)
        index = self.tag_combo.findData(self.note.tag_id)
        self.tag_combo.setCurrentIndex(index if index >= 0 else 0)
        self.tag_combo.blockSignals(False)

    def apply_color(self) -> None:
        color = self.tag_manager.color_for(self.note.tag_id, self.note.color)
        self.color_bar.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET + f"QDialog#reportPanel {{ background: #fff9df; border: 2px solid {color}; border-radius: 14px; }}")

    def save_from_widgets(self) -> None:
        self.note.title = self.title_edit.text().strip() or "随手记"
        self.note.content = self.content_edit.toPlainText()
        self.note.tag_id = self.tag_combo.currentData()
        self.note.color = self.tag_manager.color_for(self.note.tag_id, self.note.color)
        self.setWindowTitle(self.note.title)
        self.apply_color()
        self.notes_manager.touch(self.note)

    def toggle_pin(self) -> None:
        self.note.pinned = not self.note.pinned
        self.notes_manager.touch(self.note)
        self.pin_button.setText("取消置顶" if self.note.pinned else "置顶")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.note.pinned)
        self.show()

    def to_report(self) -> None:
        self.save_from_widgets()
        self.to_report_callback(self.note)

    def delete_note(self) -> None:
        if QMessageBox.question(self, "Koji", "确定删除这张便签吗？") != QMessageBox.Yes:
            return
        self.notes_manager.delete(self.note.id)
        self.accept()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.save_from_widgets()
        self.note.x = self.x(); self.note.y = self.y(); self.note.width = self.width(); self.note.height = self.height(); self.note.visible = False
        self.notes_manager.touch(self.note)
        event.accept()

    def moveEvent(self, event) -> None:  # type: ignore[override]
        self.note.x = self.x(); self.note.y = self.y()
        self.notes_manager.touch(self.note)
        super().moveEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self.note.width = self.width(); self.note.height = self.height()
        self.notes_manager.touch(self.note)
        super().resizeEvent(event)


class NotesListDialog(QDialog):
    def __init__(self, notes_manager: NotesManager, tag_manager: TagManager, open_callback: Callable[[Note], None], delete_callback: Callable[[str], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.notes_manager = notes_manager
        self.tag_manager = tag_manager
        self.open_callback = open_callback
        self.delete_callback = delete_callback
        self.setWindowTitle("便签列表")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(520, 460)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题或正文……")
        self.search.textChanged.connect(self.refresh)
        self.tag_filter = QComboBox()
        self.tag_filter.currentIndexChanged.connect(self.refresh)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda item: self.open_selected())
        open_button = QPushButton("显示/打开")
        open_button.clicked.connect(self.open_selected)
        hide_button = QPushButton("隐藏")
        hide_button.clicked.connect(self.hide_selected)
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self.delete_selected)
        row = QHBoxLayout()
        for button in (open_button, hide_button, delete_button):
            row.addWidget(button)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.tag_filter)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(row)
        self.refresh_tags()
        self.refresh()

    def refresh_tags(self) -> None:
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("全部 Tag", "__all__")
        self.tag_filter.addItem("未分类", None)
        for tag in self.tag_manager.all_tags():
            self.tag_filter.addItem(tag.name, tag.id)
        self.tag_filter.blockSignals(False)

    def refresh(self) -> None:
        keyword = self.search.text().strip().lower()
        tag_id = self.tag_filter.currentData()
        self.list_widget.clear()
        for note in self.notes_manager.all_notes():
            if tag_id != "__all__" and note.tag_id != tag_id:
                continue
            haystack = f"{note.title}\n{note.content}".lower()
            if keyword and keyword not in haystack:
                continue
            tag_name = self.tag_manager.name_for(note.tag_id)
            item = QListWidgetItem(f"{'👁' if note.visible else '—'} [{tag_name}] {note.title}\n{note.content[:60]}")
            item.setData(Qt.UserRole, note.id)
            self.list_widget.addItem(item)

    def selected_note(self) -> Note | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return self.notes_manager.get(str(item.data(Qt.UserRole)))

    def open_selected(self) -> None:
        note = self.selected_note()
        if note is not None:
            note.visible = True
            self.notes_manager.touch(note)
            self.open_callback(note)
            self.refresh()

    def hide_selected(self) -> None:
        note = self.selected_note()
        if note is not None:
            note.visible = False
            self.notes_manager.touch(note)
            self.refresh()

    def delete_selected(self) -> None:
        note = self.selected_note()
        if note is None:
            return
        if QMessageBox.question(self, "Koji", "确定删除这张便签吗？") != QMessageBox.Yes:
            return
        self.delete_callback(note.id)
        self.refresh()



class RelationshipPanel(QDialog):
    """Shows the current companion relationship level and progress."""

    def __init__(self, relationship_manager: RelationshipManager, collection_callback: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.relationship_manager = relationship_manager
        self.collection_callback = collection_callback
        self.setWindowTitle("角色信息")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(360, 260)

        self.name_label = QLabel("")
        self.name_label.setObjectName("panelTitle")
        self.level_label = QLabel("")
        self.level_label.setStyleSheet("QLabel { color: #5c3b25; font-size: 18px; font-weight: 800; }")
        self.exp_label = QLabel("")
        self.exp_label.setObjectName("panelSubtitle")
        self.tip_label = QLabel("关系经验会随日报、聊天、番茄钟和签到慢慢增长。")
        self.tip_label.setObjectName("panelSubtitle")
        self.tip_label.setWordWrap(True)
        collection_button = QPushButton("收藏柜")
        collection_button.clicked.connect(self.collection_callback)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)

        row = QHBoxLayout()
        row.addWidget(collection_button)
        row.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(self.name_label)
        layout.addWidget(self.level_label)
        layout.addWidget(self.exp_label)
        layout.addWidget(self.tip_label)
        layout.addStretch(1)
        layout.addLayout(row)

    def refresh(self, character) -> None:
        character_id = getattr(character, "id", "koji")
        character_name = getattr(character, "name", "Koji")
        self.name_label.setText(character_name)
        self.level_label.setText(self.relationship_manager.level_label(character_id))
        level, exp = self.relationship_manager.get(character_id)
        exp_text = "MAX" if level >= 5 else f"{exp} / {LEVEL_THRESHOLDS[level]}"
        self.exp_label.setText(exp_text)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
        self.hide()


class CollectionDialog(QDialog):
    """Collection cabinet for unlocked companion keepsakes."""

    def __init__(self, collection_manager: CollectionManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.collection_manager = collection_manager
        self.setWindowTitle("收藏柜")
        self.setObjectName("reportPanel")
        self.setStyleSheet(REPORT_PANEL_STYLESHEET)
        self.resize(520, 380)

        title = QLabel("收藏柜")
        title.setObjectName("panelTitle")
        hint = QLabel("已获得的纪念物会显示真实信息；未获得的会保持神秘感。")
        hint.setObjectName("panelSubtitle")
        hint.setWordWrap(True)
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(lambda _current, _previous: self.refresh_detail())
        self.name_label = QLabel("？？？")
        self.name_label.setStyleSheet("QLabel { color: #5c3b25; font-size: 18px; font-weight: 800; }")
        self.description_label = QLabel("选择一个收藏品查看详情。")
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("panelSubtitle")
        self.icon_label = QLabel("图标：？？？")
        self.icon_label.setObjectName("panelSubtitle")
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)

        detail = QVBoxLayout()
        detail.addWidget(self.name_label)
        detail.addWidget(self.icon_label)
        detail.addWidget(self.description_label, 1)
        detail.addWidget(close_button)
        body = QHBoxLayout()
        body.addWidget(self.list_widget, 1)
        body.addLayout(detail, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(body, 1)
        self.refresh()

    def refresh(self) -> None:
        current_id = None
        current = self.list_widget.currentItem()
        if current is not None:
            current_id = current.data(Qt.UserRole)
        self.list_widget.clear()
        selected_row = 0
        for row, collectible in enumerate(self.collection_manager.all_collectibles()):
            unlocked = self.collection_manager.is_unlocked(collectible.id)
            item = QListWidgetItem(collectible.name if unlocked else "？？？")
            item.setData(Qt.UserRole, collectible.id)
            self.list_widget.addItem(item)
            if collectible.id == current_id:
                selected_row = row
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(selected_row)
        self.refresh_detail()

    def refresh_detail(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            self.name_label.setText("？？？")
            self.description_label.setText("暂无收藏品。")
            self.icon_label.setText("图标：？？？")
            return
        collectible_id = str(item.data(Qt.UserRole) or "")
        collectible = self.collection_manager.load_collectible(collectible_id)
        if collectible is None or not self.collection_manager.is_unlocked(collectible_id):
            self.name_label.setText("？？？")
            self.description_label.setText("尚未获得。")
            self.icon_label.setText("图标：？？？")
            return
        self.name_label.setText(collectible.name)
        self.description_label.setText(collectible.description)
        self.icon_label.setText(f"图标：{collectible.icon or '无'}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
        self.hide()


class KojiPet(QWidget):
    PET_SIZE = QSize(152, 152)
    VISUAL_SIZE = QSize(132, 132)
    BREATH_AMPLITUDE = 4
    RANDOM_IDLE_MIN_MS = 30_000
    RANDOM_IDLE_MAX_MS = 90_000
    INACTIVITY_SLEEP_MS = 15 * 60 * 1000

    def __init__(self) -> None:
        super().__init__()
        self.settings_manager = SettingsManager()
        self.character_manager = CharacterManager()
        self.relationship_manager = RelationshipManager()
        self.collection_manager = CollectionManager()
        self.current_character = self.character_manager.get(str(self.settings_manager.get("current_character", "koji")))
        self.ai_runtime = AIRuntimeManager()
        self.report_manager = ReportManager()
        self.category_manager = CategoryManager()
        self.chat_manager = ChatManager(self.ai_runtime, self.category_manager)
        self.tag_manager = TagManager()
        self.notes_manager = NotesManager()
        self.pomodoro_manager = PomodoroManager(self.settings_manager)
        self.pomodoro_manager.phase_changed.connect(self.on_pomodoro_phase_changed)
        self.pomodoro_manager.focus_completed.connect(self.on_pomodoro_focus_completed)
        self.pomodoro_manager.tick.connect(self.on_pomodoro_tick)
        self.hourly_chime = HourlyChimeManager(self.settings_manager, self.report_panel_is_busy, self.pomodoro_focus_active)
        self.hourly_chime.chime.connect(lambda message: self.bubble.show_message(message, self, 3600))
        self.report_panel: ReportPanel | None = None
        self.chat_dialog: ChatDialog | None = None
        self.pomodoro_window: PomodoroWindow | None = None
        self.settings_dialog: SettingsDialog | None = None
        self.relationship_panel: RelationshipPanel | None = None
        self.collection_dialog: CollectionDialog | None = None
        self.notes_list_dialog: NotesListDialog | None = None
        self.note_windows: Dict[str, NoteCardWindow] = {}
        self.attached_window_follow_enabled = bool(self.settings_manager.get("attached_windows_follow_koji", True))
        self._attached_window_names: Dict[QWidget, str] = {}
        self._detached_attached_windows: set[QWidget] = set()
        self._positioning_attached_window = False
        self._last_pomodoro_minute_notice: int | None = None
        self.drag_position: QPoint | None = None
        self.press_position: QPoint | None = None
        self.was_dragged = False
        self.current_state = "idle"
        self.animations_enabled = bool(self.settings_manager.get("animations_enabled", True))
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

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.setSingleShot(True)
        self.inactivity_timer.timeout.connect(self.enter_sleep_from_inactivity)

        self.setWindowTitle("Koji Report Pet Next")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.label = QLabel(self)
        self.visual = KojiVisual(self.label, self.VISUAL_SIZE, self.current_character)
        self.setFixedSize(self.PET_SIZE)
        self.apply_visual_transform()
        self.set_state("idle")
        self.start_idle_motion()
        self.schedule_random_idle_activity()
        self.reset_inactivity_timer()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.open_visible_notes()
        self.handle_daily_check_in()

    def mark_user_interaction(self) -> None:
        was_sleeping = self.current_state == "sleep"
        self.reset_inactivity_timer()
        if was_sleeping:
            self.set_state("idle")
        self.schedule_random_idle_activity()
        self.open_visible_notes()

    def reset_inactivity_timer(self) -> None:
        self.inactivity_timer.start(self.INACTIVITY_SLEEP_MS)

    def enter_sleep_from_inactivity(self) -> None:
        if not self.is_dragging:
            self.set_state("sleep")

    def set_state(self, state: str, show_dialogue: bool = True) -> None:
        state = normalize_state(state)
        previous_state = self.current_state
        self.current_state = state
        self.visual.set_state(state)
        self.apply_visual_transform()
        if show_dialogue:
            dialogue = random_dialogue(state)
            self.setToolTip(dialogue)
            self.bubble.show_message(dialogue, self)
        self.sync_animation_state()
        if state != previous_state and state in {"thinking", "typing", "success", "error"}:
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
        self.visual.show_random_idle_variant()
        self.schedule_random_idle_activity()

    def select_character(self, character_id: str) -> None:
        self.character_manager.refresh()
        character = self.character_manager.get(character_id)
        if character is None:
            return
        self.current_character = character
        self.settings_manager.set("current_character", character.id)
        self.visual.set_character(character)
        self.relationship_manager.ensure_character(character.id)
        self.relationship_manager.save()
        self.refresh_growth_windows()
        self.set_state(self.current_state, show_dialogue=False)
        self.setToolTip(random_dialogue(self.current_state))


    def current_character_id(self) -> str:
        return getattr(self.current_character, "id", "koji") or "koji"

    def current_character_name(self) -> str:
        return getattr(self.current_character, "name", "Koji") or "Koji"

    def refresh_growth_windows(self) -> None:
        if self.relationship_panel is not None:
            self.relationship_panel.refresh(self.current_character)
        if self.collection_dialog is not None:
            self.collection_dialog.refresh()
        if self.report_panel is not None:
            self.report_panel.refresh_character_card()

    def show_relationship_feedback(self, change: RelationshipChange) -> None:
        self.refresh_growth_windows()
        if change.leveled_up:
            message = f"{self.current_character_name()} 对你的信任提升了。"
        else:
            message = f"{self.current_character_name()} 对你的信任提升了。"
        self.bubble.show_message(message, self, 3200)

    def award_relationship_exp(self, amount: int) -> RelationshipChange:
        change = self.relationship_manager.add_exp(self.current_character_id(), amount)
        self.show_relationship_feedback(change)
        return change

    def handle_collectible_unlock(self, result: UnlockResult) -> None:
        if not result.unlocked or result.collectible is None:
            self.refresh_growth_windows()
            return
        self.temporary_state("success", 3000)
        self.refresh_growth_windows()
        self.bubble.show_message(f"获得收藏品：{result.collectible.name}", self, 3200)

    def handle_daily_check_in(self) -> None:
        before = self.collection_manager.stats().get("last_login_date", "")
        result = self.collection_manager.record_login()
        after = self.collection_manager.stats().get("last_login_date", "")
        if after != before:
            self.award_relationship_exp(EXP_DAILY_CHECK_IN)
        self.handle_collectible_unlock(result)

    def on_report_generated_success(self) -> None:
        self.award_relationship_exp(EXP_REPORT_SUCCESS)
        self.handle_collectible_unlock(self.collection_manager.record_report_generated())

    def on_chat_success(self) -> None:
        self.award_relationship_exp(EXP_CHAT_SUCCESS)
        self.handle_collectible_unlock(self.collection_manager.record_chat_success())

    def open_relationship_panel(self) -> None:
        if self.relationship_panel is None:
            self.relationship_panel = RelationshipPanel(self.relationship_manager, self.open_collection_dialog, self)
            self.register_attached_window(self.relationship_panel, "relationship")
        self.relationship_panel.refresh(self.current_character)
        self.relationship_panel.show()
        self.position_attached_window(self.relationship_panel, force=True)
        self.relationship_panel.raise_()
        self.relationship_panel.activateWindow()

    def open_collection_dialog(self) -> None:
        if self.collection_dialog is None:
            self.collection_dialog = CollectionDialog(self.collection_manager, self)
            self.register_attached_window(self.collection_dialog, "collection")
        self.collection_dialog.refresh()
        self.collection_dialog.show()
        self.position_attached_window(self.collection_dialog, force=True)
        self.collection_dialog.raise_()
        self.collection_dialog.activateWindow()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() in {
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseMove,
            QEvent.KeyPress,
            QEvent.Wheel,
            QEvent.TouchBegin,
        }:
            was_sleeping = self.current_state == "sleep"
            self.reset_inactivity_timer()
            if was_sleeping:
                self.set_state("idle")
        return super().eventFilter(watched, event)


    def set_animations_enabled(self, enabled: bool) -> None:
        if self.animations_enabled == enabled:
            return
        self.toggle_animations(save=False)

    def toggle_animations(self, save: bool = True) -> None:
        self.animations_enabled = not self.animations_enabled
        if save:
            self.settings_manager.set("animations_enabled", self.animations_enabled)
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

    def pomodoro_focus_active(self) -> bool:
        return self.pomodoro_manager.phase == PHASE_FOCUS and self.pomodoro_manager.running

    def on_pomodoro_tick(self) -> None:
        if not self.pomodoro_focus_active():
            self._last_pomodoro_minute_notice = None
            return
        remaining_minutes = max(1, math.ceil(self.pomodoro_manager.remaining_seconds / 60))
        if remaining_minutes in {15, 10, 5, 1} and remaining_minutes != self._last_pomodoro_minute_notice:
            self._last_pomodoro_minute_notice = remaining_minutes
            self.bubble.show_message(f"专注还剩 {remaining_minutes} 分钟。稳住，别被摸鱼妖怪勾走。", self, 2600)

    def start_pomodoro(self) -> None:
        self.pomodoro_manager.start()
        self.open_pomodoro_window()

    def stop_pomodoro(self) -> None:
        self.pomodoro_manager.stop()
        self.set_state("idle")

    def open_pomodoro_window(self) -> None:
        if self.pomodoro_window is None:
            self.pomodoro_window = PomodoroWindow(self.pomodoro_manager, self)
            self.register_attached_window(self.pomodoro_window, "pomodoro")
        self.pomodoro_window.show()
        self.position_attached_window(self.pomodoro_window, force=True)
        self.pomodoro_window.raise_()
        self.pomodoro_window.activateWindow()

    def open_settings_dialog(self) -> None:
        self.settings_dialog = SettingsDialog(self.settings_manager, self.pomodoro_manager, self.tag_manager, self.notes_manager, self.character_manager, self.relationship_manager, self)
        self.register_attached_window(self.settings_dialog, "settings")
        self.settings_dialog.show()
        self.position_attached_window(self.settings_dialog, force=True)
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def on_pomodoro_phase_changed(self, phase: str) -> None:
        if phase == PHASE_FOCUS:
            self.set_state("thinking")
        elif phase in {"short_break", "long_break"}:
            self.set_state("sleep")
        elif phase == "stopped":
            self.set_state("idle")

    def on_pomodoro_focus_completed(self) -> None:
        self.set_state("happy")
        self.award_relationship_exp(EXP_POMODORO_DONE)
        prompt = QMessageBox(self)
        prompt.setWindowTitle("Koji")
        prompt.setText("本轮专注完成，要不要记录一下刚才推进了什么？")
        prompt.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        prompt.setDefaultButton(QMessageBox.Yes)
        self.position_attached_window(prompt, force=True, ignore_follow_setting=True)
        reply = prompt.exec()
        if reply == QMessageBox.Yes:
            self.open_report_panel()
            if self.report_panel is not None:
                self.report_panel.content.setFocus()

    def create_note(self) -> None:
        pos = self.frameGeometry().topRight() + QPoint(24, 0)
        note = self.notes_manager.create_note(x=pos.x(), y=pos.y())
        self.open_note_window(note)

    def open_visible_notes(self) -> None:
        for note in self.notes_manager.all_notes():
            if note.visible:
                self.open_note_window(note)

    def open_note_window(self, note: Note) -> None:
        window = self.note_windows.get(note.id)
        if window is None:
            window = NoteCardWindow(note, self.notes_manager, self.tag_manager, self.note_to_report, self)
            self.note_windows[note.id] = window
            window.finished.connect(lambda _result, note_id=note.id: self.note_windows.pop(note_id, None))
        note.visible = True
        self.notes_manager.touch(note)
        window.show()
        window.raise_()
        window.activateWindow()

    def open_notes_list(self) -> None:
        if self.notes_list_dialog is None:
            self.notes_list_dialog = NotesListDialog(self.notes_manager, self.tag_manager, self.open_note_window, self.delete_note, self)
            self.register_attached_window(self.notes_list_dialog, "notes")
        self.notes_list_dialog.refresh_tags()
        self.notes_list_dialog.refresh()
        self.notes_list_dialog.show()
        self.position_attached_window(self.notes_list_dialog, force=True)
        self.notes_list_dialog.raise_()
        self.notes_list_dialog.activateWindow()

    def delete_note(self, note_id: str) -> None:
        window = self.note_windows.pop(note_id, None)
        if window is not None:
            window.close()
        self.notes_manager.delete(note_id)

    def note_to_report(self, note: Note) -> None:
        content = note.content.strip()
        if not content:
            QMessageBox.information(self, "Koji", "便签正文为空，先写点内容吧。")
            return
        category = self.tag_manager.name_for(note.tag_id, "随手记")
        self.report_manager.add_record(category, content)
        self.open_report_panel()
        if self.report_panel is not None:
            self.report_panel.refresh_records()
        self.bubble.show_message("已把便签转成今日日报记录。", self)

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
            self.update_attached_windows_position()
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
        self.update_attached_windows_position()
        super().moveEvent(event)

    def register_attached_window(self, window: QWidget, name: str) -> None:
        if window not in self._attached_window_names:
            window.installEventFilter(self)
        self._attached_window_names[window] = name

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched in self._attached_window_names and event.type() == QEvent.Move and not self._positioning_attached_window:
            if self.attached_window_follow_enabled and watched.isVisible():
                self._detached_attached_windows.add(watched)
        return super().eventFilter(watched, event)

    def set_attached_window_follow(self, enabled: bool) -> None:
        self.attached_window_follow_enabled = enabled
        self.settings_manager.set("attached_windows_follow_koji", enabled)
        if enabled:
            self._detached_attached_windows.clear()
            self.update_attached_windows_position(force=True)
            self.bubble.follow(self)
            self.bubble.show_message("窗口跟随 Koji：开。别担心，我会把小跟班们带上。", self)
        else:
            self.bubble.show_message("窗口跟随 Koji：关。你摆好的窗口我不乱碰。", self)

    def attached_windows(self) -> list[QWidget]:
        windows: list[QWidget] = []
        for window in (self.report_panel, self.chat_dialog, self.pomodoro_window, self.notes_list_dialog, self.settings_dialog):
            if window is not None:
                windows.append(window)
        return windows

    def position_attached_window(self, window: QWidget, preferred: str = "right", force: bool = False, ignore_follow_setting: bool = False) -> None:
        if not window.isVisible() and not force:
            return
        if not self.attached_window_follow_enabled and not ignore_follow_setting:
            return
        if force:
            self._detached_attached_windows.discard(window)
        if not force and window in self._detached_attached_windows:
            return

        pet_rect = self.frameGeometry()
        window_size = window.frameGeometry().size() if force else window.size()
        screen = QGuiApplication.screenAt(pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        gap = 16
        right_x = pet_rect.right() + gap
        left_x = pet_rect.left() - window_size.width() - gap
        if preferred == "right" and right_x + window_size.width() <= available.right():
            x = right_x
        elif left_x >= available.left():
            x = left_x
        else:
            x = max(available.left(), min(right_x, available.right() - window_size.width()))

        y = pet_rect.top()
        if y + window_size.height() > available.bottom():
            y = available.bottom() - window_size.height()
        if y < available.top():
            y = available.top()

        self._positioning_attached_window = True
        try:
            window.move(x, y)
        finally:
            self._positioning_attached_window = False

    def update_attached_windows_position(self, force: bool = False) -> None:
        for window in self.attached_windows():
            self.position_attached_window(window, force=force)

    def show_context_menu(self, position: QPoint) -> None:
        self.mark_user_interaction()
        menu = QMenu(self)
        open_report = QAction("打开日报面板", self)
        open_report.triggered.connect(self.open_report_panel)
        chat = QAction("和 Koji 聊两句", self)
        chat.triggered.connect(self.open_chat_dialog)
        ai_report = QAction("AI 整理日报", self)
        ai_report.triggered.connect(self.ai_report_from_menu)
        relationship_action = QAction("角色信息", self)
        relationship_action.triggered.connect(self.open_relationship_panel)
        collection_action = QAction("收藏柜", self)
        collection_action.triggered.connect(self.open_collection_dialog)
        animation_action = QAction("关闭动画" if self.animations_enabled else "开启动画", self)
        animation_action.triggered.connect(self.toggle_animations)
        start_pomodoro = QAction("开始番茄钟", self)
        start_pomodoro.triggered.connect(self.start_pomodoro)
        pause_pomodoro = QAction("暂停/继续番茄钟", self)
        pause_pomodoro.triggered.connect(self.pomodoro_manager.toggle_pause)
        stop_pomodoro = QAction("停止番茄钟", self)
        stop_pomodoro.triggered.connect(self.stop_pomodoro)
        pomodoro_settings = QAction("番茄钟设置", self)
        pomodoro_settings.triggered.connect(self.open_settings_dialog)
        new_note = QAction("新建便签", self)
        new_note.triggered.connect(self.create_note)
        open_notes = QAction("打开便签列表", self)
        open_notes.triggered.connect(self.open_notes_list)
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        follow_action = QAction(f"窗口跟随 Koji：{'开' if self.attached_window_follow_enabled else '关'}", self)
        follow_action.setCheckable(True)
        follow_action.setChecked(self.attached_window_follow_enabled)
        follow_action.triggered.connect(lambda checked: self.set_attached_window_follow(bool(checked)))

        menu.addAction(open_report)
        menu.addAction(chat)
        menu.addAction(ai_report)
        menu.addAction(relationship_action)
        menu.addAction(collection_action)
        menu.addSeparator()
        for action in (start_pomodoro, pause_pomodoro, stop_pomodoro, pomodoro_settings):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(new_note)
        menu.addAction(open_notes)
        menu.addSeparator()
        menu.addAction(animation_action)
        menu.addAction(follow_action)
        menu.addAction(settings_action)

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
        self.temporary_state("idle")
        if self.report_panel is None:
            self.report_panel = ReportPanel(self.report_manager, self.ai_runtime, self.category_manager, self.tag_manager, self.notes_manager, self.relationship_manager, self.collection_manager, self.temporary_state, self.on_report_generated_success, self)
            self.register_attached_window(self.report_panel, "report")
        self.report_panel.refresh_ai_notice()
        self.report_panel.refresh_records()
        self.report_panel.refresh_character_card()
        self.report_panel.show()
        self.position_attached_window(self.report_panel, force=True)
        self.report_panel.raise_()
        self.report_panel.activateWindow()

    def open_chat_dialog(self) -> None:
        self.temporary_state("success")
        if self.chat_dialog is None:
            self.chat_dialog = ChatDialog(self.chat_manager, self.on_chat_success, self)
            self.register_attached_window(self.chat_dialog, "chat")
        self.chat_dialog.refresh()
        self.chat_dialog.show()
        self.position_attached_window(self.chat_dialog, force=True)
        self.chat_dialog.raise_()
        self.chat_dialog.activateWindow()


    def position_report_panel(self, force: bool = False) -> None:
        if self.report_panel is not None:
            self.position_attached_window(self.report_panel, force=force)

    def position_chat_dialog(self) -> None:
        if self.chat_dialog is not None:
            self.position_attached_window(self.chat_dialog)

    def ai_report_from_menu(self) -> None:
        self.open_report_panel()
        if self.report_panel is not None:
            self.report_panel.generate_ai()

    def shutdown(self) -> None:
        for timer in (self.idle_timer, self.drag_wobble_timer, self.random_idle_timer, self.inactivity_timer):
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
