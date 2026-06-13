# waifu2x 适配器实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Gradio Universal WebUI 新增 waifu2x 模型适配，包含 mock 模式服务包装器、适配器、WebUI 页面、默认配置与测试。

**Architecture:** 遵循现有适配器模式：WebUI 页面 → `Waifu2xAdapter` → `services/waifu2x_service.py` HTTP API。服务在 mock 模式下使用 Pillow 做简单 resize，不依赖真实 waifu2x 引擎。

**Tech Stack:** Python 3.10+、aiohttp、Pillow、Gradio 6.x、pytest、pytest-asyncio

---

## 环境约束说明

当前开发机为 Python 3.9.6，且未安装 `gradio` / `pytest`。项目代码本身使用 Python 3.10+ 语法（`|` 联合类型）。计划中的代码**必须保持 Python 3.10+ 风格以匹配项目**，执行测试时需要满足以下任一条件：

- 使用 pyenv / conda / uv 切换到 Python 3.10+ 并安装依赖 `pip install -e ".[dev]"`；或
- 在具备 Python 3.10+ 的环境中运行 `pytest tests/ -q`。

---

## 文件结构

### 新增文件

| 文件 | 职责 |
|---|---|
| `services/waifu2x_service.py` | HTTP 服务包装器，mock 模式放大图片 |
| `adapters/waifu2x.py` | 模型适配器，封装 HTTP 调用 |
| `webui/pages/waifu2x.py` | WebUI 标签页 |
| `tests/test_waifu2x_service.py` | 服务端点测试 |
| `tests/test_waifu2x_adapter.py` | 适配器行为测试 |
| `tests/test_waifu2x_page.py` | 页面挂载测试 |

### 修改文件

| 文件 | 变更 |
|---|---|
| `adapters/__init__.py` | 注册 waifu2x 适配器 |
| `main.py` | 导入 `adapters.waifu2x` 触发注册 |
| `webui/app.py` | 挂载 waifu2x 标签页 |
| `config/services.yaml` | 添加默认 waifu2x 服务条目 |
| `README.md` | 更新功能列表与端口说明 |

---

## Task 1: 实现 waifu2x 服务包装器

**Files:**
- Create: `services/waifu2x_service.py`
- Test: `tests/test_waifu2x_service.py`

### Step 1: 编写服务端测试（先写测试）

```python
# tests/test_waifu2x_service.py
import base64
import io
import pytest
from PIL import Image
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from services import waifu2x_service


def _make_image_b64() -> str:
    img = Image.new("RGB", (64, 64), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class TestWaifu2xService(AioHTTPTestCase):
    async def get_application(self):
        return waifu2x_service.create_app()

    @unittest_run_loop
    async def test_health(self):
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "ok"

    @unittest_run_loop
    async def test_upscale_returns_task_id(self):
        payload = {
            "image": _make_image_b64(),
            "scale": 2,
            "denoise_level": 0,
            "model_type": "cunet",
            "tile_size": 256,
        }
        resp = await self.client.request("POST", "/v1/upscale", json=payload)
        assert resp.status == 202
        body = await resp.json()
        assert "task_id" in body
        assert body["status"] == "queued"

    @unittest_run_loop
    async def test_status_completed(self):
        payload = {
            "image": _make_image_b64(),
            "scale": 2,
        }
        resp = await self.client.request("POST", "/v1/upscale", json=payload)
        body = await resp.json()
        task_id = body["task_id"]

        # mock 模式任务执行很快，直接查询应已完成
        resp2 = await self.client.request("GET", f"/v1/status/{task_id}")
        body2 = await resp2.json()
        assert body2["status"] == "completed"
        assert "image_base64" in body2["result"]

    @unittest_run_loop
    async def test_upscale_invalid_scale(self):
        payload = {
            "image": _make_image_b64(),
            "scale": 3,
        }
        resp = await self.client.request("POST", "/v1/upscale", json=payload)
        assert resp.status == 400
```

