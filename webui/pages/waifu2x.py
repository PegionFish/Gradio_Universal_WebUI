# webui/pages/waifu2x.py — waifu2x 模型入口页面

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


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 waifu2x 图片超分标签页。"""
    gr.Markdown("## 🔍 Waifu2x 图片超分")

    try:
        adapter = get_adapter("waifu2x")
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")

    gr.Markdown("""
    > **ℹ️ waifu2x 适配器已就绪。** 配置并启动 waifu2x 服务后，即可使用图片超分功能。
        >
        > **快速开始：**
        > 1. 在<em>服务管理</em>标签页添加一个 `waifu2x` 类型的服务
        > 2. 使用 `services/waifu2x_service.py` 启动 HTTP API 服务
        > 3. 返回此页面上传图片并点击「开始放大」
        """)

    # ── 服务选择 ──
    svc_list = registry.get_by_model_type("waifu2x")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    service_info = (
        f"已找到 {len(svc_list)} 个 waifu2x 服务"
        if svc_list else "暂无 waifu2x 服务（请在服务管理中添加）"
    )
    gr.Markdown(f"*{service_info}*")

    service_selector = gr.Dropdown(
        label="服务",
        choices=service_choices,
        interactive=True,
        scale=2,
    )

    # ── 图片输入 ──
    with gr.Row():
        image_input = gr.Image(
            label="上传图片",
            type="numpy",
            sources=["upload"],
            scale=2,
        )

        with gr.Column(scale=1):
            scale = gr.Dropdown(
                label="放大倍数",
                choices=[1, 2, 4],
                value=2,
                interactive=True,
            )
            denoise_level = gr.Dropdown(
                label="降噪等级",
                choices=[-1, 0, 1, 2, 3],
                value=0,
                interactive=True,
            )
            model_type = gr.Dropdown(
                label="模型类型",
                choices=[
                    "cunet",
                    "upconv_7_anime_style_art_rgb",
                    "upconv_7_photo",
                ],
                value="cunet",
                interactive=True,
            )
            tile_size = gr.Slider(
                label="Tile Size",
                minimum=64,
                maximum=2048,
                step=64,
                value=256,
            )

    btn_submit = gr.Button("🔍 开始放大", variant="primary")

    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.HTML(label="状态", value="")
    error_output = gr.HTML(label="")

    # ── 结果 ──
    gr.Markdown("---")
    gr.Markdown("### 放大结果")
    result_image = gr.Image(
        label="结果图片",
        interactive=False,
    )
    perf_output = gr.HTML(label="")

    # ── 提交回调 ──
    def on_submit(
        service_id, image_np, scale_val, denoise_val, model_val, tile_val
    ):
        if not service_id:
            return (
                "", build_status_badge("failed"),
                format_error_message(
                    "请先选择服务",
                    suggestion="在服务管理标签页中配置并启动 waifu2x 服务",
                ),
                None, "",
            )

        if image_np is None:
            return (
                "", build_status_badge("failed"),
                format_error_message("请先上传图片"),
                None, "",
            )

        # 将 numpy 图片转为 base64
        img = Image.fromarray(image_np.astype("uint8"))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        request_payload = {
            "image": image_b64,
            "scale": int(scale_val),
            "denoise_level": int(denoise_val),
            "model_type": model_val,
            "tile_size": int(tile_val),
        }

        task_id = scheduler.create_task(
            service_id=service_id,
            model_type="waifu2x",
            adapter_name="Waifu2xAdapter",
            request_payload=request_payload,
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, request_payload)

        try:
            adapter = get_adapter("waifu2x")
            service = registry.get(service_id)
            service_url = service.service_url if service else ""

            if not service_url:
                raise ValueError("服务 URL 未配置")

            # 异步提交
            loop = asyncio.new_event_loop()
            task_ref = loop.run_until_complete(
                adapter.submit(service_url=service_url, payload=request_payload)
            )
            loop.close()

            scheduler.update_task_status(task_id, "running")

            # 轮询等待结果（最多 60 秒）
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
                    task_id, "completed", result_paths=["outputs/upscaled.png"]
                )
                result_mgr.save_response(task_id, result_data)

                return (
                    task_id,
                    build_status_badge("completed"),
                    "",
                    result_np,
                    f"scale={scale_val} | denoise={denoise_val} | model={model_val}",
                )

            else:
                error_msg = status.get("error", "放大失败")
                scheduler.update_task_status(
                    task_id, "failed", error_summary=error_msg
                )
                return (
                    task_id,
                    build_status_badge("failed"),
                    format_error_message(
                        error_msg,
                        task_id=task_id,
                        suggestion="请检查 waifu2x 服务日志或重试",
                    ),
                    None, "",
                )

        except ConnectionError as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"服务连接失败: {e}"
            )
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    "无法连接到 waifu2x 服务",
                    service_id=service_id,
                    suggestion="请确认服务已启动并且 URL 配置正确",
                    details=str(e),
                ),
                None, "",
            )
        except ValueError as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=str(e)
            )
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    str(e),
                    service_id=service_id,
                    suggestion="请在服务管理中为该服务设置有效的 service_url",
                ),
                None, "",
            )
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"提交失败: {e}"
            )
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    "放大请求处理失败",
                    task_id=task_id,
                    suggestion="请查看任务管理标签页获取详细信息",
                    details=str(e),
                ),
                None, "",
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[
            service_selector, image_input, scale,
            denoise_level, model_type, tile_size,
        ],
        outputs=[
            task_id_output, status_output, error_output,
            result_image, perf_output,
        ],
    )

    return gr.HTML("")
