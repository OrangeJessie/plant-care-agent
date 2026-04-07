import logging
from datetime import date, datetime, timedelta

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

SOLAR_TERMS_2025_2026: list[tuple[str, str, str]] = [
    ("2025-01-05", "小寒", "注意防寒保暖，室内植物控水"),
    ("2025-01-20", "大寒", "最冷时节，不耐寒植物须入室"),
    ("2025-02-03", "立春", "春季开始，可准备育苗"),
    ("2025-02-18", "雨水", "湿度增加，防病害"),
    ("2025-03-05", "惊蛰", "虫害开始活跃，预防为主"),
    ("2025-03-20", "春分", "多数植物进入生长期，施基肥"),
    ("2025-04-04", "清明", "适宜播种、定植大部分蔬菜"),
    ("2025-04-20", "谷雨", "雨水增多，注意排水"),
    ("2025-05-05", "立夏", "进入夏季管理，增加浇水频率"),
    ("2025-05-21", "小满", "果菜类开始挂果"),
    ("2025-06-05", "芒种", "适宜播种耐热品种"),
    ("2025-06-21", "夏至", "高温来临，注意遮阴和通风"),
    ("2025-07-07", "小暑", "高温多雨，加强病虫害防治"),
    ("2025-07-22", "大暑", "一年最热，注意防晒遮阴"),
    ("2025-08-07", "立秋", "秋播准备，叶菜类可播种"),
    ("2025-08-23", "处暑", "暑热渐退，增施磷钾肥"),
    ("2025-09-07", "白露", "秋菜、大蒜适宜定植"),
    ("2025-09-23", "秋分", "昼夜均分，适宜多种作物生长"),
    ("2025-10-08", "寒露", "气温下降，不耐寒植物准备入室"),
    ("2025-10-23", "霜降", "初霜将至，做好防冻措施"),
    ("2025-11-07", "立冬", "进入冬管，减少浇水和施肥"),
    ("2025-11-22", "小雪", "控水保暖"),
    ("2025-12-07", "大雪", "严冬管理"),
    ("2025-12-21", "冬至", "最短日照，室内补光"),
    ("2026-01-05", "小寒", "注意防寒保暖，室内植物控水"),
    ("2026-01-20", "大寒", "最冷时节，不耐寒植物须入室"),
    ("2026-02-04", "立春", "春季开始，可准备育苗"),
    ("2026-03-05", "惊蛰", "虫害开始活跃，预防为主"),
    ("2026-03-20", "春分", "多数植物进入生长期，施基肥"),
    ("2026-04-05", "清明", "适宜播种、定植大部分蔬菜"),
    ("2026-04-20", "谷雨", "雨水增多，注意排水"),
    ("2026-05-05", "立夏", "进入夏季管理，增加浇水频率"),
    ("2026-05-21", "小满", "果菜类开始挂果"),
    ("2026-06-05", "芒种", "适宜播种耐热品种"),
    ("2026-06-21", "夏至", "高温来临，注意遮阴和通风"),
]


def _get_season(d: date) -> str:
    month = d.month
    if month in (3, 4, 5):
        return "春季"
    if month in (6, 7, 8):
        return "夏季"
    if month in (9, 10, 11):
        return "秋季"
    return "冬季"


def _upcoming_solar_terms(d: date, count: int = 3) -> list[tuple[str, str, str]]:
    results = []
    for date_str, name, tip in SOLAR_TERMS_2025_2026:
        term_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if term_date >= d:
            results.append((date_str, name, tip))
            if len(results) >= count:
                break
    return results


class CareSchedulerConfig(FunctionBaseConfig, name="care_scheduler"):
    pass


@register_function(config_type=CareSchedulerConfig)
async def care_scheduler_function(_config: CareSchedulerConfig, _builder: Builder):

    async def _generate_schedule(plant_info: str) -> str:
        """Generate a care schedule for a plant based on its characteristics and the current date.
        Input should describe the plant name, growth stage, and optionally the environment.
        Returns a 2-week detailed care plan with daily/weekly tasks, plus seasonal reminders."""
        today = date.today()
        season = _get_season(today)
        upcoming = _upcoming_solar_terms(today)

        lines = [
            f"🗓 养护日程（生成日期: {today.isoformat()}，{season}）",
            f"植物信息: {plant_info}",
            "",
        ]

        lines.append("【近两周养护计划】")
        for day_offset in range(14):
            d = today + timedelta(days=day_offset)
            weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d.weekday()]
            tasks = []

            if day_offset % 2 == 0:
                tasks.append("检查土壤湿度，按需浇水")
            if day_offset == 0:
                tasks.append("检查植物整体健康状况")
            if day_offset % 7 == 0:
                tasks.append("检查是否有病虫害迹象")
            if day_offset == 6:
                tasks.append("施肥（如处于生长期）")
            if day_offset == 13:
                tasks.append("松土/检查根系状态")

            if d.weekday() == 5:
                tasks.append("修剪枯叶黄叶")

            task_str = "；".join(tasks) if tasks else "日常观察"
            lines.append(f"  {d.isoformat()} ({weekday}): {task_str}")

        lines.append("")
        lines.append("【季节性重点】")
        if season == "春季":
            lines.append("  🌱 春季要点: 加强施肥，准备播种/定植，预防倒春寒")
        elif season == "夏季":
            lines.append("  ☀ 夏季要点: 增加浇水频率，注意遮阴通风，加强病虫害防治")
        elif season == "秋季":
            lines.append("  🍂 秋季要点: 减少浇水和施肥，准备越冬，秋播适期")
        else:
            lines.append("  ❄ 冬季要点: 控水控肥，防寒保暖，室内植物注意补光")

        if upcoming:
            lines.append("")
            lines.append("【近期节气提醒】")
            for date_str, name, tip in upcoming:
                lines.append(f"  {date_str} {name}: {tip}")

        lines.append("")
        lines.append("【月度提醒】")
        lines.append(f"  本月({today.month}月): 每周检查一次病虫害；每两周施肥一次（生长期）")
        next_month = today.month % 12 + 1
        lines.append(f"  下月({next_month}月): 根据生长阶段调整养护策略")

        lines.append("")
        lines.append(
            "提示: 以上为通用日程框架，请结合天气查询工具获取实时天气，"
            "并结合植物知识库中该植物的具体养护要求进行调整。"
        )

        return "\n".join(lines)

    yield FunctionInfo.from_fn(
        _generate_schedule,
        description=(
            "根据植物种类、生长阶段和当前季节生成未来两周的养护日程表，"
            "包含浇水、施肥、修剪、病虫害检查等任务，以及节气提醒和季节性建议。"
        ),
    )
