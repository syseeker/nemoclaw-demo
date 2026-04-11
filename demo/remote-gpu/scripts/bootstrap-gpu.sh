#!/usr/bin/env bash
# bootstrap-gpu.sh — One-shot GPU instance setup for NIM containers.
# Run this ONCE on a fresh H200 instance, then reboot.
# After reboot, GPUs are ready and nim-swap.sh will work immediately.
set -euo pipefail

MIN_DRIVER=580
DRIVER_PKG="nvidia-driver-580-server"

log()  { echo "[bootstrap] $*"; }
fail() { echo "[bootstrap] ERROR: $*" >&2; exit 1; }

# ── 1. Check current state ──────────────────────────────────────────────
log "Checking current NVIDIA driver..."
if command -v nvidia-smi &>/dev/null; then
  CURRENT=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo "none")
  MAJOR=${CURRENT%%.*}
  log "Current driver: $CURRENT (major: $MAJOR)"
else
  MAJOR=0
  log "No NVIDIA driver detected."
fi

# ── 2. Install / upgrade driver if needed ────────────────────────────────
if [[ "$MAJOR" -lt "$MIN_DRIVER" ]]; then
  log "Driver $MAJOR < $MIN_DRIVER required by NIM (CUDA 13.0). Installing $DRIVER_PKG..."
  sudo apt-get update -qq
  sudo apt-get install -y "$DRIVER_PKG"
  NEEDS_REBOOT=true
else
  log "Driver $MAJOR >= $MIN_DRIVER — OK."
  NEEDS_REBOOT=false
fi

# ── 3. Install Fabric Manager (required for NVSwitch multi-GPU like H200) ─
FM_PKG="nvidia-fabricmanager-${MIN_DRIVER}"
if ! dpkg -l "$FM_PKG" 2>/dev/null | grep -q "^ii"; then
  log "Installing $FM_PKG (required for NVSwitch/NVLink multi-GPU)..."
  sudo apt-get update -qq
  sudo apt-get install -y "$FM_PKG"
fi
sudo systemctl enable nvidia-fabricmanager 2>/dev/null || true

# ── 4. Enable persistence mode (survives reboot via systemd) ─────────────
log "Ensuring nvidia-persistenced is enabled on boot..."
sudo systemctl enable nvidia-persistenced 2>/dev/null || true

# ── 5. Create a systemd drop-in that enables persistence mode at boot ────
DROPIN_DIR="/etc/systemd/system/nvidia-persistenced.service.d"
sudo mkdir -p "$DROPIN_DIR"
sudo tee "$DROPIN_DIR/persistence-mode.conf" > /dev/null <<'EOF'
[Service]
ExecStartPost=/usr/bin/nvidia-smi -pm 1
EOF
sudo systemctl daemon-reload

# ── 6. If driver is already correct, enable persistence now ──────────────
if [[ "$NEEDS_REBOOT" == "false" ]]; then
  log "Enabling GPU persistence mode now..."
  sudo nvidia-smi -pm 1
fi

# ── 7. Set up NIM cache directory ────────────────────────────────────────
NIM_CACHE="${HOME}/.cache/nim"
mkdir -p "$NIM_CACHE"
chmod -R a+w "$NIM_CACHE"
log "NIM cache: $NIM_CACHE"

# ── 8. Verify NGC_API_KEY ────────────────────────────────────────────────
if [[ -z "${NGC_API_KEY:-}" ]]; then
  log "WARNING: NGC_API_KEY not set. Export it in your shell profile:"
  log "  echo 'export NGC_API_KEY=nvapi-...' >> ~/.bashrc"
fi

# ── 9. Docker + NVIDIA Container Toolkit check ──────────────────────────
if ! command -v docker &>/dev/null; then
  fail "Docker not installed. Install docker + nvidia-container-toolkit first."
fi
if ! docker info 2>/dev/null | grep -qi nvidia; then
  log "WARNING: NVIDIA container runtime may not be configured."
  log "  Install nvidia-container-toolkit if containers can't see GPUs."
fi

# ── 10. Summary ─────────────────────────────────────────────────────────
echo ""
echo "============================================"
if [[ "$NEEDS_REBOOT" == "true" ]]; then
  echo "  Driver installed. REBOOT REQUIRED."
  echo ""
  echo "  After reboot, persistence mode will"
  echo "  auto-enable and you can run:"
  echo "    ./nim-swap.sh start qwen"
  echo ""
  echo "  Reboot now with:  sudo reboot"
else
  echo "  GPU setup complete. No reboot needed."
  echo ""
  echo "  Ready to run:  ./nim-swap.sh start qwen"
fi
echo "============================================"
