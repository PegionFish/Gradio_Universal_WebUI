# webui/pages/settings.py — 统一模型设置页面

import gradio as gr
import yaml
from core import config as cfg, registry, process_manager
from core.config_service import ConfigError
from webui.components.error_display import format_error_message

# 每个模型类型的可配置字段定义
MODEL_FIELDS = {
    "qwen3-tts": {
        "display_name": "Qwen3 TTS 语音合成",
        "fields": [
            {"key": "models_dir", "label": "模型目录", "type": "text",
             "placeholder": "/path/to/Qwen3TTS/models", "required": True},
            {"key": "port", "label": "服务端口", "type": "number", "default": 17910},
            {"key": "gpu_min_memory_gb", "label": "GPU 最小显存 (GB)", "type": "number", "default": 3},
        ],
    },
    "rembg": {
        "display_name": "RemBg 背景移除",
        "fields": [
            {"key": "models_dir", "label": "ONNX 模型目录", "type": "text",
             "placeholder": "/path/to/rembg/models", "required": True},
            {"key": "port", "label": "服务端口", "type": "number", "default": 17920},
            {"key": "gpu_min_memory_gb", "label": "GPU 最小显存 (GB)", "type": "number", "default": 1},
        ],
    },
    "llm-translator": {
        "display_name": "LLM 翻译",
        "fields": [
            {"key": "port", "label": "服务端口", "type": "number", "default": 17930},
            {"key": "api_base_url", "label": "API Base URL", "type": "text",
             "placeholder": "https://api.siliconflow.cn/v1"},
            {"key": "api_key", "label": "API Key", "type": "password",
             "placeholder": "sk-xxx"},
            {"key": "model", "label": "模型名称", "type": "text",
             "placeholder": "Qwen/Qwen2.5-7B-Instruct"},
        ],
    },
    "qwen3-asr": {
        "display_name": "Qwen3 ASR 语音识别",
        "fields": [
            {"key": "checkpoint", "label": "模型路径", "type": "text",
             "placeholder": "/path/to/Qwen3ASR checkpoint", "required": True},
            {"key": "port", "label": "服务端口", "type": "number", "default": 8100},
            {"key": "gpu_min_memory_gb", "label": "GPU 最小显存 (GB)", "type": "number", "default": 3},
        ],
    },
    "whisperx": {
        "display_name": "WhisperX 语音识别",
        "fields": [
            {"key": "model_size", "label": "模型大小", "type": "dropdown",
             "choices": ["tiny", "base", "small", "medium", "large-v3"], "default": "large-v3"},
            {"key": "port", "label": "服务端口", "type": "number", "default": 8200},
            {"key": "hf_token", "label": "HuggingFace Token（说话人识别用）", "type": "password"},
            {"key": "gpu_min_memory_gb", "label": "GPU 最小显存 (GB)", "type": "number", "default": 3},
        ],
    },
    "fastwhisper": {
        "display_name": "FastWhisper 语音识别",
        "fields": [
            {"key": "model_size", "label": "模型大小", "type": "dropdown",
             "choices": ["tiny", "base", "small", "medium", "large-v3"], "default": "large-v3"},
            {"key": "port", "label": "服务端口", "type": "number", "default": 8300},
            {"key": "gpu_min_memory_gb", "label": "GPU 最小显存 (GB)", "type": "number", "default": 2},
        ],
    },
    "waifu2x": {
        "display_name": "Waifu2x 图片超分",
        "fields": [
            {"key": "port", "label": "服务端口", "type": "number", "default": 17900},
            {"key": "gpu_min_memory_gb", "label": "GPU 最小显存 (GB)", "type": "number", "default": 2},
        ],
    },
    "stable-diffusion": {
        "display_name": "Stable Diffusion",
        "fields": [
            {"key": "port", "label": "服务端口", "type": "number", "default": 17860},
            {"key": "gpu_min_memory_gb", "label": "GPU 最小显存 (GB)", "type": "number", "default": 4},
        ],
    },
}


def _build_service_command(model_type: str, values: dict) -> str:
    """根据模型类型和配置值生成启动命令。"""
    port = values.get("port", 17900)

    commands = {
        "qwen3-tts": f"python services/qwen3_tts_service.py --port {port} --models-dir {values.get('models_dir', './models')}",
        "rembg": f"python services/rembg_service.py --port {port} --models-dir {values.get('models_dir', './models')}",
        "llm-translator": f"python services/llm_translator_service.py --port {port}",
        "qwen3-asr": f"python services/qwen3_asr_service.py --port {port} --checkpoint {values.get('checkpoint', '')}",
        "whisperx": f"python services/whisperx_service.py --port {port} --model {values.get('model_size', 'large-v3')}",
        "fastwhisper": f"python services/fastwhisper_service.py --port {port} --model {values.get('model_size', 'large-v3')}",
        "waifu2x": f"python services/waifu2x_service.py --port {port}",
        "stable-diffusion": f"python services/stable_diffusion_service.py --port {port}",
    }
    return commands.get(model_type, "")


