# Koji 桌宠素材目录

这里用于放置 Koji 桌宠动作素材。Koji Report Pet v0.5 会优先使用本目录中的图片素材；素材缺失时不会联网，也不会显示破图。

## 当前支持的 13 个状态

```text
idle          待机
wave          打招呼
record_ready  准备记录
collect       收集记录
success       通用成功
thinking      思考
writing       写日报
happy         开心
confused      疑惑
angry         催日报
sleep         困倦
drag          拖动
error         报错
```

## 支持格式

同一个状态 key 支持以下格式：

```text
webp
gif
png
```

推荐命名示例：

```text
assets/koji/idle.webp
assets/koji/idle.gif
assets/koji/idle.png
assets/koji/wave.webp
assets/koji/record_ready.webp
assets/koji/collect.webp
assets/koji/success.webp
assets/koji/thinking.webp
assets/koji/writing.webp
assets/koji/happy.webp
assets/koji/confused.webp
assets/koji/angry.webp
assets/koji/sleep.webp
assets/koji/drag.webp
assets/koji/error.webp
```

也可以只提供 `.png` 或 `.gif`，只要文件名保持 `状态 key + 扩展名` 即可。

## 加载优先级与回退规则

v0.5 推荐并实现的加载优先级：

1. `assets/koji/<state>.webp`
2. `assets/koji/<state>.gif`
3. `assets/koji/<state>.png`
4. 如果当前状态没有专属素材，回退到 `idle` 素材
5. 如果 `idle` 也没有素材，回退 emoji

因此即使只放入 `assets/koji/idle.png`，13 个状态也会优先回退显示 idle 图片，而不是显示破图。

## 素材检查

主窗口设置区提供“Koji 动作测试与素材检查”：

- 显示 13 个状态。
- 显示是否检测到专属素材。
- 显示当前实际使用的素材路径。
- 标注“回退到 idle”或“回退 emoji”。
- 每个状态可点击“测试动作”。
- 可通过“刷新素材状态”重新检测。