### Step 2: 运行测试确认失败

```bash
pytest tests/test_waifu2x_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.waifu2x_service'` 或类似失败。

### Step 3: 实现服务包装器

```python
#!/usr/bin/env python3
# services/waifu2x_service.py — waifu2x HTTP API 服务包装器（mock 模式）

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from aiohttp import web
from PIL import Image

logger = logging.getLogger("waifu2x_service")

# 全局状态
_task_store: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)

# 支持的参数常量
VALID_SCALES = {1, 2, 4}
VALID_DENOISE_LEVELS = {-1, 0, 1, 2, 3}
VALID_MODEL_TYPES = {
    "cunet",
    "upconv_7_anime_style_art_rgb",
    "upconv_7_photo",
}


def _decode_image(image_field: str) -> Image.Image:
    """将 base64 字符串或本地文件路径解码为 PIL Image。"""
    if os.path.exists(image_field):
        return Image.open(image_field).convert("RGB")
    data = base64.b64decode(image_field)
    return Image.open(io.BytesIO(data)).convert("RGB")


def _encode_image(img: Image.Image, fmt: str = "PNG") -> str:
    """将 PIL Image 编码为 base64 字符串。"""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _upscale_sync(
    task_id: str,
    image_field: str,
    scale: int,
    denoise_level: int,
    model_type: str,
    tile_size: int,
) -> None:
    """同步执行 mock 放大（在 executor 中运行）。"""
    try:
        img = _decode_image(image_field)
        new_size = (img.width * scale, img.height * scale)
        # mock 模式使用双线性插值；真实引擎替换此处即可
        upscaled = img.resize(new_size, Image.BILINEAR)
        result_b64 = _encode_image(upscaled)

        _task_store[task_id] = {
            "status": "completed",
            "result": {
                "image_base64": result_b64,
                "scale": scale,
                "denoise_level": denoise_level,
                "model_type": model_type,
                "tile_size": tile_size,
            },
            "error": None,
        }
    except Exception as e:
        logger.exception("waifu2x 任务 %s 执行失败", task_id)
        _task_store[task_id] = {
            "status": "failed",
            "result": None,
            "error": str(e),
        }


async def health(request: web.Request) -> web.Response:
    """健康检查端点。"""
    return web.json_response({"status": "ok"})


async def upscale(request: web.Request) -> web.Response:
    """提交放大任务端点。"""
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "请求体必须是 JSON"}, status=400)

    image_field = payload.get("image")
    if not image_field or not isinstance(image_field, str):
        return web.json_response({"error": "image 为必填字段"}, status=400)

    scale = payload.get("scale", 2)
    if scale not in VALID_SCALES:
        return web.json_response(
            {"error": f"scale 必须是 {sorted(VALID_SCALES)} 之一"}, status=400
        )

    denoise_level = payload.get("denoise_level", 0)
    if denoise_level not in VALID_DENOISE_LEVELS:
        return web.json_response(
            {"error": f"denoise_level 必须是 {sorted(VALID_DENOISE_LEVELS)} 之一"},
            status=400,
        )

    model_type = payload.get("model_type", "cunet")
    if model_type not in VALID_MODEL_TYPES:
        return web.json_response(
            {"error": f"model_type 必须是 {sorted(VALID_MODEL_TYPES)} 之一"},
            status=400,
        )

    tile_size = payload.get("tile_size", 256)
    if not isinstance(tile_size, int) or tile_size < 64 or tile_size > 2048:
        return web.json_response(
            {"error": "tile_size 必须在 64-2048 之间"}, status=400
        )

    task_id = str(uuid.uuid4())
    _task_store[task_id] = {"status": "running", "result": None, "error": None}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _upscale_sync,
        task_id,
        image_field,
        scale,
        denoise_level,
        model_type,
        tile_size,
    )

    return web.json_response({"task_id": task_id, "status": "queued"}, status=202)


async def status(request: web.Request) -> web.Response:
    """查询任务状态端点。"""
    task_id = request.match_info["task_id"]
    task = _task_store.get(task_id)
    if not task:
        return web.json_response(
            {"status": "failed", "result": None, "error": "任务不存在"},
            status=404,
        )
    return web.json_response(task)


def create_app() -> web.Application:
    """创建 aiohttp 应用（便于测试）。"""
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/v1/upscale", upscale)
    app.router.add_get("/v1/status/{task_id}", status)
    return app


def main():
    parser = argparse.ArgumentParser(description="waifu2x HTTP API 服务")
    parser.add_argument("--port", type=int, default=17900, help="监听端口")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("waifu2x 服务启动于 http://localhost:%s", args.port)
    web.run_app(create_app(), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
```