def _load_service_config(service_id: str) -> dict:
    """从 services.yaml 加载单个服务的配置值。"""
    services = cfg.get_services_list()
    for svc in services:
        if svc.get("id") == service_id:
            start_cmd = svc.get("start", {}).get("command", "")
            values = {
                "enabled": svc.get("enabled", False),
                "port": svc.get("service_url", "").split(":")[-1].split("/")[0] if ":" in svc.get("service_url", "") else 17900,
            }
            # 从命令中解析参数
            if "--models-dir" in start_cmd:
                parts = start_cmd.split("--models-dir")
                if len(parts) > 1:
                    values["models_dir"] = parts[1].strip().split()[0]
            if "--checkpoint" in start_cmd:
                parts = start_cmd.split("--checkpoint")
                if len(parts) > 1:
                    values["checkpoint"] = parts[1].strip().split()[0]
            if "--model" in start_cmd:
                parts = start_cmd.split("--model")
                if len(parts) > 1:
                    values["model_size"] = parts[1].strip().split()[0]
            gpu = svc.get("gpu", {})
            values["gpu_min_memory_gb"] = gpu.get("min_memory_gb", 0)
            return values
    return {}


def _save_service_config(service_id: str, values: dict):
    """保存单个服务的配置到 services.yaml。"""
    services = cfg.get_services_list()
    model_type = ""

    for svc in services:
        if svc.get("id") == service_id:
            model_type = svc.get("model_type", "")
            port = values.get("port", 17900)
            svc["enabled"] = values.get("enabled", False)
            svc["service_url"] = f"http://localhost:{port}"
            svc["start"]["command"] = _build_service_command(model_type, values)
            gpu = svc.setdefault("gpu", {})
            gpu["min_memory_gb"] = values.get("gpu_min_memory_gb", 0)
            break
    else:
        # 服务不存在，创建新的
        model_type = service_id
        port = values.get("port", 17900)
        new_svc = {
            "id": service_id,
            "display_name": MODEL_FIELDS.get(model_type, {}).get("display_name", service_id),
            "model_type": model_type,
            "enabled": values.get("enabled", False),
            "gpu": {"min_memory_gb": values.get("gpu_min_memory_gb", 0), "assignment": []},
            "service_url": f"http://localhost:{port}",
            "health_endpoint": "/health",
            "start": {
                "command": _build_service_command(model_type, values),
                "working_dir": ".",
                "env": {},
                "stop_timeout_seconds": 30,
            },
        }
        services.append(new_svc)

    cfg.save_services_config(services)
    registry.load_from_config(services)


