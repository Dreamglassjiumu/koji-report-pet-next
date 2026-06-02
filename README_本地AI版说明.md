# Koji Report Pet Next 本地 AI 版说明

Koji Report Pet Next v0.4 支持“普通模板日报”和“本地 AI 智能模式”。默认不联网、不调用在线 API、不内置任何云端 API Key。

## 普通模式：不放模型也可以用

即使没有放入 `llama-server.exe` 或 `model.gguf`，程序也能正常启动，并继续使用：

- Koji 桌宠窗口
- 日报记录添加、编辑、删除、清空
- 普通模板整理日报
- 复制与导出日报文本
- 聊天面板占位回复

AI 文件缺失时，界面会提示“可继续使用普通模板日报”，不会崩溃，也不会清空已有日报草稿。

## AI 模式：手动放入本地 runtime 和模型

如需启用 **AI 整理日报** 与 **和 Koji 聊天**，请把文件放到程序目录下的 `ai-runtime/`：

```text
ai-runtime/
├─ llama-server.exe
└─ model.gguf
```

注意：

1. 需要把 llama.cpp 的 `llama-server.exe` 放入 `ai-runtime/`。
2. 需要把 GGUF 模型文件重命名为 `model.gguf` 并放入 `ai-runtime/`。
3. 双击启动 Koji 后，点击“AI 整理日报”或发送聊天消息，会自动启动本地 AI。
4. 第一次启动可能需要几十秒，模型越大等待越久。
5. 如果启动失败，普通模板日报仍然可用。

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
│  └─ koji/
├─ data/
│  └─ koji-dialogues.json
├─ ai-runtime/
│  ├─ .gitkeep
│  ├─ README_AI_RUNTIME.txt
│  ├─ llama-server.exe       # 发布时手动放入，不提交 git
│  └─ model.gguf             # 发布时手动放入，不提交 git
├─ 启动 Koji.bat
└─ README_本地AI版说明.md
```

如果构建机本地已经存在 `ai-runtime/llama-server.exe` 和 `ai-runtime/model.gguf`，`build.bat` 会复制到便携目录；否则只复制说明文件并提示发布前手动补充。
