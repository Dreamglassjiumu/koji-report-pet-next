# Koji Report Pet Next 开发说明

Koji Report Pet Next 是一个 Python 3 + PySide6 桌面宠物日报工具。项目默认不联网、不调用在线 API、不内置任何云端 API Key。

## 安装依赖

```bat
python -m pip install -r requirements.txt
```

## 运行

```bat
python main.py
```

程序在没有 Koji 图片、没有 `llama-server.exe`、没有 `model.gguf` 的情况下也可以启动：

- 没有图片时显示 emoji / 文字占位 Koji。
- 没有本地 AI runtime 时，仍可添加记录并使用普通模板整理日报。

## 打包

```bat
build.bat
```

打包使用 PyInstaller。生成产物位于 `dist/`，中间文件位于 `build/`，二者不会提交到 Git。

## 目录约定

- `assets/koji/`：运行时可手动放入 Koji 状态图；仓库内只保留 `.gitkeep` 或 README。
- `ai-runtime/`：运行时可手动放入本地 AI 文件；仓库内只保留 `.gitkeep` 或 README。
- `data/koji-dialogues.json`：Koji 状态台词。
- `data/records.json`：本机日报记录，已加入 `.gitignore`。
- `data/chat_history.json`：本机聊天历史，已加入 `.gitignore`。

## 状态图片加载规则

状态名包括：`idle`、`wave`、`record_ready`、`collect`、`success`、`thinking`、`writing`、`happy`、`confused`、`angry`、`sleep`、`drag`、`error`。

程序会优先查找：

1. `assets/koji/<state>.webp`
2. `assets/koji/<state>.gif`
3. `assets/koji/<state>.png`
4. 回退 `idle` 状态图片
5. 仍缺失时显示占位 Koji
