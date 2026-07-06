# webui/pages/llm_translator.py — LLM 翻译模型入口页面

import asyncio
import base64
import io
import logging
import os

import gradio as gr

from adapters import get_adapter
from core import registry, scheduler, result_mgr
from webui.components.error_display import format_error_message
from webui.components.progress_indicator import build_status_badge

logger = logging.getLogger(__name__)

TARGET_LANGUAGES = [
    "Simplified Chinese",
    "Traditional Chinese",
    "English",
    "Japanese",
    "Korean",
    "French",
    "German",
    "Spanish",
    "Russian",
]


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## 📖 LLM 翻译")

    try:
        adapter = get_adapter("llm-translator")
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")

    gr.Markdown("""
    > **ℹ️ LLM 翻译适配器已就绪。** 配置并启动翻译服务后，即可使用 EPUB 翻译功能。
    >
    > **快速开始：**
    > 1. 在<em>服务管理</em>标签页添加一个 `llm-translator` 类型的服务
    > 2. 使用 `services/llm_translator_service.py` 启动 HTTP API 服务
    > 3. 返回此页面配置 API 信息并上传 EPUB 文件
    """)

    svc_list = registry.get_by_model_type("llm-translator")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    service_info = (
        f"已找到 {len(svc_list)} 个翻译服务"
        if svc_list else "暂无翻译服务（请在服务管理中添加）"
    )
    gr.Markdown(f"*{service_info}*")

    service_selector = gr.Dropdown(
        label="服务",
        choices=service_choices,
        interactive=True,
    )

    gr.Markdown("### API 配置")
    with gr.Row():
        base_url_input = gr.Textbox(
            label="API Base URL",
            placeholder="https://api.siliconflow.cn/v1",
            value="https://api.siliconflow.cn/v1",
        )
        api_key_input = gr.Textbox(
            label="API Key",
            placeholder="sk-xxx",
            type="password",
        )
        model_input = gr.Textbox(
            label="模型",
            placeholder="Qwen/Qwen2.5-7B-Instruct",
            value="Qwen/Qwen2.5-7B-Instruct",
        )

    gr.Markdown("### 翻译设置")
    with gr.Row():
        epub_input = gr.File(
            label="上传 EPUB 文件",
            file_types=[".epub"],
            file_count="single",
        )
        target_lang = gr.Dropdown(
            label="目标语言",
            choices=TARGET_LANGUAGES,
            value="Simplified Chinese",
            interactive=True,
        )

    btn_submit = gr.Button("📖 开始翻译", variant="primary")

    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.HTML(label="状态", value="")
    error_output = gr.HTML(label="")

    progress_output = gr.Markdown("")
    download_output = gr.File(label="翻译结果", visible=False)

    def on_submit(service_id, epub_file, base_url, api_key, model, target_lang):
        if not service_id:
            return (
                "", build_status_badge("failed"),
                format_error_message(
                    "请先选择服务",
                    suggestion="在服务管理标签页中配置并启动翻译服务",
                ),
                "", None,
            )

        if not epub_file:
            return (
                "", build_status_badge("failed"),
                format_error_message("请上传 EPUB 文件"),
                "", None,
            )

        if not api_key:
            return (
                "", build_status_badge("failed"),
                format_error_message("请填写 API Key"),
                "", None,
            )

        if not model:
            return (
                "", build_status_badge("failed"),
                format_error_message("请填写模型名称"),
                "", None,
            )

        epub_path = epub_file.name if hasattr(epub_file, "name") else epub_file
        epub_name = epub_path.split("/")[-1].split("\\")[-1]

        with open(epub_path, "rb") as f:
            epub_b64 = base64.b64encode(f.read()).decode("utf-8")

        request_payload = {
            "epub_data": epub_b64,
            "epub_name": epub_name,
            "base_url": base_url or "https://api.siliconflow.cn/v1",
            "api_key": api_key,
            "model": model,
            "target_language": target_lang,
        }

        task_id = scheduler.create_task(
            service_id=service_id,
            model_type="llm-translator",
            adapter_name="LLMTranslatorAdapter",
            request_payload={
                "epub_name": epub_name,
                "model": model,
                "target_language": target_lang,
            },
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {
            "epub_name": epub_name,
            "model": model,
            "target_language": target_lang,
        })

        try:
            adapter = get_adapter("llm-translator")
            service = registry.get(service_id)
            service_url = service.service_url if service else ""

            if not service_url:
                raise ValueError("服务 URL 未配置")

            loop = asyncio.new_event_loop()
            task_ref = loop.run_until_complete(
                adapter.submit(service_url=service_url, payload=request_payload)
            )
            loop.close()

            scheduler.update_task_status(task_id, "running")

            for _ in range(120):
                loop = asyncio.new_event_loop()
                status = loop.run_until_complete(
                    adapter.poll_status(service_url, task_ref)
                )
                loop.close()

                if status["status"] in ("completed", "failed"):
                    break

                result = status.get("result") or {}
                progress = result.get("progress", 0)
                translated = result.get("translated_chapters", 0)
                total = result.get("total_chapters", 0)

                import time
                time.sleep(3)

            if status["status"] == "completed":
                result_data = status.get("result", {})
                epub_out_b64 = result_data.get("epub_base64", "")
                epub_out_name = result_data.get("epub_name", "translated.epub")

                if epub_out_b64:
                    epub_bytes = base64.b64decode(epub_out_b64)
                    out_path = f"data/jobs/tasks/{task_id}/outputs/{epub_out_name}"
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(epub_bytes)

                    scheduler.update_task_status(
                        task_id, "completed",
                        result_paths=[f"outputs/{epub_out_name}"],
                    )
                    result_mgr.save_response(task_id, {
                        "epub_name": epub_out_name,
                        "status": "completed",
                    })

                    return (
                        task_id,
                        build_status_badge("completed"),
                        f"翻译完成！共 {result_data.get('total_chapters', 0)} 章",
                        f"**{epub_out_name}**",
                        out_path,
                    )

                scheduler.update_task_status(task_id, "completed")
                return (
                    task_id,
                    build_status_badge("completed"),
                    "翻译完成",
                    "",
                    None,
                )

            error_msg = status.get("error", "翻译失败")
            scheduler.update_task_status(task_id, "failed", error_summary=error_msg)
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    error_msg,
                    task_id=task_id,
                    suggestion="请检查翻译服务日志或 API 配置",
                ),
                "",
                None,
            )

        except ConnectionError as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"服务连接失败: {e}"
            )
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    "无法连接到翻译服务",
                    service_id=service_id,
                    suggestion="请确认服务已启动并且 URL 配置正确",
                    details=str(e),
                ),
                "",
                None,
            )
        except ValueError as e:
            scheduler.update_task_status(task_id, "failed", error_summary=str(e))
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    str(e),
                    service_id=service_id,
                    suggestion="请在服务管理中为该服务设置有效的 service_url",
                ),
                "",
                None,
            )
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"提交失败: {e}"
            )
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    "翻译请求处理失败",
                    task_id=task_id,
                    suggestion="请查看任务管理标签页获取详细信息",
                    details=str(e),
                ),
                "",
                None,
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[
            service_selector, epub_input, base_url_input,
            api_key_input, model_input, target_lang,
        ],
        outputs=[
            task_id_output, status_output, error_output,
            progress_output, download_output,
        ],
    )

    return gr.HTML("")