def create_page(app_state: gr.State) -> gr.HTML:
    gr.Markdown("## 模型设置")

    gr.Markdown("""
    > 统一配置所有模型服务的参数。修改后点击保存，配置将自动写入 `services.yaml`。
    > 设置 `enabled` 为开启后，下次启动 WebUI 时服务将自动运行。
    """)

    # 服务选择
    service_choices = [(v["display_name"], k) for k, v in MODEL_FIELDS.items()]
    service_selector = gr.Dropdown(
        label="选择模型服务",
        choices=service_choices,
        interactive=True,
    )

    # 动态表单区域
    form_html = gr.HTML("")
    form_state = gr.State({})

    # 启用开关
    enabled_toggle = gr.Checkbox(label="启用此服务（启动 WebUI 时自动运行）", value=False)

    # 动态字段容器
    dynamic_fields = gr.Column()

    save_status = gr.Textbox(label="状态", interactive=False)

    def on_select_service(service_id):
        if not service_id:
            return gr.update(value=""), gr.update(visible=False), {}

        field_def = MODEL_FIELDS.get(service_id, {})
        values = _load_service_config(service_id)
        enabled = values.get("enabled", False)

        # 构建字段说明
        html_parts = [f"<h4>{field_def.get('display_name', service_id)}</h4>"]
        html_parts.append("<p style='color: #666; font-size: 0.9em;'>")
        html_parts.append(f"模型类型: <code>{service_id}</code>")
        html_parts.append("</p>")

        return (
            gr.update(value="".join(html_parts)),
            gr.update(value=enabled),
            {"service_id": service_id, "values": values, "fields": field_def.get("fields", [])},
        )

    service_selector.change(
        fn=on_select_service,
        inputs=service_selector,
        outputs=[form_html, enabled_toggle, form_state],
    )

    # 构建动态字段的容器
    with gr.Row(visible=False) as fields_row:
        pass

    # 使用 State 存储动态字段值
    field_values = gr.State({})

    def render_fields(state):
        """渲染动态字段。"""
        if not state or not state.get("fields"):
            return gr.update(visible=False), {}

        service_id = state["service_id"]
        fields = state["fields"]
        values = state.get("values", {})

        components = []
        field_map = {}

        for field in fields:
            key = field["key"]
            label = field["label"]
            ftype = field["type"]
            default = values.get(key, field.get("default", ""))

            if ftype == "text":
                comp = gr.Textbox(
                    label=label,
                    value=str(default) if default else "",
                    placeholder=field.get("placeholder", ""),
                )
            elif ftype == "password":
                comp = gr.Textbox(
                    label=label,
                    value=str(default) if default else "",
                    placeholder=field.get("placeholder", ""),
                    type="password",
                )
            elif ftype == "number":
                comp = gr.Number(
                    label=label,
                    value=default if default else field.get("default", 0),
                )
            elif ftype == "dropdown":
                comp = gr.Dropdown(
                    label=label,
                    choices=field.get("choices", []),
                    value=default or field.get("default"),
                    interactive=True,
                )
            else:
                comp = gr.Textbox(label=label, value=str(default))

            field_map[key] = comp
            components.append(comp)

        return gr.update(visible=True), field_map

    # 保存按钮
    btn_save = gr.Button("💾 保存配置", variant="primary")

    def on_save(service_id, enabled, form_state, *args):
        if not service_id:
            return "请先选择服务"

        fields = form_state.get("fields", [])
        values = {"enabled": enabled}

        for i, field in enumerate(fields):
            key = field["key"]
            val = args[i] if i < len(args) else field.get("default", "")
            if field["type"] == "number":
                val = int(val) if val else field.get("default", 0)
            values[key] = val

        try:
            _save_service_config(service_id, values)
            return f"✅ 配置已保存: {service_id}"
        except Exception as e:
            return f"❌ 保存失败: {e}"

    # 简化方案：使用固定字段布局
    gr.Markdown("---")
    gr.Markdown("### 快速配置")

    with gr.Row():
        with gr.Column():
            quick_model_dir = gr.Textbox(
                label="模型目录（TTS/ASR/RemBg 共用）",
                placeholder="/path/to/models",
            )
            quick_port = gr.Number(label="服务端口", value=17910)
        with gr.Column():
            quick_api_url = gr.Textbox(
                label="翻译 API Base URL",
                placeholder="https://api.siliconflow.cn/v1",
                value="https://api.siliconflow.cn/v1",
            )
            quick_api_key = gr.Textbox(
                label="翻译 API Key",
                type="password",
                placeholder="sk-xxx",
            )

    btn_quick_save = gr.Button("⚡ 一键保存所有配置", variant="primary")
    quick_status = gr.Textbox(label="状态", interactive=False)

    def on_quick_save(model_dir, port, api_url, api_key):
        services = cfg.get_services_list()
        updated = []

        for svc in services:
            mt = svc.get("model_type", "")
            cmd = svc.get("start", {}).get("command", "")

            if mt in ("qwen3-tts", "rembg", "qwen3-asr") and model_dir:
                if "--models-dir" in cmd:
                    parts = cmd.split("--models-dir")
                    cmd = parts[0] + f"--models-dir {model_dir}"
                elif "--checkpoint" in cmd:
                    parts = cmd.split("--checkpoint")
                    cmd = parts[0] + f"--checkpoint {model_dir}"
                svc["start"]["command"] = cmd
                updated.append(svc["display_name"])

            if mt == "llm-translator":
                if api_key:
                    svc["start"]["command"] = f"python services/llm_translator_service.py --port {int(port)}"
                updated.append(svc["display_name"])

        if updated:
            cfg.save_services_config(services)
            registry.load_from_config(services)
            return f"✅ 已更新: {', '.join(updated)}"
        return "未找到可更新的服务"

    btn_quick_save.click(
        fn=on_quick_save,
        inputs=[quick_model_dir, quick_port, quick_api_url, quick_api_key],
        outputs=quick_status,
    )

    return gr.HTML("")