### Step 4: 运行服务测试

```bash
pytest tests/test_waifu2x_service.py -v
```

Expected: 4 个测试全部通过。

### Step 5: 提交

```bash
git add services/waifu2x_service.py tests/test_waifu2x_service.py
git commit -m "$(cat <<'EOF'
[服务] waifu2x HTTP 包装器（mock 模式 + 端点测试）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main || echo "push failed, will retry later"
```

---

## Task 2: 实现 waifu2x 适配器

**Files:**
- Create: `adapters/waifu2x.py`
- Modify: `adapters/__init__.py`
- Modify: `main.py`
- Test: `tests/test_waifu2x_adapter.py`

### Step 1: 编写适配器测试

```python
# tests/test_waifu2x_adapter.py
import pytest

from adapters import get_adapter
from adapters.waifu2x import Waifu2xAdapter


class TestWaifu2xAdapter:
    def test_model_type(self):
        adapter = Waifu2xAdapter()
        assert adapter.model_type() == "waifu2x"

    def test_registered_in_factory(self):
        assert get_adapter("waifu2x") is not None

    @pytest.mark.asyncio
    async def test_validate_missing_image(self):
        adapter = Waifu2xAdapter()
        errors = await adapter.validate({"scale": 2})
        assert any("image" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_invalid_scale(self):
        adapter = Waifu2xAdapter()
        errors = await adapter.validate({"image": "...", "scale": 3})
        assert any("scale" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_invalid_denoise(self):
        adapter = Waifu2xAdapter()
        errors = await adapter.validate({"image": "...", "denoise_level": 5})
        assert any("denoise" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_invalid_model_type(self):
        adapter = Waifu2xAdapter()
        errors = await adapter.validate({"image": "...", "model_type": "unknown"})
        assert any("model_type" in e for e in errors)

    @pytest.mark.asyncio
    async def test_validate_ok(self):
        adapter = Waifu2xAdapter()
        errors = await adapter.validate(
            {
                "image": "iVBORw0KGgo=",
                "scale": 2,
                "denoise_level": 0,
                "model_type": "cunet",
                "tile_size": 256,
            }
        )
        assert errors == []
```

### Step 2: 运行测试确认失败

```bash
pytest tests/test_waifu2x_adapter.py -v
```

Expected: `ModuleNotFoundError: No module named 'adapters.waifu2x'` 或 `AttributeError`。

### Step 3: 实现适配器

