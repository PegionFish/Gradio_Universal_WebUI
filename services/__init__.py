# services/__init__.py — 模型服务 HTTP 包装器模块

# 此目录包含各模型服务的 HTTP API 包装脚本。
# 每个脚本将模型推理代码封装为标准的 REST API 端点，
# 供 WebUI 适配器通过 HTTP 调用。
#
# API 约定（所有服务统一）：
# - POST /v1/submit       提交任务 → 返回 {"task_id": "..."}
# - GET  /v1/status/<id>  查询状态 → 返回 {"status": "...", "result": {...}}
# - GET  /health          健康检查 → 返回 2xx
