"""web_search — 联网搜索工具，用于查询植物养护、病虫害、品种等实时信息。

底层使用 duckduckgo-search（免费、无需 API key）。
"""

import logging

from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)


class WebSearchConfig(FunctionBaseConfig, name="web_search"):
    max_results: int = Field(default=5, ge=1, le=20, description="每次搜索返回的最大结果数")
    region: str = Field(default="cn-zh", description="搜索区域偏好")


@register_function(config_type=WebSearchConfig)
async def web_search_function(config: WebSearchConfig, _builder: Builder):

    async def _search(query: str) -> str:
        """Search the web for information about plants, gardening, pest control, etc.
        Input: search query string (Chinese or English).
        Returns: top search results with titles, URLs, and snippets."""
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return (
                "web_search 依赖 duckduckgo-search 包，请先安装：\n"
                "  pip install duckduckgo-search"
            )

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, region=config.region, max_results=config.max_results))
        except Exception as e:
            logger.warning("Web search failed: %s", e)
            return f"搜索失败: {e}\n请检查网络连接后重试。"

        if not results:
            return f"未找到「{query}」的相关结果。请尝试换个关键词。"

        lines = [f"🔍 搜索「{query}」共找到 {len(results)} 条结果：\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")
            lines.append(f"**{i}. {title}**")
            if href:
                lines.append(f"   链接: {href}")
            if body:
                lines.append(f"   {body}")
            lines.append("")

        return "\n".join(lines)

    async def _search_images(query: str) -> str:
        """Search the web for plant images.
        Input: search query (e.g. '番茄叶斑病症状').
        Returns: image URLs with descriptions."""
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "web_search 依赖 duckduckgo-search 包，请先安装：pip install duckduckgo-search"

        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query, region=config.region, max_results=config.max_results))
        except Exception as e:
            logger.warning("Image search failed: %s", e)
            return f"图片搜索失败: {e}"

        if not results:
            return f"未找到「{query}」的相关图片。"

        lines = [f"🖼️ 图片搜索「{query}」共 {len(results)} 张：\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("image", "")
            source = r.get("source", "")
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   图片: {url}")
            if source:
                lines.append(f"   来源: {source}")
            lines.append("")

        return "\n".join(lines)

    yield FunctionInfo.from_fn(
        _search,
        description="联网搜索植物种植、养护、病虫害等信息。支持中英文查询。",
    )
    yield FunctionInfo.from_fn(
        _search_images,
        description="联网搜索植物相关图片（病虫害症状、品种对比等）。",
    )
