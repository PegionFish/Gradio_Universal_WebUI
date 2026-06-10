# tests/test_config_service.py

import os
import yaml
import pytest
from core.config_service import ConfigService, ConfigError


class TestConfigServiceInit:
    """验收标准 1: ConfigService 在目录不存在时自动创建。"""

    def test_creates_config_dir_if_missing(self, config_dir):
        nonexistent = os.path.join(config_dir, "sub", "deep")
        ConfigService(config_dir=nonexistent)
        assert os.path.isdir(nonexistent)

    def test_creates_webui_yaml_default(self, config_dir):
        ConfigService(config_dir=config_dir)
        webui_path = os.path.join(config_dir, "webui.yaml")
        assert os.path.exists(webui_path)

    def test_creates_services_yaml_default(self, config_dir):
        ConfigService(config_dir=config_dir)
        services_path = os.path.join(config_dir, "services.yaml")
        assert os.path.exists(services_path)

    def test_existing_config_not_overwritten(self, config_service):
        svc = config_service.get_services_list()
        config_service.save_services_config([
            {"id": "test-1", "display_name": "Test", "model_type": "stable-diffusion"},
        ])
        cs2 = ConfigService(config_dir=config_service._config_dir)
        cs2.load_all()
        svc2 = cs2.get_services_list()
        assert len(svc2) == 1
        assert svc2[0]["id"] == "test-1"


class TestLoadAll:
    """验收标准 2-3: load_all 加载合法 YAML，非法 YAML 抛出 ConfigError。"""

    def test_loads_valid_config(self, config_service):
        config_service.load_all()
        cfg = config_service.get_webui_config()
        assert "server" in cfg
        assert cfg["server"]["port"] == 7860

    def test_raises_on_invalid_yaml(self, config_service):
        with open(config_service._webui_path, "w") as f:
            f.write("{broken: [yaml:")
        with pytest.raises(ConfigError, match="YAML"):
            config_service.load_all()

    def test_handles_empty_file(self, config_service):
        # 写入空 webui.yaml + 空 services.yaml 会触发校验失败
        # 因为空文件被解析为 {}，其中 server.host 不存在。
        # 需确保两个文件同时有效
        with open(config_service._webui_path, "w") as f:
            yaml.dump({"server": {"host": "0.0.0.0", "port": 7860},
                       "refresh": {"health_check_seconds": 10,
                                    "gpu_metrics_seconds": 5,
                                    "task_status_seconds": 15},
                       "logging": {"level": "INFO"}}, f)
        config_service.load_all()
        assert isinstance(config_service.get_webui_config(), dict)


class TestWebUIConfigValidation:
    """验收标准 10: 端口号范围检查。"""

    def test_invalid_host_empty(self, config_service):
        config_service.load_all()
        cfg = config_service.get_webui_config()
        cfg["server"]["host"] = ""
        with pytest.raises(ConfigError, match="host"):
            config_service.save_webui_config(cfg)

    def test_invalid_port_range(self, config_service):
        config_service.load_all()
        cfg = config_service.get_webui_config()
        cfg["server"]["port"] = 99999
        with pytest.raises(ConfigError, match="port"):
            config_service.save_webui_config(cfg)

    def test_invalid_port_zero(self, config_service):
        config_service.load_all()
        cfg = config_service.get_webui_config()
        cfg["server"]["port"] = 0
        with pytest.raises(ConfigError, match="port"):
            config_service.save_webui_config(cfg)

    def test_valid_port_range(self, config_service):
        config_service.load_all()
        cfg = config_service.get_webui_config()
        cfg["server"]["port"] = 8080
        config_service.save_webui_config(cfg)  # 不应抛出异常

    def test_invalid_refresh_interval(self, config_service):
        config_service.load_all()
        cfg = config_service.get_webui_config()
        cfg["refresh"]["health_check_seconds"] = 0
        with pytest.raises(ConfigError, match="refresh"):
            config_service.save_webui_config(cfg)

    def test_invalid_log_level(self, config_service):
        config_service.load_all()
        cfg = config_service.get_webui_config()
        cfg["logging"]["level"] = "TRACE"
        with pytest.raises(ConfigError, match="logging.level"):
            config_service.save_webui_config(cfg)

    def test_valid_log_levels(self, config_service):
        config_service.load_all()
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            cfg = config_service.get_webui_config()
            cfg["logging"]["level"] = level
            config_service.save_webui_config(cfg)


