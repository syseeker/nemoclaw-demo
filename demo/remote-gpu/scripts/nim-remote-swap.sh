#!/usr/bin/env bash
# nim-remote-swap.sh — Switch between cloud inference and self-hosted NIMs.
#
# Uses openshell provider + inference set for hot-swapping. Each remote
# model has a pre-registered provider (nim-qwen, nim-glm, etc.) with
# OPENAI_BASE_URL pointing to the GPU box.
#
# Providers must be created first (one-time setup):
#   openshell provider create --name nim-qwen --type openai \
#     --credential OPENAI_API_KEY=not-required \
#     --config OPENAI_BASE_URL=http://<gpu-ip>:8000/v1
set -euo pipefail

CONFIG="${NIM_REMOTE_SWAP_ENV:-$HOME/.config/nim-remote-swap.env}"
[[ -f "$CONFIG" ]] && set -a && . "$CONFIG" && set +a

GPU_HOST="${NIM_GPU_HOST:-nim-gpu}"

DEFAULT_PROVIDER="${NIM_DEFAULT_PROVIDER:-nvidia-prod}"

declare -A NIM_PROVIDERS=(
  [qwen]="nim-qwen"
  [glm]="nim-glm"
  [nemotron]="nim-nemotron"
  [kimi]="nim-kimi"
)

declare -A NIM_MODELS=(
  [qwen]="qwen/qwen3.5-397b-a17b"
  [glm]="zai-org/glm-5"
  [nemotron]="nvidia/nemotron-3-super-120b-a12b"
  [kimi]="moonshotai/kimi-k2.5"
)

usage() {
  cat <<HELP
Usage: nim-remote-swap.sh <command> [alias]

Switch between cloud inference and self-hosted NIMs on the GPU box.
Uses openshell inference set for hot-swapping.

Commands:
  switch <alias>    Route inference to a remote NIM (qwen|glm|nemotron|kimi).
                    Starts the model on the GPU box if needed, then
                    runs: openshell inference set --provider nim-<alias>
  reset             Restore default cloud provider ($DEFAULT_PROVIDER).
                    Runs: openshell inference update --provider $DEFAULT_PROVIDER
  start <alias>     Start a model on the GPU box (without switching to it)
  stop <alias>      Stop a model on the GPU box
  stop-all          Stop all models on the GPU box
  status            Show current inference route + running models on GPU box
HELP
  exit 1
}

remote_ssh() {
  ssh "$GPU_HOST" "NGC_API_KEY='${NGC_API_KEY}' $*"
}

switch_to() {
  local alias="$1"
  local provider="${NIM_PROVIDERS[$alias]}"
  local model="${NIM_MODELS[$alias]}"

  echo "[gpu] Ensuring $alias is running..."
  remote_ssh "~/nim-swap.sh start $alias"

  echo "[cpu] Hot-swapping inference → $provider / $model"
  openshell inference set --provider "$provider" --model "$model" --no-verify

  echo ""
  echo "ACTIVE: $alias ($model) via provider $provider"
  echo "To restore cloud: nim-remote-swap.sh reset"
}

reset_to_default() {
  echo "[cpu] Restoring cloud provider → $DEFAULT_PROVIDER"
  openshell inference update --provider "$DEFAULT_PROVIDER"

  echo ""
  echo "ACTIVE: $DEFAULT_PROVIDER (cloud)"
  openshell inference get
}

show_status() {
  echo "=== Gateway inference ==="
  openshell inference get
  echo ""
  echo "=== GPU box models ==="
  remote_ssh "~/nim-swap.sh status"
}

[[ $# -lt 1 ]] && usage

case "$1" in
  switch)
    [[ $# -lt 2 ]] && usage
    switch_to "$2"
    ;;
  reset)
    reset_to_default
    ;;
  start)
    [[ $# -lt 2 ]] && usage
    remote_ssh "~/nim-swap.sh start $2"
    ;;
  stop)
    [[ $# -lt 2 ]] && usage
    remote_ssh "~/nim-swap.sh stop $2"
    ;;
  stop-all)
    remote_ssh "~/nim-swap.sh stop-all"
    ;;
  status)
    show_status
    ;;
  *) usage ;;
esac
