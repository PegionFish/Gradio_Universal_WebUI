# webui/pages/login.py — 认证登录页面

import gradio as gr
from core.auth import get_auth


def create_login_page() -> tuple[gr.Blocks, gr.State]:
    """创建登录页面。

    Returns:
        (page, session_state) — session_state 存储当前会话 ID (str)
    """
    with gr.Blocks() as page:
        session_state = gr.State("")
        gr.Markdown("# 🔐 统一 AI WebUI")

        auth_manager = get_auth()

        if not auth_manager.enabled:
            gr.Markdown("### 认证未启用")
            gr.Markdown("*直接使用所有功能。如需启用认证，请设置 `WEBUI_AUTH_TOKEN` 环境变量。*")
            session_state.value = "_no_auth_session"
            return page, session_state

        gr.Markdown("### 请输入访问令牌")

        token_input = gr.Textbox(
            label="访问令牌",
            type="password",
            placeholder="输入管理员提供的访问令牌...",
        )
        login_btn = gr.Button("登录", variant="primary")
        status_msg = gr.Markdown("")

        def on_login(token: str, current_session: str):
            if not token:
                return current_session, "**⚠️ 请输入令牌**"

            session = auth_manager.login(token)
            if session:
                return session, "**✅ 登录成功**"
            else:
                return "", "**❌ 令牌错误，请重试**"

        login_btn.click(
            fn=on_login,
            inputs=[token_input, session_state],
            outputs=[session_state, status_msg],
        )

    return page, session_state
