# ============================================================
# Gradio Universal AI WebUI — Docker 镜像
# ============================================================
# 构建: docker build -t gradio-webui:latest .
# 运行: docker compose up -d

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="Gradio Universal AI WebUI"
LABEL org.opencontainers.image.description="一站式管理本地 AI 负载的 WebUI 前端套件"

# ── 系统依赖 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── 应用目录 ──
WORKDIR /app

# ── Python 依赖（分层缓存）──
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || \
    pip install --no-cache-dir gradio pyyaml aiohttp

# ── 源码 ──
COPY . .

# ── 数据目录 ──
RUN mkdir -p /app/data/logs /app/data/jobs /app/data/tasks /app/config

# ── 健康检查 ──
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:7860/ || exit 1

# ── 端口 ──
EXPOSE 7860

# ── 入口 ──
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "7860", "--config", "config/"]
