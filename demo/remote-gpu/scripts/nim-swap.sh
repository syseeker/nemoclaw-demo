#!/usr/bin/env bash
# nim-swap.sh — NIM container lifecycle on the GPU instance.
# Manages start/stop of individual models on fixed host ports.
# No OpenShell, no gateway updates — those happen on the CPU side.
set -euo pipefail

HEALTH_TIMEOUT=900
NIM_CACHE="${LOCAL_NIM_CACHE:-$HOME/.cache/nim}"

declare -A NIM_IMAGES=(
  [qwen]="nvcr.io/nim/qwen/qwen3.5-397b-a17b:latest"
  [glm]="nvcr.io/nim/zai-org/glm-5:latest"
  [nemotron]="nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b:latest"
  [kimi]="nvcr.io/nim/moonshotai/kimi-k2.5:latest"
)

declare -A NIM_PORTS=(
  [qwen]=8000
  [glm]=8001
  [nemotron]=8002
  [kimi]=8003
)

# Per-model docker flags: --ipc and --shm-size differ
declare -A NIM_SHM=(
  [qwen]="32g"
  [glm]="16g"
  [nemotron]="16g"
  [kimi]="32g"
)

declare -A NIM_IPC=(
  [qwen]="host"
  [glm]=""
  [nemotron]=""
  [kimi]="host"
)

ALIASES=(qwen glm nemotron kimi)

preflight() {
  local errors=0

  # Driver version check — NIM containers require CUDA 13.0 → driver 580+
  if ! command -v nvidia-smi &>/dev/null; then
    echo "[preflight] FAIL: nvidia-smi not found. No NVIDIA driver installed."
    return 1
  fi

  local driver_ver major
  driver_ver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
  major=${driver_ver%%.*}
  if [[ "$major" -lt 580 ]]; then
    echo "[preflight] FAIL: Driver $driver_ver too old. Need 580+ for CUDA 13.0."
    echo "           Run: ./bootstrap-gpu.sh"
    errors=$((errors + 1))
  else
    echo "[preflight] OK: Driver $driver_ver"
  fi

  # Driver/library version mismatch (kernel module vs userspace)
  if nvidia-smi &>/dev/null; then
    echo "[preflight] OK: nvidia-smi responds"
  else
    echo "[preflight] FAIL: nvidia-smi not responding. Driver mismatch? Reboot needed."
    errors=$((errors + 1))
  fi

  # GPU persistence mode
  local pm
  pm=$(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader 2>/dev/null | head -1)
  if [[ "$pm" != "Enabled" ]]; then
    echo "[preflight] WARN: GPU persistence mode disabled. Enabling..."
    sudo nvidia-smi -pm 1 2>/dev/null || {
      echo "[preflight] FAIL: Could not enable persistence mode."
      errors=$((errors + 1))
    }
  else
    echo "[preflight] OK: Persistence mode enabled"
  fi

  # nvidia-persistenced daemon
  if systemctl is-active --quiet nvidia-persistenced 2>/dev/null; then
    echo "[preflight] OK: nvidia-persistenced running"
  else
    echo "[preflight] WARN: nvidia-persistenced not running. Starting..."
    sudo systemctl start nvidia-persistenced 2>/dev/null || {
      echo "[preflight] FAIL: Could not start nvidia-persistenced."
      errors=$((errors + 1))
    }
  fi

  # Fabric Manager (required for NVSwitch multi-GPU)
  if systemctl is-active --quiet nvidia-fabricmanager 2>/dev/null; then
    echo "[preflight] OK: nvidia-fabricmanager running"
  else
    echo "[preflight] WARN: nvidia-fabricmanager not running. Starting..."
    sudo systemctl start nvidia-fabricmanager 2>/dev/null || {
      echo "[preflight] FAIL: Could not start nvidia-fabricmanager."
      echo "           Install: sudo apt install nvidia-fabricmanager-580"
      errors=$((errors + 1))
    }
  fi

  # NGC_API_KEY
  if [[ -z "${NGC_API_KEY:-}" ]]; then
    echo "[preflight] FAIL: NGC_API_KEY not set."
    errors=$((errors + 1))
  else
    echo "[preflight] OK: NGC_API_KEY set"
  fi

  if [[ $errors -gt 0 ]]; then
    echo "[preflight] $errors issue(s) found. Fix before starting NIM."
    return 1
  fi
  echo "[preflight] All checks passed."
}

