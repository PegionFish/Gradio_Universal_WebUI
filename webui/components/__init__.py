# webui/components/__init__.py — 可复用 Gradio 组件模块

from webui.components.service_table import build_service_table_html, render_service_controls
from webui.components.task_list import build_task_list_html, render_task_filters
from webui.components.gpu_dashboard import build_gpu_cards_html, render_gpu_recommendation, build_recommendation_html
from webui.components.config_editor import create_yaml_editor
from webui.components.error_display import format_error_message, render_error_card
from webui.components.progress_indicator import (
    build_progress_bar, build_status_badge, build_task_timeline,
)

__all__ = [
    "build_service_table_html",
    "render_service_controls",
    "build_task_list_html",
    "render_task_filters",
    "build_gpu_cards_html",
    "render_gpu_recommendation",
    "build_recommendation_html",
    "create_yaml_editor",
    "format_error_message",
    "render_error_card",
    "build_progress_bar",
    "build_status_badge",
    "build_task_timeline",
]
