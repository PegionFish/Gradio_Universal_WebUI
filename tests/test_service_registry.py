# tests/test_service_registry.py

import pytest
from core.service_record import ServiceRecord
from core.service_registry import ServiceRegistry
from core.event_bus import bus, Event


class TestServiceRecord:
    """ServiceRecord 数据类测试。"""

    def test_from_dict_basic(self):
        d = {
            "id": "sd-1",
            "display_name": "SD",
            "model_type": "stable-diffusion",
        }
        record = ServiceRecord.from_dict(d)
        assert record.id == "sd-1"
        assert record.display_name == "SD"
        assert record.model_type == "stable-diffusion"
        assert record.runtime_state == "stopped"

    def test_from_dict_with_start(self):
        d = {
            "id": "svc", "display_name": "Svc", "model_type": "qwen3-asr",
            "start": {"command": "python app.py", "working_dir": "/tmp"},
        }
        record = ServiceRecord.from_dict(d)
        assert record.start_command == "python app.py"
        assert record.working_dir == "/tmp"

    def test_from_dict_with_gpu(self):
        d = {
            "id": "svc", "display_name": "Svc", "model_type": "whisperx",
            "gpu": {"assignment": [0, 1], "min_memory_gb": 8},
        }
        record = ServiceRecord.from_dict(d)
        assert record.gpu_assignment == [0, 1]
        assert record.gpu_min_memory_gb == 8

    def test_from_dict_defaults(self):
        d = {"id": "x", "display_name": "X", "model_type": "fastwhisper"}
        record = ServiceRecord.from_dict(d)
        assert record.enabled is False
        assert record.service_url == ""
        assert record.health_endpoint == "/health"
        assert record.stop_timeout_seconds == 30

    def test_to_dict_roundtrip(self):
        d = {
            "id": "test", "display_name": "Test",
            "model_type": "stable-diffusion",
            "enabled": True,
            "service_url": "http://localhost:7861",
            "start": {"command": "python app.py", "working_dir": "/tmp",
                      "stop_timeout_seconds": 15},
            "gpu": {"assignment": [0], "min_memory_gb": 6},
        }
        record = ServiceRecord.from_dict(d)
        out = record.to_dict()
        assert out["id"] == "test"
        assert out["start"]["command"] == "python app.py"
        assert out["gpu"]["assignment"] == [0]

    def test_clone_creates_independent_copy(self):
        record = ServiceRecord.from_dict({
            "id": "x", "display_name": "X", "model_type": "stable-diffusion",
        })
        clone = record.clone()
        assert clone.id == record.id
        clone.runtime_state = "running"
        assert record.runtime_state == "stopped"
        clone.env["NEW_KEY"] = "val"
        assert record.env == {}

    def test_is_managed(self):
        managed = ServiceRecord.from_dict({
            "id": "x", "display_name": "X", "model_type": "stable-diffusion",
            "start": {"command": "python app.py", "working_dir": "/tmp"},
        })
        unmanaged = ServiceRecord.from_dict({
            "id": "y", "display_name": "Y", "model_type": "stable-diffusion",
        })
        assert managed.is_managed is True
        assert unmanaged.is_managed is False


class TestServiceRegistryLoad:
    """验收标准 1, 2, 3, 4, 9, 10。"""

    def test_load_from_config_creates_services(self, registry, sample_services_list):
        registry.load_from_config(sample_services_list)
        assert len(registry.list_services()) == 3

    def test_get_returns_correct_record(self, registry_loaded):
        record = registry_loaded.get("sd-1")
        assert record is not None
        assert record.display_name == "Stable Diffusion v1"

    def test_get_nonexistent(self, registry_loaded):
        assert registry_loaded.get("nonexistent") is None

    def test_list_services(self, registry_loaded):
        svcs = registry_loaded.list_services()
        assert len(svcs) == 3
        ids = {s.id for s in svcs}
        assert ids == {"sd-1", "asr-1", "whisper-1"}

    def test_get_by_model_type(self, registry_loaded):
        sd = registry_loaded.get_by_model_type("stable-diffusion")
        assert len(sd) == 1
        assert sd[0].id == "sd-1"
        asr = registry_loaded.get_by_model_type("qwen3-asr")
        assert len(asr) == 1
        none = registry_loaded.get_by_model_type("fastwhisper")
        assert len(none) == 0

    def test_load_preserves_runtime_state(self, registry, sample_services_list):
        registry.load_from_config(sample_services_list)
        registry.set_runtime_state("sd-1", "running")
        modified = [
            {**sample_services_list[0], "display_name": "SD Updated"},
            sample_services_list[1],
        ]
        registry.load_from_config(modified)
        sd = registry.get("sd-1")
        assert sd.runtime_state == "running"
        assert sd.display_name == "SD Updated"

    def test_load_removes_vanished_services(self, registry_loaded):
        registry_loaded.load_from_config([
            {"id": "sd-1", "display_name": "SD", "model_type": "stable-diffusion"},
        ])
        assert registry_loaded.get("sd-1") is not None
        assert registry_loaded.get("asr-1") is None
        assert registry_loaded.get("whisper-1") is None

    def test_load_publishes_config_reloaded_event(self, registry, sample_services_list):
        events = []
        bus.on("config_reloaded", lambda e: events.append(e))
        registry.load_from_config([sample_services_list[0]])
        assert len(events) == 1
        assert "sd-1" in events[0].data["service_ids"]
        bus.clear()


class TestServiceRegistryState:
    """验收标准 5。"""

    def test_set_runtime_state_updates_and_publishes(self, registry_loaded):
        events = []
        bus.on("service_state_changed", lambda e: events.append(e))
        registry_loaded.set_runtime_state("sd-1", "running")
        assert registry_loaded.get("sd-1").runtime_state == "running"
        assert len(events) == 1
        assert events[0].data["old_state"] == "stopped"
        assert events[0].data["new_state"] == "running"
        assert events[0].source == "ServiceRegistry"
        bus.clear()

    def test_set_runtime_state_nonexistent_silent(self, registry_loaded):
        registry_loaded.set_runtime_state("ghost", "running")

    def test_set_pid(self, registry_loaded):
        registry_loaded.set_pid("sd-1", 12345)
        assert registry_loaded.get("sd-1").pid == 12345

    def test_set_pid_none(self, registry_loaded):
        registry_loaded.set_pid("sd-1", 12345)
        registry_loaded.set_pid("sd-1", None)
        assert registry_loaded.get("sd-1").pid is None
