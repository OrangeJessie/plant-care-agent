---
name: 主动巡检与推送
description: 用 cron 定时拉天气、扫多株植物日志，写简报并推送到手机（ntfy）或 webhook
when_to_use: 希望不打开聊天也能收到「花园动态」提醒，或要配置定时巡检时
---

# 主动巡检与推送（不是子 Agent）

本能力由 **cron + 独立脚本** 完成，**不是**再启动一个对话 Agent。主 Agent 仍只在您发消息时运行。

启用后，脚本会定时：

1. 拉取您配置地点的天气（Open-Meteo）
2. 读取 `data/garden/*.md` 里每株植物的日志（**`plant_id` = 文件名去掉 `.md`**，与 `growth_journal`、`X-Focus-Plant` 一致）
3. 写入 **`data/garden/PROACTIVE_DIGEST.md`** 完整简报
4. 若配置 **ntfy** 或 **webhook**，在「有新日志或天气警戒变化」时 **主动推送**（无需您先在聊天里提问）

## 一键开启（推荐）

在终端使用 `python scripts/claude_style_chat.py` 时可直接输入（**不经过模型**）：

- `/proactive on` — 开启监控（写 `enabled: true`）
- `/proactive off` — 关闭
- `/proactive ntfy <topic>` — 设置 ntfy 主题并打开推送
- `/proactive webhook <url>` — 设置通用 webhook
- `/proactive status` — 查看配置与简报路径

城市默认读环境变量 `PLANT_CARE_LOCATION`，否则可在 YAML 里改 `location`。

## 配置文件

路径：`data/garden/proactive_monitor.yaml`（可加入 `.gitignore`，勿提交隐私）

要点：

- `enabled: true`
- `location: 上海`（或 `latitude` / `longitude`）
- `plant_ids: []` 空表示所有植物；否则只列文件名 stem 列表
- `push.mode`: `none` | `ntfy` | `webhook`
- `push.only_on_change`: 默认 `true`（无新动态不推，避免刷屏）
- `push.min_interval_minutes`: 默认 `60`

### ntfy 示例

1. 手机安装 [ntfy](https://ntfy.sh/)，订阅一个 topic（勿用易猜密码）
2. YAML 中：

```yaml
push:
  mode: ntfy
  ntfy:
    server: https://ntfy.sh
    topic: 你的私密主题名
```

## Cron

在项目根目录（与 `data/` 同级）：

```cron
0 8,20 * * * cd /path/to/plant-care-agent && /path/to/python scripts/proactive_digest.py >> /tmp/plant_care_cron.log 2>&1
```

需与安装 `plant-care-agent` 的 **同一 Python**。

## 多株植物如何区分

简报与推送中每株单独一节，并标明 **`plant_id: \`文件名stem\``** 与显示名（frontmatter `name`）。请保证日志文件名与 `log_event` 里植物名一致。

## 纯 curl 用户

若无 TUI，请手建 `proactive_monitor.yaml` 并配置 crontab，字段含义同上。
