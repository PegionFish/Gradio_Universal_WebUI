# webui/pages/tasks.py — 任务管理页面

import gradio as gr
from core import scheduler, result_mgr


def create_page(app_state: gr.State) -> gr.HTML:
    """创建任务管理标签页。"""
    gr.Markdown("## 任务管理")

    # 筛选区
    with gr.Row():
        filter_service = gr.Dropdown(
            label="筛选服务",
            choices=[],
            interactive=True,
            scale=1,
        )
        filter_status = gr.Dropdown(
            label="筛选状态",
            choices=["全部", "queued", "running", "completed", "failed", "cancelled"],
            value="全部",
            interactive=True,
            scale=1,
        )
        btn_refresh = gr.Button("刷新", variant="secondary", scale=0)

    task_list = gr.HTML("加载中...")

    gr.Markdown("---")
    gr.Markdown("### 任务详情")
    with gr.Row():
        task_id_input = gr.Textbox(
            label="任务 ID", placeholder="输入任务 ID 查看详情", scale=3,
        )
        btn_view = gr.Button("查看", variant="secondary", scale=1)

    with gr.Row():
        task_detail = gr.JSON(label="任务数据")
        result_files = gr.HTML(label="输出文件")

    # ── 从 app_state 刷新服务选择器 ──
    def refresh_from_state(state):
        svc_list = state.get("services", [])
        svc_choices = [("全部服务", "")] + [
            (s.get("display_name", s.get("id", "")), s.get("id", ""))
            for s in svc_list
        ]
        return gr.update(choices=svc_choices)

    task_list.select(
        refresh_from_state,
        inputs=app_state,
        outputs=filter_service,
    )

    # ── 加载任务列表 ──
    def load_tasks(svc_filter, status_filter):
        status = status_filter if status_filter != "全部" else None
        sid = svc_filter if svc_filter else None
        tasks = scheduler.list_tasks(service_id=sid, status=status)

        if not tasks:
            return gr.update(value="<p>暂无任务</p>")

        lines = [
            "<table border='1' cellpadding='4' "
            "style='border-collapse:collapse; width:100%'>",
            "<tr><th>ID</th><th>服务</th><th>模型</th>"
            "<th>状态</th><th>创建时间</th><th>错误</th></tr>",
        ]
        for t in tasks:
            error = t.get("error_summary", "") or ""
            lines.append(
                f"<tr><td>{t['id'][:8]}...</td>"
                f"<td>{t.get('service_id', '')}</td>"
                f"<td>{t.get('model_type', '')}</td>"
                f"<td>{t.get('status', '')}</td>"
                f"<td>{t.get('created_at', '')[:19]}</td>"
                f"<td style='color:red'>{error[:40]}</td></tr>"
            )
        lines.append("</table>")
        return gr.update(value="".join(lines))

    btn_refresh.click(
        load_tasks,
        inputs=[filter_service, filter_status],
        outputs=task_list,
    )

    filter_status.change(
        load_tasks, inputs=[filter_service, filter_status], outputs=task_list,
    )
    filter_service.change(
        load_tasks, inputs=[filter_service, filter_status], outputs=task_list,
    )

    # ── 查看任务详情 ──
    def view_task(task_id):
        if not task_id:
            return {}, ""
        task = scheduler.get_task(task_id)
        if not task:
            return {"error": "任务不存在"}, ""
        files = result_mgr.list_outputs(task_id)
        files_html = (
            "<ul>" + "".join(f"<li>{f}</li>" for f in files) + "</ul>"
            if files else "<p>(无输出文件)</p>"
        )
        return task, files_html

    btn_view.click(
        view_task, inputs=task_id_input, outputs=[task_detail, result_files],
    )

    return task_list
