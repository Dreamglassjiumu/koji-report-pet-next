"""Koji chat history and AI prompt orchestration."""
from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

from ai_runtime_manager import AIRuntimeManager
from storage import CHAT_HISTORY_FILE, load_json, save_json

SYSTEM_PROMPT = """你是 Koji，一个陪伴文案策划工作的桌宠。你不是严肃客服，也不是正式办公机器人。你说话有点贱贱的、轻松、吐槽感强，但要友好、可爱、不过界。你可以提醒用户记录日报、整理思路、陪用户闲聊，也可以用一点中英日混合的小梗，但不要过度。  \n当用户只是闲聊，比如问“晚上好”“你吃了吗”“累死了”，你要自然回应，不要强行扯到任务确认。  \n当用户问工作问题时，你可以给出简洁实用的建议。  \n当用户提到日报、工作记录、文案、任务、角色、剧本、pitch 时，你可以主动建议把内容记录到日报。  \n不要输出露骨、歧视、攻击现实群体或恶毒辱骂内容。  \n不要每句话都很长。聊天回复应自然、短一些，像桌宠在和用户对话。"""

CHAT_UNAVAILABLE_FALLBACK = (
    "Koji 的本地脑子还没装好，现在只能装可爱。"
    "等 model.gguf 放进去后，我再认真陪你聊。"
)
CHAT_EMPTY_REPLY = "Koji 刚刚张嘴但没发出声音……本地模型返回了空内容，等我缓一秒再试。"
CHAT_ERROR_REPLY = "Koji 的本地脑子刚刚打结了：{error}\n日报功能不受影响，可以稍后再试。"



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

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.recent_context(rounds=10))
        ok, answer = self.ai_runtime.chat(messages, temperature=0.7, top_p=0.9, max_tokens=800)
        if not ok:
            runtime_error = answer.strip()
            if any(keyword in runtime_error for keyword in ("未检测到本地 AI 运行器", "未检测到本地 AI 模型", "本地 AI 启动失败", "启动超时", "进程已退出", "端口")):
                answer = unavailable_reply or CHAT_UNAVAILABLE_FALLBACK
            else:
                answer = CHAT_ERROR_REPLY.format(error=runtime_error or "没有拿到错误信息，主打一个神秘掉线")
            self.add_message("assistant", answer)
            return False, answer
        answer = answer.strip()
        if not answer:
            answer = CHAT_EMPTY_REPLY
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
