# adapters/llm_translator.py — LLM 翻译模型适配器

from typing import Optional

import aiohttp

from adapters import register_adapter
from adapters.base import BaseModelAdapter


class LLMTranslatorAdapter(BaseModelAdapter):
    """LLM 翻译适配器。

    通过 HTTP API 调用外部翻译服务。支持：
    - EPUB 文件翻译
    - OpenAI 兼容 API（SiliconFlow/OpenAI/Ollama）
    - 自定义目标语言

    HTTP API 约定：
    - POST /v1/translate           提交翻译任务
    - GET  /v1/status/<task_id>    查询任务状态
    - GET  /health                 健康检查
    """

    def model_type(self) -> str:
        return "llm-translator"

    async def validate(self, payload: dict) -> list[str]:
        errors = []
        if not payload.get("epub_data"):
            errors.append("epub_data 为必填字段（base64 编码的 EPUB 文件）")

        if not payload.get("api_key"):
            errors.append("api_key 为必填字段")

        if not payload.get("model"):
            errors.append("model 为必填字段（LLM 模型名称）")

        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        url = service_url.rstrip("/") + "/v1/translate"
        body = {
            "epub_data": payload.get("epub_data"),
            "epub_name": payload.get("epub_name", "book.epub"),
            "base_url": payload.get("base_url", "https://api.siliconflow.cn/v1"),
            "api_key": payload.get("api_key"),
            "model": payload.get("model"),
            "target_language": payload.get("target_language", "Simplified Chinese"),
        }

        timeout = aiohttp.ClientTimeout(total=600)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    if resp.status == 202:
                        data = await resp.json()
                        return data["task_id"]
                    text = await resp.text()
                    if resp.status == 400:
                        raise ValueError(text[:200])
                    raise ConnectionError(
                        f"翻译服务返回 {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"无法连接到翻译服务: {e}") from e

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        url = f"{service_url.rstrip('/')}/v1/status/{task_ref}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return {
                            "status": "failed",
                            "result": None,
                            "error": f"任务 {task_ref} 未找到",
                        }
                    return {
                        "status": "failed",
                        "result": None,
                        "error": f"状态查询失败: HTTP {resp.status}",
                    }
        except aiohttp.ClientError as e:
            return {
                "status": "failed",
                "result": None,
                "error": f"状态查询异常: {e}",
            }


register_adapter("llm-translator", LLMTranslatorAdapter)
