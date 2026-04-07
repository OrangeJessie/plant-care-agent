from plant_care_agent.logging_setup import bootstrap_file_logging_from_env

bootstrap_file_logging_from_env()

# --- 共享工具（个人模式 & 农业模式均可用）---
import plant_care_agent.tools.weather_forecast  # noqa: F401
import plant_care_agent.tools.plant_image_analyzer  # noqa: F401
import plant_care_agent.tools.web_search  # noqa: F401
import plant_care_agent.tools.shell_tool  # noqa: F401
import plant_care_agent.tools.skill_tools  # noqa: F401
import plant_care_agent.tools.read_project_file  # noqa: F401

# --- 个人模式专属工具 ---
import plant_care_agent.tools.plant_knowledge  # noqa: F401
import plant_care_agent.tools.care_scheduler  # noqa: F401
import plant_care_agent.tools.growth_journal  # noqa: F401
import plant_care_agent.tools.plant_chart  # noqa: F401
import plant_care_agent.tools.growth_slides  # noqa: F401

# --- 农业模式专属工具 ---
import plant_care_agent.tools.sensor_monitor  # noqa: F401
import plant_care_agent.tools.farm_automation  # noqa: F401
import plant_care_agent.tools.farm_journal  # noqa: F401
import plant_care_agent.tools.farm_chart  # noqa: F401
import plant_care_agent.tools.farm_report  # noqa: F401

# --- Workflow wrappers ---
import plant_care_agent.plant_memory_wrapper  # noqa: F401
import plant_care_agent.farm_memory_wrapper  # noqa: F401