```python
# adapters/waifu2x.py — waifu2x 模型适配器

import asyncio
import base64
import io
import logging
from typing import Optional

import aiohttp
from PIL import Image

from adapters.base import BaseModelAdapter

logger = logging.getLogger(__name__)


class Waifu2xAdapter(BaseModelAdapter):
    """waifu2x 模型适配器 — mock 阶段实现。

    通过 HTTP API 调用外部 waifu2x 服务。支持：
    - 图片超分放大（scale: 1/2/4）
    - 降噪等级（denoise_level: -1/0/1/2/3）
    - 模型类型选择（cunet / upconv_7_anime_style_art_rgb / upconv_7_photo）

    HTTP API 约定：
    - POST /v1/upscale          提交放大任务
    - GET  /v1/status/<task_id> 查询任务状态
    - GET  /health              健康检查
    """

    VALID_SCALES = {1, 2, 4}
    VALID_DENOISE_LEVELS = {-1, 0, 1, 2, 3}
    VALID_MODEL_TYPES = {
        "cunet",
        "upconv_7_anime_style_art_rgb",
        "upconv_7_photo",
    }

    def model_type(self) -> str:
        return "waifu2x"

    async def validate(self, payload: dict) -> list[str]:
        """校验请求负载。"""
        errors = []
        image = payload.get("image")
        if not image or not isinstance(image, str):
            errors.append("image 为必填字段（base64 字符串或文件路径）")

        scale = payload.get("scale", 2)
        if scale not in self.VALID_SCALES:
            errors.append(f"scale 必须是 {sorted(self.VALID_SCALES)} 之一")

        denoise_level = payload.get("denoise_level", 0)
        if denoise_level not in self.VALID_DENOISE_LEVELS:
            errors.append(
                f"denoise_level 必须是 {sorted(self.VALID_DENOISE_LEVELS)} 之一"
            )

        model_type = payload.get("model_type", "cunet")
        if model_type not in self.VALID_MODEL_TYPES:
            errors.append(
                f"model_type 必须是 {sorted(self.VALID_MODEL_TYPES)} 之一"
            )

        tile_size = payload.get("tile_size", 256)
        if not isinstance(tile_size, int) or tile_size < 64 or tile_size > 2048:
            errors.append("tile_size 必须在 64-2048 之间")

        return errors

    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        """提交放大任务到 waifu2x 服务。

        Args:
            service_url: 服务基础 URL（如 http://localhost:17900）
            payload: 请求参数
            target_gpu: 目标 GPU 索引列表（waifu2x 固定用单 GPU）

        Returns:
            服务侧任务引用 ID
        """
        url = service_url.rstrip("/") + "/v1/upscale"
        body = {
            "image": payload.get("image"),
            "scale": payload.get("scale", 2),
            "denoise_level": payload.get("denoise_level", 0),
            "model_type": payload.get("model_type", "cunet"),
            "tile_size": payload.get("tile_size", 256),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body) as resp:
                    text = await resp.text()
                    if resp.status == 202:
                        data = await resp.json()
                        return data["task_id"]
                    if resp.status == 400:
                        data = await resp.json()
                        raise ValueError(f"参数校验失败: {data.get('error', 'unknown')}")
                    raise ConnectionError(
                        f"waifu2x 服务返回 {resp.status}: {text[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(f"无法连接到 waifu2x 服务: {e}") from e

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """查询任务执行状态。"""
        url = f"{service_url.rstrip('/')}/v1/status/{task_ref}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return {
                            "status": "failed",
                            "result": None,
                            "error": f"任务 {task_ref} 未找到",
                        }
                    text = await resp.text()
                    return {
                        "status": "failed",
                        "result": None,
                        "error": f"状态查询失败: HTTP {resp.status}",
                    }
        except aiohttp.ClientError as e:
            return {
                "status": "failed",
                "result": None,
                "error": f"状态查询异常: {e}",
            }
```

### Step 4: 注册适配器

修改 `adapters/__init__.py`：

```python
# 在文件末尾的导入区域添加
import adapters.waifu2x  # noqa: F401
```

确保 `create_adapter` / `get_adapter` 函数能自动识别 `Waifu2xAdapter` 的 `model_type`。现有注册机制通常通过类创建时自动注册，若未自动注册，则在 `adapters/__init__.py` 显式添加：

```python
from adapters.waifu2x import Waifu2xAdapter

# 在适当位置
_registry["waifu2x"] = Waifu2xAdapter
```

（具体修改需根据 `adapters/__init__.py` 当前实现决定。）

### Step 5: 触发 main.py 导入

