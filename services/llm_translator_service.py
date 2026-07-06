#!/usr/bin/env python3
# services/llm_translator_service.py — LLM 翻译 HTTP API 服务包装器
"""
将 EPUB 翻译功能封装为 HTTP API 服务，供 WebUI 适配器调用。

使用 OpenAI 兼容 API 进行翻译，支持 SiliconFlow/OpenAI/Ollama 等后端。

启动方式:
    python services/llm_translator_service.py --port 17930

API 端点:
    POST /v1/translate             提交翻译任务
    GET  /v1/status/<task_id>      查询任务状态与结果
    GET  /health                   健康检查
"""

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

logger = logging.getLogger("llm_translator_service")

_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)


def _translate_epub_sync(
    task_id: str,
    epub_data: bytes,
    epub_name: str,
    base_url: str,
    api_key: str,
    model: str,
    target_language: str,
) -> None:
    try:
        from openai import OpenAI
        from ebooklib import epub
        from bs4 import BeautifulSoup

        client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)

        with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
            tmp.write(epub_data)
            epub_path = tmp.name

        try:
            book = epub.read_epub(epub_path)
            chapters = []
            for item in book.get_items():
                if item.get_type() == 1:  # ITEM_DOCUMENT
                    html_content = item.get_content().decode("utf-8")
                    soup = BeautifulSoup(html_content, "lxml")
                    text = soup.get_text(separator="\n", strip=True)
                    if text.strip():
                        chapters.append({
                            "id": item.get_name(),
                            "html": html_content,
                            "text": text.strip(),
                        })

            total = len(chapters)
            _task_store[task_id]["result"] = {
                "progress": 0,
                "total_chapters": total,
                "translated_chapters": 0,
            }

            for idx, chapter in enumerate(chapters):
                try:
                    paragraphs = _split_paragraphs(chapter["text"])
                    translated_parts = []

                    for para in paragraphs:
                        if not para.strip():
                            translated_parts.append("")
                            continue
                        prompt = (
                            f"Translate the following text to {target_language}. "
                            f"Keep the original meaning and tone. "
                            f"Only output the translation, no explanations.\n\n{para}"
                        )
                        translation = _call_llm(client, model, prompt)
                        translated_parts.append(translation if translation else para)

                    translated_text = "\n".join(translated_parts)
                    _update_html_item(book, chapter["id"], chapter["html"], translated_text)

                    _task_store[task_id]["result"]["translated_chapters"] = idx + 1
                    _task_store[task_id]["result"]["progress"] = int(
                        (idx + 1) / total * 100
                    )

                except Exception as e:
                    logger.warning("章节 %s 翻译失败，保留原文: %s", chapter["id"], e)

            output_buf = io.BytesIO()
            epub.write_epub(output_buf, book)
            epub_b64 = base64.b64encode(output_buf.getvalue()).decode("utf-8")

            _task_store[task_id] = {
                "status": "completed",
                "result": {
                    "epub_base64": epub_b64,
                    "epub_name": epub_name.rsplit(".", 1)[0] + "_translated.epub",
                    "progress": 100,
                    "total_chapters": total,
                    "translated_chapters": total,
                },
                "error": None,
            }

        finally:
            os.unlink(epub_path)

    except ImportError as e:
        logger.error("缺少依赖: %s", e)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": f"缺少依赖: {e}。请安装: pip install openai ebooklib beautifulsoup4 lxml",
        }
    except Exception as e:
        logger.exception("翻译任务 %s 失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
        }


def _split_paragraphs(text: str, max_chars: int = 50000) -> list[str]:
    raw_paragraphs = text.split("\n")
    chunks = []
    current = ""
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 1 > max_chars:
            if current:
                chunks.append(current)
            current = para
        else:
            current = current + "\n" + para if current else para
    if current:
        chunks.append(current)
    return chunks


def _call_llm(client, model: str, prompt: str) -> str:
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if "rate" in str(e).lower() and attempt < 2:
                import time
                time.sleep(60)
            else:
                logger.error("LLM 调用失败: %s", e)
                return ""


def _update_html_item(book, item_name: str, original_html: str, translated_text: str):
    translated_paragraphs = translated_text.split("\n")
    for item in book.get_items():
        if item.get_name() == item_name:
            soup = BeautifulSoup(item.get_content().decode("utf-8"), "lxml")
            text_elements = soup.find_all(
                ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "span", "div"]
            )
            p_idx = 0
            for elem in text_elements:
                elem_text = elem.get_text(strip=True)
                if not elem_text:
                    continue
                if p_idx < len(translated_paragraphs):
                    elem.string = translated_paragraphs[p_idx]
                    p_idx += 1
            item.set_content(str(soup).encode("utf-8"))
            break


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "llm-translator"})


async def handle_translate(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "请求体必须是 JSON"}, status=400)

    epub_b64 = payload.get("epub_data")
    if not epub_b64:
        return web.json_response({"error": "epub_data 为必填字段"}, status=400)

    api_key = payload.get("api_key")
    if not api_key:
        return web.json_response({"error": "api_key 为必填字段"}, status=400)

    model = payload.get("model")
    if not model:
        return web.json_response({"error": "model 为必填字段"}, status=400)

    try:
        epub_data = base64.b64decode(epub_b64)
    except Exception:
        return web.json_response({"error": "无效的 base64 EPUB 数据"}, status=400)

    task_id = str(uuid.uuid4())
    _task_store[task_id] = {
        "status": "queued",
        "result": {"progress": 0, "total_chapters": 0, "translated_chapters": 0},
        "error": None,
    }

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _translate_epub_sync,
        task_id,
        epub_data,
        payload.get("epub_name", "book.epub"),
        payload.get("base_url", "https://api.siliconflow.cn/v1"),
        api_key,
        model,
        payload.get("target_language", "Simplified Chinese"),
    )

    return web.json_response({"task_id": task_id, "status": "queued"}, status=202)


async def handle_status(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    task = _task_store.get(task_id)
    if not task:
        return web.json_response(
            {"status": "failed", "result": None, "error": "任务不存在"},
            status=404,
        )
    return web.json_response(task)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/v1/translate", handle_translate)
    app.router.add_get("/v1/status/{task_id}", handle_status)
    return app


def main():
    parser = argparse.ArgumentParser(description="LLM 翻译 HTTP API 服务")
    parser.add_argument("--port", type=int, default=17930, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("LLM 翻译服务启动于 http://%s:%s", args.host, args.port)
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
