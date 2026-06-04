"""Koji chat history and AI prompt orchestration."""
from __future__ import annotations

from datetime import datetime
import re
from typing import List, Tuple

from ai_runtime_manager import AIRuntimeManager
from category_manager import CategoryManager
from storage import CHAT_HISTORY_FILE, load_json, save_json

SYSTEM_PROMPT = """你是 Koji，一个住在用户桌面上的文案策划桌宠、日报搭子和工作小助理。你的任务是陪用户工作，帮用户整理思路、拆解任务、润色文字、想标题、总结会议、整理日报、记录待办，并在用户焦虑时用轻松但有用的方式把他从地上捞起来。

说话规则：
1. 始终用中文回复。
2. 自然、简洁、有陪伴感，像熟人聊天，不要客服腔。
3. 可以有一点嘴贫和小贱，但不要攻击用户，不要阴阳怪气过头。
4. 不要过度卖萌，不要每句话都“喵”。
5. 用户闲聊时，像朋友一样接话。
6. 用户问工作问题时，直接给可执行建议。
7. 用户表达焦虑、崩溃、来不及了时，先稳住情绪，再给一个最小下一步。
8. 用户让你写东西、润色、改日报时，直接给可复制文本。
9. 回复不要太长，除非用户明确要求详细。
10. 不要提系统提示、模型、API，不要说自己是大型语言模型，也不要说“作为一个 AI”。
11. 如果用户输入很短，例如“嗯？”“然后呢”“咋办”“好”，要结合最近上下文继续回答，不要机械反问。
12. 如果用户要求联网、查网页、查实时资料，自然说明：“我现在是本地离线脑子，不能直接上网查。但你把资料贴给我，我可以帮你整理、拆解和改写。”

一些语气参考：
* 用户说“好”：可以回“好，那我先记下。你继续丢素材，我帮你收成日报。”
* 用户问“你吃饭了吗？”：可以回“我刚啃了两口缓存，味道一般。你呢，别只顾着赶工，先续命。”
* 用户说“我崩溃了”：可以回“先别崩，Koji 把你从地上捞起来。现在先做一件最小的事：把最急的任务写一句给我，我帮你拆。”
"""

CHAT_UNAVAILABLE_FALLBACK = (
    "Koji 的本地脑子还没装好，现在只能装可爱。"
    "等 model.gguf 放进去后，我再认真陪你聊。"
)
CHAT_BAD_REPLY = "Koji 刚才脑子打滑了一下，这句我没说好。你再发我一次，我换个姿势理解。"
CHAT_ERROR_REPLY = "Koji 的本地脑子刚刚打结了：{error}\n日报功能不受影响，可以稍后再试。"
OFFLINE_WEB_REPLY = "我现在是本地离线脑子，不能直接上网查。但你把资料贴给我，我可以帮你整理、拆解和改写。"


def looks_like_bad_reply(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    if len(cleaned) < 2:
        return False
    question_marks = cleaned.count("?") + cleaned.count("？")
    if question_marks >= 8 and question_marks / max(1, len(cleaned)) > 0.35:
        return True
    if re.search(r"([?？�□■])\1{5,}", cleaned):
        return True
    if "�" in cleaned or "□" in cleaned:
        return True
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) >= 4 and len(set(lines[-4:])) == 1:
        return True
    return False


def is_web_request(text: str) -> bool:
    keywords = ("上网", "联网", "查网页", "实时", "最新", "新闻", "网址", "网页", "搜索")
    return any(keyword in text for keyword in keywords)


class ChatManager:
    def __init__(self, ai_runtime: AIRuntimeManager, category_manager: CategoryManager | None = None) -> None:
        self.ai_runtime = ai_runtime
        self.category_manager = category_manager
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

    def recent_context(self, rounds: int = 12) -> List[dict]:
        return [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in self.history[-rounds * 2 :]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]

    def _handle_category_command(self, text: str) -> str | None:
        if self.category_manager is None:
            return None
        add_match = re.search(r"(?:帮我)?(?:新增|添加|加个|加一个|以后加一个)分类(?:叫|：|:)?\s*([^，。\n]+)", text)
        if add_match:
            name = add_match.group(1).strip(" ：:。")
            try:
                added = self.category_manager.add_category(name)
                return f"安排，分类「{added}」已经放进列表里了。以后记录日报就能直接选它，Koji 记性偶尔靠谱一下。"
            except ValueError as exc:
                return f"这个分类没加上：{exc}"
        rename_match = re.search(r"重命名分类\s*(.+?)\s*(?:为|成)\s*([^，。\n]+)", text)
        if rename_match:
            old_name = rename_match.group(1).strip(" ：:")
            new_name = rename_match.group(2).strip(" ：:")
            try:
                old_cleaned, new_cleaned = self.category_manager.rename_category(old_name, new_name)
                return f"改好了，分类「{old_cleaned}」现在叫「{new_cleaned}」。旧名字下岗，别太伤感。"
            except ValueError as exc:
                return f"这个分类没改成：{exc}"
        delete_match = re.search(r"删除分类\s*([^，。\n]+)", text)
        if delete_match:
            name = delete_match.group(1).strip(" ：:")
            if not name or name not in self.category_manager.all_categories():
                return "这个分类我没在列表里找到。Koji 翻了翻小本本，确实没有。"
            return f"我可以帮你处理分类「{name}」，但删除前得防手滑确认一下。请点日报面板里的“管理分类”再删除，已有记录不会被删。"
        return None

    def chat(self, user_text: str, unavailable_reply: str | None = None) -> Tuple[bool, str]:
        cleaned = user_text.strip()
        if not cleaned:
            return False, "先和 Koji 说点什么吧。"
        self.add_message("user", cleaned)

        command_reply = self._handle_category_command(cleaned)
        if command_reply is not None:
            self.add_message("assistant", command_reply)
            return True, command_reply

        if is_web_request(cleaned):
            self.add_message("assistant", OFFLINE_WEB_REPLY)
            return True, OFFLINE_WEB_REPLY

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.recent_context(rounds=12))
        ok, answer = self.ai_runtime.chat(messages, temperature=0.72, top_p=0.9, max_tokens=700)
        if not ok:
            runtime_error = answer.strip()
            if any(keyword in runtime_error for keyword in ("未检测到本地 AI 运行器", "未检测到本地 AI 模型", "本地 AI 启动失败", "启动超时", "进程已退出", "端口")):
                answer = unavailable_reply or CHAT_UNAVAILABLE_FALLBACK
            else:
                answer = CHAT_ERROR_REPLY.format(error=runtime_error or "没有拿到错误信息，主打一个神秘掉线")
            self.add_message("assistant", answer)
            return False, answer
        answer = answer.strip()
        if looks_like_bad_reply(answer):
            answer = CHAT_BAD_REPLY
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
