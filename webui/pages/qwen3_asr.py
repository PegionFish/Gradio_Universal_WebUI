# webui/pages/qwen3_asr.py — Qwen3 ASR 模型入口页面（完整实现）

import asyncio
import gradio as gr
from adapters import get_adapter
from core import registry, scheduler, result_mgr, gpu_monitor
from webui.components.error_display import format_error_message


SUPPORTED_LANGUAGES = [
    "Auto", "zh", "en", "ja", "ko", "yue",
    "de", "fr", "es", "it", "pt", "ru", "ar",
]


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 Qwen3 ASR 模型入口标签页。"""
    gr.Markdown("## 🎙️ Qwen3 ASR 语音识别")

    # 检查适配器
    try:
        adapter = get_adapter("qwen3-asr")
        is_placeholder = isinstance(adapter.submit, type(lambda: None))
        # 检测是否是占位实现：尝试调用会抛出 NotImplementedError
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                adapter.submit("http://localhost", {"audio_path": "/dev/null"})
            )
            loop.close()
        except NotImplementedError:
            is_placeholder = True
        except Exception:
            is_placeholder = False
    except ValueError:
        gr.Markdown("> **⚠️ 适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")

    if is_placeholder:
        gr.Markdown("""
        > **ℹ️ Qwen3 ASR 适配器已就绪。** 配置并启动 Qwen3ASR 服务后，即可使用音频转录功能。
        >
        > **快速开始：**
        > 1. 在<em>服务管理</em>标签页添加一个 `qwen3-asr` 类型的服务
        > 2. 使用 `services/qwen3_asr_service.py` 启动 HTTP API 服务
        > 3. 返回此页面使用转录功能
        """)

    # ── 服务选择 ──
    svc_list = registry.get_by_model_type("qwen3-asr")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    service_info = (
        f"已找到 {len(svc_list)} 个 Qwen3ASR 服务"
        if svc_list else "暂无 Qwen3ASR 服务（请在服务管理中添加）"
    )
    gr.Markdown(f"*{service_info}*")

    service_selector = gr.Dropdown(
        label="服务",
        choices=service_choices,
        interactive=True,
        scale=2,
    )

    # ── 音频输入 ──
    with gr.Row():
        audio_input = gr.Audio(
            label="音频输入",
            type="numpy",
            sources=["upload", "microphone"],
            scale=2,
        )

        with gr.Column(scale=1):
            language_selector = gr.Dropdown(
                label="语种",
                choices=SUPPORTED_LANGUAGES,
                value="Auto",
                interactive=True,
            )
            return_timestamps = gr.Checkbox(
                label="返回时间戳",
                value=True,
            )
            return_srt = gr.Checkbox(
                label="返回 SRT 字幕",
                value=False,
            )

    # ── 提交按钮 ──
    btn_submit = gr.Button("🎙️ 开始转录", variant="primary")

    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.Textbox(label="状态", interactive=False)
    error_output = gr.HTML(label="")

    # ── 转录结果 ──
    gr.Markdown("---")
    gr.Markdown("### 识别结果")
    result_text = gr.Textbox(
        label="转录文本",
        lines=5,
        interactive=False,
        placeholder="转录结果将在此处显示...",
    )
    srt_output = gr.Textbox(
        label="SRT 字幕",
        lines=10,
        interactive=False,
        visible=False,
        placeholder="勾选「返回 SRT 字幕」后将在此处显示...",
    )

    def toggle_srt_visibility(checked):
        return gr.update(visible=checked)

    return_srt.change(
        fn=toggle_srt_visibility,
        inputs=return_srt,
        outputs=srt_output,
    )

    # ── 提交回调 ──
    def on_submit(service_id, audio, language, with_timestamps, with_srt):
        if not service_id:
            return (
                "", "错误",
                format_error_message(
                    "请先选择服务",
                    suggestion="在服务管理标签页中配置并启动 Qwen3ASR 服务",
                ),
                "", "",
            )

        if audio is None:
            return (
                "", "错误",
                format_error_message(
                    "请上传音频文件或使用麦克风录制",
                    suggestion="支持的格式: WAV, MP3, FLAC, M4A",
                ),
                "", "",
            )

        # 创建任务记录
        import numpy as np
        task_id = scheduler.create_task(
            service_id=service_id,
            model_type="qwen3-asr",
            adapter_name="Qwen3ASRAdapter",
            request_payload={
                "language": language,
                "return_timestamps": with_timestamps,
                "return_srt": with_srt,
                "audio_duration": len(audio[1]) / audio[0] if isinstance(audio, tuple) else 0,
            },
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {
            "language": language,
            "return_timestamps": with_timestamps,
            "return_srt": with_srt,
        })

        try:
            adapter = get_adapter("qwen3-asr")
            service = registry.get(service_id)
            service_url = service.service_url if service else ""

            if not service_url:
                raise ValueError("服务 URL 未配置")

            # 将音频 numpy 数组转为 base64
            import base64
            import io
            from scipy.io.wavfile import write as wav_write

            if isinstance(audio, tuple):
                sr, data = audio
            else:
                sr, data = audio[0], audio[1]

            # 确保是 float32 单声道
            if data.ndim > 1:
                data = data.mean(axis=1)
            data = data.astype(np.float32)

            # 写入 WAV bytes
            wav_buffer = io.BytesIO()
            wav_write(wav_buffer, sr, data)
            audio_b64 = base64.b64encode(wav_buffer.getvalue()).decode("utf-8")

            # 异步提交
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                adapter.submit(
                    service_url=service_url,
                    payload={
                        "audio": audio_b64,
                        "language": language,
                        "return_timestamps": with_timestamps,
                        "return_srt": with_srt,
                    },
                )
            )
            loop.close()

            scheduler.update_task_status(task_id, "running")

            # 轮询等待结果（最多 60 秒）
            for _ in range(30):
                loop = asyncio.new_event_loop()
                status = loop.run_until_complete(
                    adapter.poll_status(service_url, result)
                )
                loop.close()

                if status["status"] in ("completed", "failed"):
                    break
                import time
                time.sleep(2)

            if status["status"] == "completed":
                result_data = status.get("result", {})
                text = result_data.get("text", "")
                srt = result_data.get("srt", "")

                scheduler.update_task_status(
                    task_id, "completed",
                    result_paths=["outputs/transcript.txt"],
                )
                result_mgr.save_response(task_id, {
                    "text": text, "srt": srt, "status": "completed",
                })
                result_mgr.save_log(task_id, "transcript.txt", text)

                return (
                    task_id, "✅ 完成", "",
                    text, srt if with_srt else "",
                )

            else:
                error_msg = status.get("error", "转录失败")
                scheduler.update_task_status(
                    task_id, "failed", error_summary=error_msg,
                )
                return (
                    task_id, "❌ 失败",
                    format_error_message(
                        error_msg,
                        task_id=task_id,
                        suggestion="请检查 Qwen3ASR 服务日志或重试",
                    ),
                    "", "",
                )

        except NotImplementedError as e:
            scheduler.update_task_status(
                task_id, "failed",
                error_summary=str(e),
            )
            result_mgr.save_log(task_id, "error.log", str(e))
            return (
                task_id, "❌ 失败",
                format_error_message(
                    "Qwen3ASR 适配器尚未实现。",
                    suggestion="启动 Qwen3ASR 服务: python services/qwen3_asr_service.py --port 8100 --checkpoint /path/to/model",
                    details=str(e),
                ),
                "", "",
            )
        except ConnectionError as e:
            scheduler.update_task_status(
                task_id, "failed",
                error_summary=f"服务连接失败: {e}",
            )
            return (
                task_id, "❌ 连接失败",
                format_error_message(
                    "无法连接到 Qwen3ASR 服务",
                    service_id=service_id,
                    suggestion="请确认服务已启动并且 URL 配置正确",
                    details=str(e),
                ),
                "", "",
            )
        except ValueError as e:
            scheduler.update_task_status(
                task_id, "failed",
                error_summary=str(e),
            )
            return (
                task_id, "❌ 配置错误",
                format_error_message(
                    str(e),
                    service_id=service_id,
                    suggestion="请在服务管理中为该服务设置有效的 service_url",
                ),
                "", "",
            )
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed",
                error_summary=f"提交失败: {e}",
            )
            return (
                task_id, "❌ 错误",
                format_error_message(
                    "转录请求处理失败",
                    task_id=task_id,
                    suggestion="请查看任务管理标签页获取详细信息",
                    details=str(e),
                ),
                "", "",
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[
            service_selector, audio_input, language_selector,
            return_timestamps, return_srt,
        ],
        outputs=[
            task_id_output, status_output, error_output,
            result_text, srt_output,
        ],
    )

    return gr.HTML("")
