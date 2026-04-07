# 🌱 Plant Care Agent — 花花助手

基于 [NVIDIA NeMo Agent Toolkit](https://github.com/NVIDIA/NeMo-Agent-Toolkit) 的植物种植全流程 AI 助手。架构上参考本机 `insightor`（Claude Code 风格 CLI）中 **Markdown 提示词 + Skills + 基础工具** 的分层方式：**提示词 Markdown 化**、**Skills 目录**、**只读文件 + Shell** 等基础能力。

## 功能

| 工具 | 说明 |
|------|------|
| 🌿 **plant_knowledge** | 查询常见植物的种植条件、养护、病虫害、伴生植物等 |
| 🌤 **weather_forecast** | Open-Meteo 7 天预报与种植提示 |
| 📅 **care_scheduler** | 植物特性 + 季节 + 二十四节气两周日程 |
| 📸 **plant_image_analyzer** | 本地多模态模型图像诊断 |
| 📖 **growth_journal** | Markdown 生长日志（`data/garden/`） |
| 🔍 **web_search** | DuckDuckGo 联网搜索 / 搜图 |
| 💻 **shell_tool** | 受限 Shell（grep、ls、python 等） |
| 📄 **read_project_file** | 安全读取项目内文本（类 insightor Read） |
| 📊 **plant_chart** | Matplotlib 时间线 / 看板 / 多株对比 |
| 📽 **growth_slides** | 成长故事 PPTX |
| 🧩 **skill_tools** | `list_skills` / `load_skill`，加载 `SKILL.md` 工作流 |

## 提示词（Markdown）

主 Agent 的 `system_prompt` 由以下文件拼接而成（**勿删** `tools_block.md` 中的 `{tools}`、`{tool_names}`）：

```
src/plant_care_agent/prompts/
  core.md
  workflow.md
  style.md
  tools_block.md
```

修改后同步进 YAML：

```bash
python scripts/assemble_config.py
```

## Skills 系统

与 insightor / Claude Code 类似：每个技能一个目录 + **`SKILL.md`**，YAML frontmatter 可写 `name`、`description`、`when_to_use`。

扫描顺序（后者同名覆盖）：

1. 包内置：`src/plant_care_agent/skills/bundled/<skill_id>/SKILL.md`
2. 环境变量 **`PLANT_CARE_SKILL_DIRS`**（`:` 分隔多个根目录）
3. 项目根 **`./skills/<skill_id>/SKILL.md`**
4. **`~/.plant-care-agent/skills/<skill_id>/SKILL.md`**

每轮请求会在 system 消息中注入 **Skills 目录摘要**（可通过 `workflow.inject_skills_index: false` 关闭）；模型应使用 **`load_skill`** 拉取完整正文再执行。

## 快速开始

### 前置条件

- Python 3.11–3.13
- [Ollama](https://ollama.com/)（或兼容 OpenAI API 的本地推理）
- 已安装 `nvidia-nat[langchain]` 与本包（与 `nat` 命令使用**同一 Python 环境**）

### 模型示例

```bash
ollama pull qwen3.5:35b
ollama pull llava:13b
```

### 安装

```bash
cd plant-care-agent
pip install -e .
# 或 uv pip install -e .
```

### 运行

```bash
nat serve --config_file src/plant_care_agent/configs/config.yml
```

### 记忆与日志（Markdown）

- **默认文件**：`data/logs/plant_care_memory_log.md`（`config.yml` → `workflow.file_log_path`；可改为 `.log` 纯文本；设为空字符串则关闭）。
- **`.md` 文件结构**：
  1. **Runtime（logging）**：标准 `logging` 输出，每条为 Markdown **引用块**（`> `），便于与正文区分。
  2. **轮次**：每次请求后追加 `## 轮次 · …`，含 **TO_LLM**（完整 `messages`，按条 `####` + ` ```text` 代码块）、**FROM_LLM**（assistant 全文 + usage 等元数据）。失败时写入 **ERROR** 代码块；完整 Python 栈仍在 `logger.exception`。
- **早于首次对话**：环境变量 `PLANT_CARE_LOG_FILE`（路径，推荐 `.md`）与可选 `PLANT_CARE_LOG_LEVEL`。

`data/logs/` 下生成文件建议勿提交（见 `.gitignore`）。

### 一般对话记忆（服务端）

除「种植日记」Markdown 外，**闲聊与多轮对话**也可由服务端持久化（与客户端是否带全量 `messages` 无关）：

- **存储**：`data/conversations/{X-User-ID}__{X-Session-ID}.md`（Markdown，YAML 头 + `# 对话记忆` + 若干 `### user` / `### assistant` 与 ` ```text` 正文；仅 user/assistant，不含注入的 system）。首次启动若发现旧版 **`.json`** 会自动迁移为 `.md` 并删除 `.json`。
- **配置**：`workflow.conversation_memory_enabled`（默认开启）、`conversation_store_dir`、`conversation_auto_incremental`。
- **合并规则**：
  - 客户端带**完整多轮** `messages`（如 TUI）→ 与磁盘**全量同步**（以本次请求为准）。
  - 仅发 **1 条 user** 且开启自动 incremental（默认）→ **拼在磁盘历史后面**（适合只发本轮句子的 API 集成）。
  - 请求头 **`X-Chat-Incremental: 0`** 可强制按全量同步；**`1`** 强制增量。
  - **`X-Conversation-Reset: 1`**：清空该用户+会话的磁盘记录后再合并本次正文（TUI 的 `/clear` 下一跳会带上）。
- **TUI**：环境变量 `NAT_USER_ID`、`NAT_SESSION_ID`；`/clear` 会下一跳重置服务端同会话记忆。

终端对话（另开终端）：

```bash
pip install rich "prompt-toolkit>=3.0"
python scripts/claude_style_chat.py
```

### 主动巡检（cron + 推送）

定时拉天气、汇总多株植物日志，写入 `data/garden/PROACTIVE_DIGEST.md`；可选 **ntfy** 或 **webhook** 推送。由独立脚本执行，**不是**子 Agent。

- 技能说明：`load_skill` → **主动巡检与推送**（`proactive_monitoring`）
- TUI 快捷命令（不经过模型）：`/proactive on`、`/proactive ntfy <topic>`、`/proactive status` 等
- Cron 示例：

```bash
0 8,20 * * * cd /path/to/plant-care-agent && /path/to/python scripts/proactive_digest.py
```

配置默认写在 `data/garden/proactive_monitor.yaml`（已在 `.gitignore` 中忽略）。若希望在对话里附带简报摘要，可在 `config.yml` 的 `workflow` 中设置 `inject_proactive_digest: true`。

## 项目结构（节选）

```
src/plant_care_agent/
├── register.py
├── plant_memory_wrapper.py   # 注入种植记忆 + Skills 摘要
├── prompts/                  # system 提示词片段（MD）
├── skills/
│   ├── registry.py           # 发现与索引
│   └── bundled/              # 内置 Skills
├── configs/config.yml
├── tools/
└── data/plants_db.json
```

## License

Apache-2.0

## 文档

- [图片传输模式说明](docs/image-transmission.md) — `/image` 命令四种模式（path / base64 / multipart / url）的使用与测试
