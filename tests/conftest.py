# tests/conftest.py — 共享 fixtures

import pytest
import tempfile
import os
import shutil

# pytest-asyncio: all async tests automatically detected
pytest_plugins = ("pytest_asyncio",)


@pytest.fixture
def tmp_workspace():
    """创建临时工作目录，测试结束后自动清理。"""
    d = tempfile.mkdtemp()
    yield d
    try:
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def config_dir(tmp_workspace):
    """创建临时的 config/ 目录（含默认 webui.yaml）。"""
    d = os.path.join(tmp_workspace, "config")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def data_dir(tmp_workspace):
    """创建临时的 data/ 根目录。"""
    d = os.path.join(tmp_workspace, "data")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def config_service(config_dir):
    """返回已初始化的 ConfigService（未 load_all）。"""
    from core.config_service import ConfigService
    return ConfigService(config_dir=config_dir)


@pytest.fixture
def config_service_loaded(config_service):
    """返回已 load_all 的 ConfigService。"""
    config_service.load_all()
    return config_service


@pytest.fixture
def sample_services_list():
    """返回合法的示例服务列表，用于测试。"""
    return [
        {
            "id": "sd-1",
            "display_name": "Stable Diffusion v1",
            "model_type": "stable-diffusion",
            "enabled": True,
            "service_url": "http://localhost:7861",
            "start": {
                "command": "python app.py",
                "working_dir": "/tmp/sd",
                "stop_timeout_seconds": 15,
            },
            "gpu": {
                "assignment": [0],
                "min_memory_gb": 8,
            },
        },
        {
            "id": "asr-1",
            "display_name": "Qwen3 ASR",
            "model_type": "qwen3-asr",
            "enabled": False,
            "service_url": "http://localhost:8000",
            "health_endpoint": "/healthz",
        },
        {
            "id": "whisper-1",
            "display_name": "WhisperX Instance",
            "model_type": "whisperx",
            "enabled": True,
            "service_url": "",
        },
    ]


@pytest.fixture
def registry():
    """返回干净的 ServiceRegistry 实例。"""
    from core.service_registry import ServiceRegistry
    return ServiceRegistry()


@pytest.fixture
def registry_loaded(registry, sample_services_list):
    """返回已加载示例服务的 ServiceRegistry。"""
    registry.load_from_config(sample_services_list)
    return registry


@pytest.fixture
def event_bus():
    """返回干净的 EventBus 实例（非全局单例）。"""
    from core.event_bus import EventBus
    return EventBus()


@pytest.fixture
def scheduler(tmp_workspace):
    """返回使用临时数据库的 TaskScheduler。"""
    from core.task_scheduler import TaskScheduler
    db_path = os.path.join(tmp_workspace, "test_tasks.sqlite3")
    return TaskScheduler(db_path=db_path)


@pytest.fixture
def result_mgr(tmp_workspace):
    """返回使用临时目录的 ResultManager。"""
    from core.result_manager import ResultManager
    base = os.path.join(tmp_workspace, "jobs")
    return ResultManager(base_dir=base)
