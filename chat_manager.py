"""Koji chat history and AI prompt orchestration."""
from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

from ai_runtime_manager import AIRuntimeManager, AI_UNAVAILABLE_MESSAGE
from storage import CHAT_HISTORY_FILE, load_json, save_json

SYSTEM_PROMPT = (
    "你是 Koji，一只温柔、有点俏皮的日报桌宠。"
    "你会用简短中文回应，帮助用户整理想法，不联网，不声称自己能访问云端。"
)


class ChatManager:
    def __init__(self, ai_runtime: AIRuntimeManager) -> None:
        self.ai_runtime = ai_runtime
        self.history: List[dict] = []
        self.load()

    def load(self) -> None:
        data = load_json(CHAT_HISTORY_FILE, [])
        self.history = data if isinstance(data, list) else []

    def save(self) -> None:
        save_json(CHAT_HISTORY_FILE, self.history[-80:])

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content, "time": datetime.now().isoformat(timespec="seconds")})
        self.save()

    def chat(self, user_text: str, unavailable_reply: str | None = None) -> Tuple[bool, str]:
        cleaned = user_text.strip()
        if not cleaned:
            return False, "先和 Koji 说点什么吧。"
        self.add_message("user", cleaned)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": item.get("role", "user"), "content": item.get("content", "")} for item in self.history[-12:])
        ok, answer = self.ai_runtime.chat(messages, temperature=0.8, max_tokens=400)
        if not ok:
            answer = unavailable_reply or AI_UNAVAILABLE_MESSAGE
            self.add_message("assistant", answer)
            return False, answer
        self.add_message("assistant", answer)
        return True, answer

    def clear(self) -> None:
        self.history = []
        self.save()

    def render_history(self) -> str:
        if not self.history:
            return "Koji：可以跟我聊聊今天做了什么。"
        names = {"user": "你", "assistant": "Koji"}
        return "\n".join(f"{names.get(item.get('role'), item.get('role'))}：{item.get('content', '')}" for item in self.history[-30:])
