---
name: unified-ai-webui-first-phase-design
description: First-phase design for a Gradio-based unified AI frontend suite managing local AI workloads.
metadata:
  type: project
---

# Unified AI WebUI First-Phase Design

Date: 2026-06-08

## 1. Goal

Build the first phase of a Gradio-based unified AI frontend suite for a Linux local server serving LAN users. The suite provides one public WebUI port for navigation, control, configuration, task management, service management, and GPU monitoring, while each AI model service remains an independent HTTP service with its own port.

The first phase implements the framework and management layer. Model-specific inference for Qwen3ASR, WhisperX, and FastWhisper is intentionally deferred to later sessions. Stable Diffusion, Qwen3ASR, WhisperX, and FastWhisper are represented as pluggable model entries and adapter placeholders in phase one.

## 2. User Requirements Confirmed

- One Gradio WebUI exposes all management features through a single external port.
- Each model service keeps its own HTTP port for direct use by other applications or workflow automation.
- LAN users can access the full feature set without authentication in phase one.
- NVIDIA GPU acceleration is required.
- Users can select target GPU with high granularity.
- The system shows GPU memory, utilization, temperature, and workload status.
- The system recommends suitable GPUs based on current load, but the user keeps final control.
- Model services can run on different GPUs, or different models can share one GPU depending on configuration and workload.
- Configuration is managed through the WebUI and saved to local YAML.
- Task queue and task history are persisted with SQLite.
- Task result files are stored under a fixed project directory, `data/jobs/`.
- The WebUI can start, stop, restart, and monitor model services.
- Phase-one target deployment is a Linux local server for LAN users.
- Python environment management is not locked in phase one; the design keeps an extension point for venv, conda, or containerized services.

## 3. Scope

### In Scope for Phase One

- Gradio unified WebUI with a single public port.
- Navigation and model entry pages for:
  - Stable Diffusion
  - Qwen3ASR
  - WhisperX
  - FastWhisper
- Service registry and service configuration stored in YAML.
- WebUI configuration editor with YAML persistence.
- Service manager for start, stop, restart, and status display.
- Health checking for HTTP model services.
- SQLite-backed task queue and task history.
- Result file management under `data/jobs/`.
- NVIDIA GPU monitoring and recommendation logic.
- Adapter interface definitions for model services.
- Placeholder adapters for first-batch model entries.
- Basic error handling, logs, and user-facing status messages.
- Tests for core framework behavior where model inference is not required.

### Out of Scope for Phase One

- Authentication, authorization, and multi-user permissions.
- Full Qwen3ASR inference integration.
- Full WhisperX inference integration.
- Full FastWhisper inference integration.
- Binding Stable Diffusion to a specific backend such as A1111, ComfyUI, or Diffusers.
- Automatic GPU protection that blocks user-submitted jobs.
- Docker Compose-first deployment.
- Multi-user role separation.
- Long-running workflow orchestration across multiple model services.
- Production-grade remote deployment hardening.

## 4. Architecture

```text
LAN Browser
   |
   v
[ Unified Gradio WebUI : one public port ]
   |
   |-- Navigation and model pages
   |-- Control Panel
   |-- Configuration Editor
   |-- Task Queue UI
   |-- GPU Monitor
   |-- Service Manager
   |
   v
[ Core Services inside WebUI process ]
   |-- ConfigService
   |-- ServiceRegistry
   |-- ProcessManager
   |-- HealthChecker
   |-- TaskScheduler
   |-- GpuMonitor
   |-- ResultManager
   |
   v
[ Adapter Layer ]
   |-- BaseModelAdapter
   |-- StableDiffusionAdapter placeholder
   |-- Qwen3ASRAdapter placeholder
   |-- WhisperXAdapter placeholder
   |-- FastWhisperAdapter placeholder
   |
   v
[ Independent Model HTTP Services ]
   |-- stable-diffusion-service : own HTTP port
   |-- qwen3-asr-service : future
   |-- whisperx-service : future
   |-- fastwhisper-service : future
```

## 5. Component Design

### 5.1 Gradio WebUI

The WebUI is the only externally exposed user interface. It provides:

- Model navigation.
- Control panel.
- Configuration editor.
- Service status table.
- Service start/stop/restart controls.
- Task submission and task history views.
- GPU monitoring dashboard.
- Result file links.

The WebUI does not directly implement model inference. It delegates model work to adapters and HTTP model services.

### 5.2 ConfigService

`ConfigService` reads and writes YAML configuration. The WebUI edits configuration through forms and tables, then persists changes to disk.

Recommended initial file:

```text
config/services.yaml
```

Configuration includes:

- Service name.
- Display name.
- Model type.
- Enabled flag.
- HTTP URL or host/port.
- Local working directory.
- Command to start the service.
- GPU assignment or allowed GPU list.
- Environment variables.
- Health check path.
- Result directory override, if needed.

