# Koji Report Pet Next 本地 AI 版说明

Koji Report Pet Next 默认不联网、不调用在线 API、不内置任何云端 API Key。日报记录和聊天历史只保存在本机。

## 没有模型也能使用

即使便携包里没有本地 AI 模型，程序也能正常启动，并且可以继续使用：

- Koji 桌宠窗口
- 日报记录添加、删除、清空
- 普通模板整理日报
- 复制日报文本

当 AI 不可用时，程序会提示：

> 当前便携包未包含本地 AI 模型，可继续使用普通日报模式

## 启用本地 AI

如需启用 AI 整理日报和 AI 聊天，需要手动放入以下文件：

```text
ai-runtime/llama-server.exe
ai-runtime/model.gguf
```

程序会尝试使用默认端口 `38765`，如果端口冲突，会依次尝试 `38766`、`38767`。启动成功后，应用会通过以下接口调用本地模型：

```text
http://127.0.0.1:<port>/v1/chat/completions
```

## 本机数据

本地运行时数据文件：

```text
data/records.json
data/chat_history.json
```

这些文件只保存在你的电脑上，并已加入 `.gitignore`，不会作为项目代码提交。
