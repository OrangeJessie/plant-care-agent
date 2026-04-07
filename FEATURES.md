# Plant Care Agent — 功能清单与协作看板

> 本文档用于多人协作时追踪功能实现状态、已知问题和测试情况。  
> 修改代码后请同步更新对应模块的状态。

---

## 目录

- [架构概览](#架构概览)
- [模式切换](#模式切换)
- [一、个人模式（花花助手）](#一个人模式花花助手)
- [二、大规模农业模式（农场智管）](#二大规模农业模式农场智管)
- [三、共享模块](#三共享模块)
- [四、传感器模拟模块](#四传感器模拟模块)
- [五、基础设施](#五基础设施)
- [六、已知问题](#六已知问题)
- [七、环境搭建](#七环境搭建)

---

## 架构概览

```
plant-care-agent/
├── src/plant_care_agent/
│   ├── register.py              # NAT 插件入口，统一注册所有工具
│   ├── configs/
│   │   ├── config.yml           # 个人模式配置
│   │   └── config_farm.yml      # 农业模式配置
│   ├── sensors/                 # 独立传感器模拟模块
│   ├── tools/                   # NAT 工具（个人 + 农业 + 共享）
│   ├── memory/                  # 上下文构建器
│   ├── prompts/                 # Markdown 提示词
│   ├── skills/bundled/          # 内置 Skills
│   ├── proactive/               # 主动巡检
│   └── data/                    # 打包数据
├── scripts/                     # 辅助脚本
├── data/                        # 运行时数据（gitignore）
└── pyproject.toml
```

两个模式通过不同的 `config_*.yml` 启动，共享工具在 `register.py` 中统一导入。

---

## 模式切换

| 模式 | 启动命令 | 配置文件 | Workflow |
|------|---------|---------|----------|
| 个人 | `nat serve --config_file src/plant_care_agent/configs/config.yml` | `config.yml` | `plant_memory_wrapper` |
| 农业 | `nat serve --config_file src/plant_care_agent/configs/config_farm.yml` | `config_farm.yml` | `farm_memory_wrapper` |

> **TODO**: 目前需要手动指定 config 文件，后续可考虑添加交互式启动脚本自动选择模式。

---

## 一、个人模式（花花助手）

### 1.1 植物知识库 (`plant_knowledge`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/plant_knowledge.py` + `data/plants_db.json` |
| 功能 | 查询植物种植条件、养护要点、病虫害、伴生植物 |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 1.2 养护日程 (`care_scheduler`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/care_scheduler.py` |
| 功能 | 根据植物特性 + 季节 + 二十四节气生成两周养护日程 |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 1.3 生长日志 (`growth_journal`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/growth_journal.py` |
| 功能 | Markdown 格式单株植物生长日志，支持记录事件和查询历史 |
| 存储 | `data/garden/{plant_name}.md` |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 1.4 植物图表 (`plant_chart`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/plant_chart.py` |
| 功能 | 生成时间线、看板 dashboard、多株对比图 (Matplotlib) |
| 输出 | `data/charts/*.png` |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 1.5 成长幻灯片 (`growth_slides`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/growth_slides.py` |
| 功能 | 生成 PPTX 成长报告（嵌入图表） |
| 输出 | `data/slides/*.pptx` |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 1.6 个人模式记忆 (`plant_memory_wrapper`)

| 项目 | 内容 |
|------|------|
| 文件 | `plant_memory_wrapper.py` + `memory/context_builder.py` |
| 功能 | 注入多株植物种植日志摘要到 Agent 上下文 |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 1.7 主动巡检 (`proactive/`)

| 项目 | 内容 |
|------|------|
| 文件 | `proactive/*.py` + `scripts/proactive_digest.py` |
| 功能 | 定时拉天气、汇总植物日志、生成 PROACTIVE_DIGEST.md、ntfy/webhook 推送 |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | 独立脚本，非 Agent 子模块；需 cron 调度 |

### 1.8 植物子 Agent 巡检系统 (`inspector/`)

用户种植新植物时自动创建管理项目，每棵植物有独立的巡检子 Agent。支持后台定时巡检和用户交互时即时巡检。

#### 架构

```
plant_memory_wrapper (主 Agent)
  ├── 意图检测: "种了XXX" → 提示 Agent 调 create_plant_project
  ├── 请求前: 调度 PlantInspector 执行巡检
  ├── 聚合报告 → 注入 system message
  └── inner_react (LLM Agent, 含 plant_project 工具)

scripts/plant_inspector_cron.py (后台定时)
  └── 遍历 projects.json → 各植物巡检 → 写入报告 → 推送告警
```

#### 子模块详情

| 模块 | 文件 | 功能 | 已测试 | 功能正常 |
|------|------|------|--------|---------|
| PlantProjectManager | `inspector/project_manager.py` | 植物项目 CRUD，存储 `data/garden/projects.json` | [ ] | [ ] |
| PlantInspector | `inspector/inspector.py` | 4 项规则引擎巡检（天气/养护/生长/病虫害） | [ ] | [ ] |
| InspectionReport | `inspector/report.py` | 单株报告生成 + 多株聚合 | [ ] | [ ] |
| plant_project 工具 | `tools/plant_project.py` | NAT Tool: create/list/inspect/remove 项目 | [ ] | [ ] |
| 定时巡检脚本 | `scripts/plant_inspector_cron.py` | cron 后台巡检 + 推送 | [ ] | [ ] |

#### 4 项巡检内容

| 检查项 | 数据来源 | 输出 |
|--------|---------|------|
| 天气评估 | Open-Meteo API（未来 3 天） | 极端天气预警 + 操作建议 |
| 养护日程 | 生长日志事件分析 | 距上次浇水/施肥天数 + 待办提醒 |
| 生长分析 | `data/garden/{plant}.md` | 阶段评估 + 记录频率检查 |
| 病虫害风险 | 天气条件 + 生长阶段 | 风险等级（低/中/高）+ 预防措施 |

#### Wrapper 意图检测

| 用户消息模式 | 触发行为 |
|-------------|---------|
| "种了/种植了/播种了 XXX" | Agent 调用 `create_plant_project` + `log_event` |
| "巡检/检查一下/怎么样了" | 强制执行全部巡检 |
| 其他（有活跃项目且已到巡检时间） | 静默巡检并注入结果 |
| 其他（无项目或未到时间） | 跳过巡检 |

#### 定时巡检 cron 配置

```bash
# 每天 7:00、12:00、19:00 执行
0 7,12,19 * * * cd /path/to/plant-care-agent && /path/to/python scripts/plant_inspector_cron.py
```

---

## 二、大规模农业模式（农场智管）

### 2.1 传感器监控 (`sensor_monitor`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/sensor_monitor.py` |
| 功能 | 5 个子工具：`read_sensors`、`read_sensor`、`read_sensor_history`、`list_zones`、`check_alerts` |
| 依赖 | `sensors/hub.py` (SensorHub) |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 2.2 自动化操作 (`farm_automation`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/farm_automation.py` |
| 功能 | 两步操作流：`propose_operation`（提议）→ 用户确认 → `execute_operation`（执行）|
| 操作类型 | `irrigate`(灌溉)、`fertilize`(施肥)、`pest_control`(除虫)、`climate_control`(通风遮阳)、`harvest`(收割) |
| 存储 | `data/farm/pending_operations.json` + `operation_history.json` |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | `pest_control` 和 `harvest` 的 effects 为空字典，不影响传感器数值 |

### 2.3 农场日志 (`farm_journal`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/farm_journal.py` |
| 功能 | 按地块记录操作日志（Markdown）+ 自动维护 `FARM_INDEX.md` 索引 |
| 存储 | `data/farm/zones/{zone_id}.md` + `data/farm/FARM_INDEX.md` |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 2.4 农场数据图表 (`farm_chart`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/farm_chart.py` |
| 功能 | 4 种图表：`sensor_trend`(趋势图)、`farm_dashboard`(仪表盘)、`zone_comparison`(地块对比)、`operation_timeline`(操作时间线) |
| 输出 | `data/farm/charts/*.png` |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | 依赖 matplotlib；中文字体需要系统安装 |

### 2.5 农场报告 (`farm_report`)

| 项目 | 内容 |
|------|------|
| 文件 | `tools/farm_report.py` |
| 功能 | `generate_daily_report`(日报) + `generate_zone_report`(地块报告，含参考资料链接) |
| 输出 | `data/farm/reports/*.md` |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | **已知 BUG**: 地块报告查找图表路径时在 reports 目录找，但图表在 charts 目录 → 链接可能失效 |

### 2.6 农业模式记忆 (`farm_memory_wrapper`)

| 项目 | 内容 |
|------|------|
| 文件 | `farm_memory_wrapper.py` + `memory/farm_context_builder.py` |
| 功能 | 注入实时传感器快照 + 告警 + 待确认操作到 Agent 上下文 |
| 已测试 | [ ] |
| 功能正常 | [ ] |
| 备注 | |

### 2.7 农业 Skills

| Skill | 文件 | 功能 | 已测试 | 功能正常 |
|-------|------|------|--------|---------|
| 作物轮作 | `skills/bundled/crop_rotation/SKILL.md` | 多季作物轮作规划 SOP | [ ] | [ ] |
| 灌溉管理 | `skills/bundled/irrigation_management/SKILL.md` | 灌溉决策流程 | [ ] | [ ] |
| IPM 虫害管理 | `skills/bundled/pest_integrated_management/SKILL.md` | 综合虫害防治流程 | [ ] | [ ] |

---

## 三、共享模块

两个模式均可使用的工具：

| 工具 | 文件 | 功能 | 已测试 | 功能正常 |
|------|------|------|--------|---------|
| 天气预报 | `tools/weather_forecast.py` | Open-Meteo 7 天预报 | [ ] | [ ] |
| 图像分析 | `tools/plant_image_analyzer.py` | 多模态模型植物诊断 | [ ] | [ ] |
| 联网搜索 | `tools/web_search.py` | DuckDuckGo 搜索 | [ ] | [ ] |
| Shell | `tools/shell_tool.py` | 受限 Shell 命令 | [ ] | [ ] |
| Skills | `tools/skill_tools.py` | list_skills / load_skill | [ ] | [ ] |
| 文件读取 | `tools/read_project_file.py` | 安全读取项目文本文件 | [ ] | [ ] |

### 共享 Skills

| Skill | 文件 | 功能 | 已测试 | 功能正常 |
|-------|------|------|--------|---------|
| 阳台蔬菜 | `skills/bundled/balcony_vegetables/SKILL.md` | 阳台种菜指导 | [ ] | [ ] |
| 生长记录 | `skills/bundled/growth_logging/SKILL.md` | 记录流程说明 | [ ] | [ ] |
| 病虫诊断 | `skills/bundled/pest_diagnosis/SKILL.md` | 病虫害排查流程 | [ ] | [ ] |
| 主动巡检 | `skills/bundled/proactive_monitoring/SKILL.md` | 巡检配置与推送 | [ ] | [ ] |

---

## 四、传感器模拟模块

独立于 Agent 工具层的传感器模拟子系统，位于 `src/plant_care_agent/sensors/`。

### 架构

```
SensorHub (hub.py)
  ├── StateStore (state_store.py)    # JSON 时序存储
  ├── ZoneConfig / SensorContext     # 数据结构 (base.py)
  └── 7 类传感器实例 (per zone)
       ├── SoilMoistureSensor        # ET 蒸散模型 + 灌溉效果
       ├── AirTemperatureSensor      # 日变化正弦 + 天气耦合
       ├── AirHumiditySensor         # 温湿度耦合 + 降雨/灌溉效果
       ├── LightIntensitySensor      # 太阳高度 + 云量
       ├── SoilPhSensor              # 土壤基线 + 施肥影响
       ├── WindSpeedSensor           # Weibull 分布 + 阵风
       └── RainfallSensor            # 降水概率 + Gamma 采样
```

### 传感器详情

| 传感器 | 文件 | 物理模型 | 操作影响 | 已测试 | 功能正常 |
|--------|------|---------|---------|--------|---------|
| 土壤湿度 | `soil_moisture.py` | ET 蒸散衰减 + 降雨补充 | irrigate: +moisture_delta | [ ] | [ ] |
| 空气温度 | `air_temperature.py` | 日正弦曲线 + 天气 min/max | climate_control: +temp_delta | [ ] | [ ] |
| 空气湿度 | `air_humidity.py` | 天气基线 + 温度耦合 + 夜间/雨天增益 | climate_control: +humidity_delta, irrigate: 微增 | [ ] | [ ] |
| 光照强度 | `light_intensity.py` | 太阳高度 + 云量 + 季节因子 | 无 | [ ] | [ ] |
| 土壤 pH | `soil_ph.py` | 土壤类型基线 + 缓慢回复 | fertilize: +ph_delta | [ ] | [ ] |
| 风速 | `wind_speed.py` | Weibull 分布 + 天气风速 | 无 | [ ] | [ ] |
| 降雨量 | `rainfall.py` | 降水概率 + Gamma 强度采样 | 无 | [ ] | [ ] |

### 核心组件

| 组件 | 文件 | 功能 | 已测试 | 功能正常 |
|------|------|------|--------|---------|
| SensorHub | `hub.py` | 管理所有地块传感器，读取/告警/操作转发 | [ ] | [ ] |
| StateStore | `state_store.py` | JSON 时序数据持久化 + 历史查询 + 30天清理 | [ ] | [ ] |
| BaseSensor | `base.py` | 抽象基类：采样 + 噪声 + 阈值判定 | [ ] | [ ] |
| ZoneConfig | `base.py` | 地块配置（面积、作物、土壤、阈值） | [ ] | [ ] |
| 默认农场 | `hub.py` → `_init_default_farm` | 首次运行自动创建 3 个地块（水稻田/蔬菜大棚/果园） | [ ] | [ ] |

---

## 五、基础设施

| 模块 | 文件 | 功能 | 已测试 | 功能正常 |
|------|------|------|--------|---------|
| 对话持久化 | `conversation_store.py` | 按 user+session 的 Markdown 对话存储 | [ ] | [ ] |
| 轮次日志 | `chat_round_log.py` | 每轮请求/响应完整记录到 .md | [ ] | [ ] |
| 日志系统 | `logging_setup.py` + `md_log_file.py` | Markdown 格式文件日志 | [ ] | [ ] |
| Skills 注册 | `skills/registry.py` | 多路径 Skill 发现与索引 | [ ] | [ ] |
| 提示词加载 | `prompts/loader.py` | Markdown 拼接 → system_prompt | [ ] | [ ] |
| 配置组装 | `scripts/assemble_config.py` | 提示词 MD → YAML | [ ] | [ ] |
| TUI 客户端 | `scripts/claude_style_chat.py` | Rich + prompt-toolkit 终端对话 | [ ] | [ ] |

---

## 六、已知问题

| # | 严重程度 | 模块 | 描述 | 状态 |
|---|---------|------|------|------|
| 1 | P2 | `farm_report.py` | `generate_zone_report` 查找图表时在 `report_dir` 下查找 `*_trend.png`，但图表输出在 `charts_dir`，导致图表链接永远找不到 | 待修复 |
| 2 | P3 | `hub.py` | `_build_ctx` 中 `get_latest` 取到后未传入 `SensorContext`，属于死代码 | 待修复 |
| 3 | P3 | `farm_automation.py` | `pest_control` 和 `harvest` 操作的 effects 为空字典，执行后传感器无任何变化 | 待评估 |
| 4 | P2 | `hub.py` | 天气数据未自动同步，`set_weather` 需外部调用，否则传感器使用默认值（与真实天气无关） | 待修复 |
| 5 | P3 | 启动流程 | 无交互式模式选择，需手动指定 `--config_file` 路径 | 待开发 |
| 6 | P1 | `.venv` | 虚拟环境解释器指向旧路径 `/Users/sijie.guo/flower/`，需重建 | 待修复 |

---

## 七、环境搭建

### 前置条件

- Python 3.11 ~ 3.13
- Ollama（或兼容 OpenAI API 的推理服务）

### 安装步骤

```bash
cd plant-care-agent

# 1. 重建虚拟环境（当前 .venv 已损坏）
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -e .

# 3. 拉取模型（如用 Ollama）
ollama pull qwen3.5:35b
ollama pull llava:13b

# 4. 启动
nat serve --config_file src/plant_care_agent/configs/config.yml      # 个人模式
nat serve --config_file src/plant_care_agent/configs/config_farm.yml  # 农业模式
```

### TUI 客户端

```bash
pip install rich "prompt-toolkit>=3.0"
python scripts/claude_style_chat.py
```

### 如果不用 Ollama

修改 `config.yml` / `config_farm.yml` 中的 `llms` 部分，替换 `base_url` 和 `model_name`。

---

## 更新日志

| 日期 | 修改人 | 内容 |
|------|--------|------|
| 2026-04-07 | AI | 初始功能清单创建 |
| 2026-04-07 | AI | 新增植物子 Agent 巡检系统（inspector/ + plant_project 工具 + cron 脚本） |

---

> **协作约定**: 修改功能代码后，请在对应模块的表格中更新「已测试」和「功能正常」状态，并在「已知问题」或「更新日志」中记录变更。