The WebUI must validate configuration before saving. Invalid configuration should be rejected with a clear message and must not overwrite a previously valid file.

### 5.3 ServiceRegistry

`ServiceRegistry` stores the known set of model services. It is populated from YAML and exposes service metadata to the WebUI, scheduler, health checker, and adapters.

Each service record contains:

- Stable service ID.
- Human-readable name.
- Model family.
- Service URL.
- Start command.
- Working directory.
- GPU policy.
- Health endpoint.
- Enabled state.
- Current runtime state.

### 5.4 ProcessManager

`ProcessManager` starts, stops, and restarts model service processes.

Phase-one requirements:

- Start a configured service command.
- Stop a running service gracefully.
- Force stop if graceful shutdown times out.
- Restart by stop then start.
- Capture stdout/stderr logs.
- Store process PID and start time.
- Mark process as exited if it terminates unexpectedly.

Phase-one implementation should target Linux process management. Windows support can be added later through an abstraction layer.

### 5.5 HealthChecker

`HealthChecker` periodically probes each enabled service HTTP endpoint.

Minimum health response contract:

```json
{
  "status": "ok",
  "service": "stable-diffusion",
  "model": "default",
  "gpu": [0],
  "message": "ready"
}
```

If a service does not implement this contract yet, the service can expose a minimal phase-one health endpoint that returns service identity and readiness.

### 5.6 TaskScheduler

`TaskScheduler` persists task state and queue metadata in SQLite.

Recommended database file:

```text
data/tasks.sqlite3
```

Task states:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`

Task records include:

- Task ID.
- Service ID.
- Model type.
- Adapter name.
- Request payload.
- Target GPU.
- Status.
- Created time.
- Started time.
- Finished time.
- Result file paths.
- Error summary.
- Log reference.

The scheduler should be able to enqueue tasks even when a target service is offline, but the WebUI should warn the user before submitting to an offline service.

### 5.7 GpuMonitor

`GpuMonitor` collects NVIDIA GPU metrics and provides recommendations.

Minimum metrics:

- GPU index.
- GPU name.
- Memory total.
- Memory used.
- Memory free.
- Utilization percentage.
- Temperature.
- Running CUDA processes, where available.

Recommendation logic should rank GPUs by available memory first, then utilization, then temperature. The recommendation is advisory only. The user can manually override the recommended GPU.

The system must not automatically block jobs in phase one.

### 5.8 ResultManager

`ResultManager` writes and tracks outputs under:

```text
data/jobs/
```

Recommended structure:

```text
data/jobs/
  tasks/
    <task_id>/
      request.json
      response.json
      logs/
      outputs/