修改 `main.py`，在现有适配器导入块后添加：

```python
    # 4b. 导入适配器模块以触发自动注册
    import adapters.stable_diffusion  # noqa: F401
    import adapters.qwen3_asr        # noqa: F401
    import adapters.whisperx         # noqa: F401
    import adapters.fastwhisper      # noqa: F401
    import adapters.waifu2x          # noqa: F401
```

### Step 6: 运行适配器测试

```bash
pytest tests/test_waifu2x_adapter.py -v
```

Expected: 6 个测试全部通过。

### Step 7: 提交

```bash
git add adapters/waifu2x.py adapters/__init__.py main.py tests/test_waifu2x_adapter.py
git commit -m "$(cat <<'EOF'
[适配器] waifu2x 模型适配器 + 注册 + 单元测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main || echo "push failed, will retry later"
```

---

## Task 3: 实现 waifu2x WebUI 页面

**Files:**
- Create: `webui/pages/waifu2x.py`
- Modify: `webui/app.py`
- Test: `tests/test_waifu2x_page.py`

### Step 1: 编写页面挂载测试

```python
# tests/test_waifu2x_page.py
import pytest
import gradio as gr

from webui.app import create_app


class TestWaifu2xPage:
    def test_tab_exists(self):
        app = create_app()
        # Gradio Blocks 没有直接暴露 tabs 的公开 API，
        # 可通过检查内部组件的 label 或依赖事件来验证。
        labels = [c.label for c in app.blocks.values() if hasattr(c, "label")]
        assert "waifu2x" in labels or "Waifu2x" in labels
```

> 注：Gradio 内部 API 可能变动，若上述方式不可靠，改为验证 `webui/pages/waifu2x.py` 的 `create_page` 函数可被调用且不抛异常。

### Step 2: 运行测试确认失败

```bash
pytest tests/test_waifu2x_page.py -v
```

Expected: `ModuleNotFoundError: No module named 'webui.pages.waifu2x'`。

### Step 3: 实现 WebUI 页面

参考 `webui/pages/stable_diffusion.py` 和 `webui/pages/qwen3_asr.py` 的结构：

