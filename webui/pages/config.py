# webui/pages/config.py — 配置管理页面

import gradio as gr
import yaml
from core import config as cfg
from core import registry
from core.config_service import ConfigError


def create_page(app_state: gr.State) -> gr.HTML:
    """创建配置管理标签页。"""
    gr.Markdown("## 配置管理")

    gr.Markdown("""
    编辑 `config/services.yaml` 的完整内容。
    修改后点击保存，系统将校验并持久化。
    """)

    yaml_editor = gr.Textbox(
        label="services.yaml",
        lines=25,
        max_lines=40,
        value="",
        interactive=True,
    )

    with gr.Row():
        btn_load = gr.Button("重新加载", variant="secondary")
        btn_save = gr.Button("保存", variant="primary")

    save_status = gr.Textbox(label="状态", interactive=False)
    error_display = gr.Textbox(label="校验错误", lines=5, interactive=False)

    # 加载当前配置
    def load_yaml():
        try:
            services = cfg.get_services_list()
            payload = {"services": services}
            yaml_text = yaml.dump(
                payload, default_flow_style=False, allow_unicode=True,
            )
            return yaml_text, "", ""
        except Exception as e:
            return "", "", f"加载失败: {e}"

    btn_load.click(load_yaml, outputs=[yaml_editor, save_status, error_display])

    # 保存
    def save_yaml(yaml_text: str):
        try:
            parsed = yaml.safe_load(yaml_text)
            if not isinstance(parsed, dict):
                raise ConfigError("YAML 必须是一个字典")
            services_list = parsed.get("services", [])
            cfg.save_services_config(services_list)
            registry.load_from_config(services_list)
            return "保存成功", ""
        except yaml.YAMLError as e:
            return "", f"YAML 解析错误: {e}"
        except ConfigError as e:
            return "", f"配置校验错误: {e}"
        except Exception as e:
            return "", f"保存失败: {e}"

    btn_save.click(
        save_yaml, inputs=yaml_editor, outputs=[save_status, error_display],
    )

    return gr.HTML("")
