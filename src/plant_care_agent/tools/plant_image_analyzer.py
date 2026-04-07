import asyncio
import base64
import logging
import mimetypes
import urllib.error
import urllib.request
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
    internal_base_url: str = Field(
        default="",
        description=(
            "工具内部下载图片时使用的 base URL（scheme://host:port），留空则直接使用传入 URL。\n"
            "当客户端上传使用公网地址（如 http://1.2.3.4:9058）而服务端 NAT 实际监听内网端口"
            "（如 http://localhost:9000）时填写，避免 hairpin NAT 问题。\n"
            "示例: http://localhost:9000"
        ),
    )


def _http_url_to_data_url(url: str, timeout: int = 30) -> tuple[str, str]:
    """下载 http/https 图片，返回 (data_url, file_name)。"""
    req = urllib.request.Request(url, headers={"User-Agent": "plant-care-agent/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        image_data = resp.read()
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()

    # 根据 Content-Type 或 URL 后缀确定 MIME
    if content_type.startswith("image/"):
        mime_type = content_type
    else:
        suffix = Path(url.split("?")[0]).suffix.lower()
        mime_type = mimetypes.guess_type(f"file{suffix}")[0] or "image/jpeg"

    b64 = base64.b64encode(image_data).decode("utf-8")
    file_name = url.rsplit("/", 1)[-1].split("?")[0] or "downloaded_image"
    return f"data:{mime_type};base64,{b64}", file_name


@register_function(
    config_type=PlantImageAnalyzerConfig,
    framework_wrappers=[LLMFrameworkEnum.LANGCHAIN],
)
async def plant_image_analyzer_function(config: PlantImageAnalyzerConfig, builder: Builder):
    from langchain_core.messages import HumanMessage
    from urllib.parse import urlparse, urlunparse

    vision_llm = await builder.get_llm(config.vision_llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    _internal_base = (config.internal_base_url or "").rstrip("/")

    def _rewrite_url(url: str) -> str:
        """将公网 URL 替换为内部 base URL（仅替换 scheme://host:port 部分）。"""
        if not _internal_base:
            return url
        parsed = urlparse(url)
        internal = urlparse(_internal_base)
        rewritten = parsed._replace(
            scheme=internal.scheme,
            netloc=internal.netloc,
        )
        new_url = urlunparse(rewritten)
        if new_url != url:
            logger.info("URL rewritten for internal access: %s -> %s", url, new_url)
        return new_url

    async def _analyze_image(image_path: str) -> str:
        """Analyze a plant photo to diagnose health issues, pests, diseases, and provide care recommendations.
        Input is a local file path, an http/https URL, or a base64 data URL (data:image/...;base64,...)."""
        logger.info("plant_image_analyzer called, image_path=%s", image_path[:80])

        if image_path.startswith("data:image/"):
            # ── Base64 data URL（客户端直接编码传入）
            data_url = image_path
            file_name = "uploaded_image"

        elif image_path.startswith(("http://", "https://")):
            # ── HTTP/HTTPS URL（multipart 上传后的 NAT /static/ 地址，或外部图床链接）
            # 使用 asyncio.to_thread 避免同步阻塞 I/O 占用事件循环导致超时
            download_url = _rewrite_url(image_path)
            logger.info("Downloading image from URL: %s", download_url)
            try:
                data_url, file_name = await asyncio.to_thread(_http_url_to_data_url, download_url)
                logger.info("Downloaded %s, data_url length: %d", file_name, len(data_url))
            except urllib.error.HTTPError as e:
                return f"图片下载失败 (HTTP {e.code}): {download_url}\n请确认 URL 可访问。"
            except urllib.error.URLError as e:
                return f"图片下载失败: {e.reason}\nURL: {download_url}"
            except Exception as e:
                return f"图片下载失败: {e}\nURL: {download_url}"

        else:
            # ── 本地文件路径
            path = Path(image_path.strip())
            if not path.exists():
                return f"图片文件不存在: {image_path}。请提供正确的图片路径。"

            suffix = path.suffix.lower()
            if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                return f"不支持的图片格式: {suffix}。请使用 JPG、PNG 或 WebP 格式。"

            image_data = await asyncio.to_thread(path.read_bytes)
            b64 = base64.b64encode(image_data).decode("utf-8")
            mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
            data_url = f"data:{mime_type};base64,{b64}"
            file_name = path.name

        message = HumanMessage(
            content=[
                {"type": "text", "text": DIAGNOSIS_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )

        try:
            logger.info("Calling vision LLM for image: %s (data_url length: %d)", file_name, len(data_url))
            response = await vision_llm.ainvoke([message])
            result_text = response.content if hasattr(response, "content") else str(response)
            logger.info("Vision LLM response received, length: %d chars, preview: %s",
                        len(result_text), repr(result_text[:200]))
            return f"[TOOL_OK] 🔍 植物图像诊断报告\n图片: {file_name}\n\n{result_text}"
        except Exception as e:
            logger.error("Image analysis failed: %s", e)
            return (
                f"[TOOL_ERR] 图像分析失败: {e}\n"
                "可能原因：1) 视觉模型未启动 2) 模型不支持图片输入\n"
                "请确保 Ollama 已拉取视觉模型（如 llava:13b）并正在运行。"
            )

    yield FunctionInfo.from_fn(
        _analyze_image,
        description=(
            "分析植物照片，诊断健康状况，识别病虫害、营养问题和环境问题，"
            "并给出处理建议。"
            "输入本地图片路径、http/https 图片链接或 base64 data URL（data:image/...;base64,...）。"
        ),
    )

