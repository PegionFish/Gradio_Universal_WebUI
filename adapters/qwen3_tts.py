# adapters/qwen3_tts.py — Qwen3 TTS 文字转语音模型适配器

from typing import Optional

import aiohttp

from adapters import register_adapter
from adapters.base import BaseModelAdapter


class Qwen3TTSAdapter(BaseModelAdapter):
    """Qwen3 TTS 模型适配器。

    通过 HTTP API 调用外部 Qwen3TTS 服务。支持：
    - 语音设计（Voice Design）：通过自然语言描述创建音色
    - 语音克隆（Voice Clone）：基于参考音频复刻声音
    - 自定义音色（Custom Voice）：使用预设说话人 + 情感控制

    HTTP API 约定：
    - POST /v1/tts                提交语音合成任务
    - GET  /v1/status/<task_id>   查询任务状态
    - GET  /health                健康检查
    """

    VALID_MODES = {"voice-design", "voice-clone", "custom-voice"}

    VALID_LANGUAGES = [
        "Chinese", "English", "Japanese", "Korean",
        "German", "French", "Russian", "Portuguese",
        "Spanish", "Italian", "Auto",
    ]

    VALID_SPEAKERS = [
        "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric",
        "Ryan", "Aiden", "Ono_Anna", "Sohee",
    ]

    def model_type(self) -> str:
        return "qwen3-tts"

    async def validate(self, payload: dict) -> list[str]:
        errors = []
        if not payload.get("text"):
            errors.append("text 为必填字段")

        mode = payload.get("mode", "voice-design")
        if mode not in self.VALID_MODES:
            errors.append(f"mode 必须是 {sorted(self.VALID_MODES)} 之一")

        lang = payload.get("language", "Auto")
        if lang not in self.VALID_LANGUAGES:
            errors.append(f"language 必须是 {self.VALID_LANGUAGES} 之一")

        if mode == "custom-voice":
            speaker = payload.get("speaker", "")
            if speaker not in self.VALID_SPEAKERS:
                errors.append(f"speaker 必须是 {self.VALID_SPEAKERS} 之一")

        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        url = service_url.rstrip("/") + "/v1/tts"
        body = {
            "text": payload.get("text"),
            "mode": payload.get("mode", "voice-design"),
            "language": payload.get("language", "Auto"),
            "instruct": payload.get("instruct", ""),
            "speaker": payload.get("speaker", "Vivian"),
            "ref_audio": payload.get("ref_audio"),
            "ref_text": payload.get("ref_text", ""),
        }

        timeout = aiohttp.ClientTimeout(total=120)
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
                        f"TTS 服务返回 {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"无法连接到 TTS 服务: {e}") from e

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


register_adapter("qwen3-tts", Qwen3TTSAdapter)
