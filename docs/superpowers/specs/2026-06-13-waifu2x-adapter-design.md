# waifu2x 模型适配设计文档

**日期**：2026-06-13  
**状态**：待实现  
**版本**：1.0

---

## 1. 范围与约束

本次迭代仅新增 waifu2x 模型适配功能，**不触碰多计算后端架构**。短期运行环境限定为 **NVIDIA GPU + Linux**，因此复用现有 `GpuMonitor` / `GpuAllocator`，不引入 `core/compute/` 抽象层。

- 服务包装器先以 **mock 模式**实现：不依赖真实 waifu2x 引擎，上传的图片按指定倍数做简单 resize 后返回。
- `model_type` 标识符统一使用 `"waifu2x"`。
- 默认服务端口：**17900**。
- 不改动任何 Docker / docker-compose 相关文件。
- 部署方式：将项目文件夹复制到目标服务器硬盘后直接执行 `python main.py`。

---

## 2. HTTP API 契约

### 2.1 服务端点

`services/waifu2x_service.py` 暴露以下端点：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/upscale` | POST | 提交放大任务 |
| `/v1/status/<task_id>` | GET | 查询任务状态与结果 |
| `/health` | GET | 健康检查 |

### 2.2 POST /v1/upscale

请求体（JSON）：

```json
{
  "image": "base64 编码图片字符串 或 服务器本地文件路径",
  "scale": 2,
  "denoise_level": 0,
  "model_type": "cunet",
  "tile_size": 256
}
```

响应（JSON）：

```json
{
  "task_id": "uuid",
  "status": "queued"
}
```

### 2.3 GET /v1/status/<task_id>

响应示例（完成）：

```json
{
  "status": "completed",
  "result": {
    "image_base64": "...",
    "scale": 2,
    "model_type": "cunet"
  },
  "error": null
}
```

响应示例（失败）：

```json
{
  "status": "failed",
  "result": null,
  "error": "放大倍数不支持"
}
```

---

## 3. 文件清单

### 3.1 新增文件

| 文件 | 职责 |
|---|---|
| `adapters/waifu2x.py` | waifu2x 模型适配器，实现 `BaseModelAdapter` |
| `services/waifu2x_service.py` | HTTP 服务包装器（mock 模式） |
| `webui/pages/waifu2x.py` | WebUI 标签页 |
| `tests/test_waifu2x_adapter.py` | 适配器单元测试 |
| `tests/test_waifu2x_service.py` | 服务包装器单元测试 |
| `tests/test_waifu2x_page.py` | WebUI 页面结构测试 |

### 3.2 修改文件

| 文件 | 变更内容 |
|---|---|
| `adapters/__init__.py` | 注册 waifu2x 适配器 |
| `webui/app.py` | 导入并挂载 waifu2x 标签页 |
| `main.py` | 导入 `adapters.waifu2x` 触发自动注册 |
| `config/services.yaml` | 添加默认 waifu2x 服务条目（`enabled: false`） |
| `README.md` | 更新功能列表、端口说明、启动命令 |

---

## 4. 数据流

```
用户上传图片 → webui/pages/waifu2x.py
                   ↓
           Waifu2xAdapter.submit()
                   ↓
        POST /v1/upscale (aiohttp)
                   ↓
        services/waifu2x_service.py
                   ↓
        生成 task_id，mock 放大图片
                   ↓
        保存结果到 data/jobs/<task_id>/
                   ↓
        WebUI 轮询 /v1/status/<task_id>
                   ↓
        展示结果图片
```

---

## 5. 参数校验

适配器 `validate()` 方法负责校验：

| 参数 | 类型 | 约束 | 默认值 |
|---|---|---|---|
| `image` | `str` | base64 字符串或服务器本地文件路径，必填 | — |
| `scale` | `int` | 支持 `1/2/4` | `2` |
| `denoise_level` | `int` | `-1/0/1/2/3` | `0` |
| `model_type` | `str` | `cunet` / `upconv_7_anime_style_art_rgb` / `upconv_7_photo` | `cunet` |
| `tile_size` | `int` | `64-2048` 之间 | `256` |

---

## 6. mock 模式行为

- 服务启动时尝试导入真实 waifu2x 引擎；若未安装，则进入 mock 模式并打印 warning。
- mock 模式下使用 `Pillow` 将输入图片按 `scale` 做最近邻 / 双线性 resize，返回 base64 编码结果。
- 不执行真实降噪，仅记录 `denoise_level` 参数到结果元数据。
- 任务在后台线程池中异步执行，状态保存在内存 `dict` 中（与现有 SD / Qwen3ASR 服务一致）。

---

## 7. 测试策略

### 7.1 适配器测试

- mock aiohttp 服务端点，验证 `submit()` 返回 task_id。
- 验证 `poll_status()` 在 completed/failed 状态下返回正确结构。
- 验证 `validate()` 对非法 `scale`、`denoise_level`、`model_type` 的拒绝行为。

### 7.2 服务测试

- 使用 aiohttp 测试应用，启动内存中的服务实例。
- 验证 `/v1/upscale` 返回合法 task_id。
- 验证 `/v1/status/<task_id>` 随任务推进返回 `running` / `completed`。
- 验证 `/health` 返回 200。

### 7.3 页面与集成测试

- 验证 `webui/app.py` 的 `create_app()` 包含 waifu2x 标签页。
- 验证 `adapters/__init__.py` 能正确解析 `model_type="waifu2x"`。
- 验证默认 `config/services.yaml` 包含 waifu2x 条目且 `model_type` 合法。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| mock 模式与真实引擎接口不一致，后续替换需改服务包装器 | 服务 API 契约保持与真实 waifu2x-ncnn-vulkan / Real-ESRGAN 一致；mock 内部用独立函数封装，便于替换。 |
| 新增服务默认未启用，用户不知道如何启动 | README 和 `config/services.yaml` 注释中补充启动命令：`python services/waifu2x_service.py --port 17900`。 |
| WebUI 页面与现有 SD 页面风格不一致 | 复用 `webui/components/` 中的 `build_status_badge`、`format_error_message` 等组件。 |

---

## 9. 后续路线图

1. **本次**：mock 模式适配器 + 服务 + WebUI 页面 + 测试。
2. **未来**：接入真实 waifu2x-ncnn-vulkan 或 Real-ESRGAN 引擎，实现真实超分与降噪。
3. **未来**：在多计算后端架构落地后，将 waifu2x 的 GPU 分配迁移到 `ComputeAllocator`。
