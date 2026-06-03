# Koji Report Pet Next 本地 AI 版说明

Koji Report Pet Next v0.5.x 支持“普通模板日报”和“本地 AI 智能模式”。默认不联网、不调用在线 API、不内置任何云端 API Key。

## 普通模式：不放模型也可以用

即使没有放入 `llama-server.exe` 或 GGUF 模型，程序也能正常启动，并继续使用：

- Koji 桌宠窗口
- 日报记录添加、编辑、删除、清空
- 普通模板整理日报
- 复制与导出日报文本
- 聊天面板占位回复

AI 文件缺失时，界面会提示“可继续使用普通模板日报”，不会崩溃，也不会清空已有日报草稿。

## AI 模式：本地 runtime 和模型

如需启用 **AI 整理日报** 与 **和 Koji 聊天**，请把 llama.cpp 的 `llama-server.exe` 放到程序目录下的 `ai-runtime/`。

### 推荐的新结构：多模型切换

```text
ai-runtime/
├─ llama-server.exe
├─ models/
│  ├─ qwen2.5-3b-q4_k_m.gguf
│  └─ qwen3-8b-q4_k_m.gguf
└─ model_config.json
```

推荐两种模型：

1. 轻量模式：`Qwen2.5-3B Q4_K_M`
   - 速度快，适合大多数电脑和日常日报。

2. 高质量模式：`Qwen3-8B Q4_K_M`
   - 输出质量更好，但可能需要 1～3 分钟，适合性能较好的电脑。

使用方法：

- 把多个模型放入 `ai-runtime/models/`。
- 在 Koji 日报面板的“当前模型”下拉框里选择模型。
- 点击“切换模型”。
- Koji 会自动重启本地 AI；如果 AI 还没启动，则会保存选择，下次生成日报或聊天时使用新模型。

说明：

- 如果电脑卡顿，建议切回轻量模型。
- 如果高质量模型生成较慢，请等待，Koji 不是死了，是在憋大的。
- 所有内容都只在本机运行，不调用在线 API。

### 兼容旧结构：单模型

旧版结构仍然可用，不要求迁移：

```text
ai-runtime/
├─ llama-server.exe
└─ model.gguf
```

如果 `ai-runtime/models/` 存在且里面有可用 `.gguf` 模型，Koji 会优先使用 `models/` 目录；如果 `models/` 不存在或为空，但 `ai-runtime/model.gguf` 存在，则继续使用旧模式。

## 高质量模型等待提示

Qwen3-8B 等高质量模型首次生成可能需要 2～3 分钟。点击“AI 整理日报”后：

- 按钮会变为“生成中...”，并禁止重复点击。
- Koji 会提示“Koji 正在认真憋日报，高质量模型可能需要 1～3 分钟。”
- 超过 60 秒会提示“模型比较大，Koji 还在写，别急。”
- 超过 180 秒仍无结果时，会建议稍后重试或切换轻量模型。
- 可以点击“取消生成”，原始记录和已有日报草稿都会保留。

## 本地 AI 端口

Koji 默认只尝试本机回环地址：

```text
127.0.0.1:38765
127.0.0.1:38766
127.0.0.1:38767
127.0.0.1:38768
127.0.0.1:38769
```

启动参数包含：

```text
--host 127.0.0.1
--ctx-size 4096
```

不会监听 `0.0.0.0`，不会开放局域网访问。

## 安全说明

- 日报记录只保存在本机 `data/records.json`。
- 聊天历史只保存在本机 `data/chat_history.json`。
- 程序不调用在线 API。
- 程序不上传日报内容或聊天内容。
- 程序不内置云端 API Key。
- 本项目不提交 `exe`、`gguf`、压缩包或图片二进制素材。

## 绿色便携包目录

运行 `build.bat` 后目标目录为：

```text
dist/KojiReportPetNext_Portable/
├─ Koji Report Pet Next.exe
├─ assets/
├─ data/
│  └─ koji-dialogues.json
├─ ai-runtime/
│  ├─ .gitkeep
│  ├─ README_AI_RUNTIME.txt
│  ├─ llama-server.exe       # 发布时手动放入，不提交 git
│  ├─ models/
│  │  ├─ qwen2.5-3b-q4_k_m.gguf
│  │  └─ qwen3-8b-q4_k_m.gguf
│  ├─ model_config.json
│  └─ model.gguf             # 旧结构兼容，可选
├─ 启动 Koji.bat
└─ README_本地AI版说明.md
```

如果构建机本地已经存在 `ai-runtime/llama-server.exe`、`ai-runtime/models/*.gguf`、`ai-runtime/model_config.json` 或旧版 `ai-runtime/model.gguf`，`build.bat` 会复制到便携目录；否则只复制说明文件并提示发布前手动补充。
