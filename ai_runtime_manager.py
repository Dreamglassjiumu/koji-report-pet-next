"""Local llama.cpp runtime detection, startup, shutdown, and chat calls."""
from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import List, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from storage import ROOT_DIR

AI_UNAVAILABLE_MESSAGE = "当前便携包未包含本地 AI 模型，可继续使用普通日报模式"


class AIRuntimeManager:
    def __init__(self, runtime_dir: Path | None = None) -> None:
        self.runtime_dir = runtime_dir or ROOT_DIR / "ai-runtime"
        self.server_path = self.runtime_dir / "llama-server.exe"
        self.model_path = self.runtime_dir / "model.gguf"
        self.process: subprocess.Popen | None = None
        self.port: int | None = None

    def check_files(self) -> Tuple[bool, str]:
        if not self.server_path.exists():
            return False, f"缺少 {self.server_path.relative_to(ROOT_DIR)}"
        if not self.model_path.exists():
            return False, f"缺少 {self.model_path.relative_to(ROOT_DIR)}"
        return True, "本地 AI 文件已就绪"

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) != 0

    def choose_port(self) -> int | None:
        for port in (38765, 38766, 38767):
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
            return False, AI_UNAVAILABLE_MESSAGE
        if self.process is not None and self.process.poll() is None and self.port is not None:
            return True, "本地 AI 已启动"

        port = self.choose_port()
        if port is None:
            return False, "本地 AI 端口 38765-38767 均被占用，请稍后重试。"

        command = [
            str(self.server_path),
            "-m",
            str(self.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        try:
            self.process = subprocess.Popen(command, cwd=str(self.runtime_dir))
        except OSError as exc:
            return False, f"本地 AI 启动失败：{exc}"

        self.port = port
        for _ in range(30):
            if self.is_ready():
                return True, "本地 AI 已启动"
            if self.process.poll() is not None:
                return False, "本地 AI 进程已退出，请检查模型文件。"
            time.sleep(0.5)
        return False, "本地 AI 启动中但尚未响应，请稍后再试。"

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
            "model": "local-koji",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
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
            return False, f"本地 AI 调用失败：{exc}"

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return False, "本地 AI 返回格式异常。"
        return True, str(content).strip()

    def shutdown(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