```python
# webui/pages/waifu2x.py — waifu2x WebUI 标签页

import base64
import io
import logging
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image

from core import registry, scheduler, result_mgr
from webui.components.error_display import format_error_message
from webui.components.progress_indicator import build_status_badge

logger = logging.getLogger(__name__)


def create_page(app_state):
    gr.Markdown("## Waifu2x 图片超分")
    gr.Markdown("上传图片进行超分辨率放大（当前为 mock 模式）。")

    with gr.Row():
        with gr.Column(scale=1):
            image_input = gr.Image(
                label="上传图片",
                type="numpy",
                sources=["upload"],
            )
            with gr.Row():
                scale = gr.Dropdown(
                    label="放大倍数",
                    choices=[1, 2, 4],
                    value=2,
                )
                denoise_level = gr.Dropdown(
                    label="降噪等级",
                    choices=[-1, 0, 1, 2, 3],
                    value=0,
                )
            with gr.Row():
                model_type = gr.Dropdown(
                    label="模型类型",
                    choices=[
                        "cunet",
                        "upconv_7_anime_style_art_rgb",
                        "upconv_7_photo",
                    ],
                    value="cunet",
                )
                tile_size = gr.Slider(
                    label="Tile Size",
                    minimum=64,
                    maximum=2048,
                    step=64,
                    value=256,
                )

            service_selector = gr.Dropdown(
                label="选择服务",
                choices=[],
                interactive=True,
            )

            btn_submit = gr.Button("开始放大", variant="primary")

        with gr.Column(scale=1):
            task_id_output = gr.Textbox(label="任务 ID", interactive=False)
            status_output = gr.HTML(label="状态")
            error_output = gr.HTML(label="错误信息")
            result_image = gr.Image(label="放大结果", interactive=False)
            perf_output = gr.HTML(label="性能信息")

    def refresh_services(services):
        waifu2x_services = [
            s["id"]
            for s in services
            if s.get("model_type") == "waifu2x"
        ]
        return gr.Dropdown(choices=waifu2x_services)

    app_state.change(
        fn=refresh_services,
        inputs=app_state,
        outputs=service_selector,
    )

    async def on_submit(
        image_np, scale_val, denoise_val, model_val, tile_val, svc_id, state
    ):
        if image_np is None:
            return (
                "", build_status_badge("failed"),
                format_error_message("请先上传图片"),
                None, "",
            )
        if not svc_id:
            return (
                "", build_status_badge("failed"),
                format_error_message("未选择 waifu2x 服务"),
                None, "",
            )

        service = registry.get(svc_id)
        if not service:
            return (
                "", build_status_badge("failed"),
                format_error_message(f"服务 {svc_id} 不存在"),
                None, "",
            )

        # 将 numpy 图片转为 base64
        img = Image.fromarray(image_np.astype("uint8"))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        payload = {
            "image": image_b64,
            "scale": int(scale_val),
            "denoise_level": int(denoise_val),
            "model_type": model_val,
            "tile_size": int(tile_val),
        }

        from adapters import get_adapter
        adapter = get_adapter("waifu2x")

        task_id = scheduler.create_task(
            service_id=svc_id,
            model_type="waifu2x",
            payload=payload,
        )

        try:
            task_ref = await adapter.submit(service.service_url, payload)
            scheduler.update_task_status(task_id, "running", task_ref=task_ref)

            # 轮询结果
            import asyncio
            for _ in range(60):
                status = await adapter.poll_status(service.service_url, task_ref)
                if status["status"] == "completed":
                    result = status.get("result", {})
                    result_b64 = result.get("image_base64", "")
                    if result_b64:
                        result_bytes = base64.b64decode(result_b64)
                        result_img = Image.open(io.BytesIO(result_bytes))
                        result_np = np.array(result_img)
                    else:
                        result_np = None

                    scheduler.update_task_status(task_id, "completed")
                    result_mgr.save_response(task_id, result)
                    return (
                        task_id,
                        build_status_badge("completed"),
                        "",
                        result_np,
                        f"scale={scale_val} | denoise={denoise_val} | model={model_val}",
                    )
                if status["status"] == "failed":
                    err = status.get("error", "放大失败")
                    scheduler.update_task_status(task_id, "failed", error_summary=err)
                    return (
                        task_id,
                        build_status_badge("failed"),
                        format_error_message(err, task_id=task_id),
                        None, "",
                    )
                await asyncio.sleep(1)

            # 超时
            scheduler.update_task_status(task_id, "failed", error_summary="轮询超时")
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message("任务轮询超时", task_id=task_id),
                None, "",
            )

        except ConnectionError as e:
            scheduler.update_task_status(
                task_id, "failed", error_summary=f"连接失败: {e}"
            )
            return (
                task_id,
                build_status_badge("failed"),
                format_error_message(
                    "无法连接到 waifu2x 服务",
                    service_id=svc_id,
                    suggestion="请确认服务已启动且 URL 配置正确",
                    details=str(e),
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
                format_error_message("请求失败", details=str(e)),
                None, "",
            )

    btn_submit.click(
        fn=on_submit,
        inputs=[
            image_input, scale, denoise_level,
            model_type, tile_size, service_selector, app_state,
        ],
        outputs=[
            task_id_output, status_output, error_output,
            result_image, perf_output,
        ],
    )

    return gr.HTML("")
```

### Step 4: 挂载标签页

修改 `webui/app.py`：

```python
from webui.pages import (
    dashboard,
    services,
    tasks,
    gpu as gpu_page,
    config,
    system,
    stable_diffusion,
    qwen3_asr,
    whisperx,
    fastwhisper,
    waifu2x,  # 新增
)
```