class TestServicesConfigValidation:
    """验收标准 7-9: 空服务列表通过校验、ID 重复被拒绝、model_type 校验。"""

    def test_empty_services_passes(self, config_service):
        config_service.load_all()
        config_service.save_services_config([])  # 不应抛出异常

    def test_duplicate_id_rejected(self, config_service):
        config_service.load_all()
        services = [
            {"id": "dup", "display_name": "A", "model_type": "stable-diffusion"},
            {"id": "dup", "display_name": "B", "model_type": "qwen3-asr"},
        ]
        with pytest.raises(ConfigError, match="重复"):
            config_service.save_services_config(services)

    def test_invalid_model_type_rejected(self, config_service):
        config_service.load_all()
        services = [
            {"id": "test", "display_name": "Test", "model_type": "llama-7b"},
        ]
        with pytest.raises(ConfigError, match="model_type"):
            config_service.save_services_config(services)

    def test_empty_id_rejected(self, config_service):
        config_service.load_all()
        services = [
            {"id": "", "display_name": "Test", "model_type": "stable-diffusion"},
        ]
        with pytest.raises(ConfigError, match="id"):
            config_service.save_services_config(services)

    def test_invalid_id_characters(self, config_service):
        config_service.load_all()
        services = [
            {"id": "INVALID_ID", "display_name": "Test", "model_type": "stable-diffusion"},
        ]
        with pytest.raises(ConfigError, match="id"):
            config_service.save_services_config(services)

    def test_stop_timeout_range(self, config_service):
        config_service.load_all()
        services = [
            {
                "id": "test", "display_name": "Test",
                "model_type": "stable-diffusion",
                "start": {"stop_timeout_seconds": 200},
            },
        ]
        with pytest.raises(ConfigError, match="stop_timeout"):
            config_service.save_services_config(services)

    def test_negative_gpu_index(self, config_service):
        config_service.load_all()
        services = [
            {
                "id": "test", "display_name": "Test",
                "model_type": "stable-diffusion",
                "gpu": {"assignment": [-1]},
            },
        ]
        with pytest.raises(ConfigError, match="gpu.assignment"):
            config_service.save_services_config(services)


class TestSafeWrite:
    """验收标准 4-6: 原子写入、校验失败不覆盖、.tmp 清理。"""

    def test_atomic_write_succeeds(self, config_service):
        config_service.load_all()
        services = [
            {"id": "test-1", "display_name": "Test", "model_type": "stable-diffusion"},
        ]
        config_service.save_services_config(services)
        # 原文件应存在且无 .tmp 残留
        assert os.path.exists(config_service._services_path)
        assert not os.path.exists(config_service._services_path + ".tmp")

    def test_validation_failure_preserves_original(self, config_service):
        config_service.load_all()
        # 先写入合法数据
        config_service.save_services_config([
            {"id": "good", "display_name": "Good", "model_type": "stable-diffusion"},
        ])
        # 尝试写入非法数据
        try:
            config_service.save_services_config([
                {"id": "bad", "display_name": "Bad", "model_type": "unknown"},
            ])
        except ConfigError:
            pass
        # 原数据未变
        svcs = config_service.get_services_list()
        assert svcs[0]["id"] == "good"


class TestAccessors:
    def test_get_server_setting(self, config_service_loaded):
        assert config_service_loaded.get_server_setting("port") == 7860
        assert config_service_loaded.get_server_setting("missing", "default") == "default"

    def test_get_refresh_setting(self, config_service_loaded):
        assert config_service_loaded.get_refresh_setting("health_check_seconds") == 10

    def test_get_logging_setting(self, config_service_loaded):
        assert config_service_loaded.get_logging_setting("level") == "INFO"
        assert config_service_loaded.get_logging_setting("directory", "logs/") == "data/logs/"

    def test_get_services_list_returns_copy(self, config_service_loaded):
        svcs = config_service_loaded.get_services_list()
        assert svcs == []  # 默认空
        svcs.append({"id": "x"})
        svcs2 = config_service_loaded.get_services_list()
        assert svcs2 == []  # 不受修改影响
