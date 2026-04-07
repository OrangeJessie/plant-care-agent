---
name: 生长日志规范
description: 统一 growth_journal 记录格式与回顾节奏
when_to_use: 用户开始长期养护、多株植物或需要「成长时间线/幻灯片」时
---

# 生长日志规范 Skill

## 记录格式
使用工具 `growth_journal.log_event`，格式严格为：
`植物名称 | 事件类型 | 描述`

可选在末尾追加：`| species=tomato | location=阳台`

事件类型建议：`播种`、`发芽`、`浇水`、`施肥`、`修剪`、`开花`、`结果`、`采收`、`病害`、`虫害`、`观察`、`其他`。

## 节奏建议
- 苗期：至少每周 1 条「观察」。
- 花果期：重大变化（开花、坐果、疏果）当天记录。
- 异常：发现病虫害先记一条「观察」再记「病害/虫害」。

## 回顾与展示
- 需要周报或复盘：先 `query_history`，再按需 `plant_chart`（dashboard）与 `growth_slides`。
- 多株对比：确保每株有稳定「植物名称」字符串，与 HTTP 头 `X-Focus-Plant` 一致以便完整记忆注入。