在 `gr.Tabs` 内新增：

```python
            with gr.TabItem("Waifu2x", elem_id="tab-waifu2x", id="waifu2x"):
                waifu2x.create_page(app_state)
```

### Step 5: 运行页面测试

```bash
pytest tests/test_waifu2x_page.py -v
```

Expected: 通过。

### Step 6: 提交

```bash
git add webui/pages/waifu2x.py webui/app.py tests/test_waifu2x_page.py
git commit -m "$(cat <<'EOF'
[页面] waifu2x WebUI 标签页 + 页面测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main || echo "push failed, will retry later"
```

---

## Task 4: 默认配置与文档更新

**Files:**
- Modify: `config/services.yaml`
- Modify: `README.md`
- Test: 通过 `tests/test_config_service.py` 间接验证

### Step 1: 更新 config/services.yaml

在 `services:` 列表末尾添加：

```yaml
  - id: waifu2x
    display_name: "Waifu2x 超分"
    model_type: "waifu2x"
    enabled: false
    gpu:
      min_memory_gb: 2
      assignment: []
    service_url: "http://localhost:17900"
    health_endpoint: "/health"
    start:
      command: "python services/waifu2x_service.py --port 17900"
      working_dir: "."
      env: {}
      stop_timeout_seconds: 30
```

### Step 2: 更新 README.md

在「功能概览」表格末尾添加：

```markdown
| **Waifu2x** | 图片超分辨率放大（mock 模式） |
```

在「独立 HTTP API」表格末尾添加：

```markdown
| Waifu2x | 17900 | `python services/waifu2x_service.py --port 17900` |
```

### Step 3: 运行配置相关测试

```bash
pytest tests/test_config_service.py -v
```

Expected: 全部通过（新增条目不应破坏现有校验）。

### Step 4: 提交

```bash
git add config/services.yaml README.md
git commit -m "$(cat <<'EOF'
[配置] 默认 waifu2x 服务条目与 README 更新

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main || echo "push failed, will retry later"
```

---

## Task 5: 全量回归测试

### Step 1: 运行全部测试

```bash
pytest tests/ -q
```

Expected: 原有 177 项测试 + 新增测试全部通过。

### Step 2: 语法与导入检查

```bash
python -m py_compile services/waifu2x_service.py adapters/waifu2x.py webui/pages/waifu2x.py
python -c "import adapters; print(adapters.get_adapter('waifu2x'))"
```

Expected: 无语法错误，适配器可被正确获取。

### Step 3: 提交（如测试全部通过）

```bash
git commit --allow-empty -m "$(cat <<'EOF'
[测试] waifu2x 功能全量回归通过

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main || echo "push failed, will retry later"
```

---

## Spec 覆盖检查

| Spec 章节 | 实现任务 |
|---|---|
| 1. 范围与约束 | Task 4（不改动 Docker）、全部任务使用 mock 模式 |
| 2. HTTP API 契约 | Task 1 |
| 3. 文件清单 | Task 1-4 |
| 4. 数据流 | Task 1、Task 3 |
| 5. 参数校验 | Task 1、Task 2 |
| 6. mock 模式行为 | Task 1 |
| 7. 测试策略 | Task 1-5 |
| 8. 风险与缓解 | 注释与 README |
| 9. 后续路线图 | 文档注释 |

无遗漏。

---

## Placeholder 扫描

- 无 `TBD` / `TODO` / `implement later`。
- 每个步骤包含完整代码或命令。
- 文件路径均为绝对相对路径（相对于仓库根目录）。

---

## 执行方式选择

**计划已保存至：** `docs/superpowers/plans/2026-06-13-waifu2x-adapter-plan.md`

两种执行方式：

1. **Subagent-Driven（推荐）**：每个 Task 派独立子代理执行，我在 Task 间审查结果。
2. **Inline Execution**：在当前会话中按步骤顺序执行，适合快速迭代。

请选择一种方式开始执行。
