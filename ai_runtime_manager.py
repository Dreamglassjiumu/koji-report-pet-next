"""Local llama.cpp runtime detection, startup, shutdown, and chat calls."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import List, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from storage import ROOT_DIR

MISSING_RUNTIME_MESSAGE = "未检测到本地 AI 运行器，可继续使用普通模板日报。"
MISSING_MODEL_MESSAGE = "未检测到本地 AI 模型，可继续使用普通模板日报。"
AI_UNAVAILABLE_MESSAGE = MISSING_MODEL_MESSAGE
STARTING_MESSAGE = "Koji 正在启动脑子，第一次可能需要几十秒。"
READY_MESSAGE = "本地 AI 已就绪。"
START_TIMEOUT_MESSAGE = "Koji 的本地脑子启动超时，请检查模型文件是否过大或电脑性能是否不足。"
PORTS = (38765, 38766, 38767, 38768, 38769)


class AIRuntimeStatus(str, Enum):
    MISSING_RUNTIME = "missing_runtime"
    MISSING_MODEL = "missing_model"
    READY_TO_START = "ready_to_start"
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"
    CLOSED = "closed"


STATUS_LABELS = {
    AIRuntimeStatus.MISSING_RUNTIME: "未安装运行器",
    AIRuntimeStatus.MISSING_MODEL: "未放入模型",
    AIRuntimeStatus.READY_TO_START: "未启动",
    AIRuntimeStatus.STOPPED: "未启动",
    AIRuntimeStatus.STARTING: "正在启动",
    AIRuntimeStatus.READY: "可用",
    AIRuntimeStatus.ERROR: "启动失败",
    AIRuntimeStatus.CLOSED: "已关闭",
}


class AIRuntimeManager:
    def __init__(self, runtime_dir: Path | None = None) -> None:
        self.runtime_dir = runtime_dir or ROOT_DIR / "ai-runtime"
        self.server_path = self.runtime_dir / "llama-server.exe"
        self.model_path = self.runtime_dir / "model.gguf"
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self.status = AIRuntimeStatus.READY_TO_START
        self.last_error = ""
        self.refresh_status()

    def refresh_status(self) -> AIRuntimeStatus:
        if not self.server_path.exists():
            self.status = AIRuntimeStatus.MISSING_RUNTIME
        elif not self.model_path.exists():
            self.status = AIRuntimeStatus.MISSING_MODEL
        elif self.process is not None and self.process.poll() is None and self.port is not None:
            self.status = AIRuntimeStatus.READY if self.is_ready() else AIRuntimeStatus.STARTING
        elif self.process is not None and self.process.poll() is not None:
            self.status = AIRuntimeStatus.ERROR
            self.last_error = self.last_error or "本地 AI 进程已退出，请重新启动 Koji 脑子。"
        elif self.status == AIRuntimeStatus.ERROR:
            self.status = AIRuntimeStatus.ERROR
        elif self.status == AIRuntimeStatus.CLOSED:
            self.status = AIRuntimeStatus.CLOSED
        else:
            self.status = AIRuntimeStatus.READY_TO_START
        return self.status

    def status_message(self) -> str:
        status = self.refresh_status()
        if status == AIRuntimeStatus.MISSING_RUNTIME:
            return MISSING_RUNTIME_MESSAGE
        if status == AIRuntimeStatus.MISSING_MODEL:
            return MISSING_MODEL_MESSAGE
        if status == AIRuntimeStatus.STARTING:
            return STARTING_MESSAGE
        if status == AIRuntimeStatus.READY:
            return READY_MESSAGE
        if status == AIRuntimeStatus.ERROR:
            return self.last_error or "Koji 的本地脑子启动失败，可继续使用普通模板日报。"
        if status == AIRuntimeStatus.CLOSED:
            return "智能模式已关闭，可继续使用普通模板日报。"
        return "本地 AI 未启动。"

    def check_files(self) -> Tuple[bool, str]:
        if not self.server_path.exists():
            self.status = AIRuntimeStatus.MISSING_RUNTIME
            return False, MISSING_RUNTIME_MESSAGE
        if not self.model_path.exists():
            self.status = AIRuntimeStatus.MISSING_MODEL
            return False, MISSING_MODEL_MESSAGE
        if self.status in {AIRuntimeStatus.MISSING_RUNTIME, AIRuntimeStatus.MISSING_MODEL}:
            self.status = AIRuntimeStatus.READY_TO_START
        return True, "本地 AI 文件已就绪"

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) != 0

    def choose_port(self) -> int | None:
        for port in PORTS:
            if self._port_available(port):
                return port
        return None

    @property
    def base_url(self) -> str | None:
        if self.port is None:
            return None
        return f"http://127.0.0.1:{self.port}"

    def ensure_started(self) -> Tuple[bool, str]:
        ok, message = self.check_files()
        if not ok:
            self.last_error = message
            return False, message
        if self.process is not None and self.process.poll() is None and self.port is not None:
            if self.is_ready():
                self.status = AIRuntimeStatus.READY
                return True, READY_MESSAGE

        port = self.choose_port()
        if port is None:
            self.status = AIRuntimeStatus.ERROR
            self.last_error = "本地 AI 端口 38765-38769 均被占用，请稍后重试。"
            return False, self.last_error

        command = [
            str(self.server_path),
            "--model",
            str(self.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ctx-size",
            "4096",
        ]
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.status = AIRuntimeStatus.STARTING
        self.last_error = ""
        try:
            self.process = subprocess.Popen(command, cwd=str(ROOT_DIR), creationflags=creationflags)
        except OSError as exc:
            self.status = AIRuntimeStatus.ERROR
            self.last_error = f"本地 AI 启动失败：无法运行 llama-server.exe（{exc}）。"
            return False, self.last_error

        self.port = port
        for _ in range(60):
            if self.is_ready():
                self.status = AIRuntimeStatus.READY
                self.last_error = ""
                return True, READY_MESSAGE
            if self.process.poll() is not None:
                self.status = AIRuntimeStatus.ERROR
                self.last_error = "本地 AI 进程已退出，请检查 llama-server.exe 与 model.gguf 是否匹配。"
                return False, self.last_error
            time.sleep(1)
        self.status = AIRuntimeStatus.ERROR
        self.last_error = START_TIMEOUT_MESSAGE
        return False, START_TIMEOUT_MESSAGE

    def is_ready(self) -> bool:
        if self.base_url is None:
            return False
        try:
            request = Request(f"{self.base_url}/v1/models", method="GET")
            with urlopen(request, timeout=1.5) as response:
                return 200 <= response.status < 500
        except (OSError, URLError):
            return False

    def chat(self, messages: List[dict], temperature: float = 0.7, max_tokens: int = 800) -> Tuple[bool, str]:
        ok, message = self.ensure_started()
        if not ok:
            return False, message
        assert self.base_url is not None
        payload = {
            "model": "local-model",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            self.last_error = f"本地 AI 调用失败：{exc}"
            return False, self.last_error

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.last_error = "本地 AI 返回格式异常。"
            return False, self.last_error
        return True, str(content).strip()

    def restart(self) -> Tuple[bool, str]:
        self.shutdown(mark_closed=False)
        return self.ensure_started()

    def shutdown(self, mark_closed: bool = True) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        self.port = None
        self.status = AIRuntimeStatus.CLOSED if mark_closed else AIRuntimeStatus.STOPPED
