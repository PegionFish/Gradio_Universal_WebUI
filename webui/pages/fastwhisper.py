# webui/pages/fastwhisper.py — FastWhisper 模型入口页面（占位）

import gradio as gr
from adapters import get_adapter
from core import registry, scheduler, result_mgr


def create_page(app_state: gr.State) -> gr.HTML:
    """创建 FastWhisper 模型入口标签页。"""
    gr.Markdown("## FastWhisper")

    try:
        get_adapter("fastwhisper")
    except ValueError:
        gr.Markdown("> **适配器未注册。** 请检查适配器模块加载。")
        return gr.HTML("")

    gr.Markdown(
        "> **FastWhisper 适配器当前为占位状态。** "
        "第二阶段将实现音频文件上传和语音转录功能。"
    )

    svc_list = registry.get_by_model_type("fastwhisper")
    service_choices = [(s.display_name, s.id) for s in svc_list]
    service_selector = gr.Dropdown(
        label="服务", choices=service_choices, interactive=True,
    )

    gr.Markdown("### 语音转录（第二阶段实现）")
    gr.Markdown("- 音频文件上传\n- 语种选择\n- 转录结果展示")

    btn_submit = gr.Button("提交测试任务", variant="secondary")
    with gr.Row():
        task_id_output = gr.Textbox(label="任务 ID", interactive=False)
        status_output = gr.Textbox(label="状态", interactive=False)
    error_output = gr.Textbox(label="信息", lines=3, interactive=False)

    def on_submit(service_id):
        if not service_id:
            return "", "错误", "请先选择服务"

        task_id = scheduler.create_task(
            service_id=service_id,
            model_type="fastwhisper",
            adapter_name="FastWhisperAdapter",
            request_payload={"action": "transcribe"},
        )
        result_mgr.ensure_task_dir(task_id)
        result_mgr.save_request(task_id, {"action": "transcribe"})

        try:
            adapter = get_adapter("fastwhisper")
            import asyncio
            loop = asyncio.new_event_loop()
            adapter.submit(service_url="", payload={"action": "transcribe"})
            loop.close()
            return task_id, "完成", ""
        except NotImplementedError as e:
            scheduler.update_task_status(task_id, "failed", error_summary=str(e))
            result_mgr.save_log(task_id, "error.log", str(e))
            return task_id, "失败", str(e)
        except Exception as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"提交失败: {e}",
            )
            return task_id, "错误", str(e)

    btn_submit.click(
        fn=on_submit,
        inputs=service_selector,
        outputs=[task_id_output, status_output, error_output],
    )

    return gr.HTML("")
