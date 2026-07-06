# webui/pages/rembg.py — RemBg 背景移除模型入口页面

import asyncio
import base64
import io
import logging

import gradio as gr
import numpy as np
from PIL import Image

from adapters import get_adapter
from core import registry, scheduler, result_mgr
from webui.components.error_display import format_error_message
from webui.components.progress_indicator import build_status_badge

logger = logging.getLogger(__name__)

REMBG_MODELS = [
    ("通用分割 (isnet-general-use)", "isnet-general-use"),
    ("高质量通用 (u2net)", "u2net"),
    ("轻量快速 (u2netp)", "u2netp"),
    ("人像分割 (u2net_human_seg)", "u2net_human_seg"),
    ("服装分割 (u2net_cloth_seg)", "u2net_cloth_seg"),
    ("动漫分割 (isnet-anime)", "isnet-anime"),
]


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## ✂️ RemBg 背景移除")

    try:
        adapter = get_adapter("rembg")
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")

    gr.Markdown("""
    > **ℹ️ RemBg 适配器已就绪。** 配置并启动 RemBg 服务后，即可使用背景移除功能。
    >
    > **快速开始：**
    > 1. 在<em>服务管理</em>标签页添加一个 `rembg` 类型的服务
    > 2. 使用 `services/rembg_service.py --models-dir /path/to/models` 启动服务
    > 3. 返回此页面上传图片并点击「开始去除背景」
    """)

    svc_list = registry.get_by_model_type("rembg")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    service_info = (
        f"已找到 {len(svc_list)} 个 RemBg 服务"
        if svc_list else "暂无 RemBg 服务（请在服务管理中添加）"
    )
    gr.Markdown(f"*{service_info}*")

    service_selector = gr.Dropdown(
        label="服务",
        choices=service_choices,
        interactive=True,
    )

    with gr.Row():
        with gr.Column(scale=1):
            image_input = gr.Image(
                label="上传图片",
                type="numpy",
                sources=["upload", "clipboard"],
            )
            model_selector = gr.Dropdown(
                label="分割模型",
                choices=REMBG_MODELS,
                value="isnet-general-use",
                interactive=True,
            )
            btn_submit = gr.Button("✂️ 开始去除背景", variant="primary")

        with gr.Column(scale=1):
            result_image = gr.Image(
                label="去背景结果",
                interactive=False,
            )

    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.HTML(label="状态", value="")
    error_output = gr.HTML(label="")

    def on_submit(service_id, image_np, model_name):
        if not service_id:
            return (
                "", build_status_badge("failed"),
                format_error_message(
                    "请先选择服务",
                    suggestion="在服务管理标签页中配置并启动 RemBg 服务",
                ),
                None,
            )

        if image_np is None:
            return (
                "", build_status_badge("failed"),
                format_error_message("请先上传图片"),
                None,
            )

        img = Image.fromarray(image_np.astype("uint8"))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        request_payload = {
            "image": image_b64,
            "model": model_name,
        }

        task_id = scheduler.create_task(
            service_id=service_id,
            model_type="rembg",
            adapter_name="RemBgAdapter",
            request_payload={"model": model_name},
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, request_payload)

        try:
            adapter = get_adapter("rembg")
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

            for _ in range(30):
                loop = asyncio.new_event_loop()
                status = loop.run_until_complete(
                    adapter.poll_status(service_url, task_ref)
                )
                loop.close()

                if status["status"] in ("completed", "failed"):
                    break
                import time
                time.sleep(2)

            if status["status"] == "completed":
                result_data = status.get("result", {})
                result_b64 = result_data.get("image_base64", "")
                if result_b64:
                    result_bytes = base64.b64decode(result_b64)
                    result_img = Image.open(io.BytesIO(result_bytes))
                    result_np = np.array(result_img)
                else:
                    result_np = None

                scheduler.update_task_status(
                    task_id, "completed", result_paths=["outputs/removed_bg.png"]
                )
                result_mgr.save_response(task_id, result_data)

                return (
                    task_id,
                    build_status_badge("completed"),
                    "",
                    result_np,
                )

            error_msg = status.get("error", "背景移除失败")
            scheduler.update_task_status(task_id, "failed", error_summary=error_msg)
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    error_msg,
                    task_id=task_id,
                    suggestion="请检查 RemBg 服务日志或重试",
                ),
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
                    "无法连接到 RemBg 服务",
                    service_id=service_id,
                    suggestion="请确认服务已启动并且 URL 配置正确",
                    details=str(e),
                ),
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
                    "背景移除请求处理失败",
                    task_id=task_id,
                    suggestion="请查看任务管理标签页获取详细信息",
                    details=str(e),
                ),
                None,
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[service_selector, image_input, model_selector],
        outputs=[task_id_output, status_output, error_output, result_image],
    )

    return gr.HTML("")