usage() {
  cat <<HELP
Usage: nim-swap.sh <command> [alias]

Models: qwen, glm, nemotron, kimi

Commands:
  start <alias>     Start a single model
  start-all         Start all models (warm standby)
  stop <alias>      Stop a single model
  stop-all          Stop all models
  stop-others <a>   Stop everything except <alias> (cold swap)
  status            Show running models and ports
  preflight         Check GPU driver, persistence, NGC key
HELP
  exit 1
}

wait_healthy() {
  local port="$1" alias="$2" elapsed=0
  echo "[$alias] Waiting for health check on port $port..."
  while [ $elapsed -lt $HEALTH_TIMEOUT ]; do
    if curl -sf "http://localhost:$port/v1/health/ready" >/dev/null 2>&1; then
      echo "[$alias] Ready (${elapsed}s)."
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    if (( elapsed % 30 == 0 )); then
      echo "[$alias]   ...still waiting (${elapsed}s)"
    fi
  done
  echo "[$alias] ERROR: not ready within ${HEALTH_TIMEOUT}s"
  return 1
}

start_model() {
  local alias="$1"
  local image="${NIM_IMAGES[$alias]}"
  local port="${NIM_PORTS[$alias]}"
  local shm="${NIM_SHM[$alias]}"
  local ipc="${NIM_IPC[$alias]}"
  local name="nim-${alias}"

  if docker ps -q --filter "name=^${name}$" | grep -q .; then
    echo "[$alias] Already running on port $port."
    return 0
  fi

  preflight || return 1

  docker rm "$name" 2>/dev/null || true
  mkdir -p "$NIM_CACHE"
  chmod -R a+w "$NIM_CACHE"

  local ipc_flag=()
  [[ -n "$ipc" ]] && ipc_flag=(--ipc "$ipc")

  echo "[$alias] Starting $image on port $port (shm=$shm ipc=${ipc:-none})"
  docker run -d \
    --name "$name" \
    --gpus all \
    "${ipc_flag[@]}" \
    --shm-size="$shm" \
    -e NGC_API_KEY \
    -e VLLM_WORKER_MULTIPROC_METHOD=spawn \
    -v "${NIM_CACHE}:/opt/nim/.cache" \
    -p "${port}:8000" \
    "$image"

  wait_healthy "$port" "$alias"
  echo "[$alias] SERVING on port $port"
}

stop_model() {
  local alias="$1"
  local name="nim-${alias}"
  if docker ps -q --filter "name=^${name}$" | grep -q .; then
    echo "[$alias] Stopping..."
    docker stop "$name" 2>/dev/null || true
    docker rm "$name" 2>/dev/null || true
    echo "[$alias] Stopped."
  else
    echo "[$alias] Not running."
  fi
}

status() {
  local found=0
  for alias in "${ALIASES[@]}"; do
    local name="nim-${alias}"
    local port="${NIM_PORTS[$alias]}"
    if docker ps -q --filter "name=^${name}$" | grep -q .; then
      echo "ACTIVE  $alias  port=$port  image=${NIM_IMAGES[$alias]}"
      found=1
    fi
  done
  [[ $found -eq 0 ]] && echo "NO_MODELS_RUNNING"
}

[[ $# -lt 1 ]] && usage

case "$1" in
  start)
    [[ $# -lt 2 ]] && usage
    start_model "$2"
    ;;
  start-all)
    for a in "${ALIASES[@]}"; do start_model "$a"; done
    ;;
  stop)
    [[ $# -lt 2 ]] && usage
    stop_model "$2"
    ;;
  stop-all)
    for a in "${ALIASES[@]}"; do stop_model "$a"; done
    ;;
  stop-others)
    [[ $# -lt 2 ]] && usage
    for a in "${ALIASES[@]}"; do
      [[ "$a" != "$2" ]] && stop_model "$a"
    done
    ;;
  status) status ;;
  preflight) preflight ;;
  *) usage ;;
esac
