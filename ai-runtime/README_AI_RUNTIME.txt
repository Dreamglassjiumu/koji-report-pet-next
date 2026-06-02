Koji Report Pet Next 本地 AI Runtime 放置说明

请在发布或个人使用时，把以下文件手动放入本目录：

1. llama-server.exe
   - 来自 llama.cpp 的 server 可执行文件。
   - 本项目不会提交或内置该 exe。

2. model.gguf
   - 你的本地 GGUF 模型文件。
   - 请重命名为 model.gguf。
   - 本项目不会提交或内置模型权重。

Koji 启动本地 AI 时只会访问：
http://127.0.0.1:38765-38769

不会调用在线 API，不会上传日报素材，不会监听 0.0.0.0。
