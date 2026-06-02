"""Koji chat history and AI prompt orchestration."""
from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

from ai_runtime_manager import AIRuntimeManager, AI_UNAVAILABLE_MESSAGE
from storage import CHAT_HISTORY_FILE, load_json, save_json

SYSTEM_PROMPT = (
    "你是 Koji，文案组桌宠。你说话有点耍宝、有点欠欠的，可以中英日混合，但要公司内部安全。"
    "你可以吐槽日报、提醒记录、帮用户整理思路。不要输出露骨、歧视、攻击现实群体或过度冒犯内容。"
    "遇到工作问题时优先给出实用建议。"
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

    def recent_context(self, rounds: int = 10) -> List[dict]:
        # One round is user + assistant. Keep at most the last 20 chat messages.
        return [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in self.history[-rounds * 2 :]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]

    def chat(self, user_text: str, unavailable_reply: str | None = None) -> Tuple[bool, str]:
        cleaned = user_text.strip()
        if not cleaned:
            return False, "先和 Koji 说点什么吧。"
        self.add_message("user", cleaned)

        ok, file_message = self.ai_runtime.check_files()
        if not ok:
            answer = unavailable_reply or AI_UNAVAILABLE_MESSAGE
            self.add_message("assistant", answer)
            return False, answer

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.recent_context(rounds=10))
        ok, answer = self.ai_runtime.chat(messages, temperature=0.8, max_tokens=500)
        if not ok:
            answer = f"Koji 的本地脑子刚刚卡住了：{answer}\n日报功能不受影响，可以稍后再试。"
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
