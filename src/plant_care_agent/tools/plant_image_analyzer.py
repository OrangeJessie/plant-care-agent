import base64
import logging
import mimetypes
from pathlib import Path

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

DIAGNOSIS_PROMPT = """你是一位专业的植物病虫害诊断专家。请仔细观察这张植物照片，从以下几个方面进行分析：

1. **植物识别**: 尝试识别植物种类
2. **整体健康评估**: 用1-10分评价植物的健康状况（10分最健康）
3. **问题诊断**: 列出发现的所有问题（如有）
   - 病害（如：白粉病、黑斑病、灰霉病等）
   - 虫害（如：蚜虫、红蜘蛛、介壳虫等）
   - 营养问题（如：缺氮黄化、缺铁、缺钾等）
   - 环境问题（如：缺水、浇水过多、光照不足、晒伤等）
4. **处理建议**: 针对每个问题给出具体的处理方法
5. **预防措施**: 给出后续养护建议防止问题复发

请用中文回答，给出具体可操作的建议。如果照片不够清晰或无法判断，请说明需要哪个角度或部位的特写照片。"""


class PlantImageAnalyzerConfig(FunctionBaseConfig, name="plant_image_analyzer"):
    vision_llm_name: LLMRef = Field(description="Name of the vision-capable LLM for image analysis.")


@register_function(
    config_type=PlantImageAnalyzerConfig,
    framework_wrappers=[LLMFrameworkEnum.LANGCHAIN],
)
async def plant_image_analyzer_function(config: PlantImageAnalyzerConfig, builder: Builder):
    from langchain_core.messages import HumanMessage

    vision_llm = await builder.get_llm(config.vision_llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    async def _analyze_image(image_path: str) -> str:
        """Analyze a plant photo to diagnose health issues, pests, diseases, and provide care recommendations.
        Input is the file path to a plant image (jpg, png, webp)."""
        path = Path(image_path.strip())
        if not path.exists():
            return f"图片文件不存在: {image_path}。请提供正确的图片路径。"

        suffix = path.suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            return f"不支持的图片格式: {suffix}。请使用 JPG、PNG 或 WebP 格式。"

        image_data = path.read_bytes()
        b64 = base64.b64encode(image_data).decode("utf-8")

        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        data_url = f"data:{mime_type};base64,{b64}"

        message = HumanMessage(
            content=[
                {"type": "text", "text": DIAGNOSIS_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )

        try:
            response = await vision_llm.ainvoke([message])
            result_text = response.content if hasattr(response, "content") else str(response)
            return f"🔍 植物图像诊断报告\n图片: {path.name}\n\n{result_text}"
        except Exception as e:
            logger.error("Image analysis failed: %s", e)
            return (
                f"图像分析失败: {e}\n"
                "可能原因：1) 视觉模型未启动 2) 模型不支持图片输入\n"
                "请确保 Ollama 已拉取视觉模型（如 llava:13b）并正在运行。"
            )

    yield FunctionInfo.from_fn(
        _analyze_image,
        description=(
            "分析植物照片，诊断健康状况，识别病虫害、营养问题和环境问题，"
            "并给出处理建议。输入图片文件路径。"
        ),
    )