```

Result files may include text, images, audio, subtitles, or service-specific artifacts. The WebUI stores paths in SQLite and provides download or preview links where applicable.

### 5.9 Adapter Layer

The adapter layer isolates WebUI logic from model-specific APIs.

Base adapter responsibilities:

- Validate request payload.
- Select target service URL.
- Attach target GPU preference if the service supports it.
- Submit task to service.
- Poll or receive task status.
- Normalize response metadata.
- Store result paths through `ResultManager`.
- Translate service errors into user-facing messages.

Phase-one adapters are placeholders. They must implement the interface and return clear `not implemented` or `service not configured` messages rather than pretending to support inference.

## 6. Data Flow

### 6.1 Service Start Flow

1. User opens Service Manager.
2. WebUI loads service records from `config/services.yaml`.
3. User clicks Start for a service.
4. `ProcessManager` resolves command, working directory, environment, and GPU assignment.
5. Service process starts.
6. `HealthChecker` probes the configured health endpoint.
7. Service status changes to `running` or `unhealthy`.
8. WebUI displays status and recent logs.

### 6.2 Configuration Save Flow

1. User edits service configuration in the WebUI.
2. `ConfigService` validates the configuration.
3. If invalid, WebUI shows validation errors and does not save.
4. If valid, WebUI writes a temporary YAML file.
5. Temporary file is validated by loading it back.
6. Temporary file replaces the original YAML file.
7. `ServiceRegistry` reloads the service definitions.
8. WebUI displays saved state.

### 6.3 Task Submission Flow

1. User opens a model page or task submission panel.
2. User selects model/service and optional target GPU.
3. WebUI shows current GPU recommendations and warnings.
4. User submits task.
5. `TaskScheduler` writes a queued task to SQLite.
6. Adapter validates payload and service availability.
7. If service is online, adapter submits the request to the service HTTP API.
8. Task status updates to `running`.
9. Result paths and final status are persisted.
10. WebUI displays task result or failure message.

### 6.4 GPU Recommendation Flow

1. `GpuMonitor` refreshes GPU metrics.
2. Scheduler receives task requirements such as model type and optional memory estimate.
3. Recommendation engine ranks GPUs.
4. WebUI displays recommended GPU and alternatives.
5. User may accept recommendation or manually select another GPU.
6. Selected GPU is stored with the task and passed to the service adapter.

## 7. Error Handling

### Configuration Errors

- Invalid YAML: show parse error and do not save.
- Missing required service fields: show field-level validation errors.
- Duplicate service ID: reject save.
- Invalid port or URL: reject save.
- Invalid command path: reject save or show service start failure.

### Service Errors

- Service fails to start: show command, working directory, and recent log excerpt.
- Service exits unexpectedly: mark service as stopped/unhealthy and keep logs.
- Health check fails: mark service unhealthy but keep last known status.
- Service endpoint returns non-2xx: store response body summary in task error.

### Task Errors

- Offline service: warn before submission; if user proceeds, task remains queued or fails with clear message.
- Invalid payload: fail fast with field-level validation.
- Adapter not implemented: return a clear message that the model adapter is reserved for a later phase.
- Result write failure: mark task failed and include storage path error.
- GPU unavailable: warn user and allow manual override unless the service rejects the request.

### User-Facing Error Format

Errors shown in the WebUI should include:

- Short summary.
- Affected service or task ID.
- Action taken by the system.
- Suggested next step.
- Link or button to view logs when available.

## 8. Testing Strategy

Phase-one tests should avoid requiring real AI model inference.

### Unit Tests

- YAML validation and safe save.
- Service registry loading.
- Service ID uniqueness validation.
- GPU recommendation ranking.
- Task state transitions.
- Result path generation.
- Adapter request validation.
- Error message normalization.

### Integration Tests

- Start a mock HTTP service from configuration.
- Health check mock service.
- Stop and restart mock service.
- Submit a task to a mock service.
- Persist task history in SQLite.
- Verify result files are written under `data/jobs/`.

### Manual Test Checklist

- Open WebUI from a LAN browser.
- View service list and GPU dashboard.
- Add or edit a service configuration.
- Save invalid configuration and confirm it is rejected.
- Start a mock service.
- Confirm health status updates.
- Stop and restart the service.
- Submit a task to a placeholder adapter and confirm clear not-implemented behavior.
- Confirm logs and task history are visible.
- Confirm result directory structure is created.

## 9. First-Phase Milestones

### Milestone 1: Project Skeleton

- Create project structure.
- Add configuration directory.
- Add data directories.
- Add core package layout.
- Add dependency files.
- Add basic README usage notes.

### Milestone 2: Configuration and Service Registry

- Define `config/services.yaml`.
- Implement `ConfigService`.
- Implement `ServiceRegistry`.
- Add validation for service definitions.
- Add WebUI configuration editor.

### Milestone 3: Service Management

- Implement `ProcessManager`.
- Implement start, stop, restart.
- Capture logs.
- Add service status table in WebUI.
- Add health checking.

### Milestone 4: Task Queue and Result Storage

- Initialize SQLite schema.
- Implement task creation and status updates.
- Add task history UI.
- Implement `ResultManager`.
- Store request/response metadata under `data/jobs/`.

### Milestone 5: GPU Monitor and Recommendation

- Collect NVIDIA GPU metrics.
- Display GPU dashboard.
- Rank GPUs by available memory, utilization, and temperature.
- Let user manually override recommended GPU.

### Milestone 6: Adapter Placeholders

- Define base adapter interface.
- Add placeholder adapters for Stable Diffusion, Qwen3ASR, WhisperX, and FastWhisper.
- Return clear not-implemented messages for unsupported model logic.
- Preserve service URL and task metadata for future implementation.

### Milestone 7: First-Phase Verification

- Run automated tests.
- Run mock service integration tests.
- Verify LAN access to WebUI.
- Verify service start/stop/restart.
- Verify configuration persistence.
- Verify task persistence.
- Verify GPU dashboard.

## 10. Future Evolution Toward Phase Two

Phase two should move from placeholder adapters to real HTTP model services.

Recommended phase-two work:

- Define a stable model service HTTP API.
- Implement Stable Diffusion adapter for a selected backend.
- Research and implement Qwen3ASR HTTP service.
- Research and implement WhisperX HTTP service.
- Research and implement FastWhisper HTTP service.
- Add service logs streaming.
- Add task cancellation.
- Add per-model configuration forms.
- Add optional Docker Compose deployment.
- Add authentication if LAN exposure requires it.

## 11. Open Decisions

- Python environment strategy: venv, conda, or containerized services.
- Stable Diffusion backend selection.
- Qwen3ASR service extraction strategy.
- WhisperX and FastWhisper implementation sources.
- Whether future workflow orchestration should be internal to the WebUI or external to it.

These open decisions are intentionally outside phase one. The phase-one architecture keeps them isolated behind service configuration, process management, and adapter interfaces.
