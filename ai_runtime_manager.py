"""Local AI runtime detection, model switching, startup, shutdown, and chat calls.

Emergency KoboldCpp-first version.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, List, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from storage import ROOT_DIR


MISSING_RUNTIME_MESSAGE = "未检测到本地 AI 运行器，可继续使用普通模板日报。"
MISSING_MODEL_MESSAGE = "未检测到本地 AI 模型，可继续使用普通模板日报。"
AI_UNAVAILABLE_MESSAGE = MISSING_MODEL_MESSAGE

STARTING_MESSAGE = "Koji 正在启动本地脑子，第一次可能需要几十秒。"
READY_MESSAGE = "本地 AI 已就绪，可以整理日报。"
START_TIMEOUT_MESSAGE = "Koji 的本地脑子启动超时，请检查模型文件或电脑性能。"

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


def _model_id_from_file(filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem or filename


def _model_name_from_file(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    lower = filename.lower()
    if "1.5b" in lower or "1-5b" in lower:
        return f"轻量稳定模式 {stem}".strip()
    if re.search(r"3\s*b", stem, re.IGNORECASE):
        return f"轻量模式 {stem}".strip()
    if re.search(r"8\s*b", stem, re.IGNORECASE):
        return f"高质量模式 {stem}".strip()
    return Path(filename).name


def _model_description_from_file(filename: str) -> str:
    lower = filename.lower()
    if "1.5b" in lower or "1-5b" in lower:
        return "体积更小，启动更快，适合内网机本地日报生成"
    if re.search(r"3\s*b", filename, re.IGNORECASE):
        return "速度快，适合日常记录和普通日报"
    if re.search(r"8\s*b", filename, re.IGNORECASE):
        return "质量更高，但生成可能需要 1～3 分钟"
    return "本地 GGUF 模型"


class AIRuntimeManager:
    def __init__(self, runtime_dir: Path | None = None) -> None:
        self.runtime_dir = runtime_dir or ROOT_DIR / "ai-runtime"

        # New preferred backend.
        self.kobold_path = self.runtime_dir / "koboldcpp.exe"

        # Legacy fallback backend.
        self.server_path = self.runtime_dir / "llama-server.exe"

        self.legacy_model_path = self.runtime_dir / "model.gguf"
        self.model_path = self.legacy_model_path

        self.models_dir = self.runtime_dir / "models"
        self.config_path = self.runtime_dir / "model_config.json"

        self.process: subprocess.Popen | None = None
        self.process_backend: str | None = None
        self.owned_process = False

        self.port: int | None = None
        self.status = AIRuntimeStatus.READY_TO_START
        self.last_error = ""

        self._lock = threading.RLock()
        self._generating_count = 0
        self._cancel_generation = False

        self.refresh_status()

    def detect_backend(self) -> str | None:
        if self.kobold_path.exists():
            return "koboldcpp"
        if self.server_path.exists():
            return "llama_server"
        return None

    def backend_label(self) -> str:
        backend = self.detect_backend()
        if backend == "koboldcpp":
            return "KoboldCpp"
        if backend == "llama_server":
            return "llama-server"
        return "未检测到"

    def _scan_model_files(self) -> list[Path]:
        if not self.models_dir.exists():
            return []
        return sorted(path for path in self.models_dir.glob("*.gguf") if path.is_file())

    def _default_model_entry(self, path: Path) -> dict[str, str]:
        return {
            "id": _model_id_from_file(path.name),
            "name": _model_name_from_file(path.name),
            "file": path.name,
            "description": _model_description_from_file(path.name),
        }

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_config(self, config: dict[str, Any]) -> None:
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
        except OSError as exc:
            self.last_error = f"模型配置保存失败：{exc}"

    def _prefer_model_file(self, models: list[dict[str, str]]) -> str:
        for model in models:
            file_name = model.get("file", "").lower()
            if "1.5b" in file_name or "1-5b" in file_name:
                return model["file"]
        return models[0]["file"] if models else ""

    def _models_config(self, write_default: bool = True) -> dict[str, Any]:
        model_files = self._scan_model_files()
        if not model_files:
            return {
                "current_model": "model.gguf" if self.legacy_model_path.exists() else "",
                "models": [],
            }

        existing_config = self._load_config()
        existing_models = existing_config.get("models") if isinstance(existing_config.get("models"), list) else []

        models_by_file: dict[str, dict[str, str]] = {}
        for item in existing_models:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file") or "")
            if not file_name:
                continue
            models_by_file[file_name] = {
                "id": str(item.get("id") or _model_id_from_file(file_name)),
                "name": str(item.get("name") or _model_name_from_file(file_name)),
                "file": file_name,
                "description": str(item.get("description") or _model_description_from_file(file_name)),
            }

        models: list[dict[str, str]] = []
        for path in model_files:
            models.append(models_by_file.get(path.name, self._default_model_entry(path)))

        available_files = {model["file"] for model in models}
        available_ids = {model["id"] for model in models}

        current_model = str(existing_config.get("current_model") or "")
        if current_model not in available_files and current_model not in available_ids:
            current_model = self._prefer_model_file(models)

        config = {
            "current_model": current_model,
            "models": models,
            "backend": "koboldcpp" if self.kobold_path.exists() else "llama_server",
        }

        if write_default and not self.config_path.exists():
            self._save_config(config)

        return config

    def list_models(self) -> list[dict[str, str]]:
        with self._lock:
            config = self._models_config()
            models = list(config.get("models") or [])
            if models:
                return models

            if self.legacy_model_path.exists():
                return [
                    {
                        "id": "legacy-model",
                        "name": "旧版 model.gguf",
                        "file": "model.gguf",
                        "description": "兼容旧结构：ai-runtime/model.gguf",
                    }
                ]

            return []

    def get_current_model(self) -> dict[str, str] | None:
        with self._lock:
            models = self.list_models()
            if not models:
                return None

            config = self._models_config(write_default=False)
            current = str(config.get("current_model") or "")

            for model in models:
                if model.get("id") == current or model.get("file") == current:
                    return model

            preferred = self._prefer_model_file(models)
            for model in models:
                if model.get("file") == preferred:
                    return model

            return models[0]

    def set_current_model(self, model_id_or_file: str) -> Tuple[bool, str]:
        with self._lock:
            models = self.list_models()
            if not models:
                self.status = AIRuntimeStatus.MISSING_MODEL
                return False, MISSING_MODEL_MESSAGE

            selected = next(
                (
                    model
                    for model in models
                    if model.get("id") == model_id_or_file or model.get("file") == model_id_or_file
                ),
                None,
            )

            if selected is None:
                return False, f"没有找到这个模型：{model_id_or_file}"

            if selected.get("file") == "model.gguf" and not self._scan_model_files():
                self.model_path = self.legacy_model_path
                return True, "已选择旧版 model.gguf。"

            config = self._models_config(write_default=False)
            config["current_model"] = selected["file"]
            config["models"] = [model for model in models if model.get("file") != "model.gguf"]
            config["backend"] = "koboldcpp" if self.kobold_path.exists() else "llama_server"
            self._save_config(config)

            self.model_path = self.models_dir / selected["file"]
            return True, f"已选择模型：{selected.get('name') or selected.get('file')}"

    def get_current_model_path(self) -> Path | None:
        with self._lock:
            if self._scan_model_files():
                current = self.get_current_model()
                if current is None:
                    return None

                path = self.models_dir / current["file"]
                self.model_path = path
                return path if path.exists() else None

            if self.legacy_model_path.exists():
                self.model_path = self.legacy_model_path
                return self.legacy_model_path

            self.model_path = self.legacy_model_path
            return None

    def is_generating(self) -> bool:
        with self._lock:
            return self._generating_count > 0

    def cancel_generation(self) -> None:
        with self._lock:
            self._cancel_generation = True

    def refresh_status(self) -> AIRuntimeStatus:
        with self._lock:
            if self.detect_backend() is None:
                self.status = AIRuntimeStatus.MISSING_RUNTIME
            elif self.get_current_model_path() is None:
                self.status = AIRuntimeStatus.MISSING_MODEL
            elif self.port is not None and self.is_ready():
                self.status = AIRuntimeStatus.READY
            elif self.process is not None and self.process.poll() is None and self.port is not None:
                self.status = AIRuntimeStatus.STARTING
            elif self.process is not None and self.process.poll() is not None:
                self.status = AIRuntimeStatus.ERROR
                backend_name = "KoboldCpp" if self.process_backend == "koboldcpp" else "llama-server"
                self.last_error = self.last_error or f"本地 AI 进程已退出，请检查 {backend_name} 与模型文件是否匹配。"
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

        backend = self.detect_backend()
        if backend == "koboldcpp":
            return "检测到 KoboldCpp 本地运行器，已优先使用兼容后端。"
        if backend == "llama_server":
            return "检测到 llama-server 本地运行器。"
        return "本地 AI 未启动。"

    def check_files(self) -> Tuple[bool, str]:
        with self._lock:
            backend = self.detect_backend()
            if backend is None:
                self.status = AIRuntimeStatus.MISSING_RUNTIME
                return False, MISSING_RUNTIME_MESSAGE

            if self.get_current_model_path() is None:
                self.status = AIRuntimeStatus.MISSING_MODEL
                return False, MISSING_MODEL_MESSAGE

            if self.status in {
                AIRuntimeStatus.MISSING_RUNTIME,
                AIRuntimeStatus.MISSING_MODEL,
                AIRuntimeStatus.CLOSED,
            }:
                self.status = AIRuntimeStatus.READY_TO_START

            if backend == "koboldcpp":
                return True, "检测到 KoboldCpp 本地运行器，已优先使用兼容后端。"

            return True, "本地 AI 文件已就绪"

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) != 0

    @property
    def base_url(self) -> str | None:
        if self.port is None:
            return None
        return f"http://127.0.0.1:{self.port}"

    def _endpoint_ready(self, port: int) -> bool:
        for endpoint in (f"http://127.0.0.1:{port}/v1/models", f"http://127.0.0.1:{port}/"):
            try:
                request = Request(endpoint, method="GET")
                with urlopen(request, timeout=1.5) as response:
                    if 200 <= response.status < 500:
                        return True
            except (OSError, URLError):
                continue
        return False

    def _find_existing_ready_port(self) -> int | None:
        for port in PORTS:
            if not self._port_available(port) and self._endpoint_ready(port):
                return port
        return None

    def choose_port(self) -> int | None:
        for port in PORTS:
            if self._port_available(port):
                return port
        return None

    def ensure_started(self) -> Tuple[bool, str]:
        ok, message = self.check_files()
        if not ok:
            self.last_error = message
            return False, message

        existing_port = self._find_existing_ready_port()
        if existing_port is not None:
            self.port = existing_port
            self.status = AIRuntimeStatus.READY
            self.last_error = ""
            self.owned_process = False
            return True, READY_MESSAGE

        if self.process is not None and self.process.poll() is None and self.port is not None:
            if self.is_ready():
                self.status = AIRuntimeStatus.READY
                return True, READY_MESSAGE

        model_path = self.get_current_model_path()
        if model_path is None:
            self.status = AIRuntimeStatus.MISSING_MODEL
            return False, MISSING_MODEL_MESSAGE

        port = self.choose_port()
        if port is None:
            self.status = AIRuntimeStatus.ERROR
            self.last_error = "本地 AI 端口 38765-38769 均被占用，请稍后重试。"
            return False, self.last_error

        backend = self.detect_backend()
        if backend == "koboldcpp":
            command = [
                str(self.kobold_path),
                "--model",
                str(model_path),
                "--port",
                str(port),
            ]
            self.process_backend = "koboldcpp"
        elif backend == "llama_server":
            command = [
                str(self.server_path),
                "--model",
                str(model_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--ctx-size",
                "4096",
            ]
            self.process_backend = "llama_server"
        else:
            self.status = AIRuntimeStatus.MISSING_RUNTIME
            return False, MISSING_RUNTIME_MESSAGE

        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self.status = AIRuntimeStatus.STARTING
        self.last_error = ""
        self.port = port

        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(self.runtime_dir),
                creationflags=creationflags,
            )
            self.owned_process = True
        except OSError as exc:
            self.status = AIRuntimeStatus.ERROR
            runner = "KoboldCpp" if backend == "koboldcpp" else "llama-server"
            self.last_error = f"本地 AI 启动失败：无法运行 {runner}（{exc}）。"
            return False, self.last_error

        for second in range(180):
            if self.is_ready():
                self.status = AIRuntimeStatus.READY
                self.last_error = ""
                return True, READY_MESSAGE

            if self.process.poll() is not None:
                self.status = AIRuntimeStatus.ERROR
                runner = "KoboldCpp" if backend == "koboldcpp" else "llama-server"
                self.last_error = f"本地 AI 进程已退出，请检查 {runner} 与 {model_path.name} 是否匹配。"
                return False, self.last_error

            if second == 60:
                self.last_error = "本地模型还在加载，请稍等。"

            time.sleep(1)

        self.status = AIRuntimeStatus.ERROR
        self.last_error = START_TIMEOUT_MESSAGE
        return False, START_TIMEOUT_MESSAGE

    def is_ready(self) -> bool:
        if self.port is None:
            return False
        return self._endpoint_ready(self.port)

    def _post_chat_utf8(self, payload: dict[str, Any], timeout: int = 240) -> dict[str, Any]:
        if self.base_url is None:
            raise RuntimeError("本地 AI 还没有启动。")

        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            return json.loads(text)

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        try:
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        if content:
                            return str(content).strip()
                    text = first.get("text")
                    if text:
                        return str(text).strip()
        except Exception:
            pass

        try:
            results = data.get("results")
            if isinstance(results, list) and results:
                first = results[0]
                if isinstance(first, dict) and first.get("text"):
                    return str(first["text"]).strip()
        except Exception:
            pass

        return ""

    def chat(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: int = 800,
        top_p: float = 0.9,
    ) -> Tuple[bool, str]:
        with self._lock:
            self._generating_count += 1
            self._cancel_generation = False

        try:
            ok, message = self.ensure_started()
            if not ok:
                return False, message

            with self._lock:
                if self._cancel_generation:
                    return False, "生成已取消。"

            payload = {
                "model": "local-model",
                "messages": messages,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
                "stream": False,
            }

            try:
                data = self._post_chat_utf8(payload, timeout=240)
            except (OSError, URLError, json.JSONDecodeError, RuntimeError) as exc:
                self.last_error = f"本地 AI 调用失败：{exc}"
                return False, self.last_error

            with self._lock:
                if self._cancel_generation:
                    return False, "生成已取消。"

            content = self._extract_content(data)
            if not content:
                self.last_error = "本地 AI 返回格式异常。"
                return False, self.last_error

            return True, content

        finally:
            with self._lock:
                self._generating_count = max(0, self._generating_count - 1)
                if self._generating_count == 0:
                    self._cancel_generation = False

    def restart_with_current_model(self) -> Tuple[bool, str]:
        self.stop_runtime(mark_closed=False)
        return self.ensure_started()

    def restart(self) -> Tuple[bool, str]:
        return self.restart_with_current_model()

    def stop_runtime(self, mark_closed: bool = True) -> None:
        with self._lock:
            self._cancel_generation = True
            process = self.process
            owned = self.owned_process

        if process is not None and owned:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        with self._lock:
            if self.process is process:
                self.process = None
            self.port = None
            self.process_backend = None
            self.owned_process = False
            self.status = AIRuntimeStatus.CLOSED if mark_closed else AIRuntimeStatus.STOPPED

    def shutdown(self, mark_closed: bool = True) -> None:
        self.stop_runtime(mark_closed=mark_closed)