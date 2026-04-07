# qq 分支合并到 main 及问题修复记录

## 背景

将 `qq` 分支（图片分析功能开发）的改动合并到 `main` 分支，并修复合并后工具调用失败的核心问题。

`qq` 分支包含 6 个提交（`8a9fe57` ~ `a683e9e`），功能涵盖：图片传输支持、视觉模型从 llava 切换到 qwen、multipart 上传、超时处理。

---

## 核心问题

**Qwen3.5 推理模型不遵循 ReAct 文本格式，导致工具永远不被调用。**

### 问题表现

模型输出 JSON 格式的工具调用：
```json
{"tool": "plant_image_analyzer", "parameters": {"image_path": "http://..."}}
```

而 NAT 框架的 `ReActOutputParser` 只识别文本格式：
```
Action: plant_image_analyzer
Action Input: {"image_path": "http://..."}
```

解析器找不到 `Action:` 关键字 -> 抛出 `missing_action=True` 异常 -> 框架将模型输出当作"直接回答"接受 -> 日志显示：
```
[AGENT] Agent produced direct answer without ReAct format, accepting as final answer
```

### 排查过程

1. 最初尝试 `use_native_tool_calling: true` -> `tool_calling_agent` 返回 `str` 类型，与 wrapper 期望的 `ChatResponse` 不兼容，报错 `'str' object has no attribute 'choices'`
2. 改回 `react_agent`，自定义中文 ReAct 提示词 -> 模型仍输出 JSON 格式
3. 移除自定义 `system_prompt`，使用 NAT 内置英文默认提示 -> 模型仍输出 JSON 格式
4. 添加 `additional_instructions` 要求模型将 Action 写在 `</think>` 标签外 -> 模型完全忽略
5. **根因确认**：Qwen3.5 的训练使其强烈倾向于 JSON 格式工具调用，ReAct 文本格式指令无法覆盖这一行为

### 最终修复

在 `register.py` 中通过猴子补丁增强 `ReActOutputParser.parse`，在原有 ReAct 解析之前拦截 JSON 格式工具调用，直接转换为 `AgentAction`。

---

## 改动文件清单

### 1. `src/plant_care_agent/register.py` -- 猴子补丁（核心修复）

新增 `_patch_react_output_parser()` 函数，在模块加载时执行：
- 检测 LLM 输出中的 JSON 工具调用（支持 ` ```json{...}``` ` 代码块和裸 JSON）
- 支持多种字段名：`tool/name/action`、`parameters/params/args/action_input/input`
- 匹配成功则直接返回 `AgentAction`，跳过 ReAct 文本解析
- 不匹配则回退到原始解析逻辑，完全兼容

### 2. `src/plant_care_agent/configs/config.yml` -- 配置调整

- `plant_image_analyzer` 新增 `internal_base_url: "http://localhost:9000"` 解决 hairpin NAT 问题
- `inner_react` 设置 `use_native_tool_calling: false`（使用文本解析模式）
- `parse_agent_response_max_retries` 从 5 改为 10
- 移除 `system_prompt: __LOAD_FROM_PROMPTS__`（使用 NAT 内置默认提示）
- 新增 `general.front_end` 配置 FastAPI 静态文件路由（支持图片上传）
- 新增 `object_stores.plant_image_store`（`in_memory` 类型，可切换 s3/redis）
- `plant_chart` 新增 `output_dir`，`growth_slides` 新增 `charts_dir` 和 `output_dir`

### 3. `src/plant_care_agent/tools/plant_image_analyzer.py` -- HTTP URL 图片支持

- 新增 `internal_base_url` 配置字段
- 新增 `_http_url_to_data_url()`：下载 HTTP/HTTPS 图片并转为 base64 data URL
- 新增 `_rewrite_url()`：将公网 URL 重写为内部 URL（避免 hairpin NAT）
- `_analyze_image` 现在支持三种输入：data URL、HTTP URL、本地路径
- 输出标记：成功 `[TOOL_OK]`，失败 `[TOOL_ERR]`

### 4. `src/plant_care_agent/plant_memory_wrapper.py` -- 多模态消息支持

- `_extract_last_user_text` 增加 `list` 类型 content 处理（多模态消息中提取 text 部分）

### 5. `src/plant_care_agent/prompts/tools_block.md` -- 提示词重写

- 重写为清晰的 Markdown 结构
- 添加两个具体工具调用示例（`plant_image_analyzer`、`weather_forecast`）
- 注：当前未被使用（config 中已移除 `system_prompt` 引用），保留作为参考

### 6. `scripts/claude_style_chat.py` -- 客户端图片上传

- 新增 4 种图片传输模式：`path`（默认）、`base64`、`multipart`、`url`
- 图片压缩功能（Pillow，可配置最大边长和 JPEG 质量）
- 支持 `/image --mode multipart --maxpx 800 rose.jpg 请诊断` 命令格式
- 环境变量：`NAT_IMAGE_MODE`、`NAT_IMAGE_MAXPX`、`NAT_IMAGE_QUALITY`、`NAT_IMAGE_TIMEOUT`

### 7. 新增文件

- `docs/image-transmission.md` -- 图片传输功能文档
- `scripts/run_client.sh` -- 客户端启动脚本
- `scripts/start_server.sh` -- 服务端启动脚本
- `README.md` -- 新增文档链接

---

## 关键技术决策

| 决策 | 原因 |
|------|------|
| 猴子补丁而非修改 NAT 源码 | 项目代码随 rsync 部署，不依赖 NAT 源码修改 |
| `use_native_tool_calling: false` | Ollama + Qwen3.5 的 native tool calling 返回类型与 wrapper 不兼容 |
| `internal_base_url` URL 重写 | 云服务器 hairpin NAT 导致服务内部无法通过公网 IP 访问自身 |
| 移除自定义 system_prompt | NAT 内置英文 ReAct 提示比自定义中文提示更稳定 |
| in_memory object_store | 开发阶段零依赖；生产可切换 s3/redis |
