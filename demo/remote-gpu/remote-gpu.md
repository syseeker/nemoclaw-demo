# Remote Inference Hot-Swapping

Route NemoClaw's inference to a remote GPU instance running
OpenAI-compatible inference servers. The operator hot-swaps models from the
CPU host using `openshell inference set` — the agent inside the sandbox
never notices. This guide uses NVIDIA NIMs as the example, but the pattern
works with any OpenAI-compatible endpoint (vLLM, SGLang, TGI, etc.).

## What you will learn

- Splitting NemoClaw (CPU, always-on) from inference (GPU, on-demand)
- Registering remote inference providers with `openshell provider create`
- Hot-swapping models with `openshell inference set` — no restart needed
- Switching between cloud and self-hosted inference at will
- Container lifecycle management on the GPU instance

---

## Model Lineup (Example: NVIDIA NIMs)


| Alias      | Image                                           | Params   | Active | Port | Docker flags                | Notes                              |
| ---------- | ----------------------------------------------- | -------- | ------ | ---- | --------------------------- | ---------------------------------- |
| `qwen`     | `nvcr.io/nim/qwen/qwen3.5-397b-a17b`            | 397B MoE | 17B    | 8000 | `--ipc host --shm-size=32g` | Hopper, Blackwell                  |
| `glm`      | `nvcr.io/nim/zai-org/glm-5`                     | 744B MoE | 40B    | 8001 | `--shm-size=16g`            | Hopper, Blackwell                  |
| `nemotron` | `nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b` | 120B MoE | 12B    | 8002 | `--shm-size=16g`            | Hopper, Blackwell                  |
| `kimi`     | `nvcr.io/nim/moonshotai/kimi-k2.5`              | 1T MoE   | 32B    | 8003 | `--ipc host --shm-size=32g` | Hopper only. Multimodal, 256K ctx. |


Each model gets a **fixed host port**. Depending on available VRAM, you
can run multiple models simultaneously (warm standby) or one at a time
(cold swap).

---

## Prerequisites

- A running CPU-based NemoClaw instance (your existing setup).
- A remote GPU instance with Docker and NVIDIA drivers.
- SSH access from the CPU instance to the GPU instance (key-based).
- NGC API key from [NGC Setup](https://org.ngc.nvidia.com/setup/api-key)
for pulling NIM container images.

---

## Architecture

```
 Operator (laptop / terminal)
  │
  │  nim-remote-swap.sh switch qwen
  │  nim-remote-swap.sh reset
  │
  ┌──────┼───────────────────────────────────────────────┐
  │      ▼                                               │
  │  CPU Instance (always-on)                            │
  │  ────────────────────────                            │
  │                                                      │
  │  openshell inference set ──► OpenShell gateway       │
  │                                    │                 │
  │  ┌─────────────────────────────────┼──────────────┐  │
  │  │  OpenShell Sandbox              │              │  │
  │  │                                 │              │  │
  │  │  OpenClaw agent ──► inference.local             │  │
  │  │       │                                        │  │
  │  │       └── tools (exec, web_fetch)              │  │
  │  └────────────────────────────────────────────────┘  │
  │                                                      │
  │  Telegram bridge (optional)                          │
  └──────────────────────────────┼───────────────────────┘
                                 │
                              network
                                 │
  ┌──────────────────────────────┼───────────────────────┐
  │                              ▼                       │
  │  GPU Instance                                        │
  │  ────────────                                        │
  │                                                      │
  │  nim-swap.sh                                         │
  │    start/stop model containers on fixed ports        │
  │                                                      │
  │  Model containers (one or more at a time)            │
  │    qwen :8000 | glm :8001 | nemotron :8002 | ...    │
  │                                                      │
  │  No NemoClaw, no OpenShell, no sandbox.              │
  │  Pure OpenAI-compatible inference server.            │
  └──────────────────────────────────────────────────────┘
```

The GPU box has no NemoClaw. It only runs Docker and the inference
containers. The operator controls which model the gateway routes to.

---

## Step 1: Set Up SSH from CPU to GPU

The CPU NemoClaw instance needs direct SSH to the GPU box for container
management.

**1. On the CPU host** — get (or create) an SSH key:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519   # skip if key exists
cat ~/.ssh/id_ed25519.pub
```

Copy the output.

**2. On the GPU box** — add the CPU host's public key:

```bash
echo "ssh-ed25519 AAAA...paste-cpu-host-key-here..." >> ~/.ssh/authorized_keys
```

**3. On the GPU box** — open the inference ports:

```bash
sudo ufw allow 8000:8003/tcp
```

**4. On the CPU host** — add a host alias and test:

Find `<gpu-instance-ip>` and `<gpu-instance-user>` from the GPU box's
shell banner (shown when you SSH in). Look for fields like:

```
Global IP: 95.x.x.x        ← this is <gpu-instance-ip>
```

The username is whatever you logged in as (shown in the prompt, e.g.
`user@hostname:~$` → `<gpu-instance-user>` is `user`).

```bash
cat >> ~/.ssh/config << 'EOF'
Host nim-gpu
    HostName <gpu-instance-ip>
    User <gpu-instance-user>
    IdentityFile ~/.ssh/id_ed25519
EOF
```

Test the alias:

```bash
ssh nim-gpu 'nvidia-smi --query-gpu=name --format=csv,noheader | head -1'
```

If that returns the GPU name, the SSH link is ready.

---

## Step 2: Pull Container Images on the GPU Instance

Pre-pull all images so hot-swaps only wait on model loading, not downloads.

### Get an NGC API key

1. Go to [NGC](https://org.ngc.nvidia.com/) and sign in.
2. Navigate to **Setup** → **API Key**.
3. Generate a new key and copy it.

### Authenticate and pull

```bash
ssh nim-gpu

export NGC_API_KEY="nvapi-xxxx"

echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin

docker pull nvcr.io/nim/qwen/qwen3.5-397b-a17b:latest
docker pull nvcr.io/nim/zai-org/glm-5:latest
docker pull nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b:latest
docker pull nvcr.io/nim/moonshotai/kimi-k2.5:latest
```

> **Tip**: Add `export NGC_API_KEY="nvapi-xxxx"` to `~/.bashrc` on the GPU
> box so it persists. The hot-swap script needs this at runtime.

---

## Step 3: Deploy the Container Manager (GPU Box)

The script `[scripts/nim-swap.sh](scripts/nim-swap.sh)` lives in this
repo at:

```
NemoClaw-Demo/demo/remote-gpu/scripts/nim-swap.sh
```

It manages the container lifecycle on the GPU box — start, stop, health
check. Each model gets its own container name and fixed port. Key design
points:

- Per-model container name (`nim-qwen`, `nim-glm`, etc.) and fixed port.
- Per-model docker flags (some models need `--ipc host`, different
`--shm-size`).
- Shared NIM cache (`~/.cache/nim`) so compiled engines persist.

From the **CPU host**, `cd` into the repo and `scp` the script to the
GPU box:

```bash
cd ~/NemoClaw-Demo/demo/remote-gpu
scp scripts/nim-swap.sh nim-gpu:~/nim-swap.sh
ssh nim-gpu 'chmod +x ~/nim-swap.sh'
```

Test from the GPU box:

```bash
ssh nim-gpu
export NGC_API_KEY="your-ngc-key"

~/nim-swap.sh start qwen
~/nim-swap.sh status       # → ACTIVE  qwen  port=8000
~/nim-swap.sh stop qwen
```

---

## Step 4: Configure, Register Providers, and Deploy the Orchestrator (CPU Box)

### Configure environment

Create the env file with your GPU instance IP and NGC API key. Both the
provider registration below and the orchestrator script source this file.

```bash
cd ~/NemoClaw-Demo/demo/remote-gpu
mkdir -p ~/.config
cp templates/nim-remote-swap.env.example ~/.config/nim-remote-swap.env
chmod 600 ~/.config/nim-remote-swap.env
```

Edit `~/.config/nim-remote-swap.env` and set:

- `NIM_GPU_IP` — the same IP from Step 1.4 (`HostName` in `~/.ssh/config`)
- `NGC_API_KEY` — your NGC key from Step 2

### One-time: register a provider per remote model

Each remote model needs an `openshell` provider with `base_url` pointing
to the GPU box. This is a one-time setup.

```bash
source ~/.config/nim-remote-swap.env

openshell provider create --name nim-qwen \
  --type nvidia --credential NGC_API_KEY \
  --config base_url=http://${NIM_GPU_IP}:8000/v1

openshell provider create --name nim-glm \
  --type nvidia --credential NGC_API_KEY \
  --config base_url=http://${NIM_GPU_IP}:8001/v1

openshell provider create --name nim-nemotron \
  --type nvidia --credential NGC_API_KEY \
  --config base_url=http://${NIM_GPU_IP}:8002/v1

openshell provider create --name nim-kimi \
  --type nvidia --credential NGC_API_KEY \
  --config base_url=http://${NIM_GPU_IP}:8003/v1

openshell provider list   # verify all created
```

> If you get `AlreadyExists` errors, the providers are already registered.
> To re-create with different settings, delete first:
> `openshell provider delete nim-qwen` then re-run the create command.

### Deploy the orchestrator script

Copy `[scripts/nim-remote-swap.sh](scripts/nim-remote-swap.sh)` to
`~/bin/` on the CPU host. It combines SSH (container management) with
`openshell inference set` (gateway hot-swap).

```bash
mkdir -p ~/bin
cp scripts/nim-remote-swap.sh ~/bin/nim-remote-swap.sh
chmod +x ~/bin/nim-remote-swap.sh
```

Ensure `~/bin` is on your `PATH`.

---

## Step 5: Hot-Swap

The operator controls which model is active. The agent inside the sandbox
is model-agnostic — it always calls `inference.local` and gets whatever
model the gateway is pointed to.

```bash
# Switch to remote Qwen
nim-remote-swap.sh switch qwen
# → starts Qwen on GPU box, runs: openshell inference set --provider nim-qwen

# Check what's active
nim-remote-swap.sh status

# Switch to a different remote model
nim-remote-swap.sh switch nemotron

# Reset to default cloud provider
nim-remote-swap.sh reset
# → runs: openshell inference set --provider nvidia-prod
```

### Verify from inside the sandbox

```bash
nemoclaw <name> connect
openclaw agent --agent main --local \
  -m "What model are you? Respond with your model name only." \
  --session-id swap-test-1
```

Use a different `--session-id` each time to avoid cached model state.

---

## Step 6: Demo with Telegram

The Telegram bridge runs on the CPU host. The operator hot-swaps the model
in one terminal while the user chats via Telegram. The agent does not know
the switch happened.

### What to show

1. User sends a reasoning prompt via Telegram → response from cloud
  model (default)
2. Operator runs `nim-remote-swap.sh switch qwen` in a terminal
3. User sends the same prompt → response from self-hosted Qwen
  (different style, different model identity)
4. Operator runs `nim-remote-swap.sh switch glm`
5. User sends the same prompt → response from GLM-5
6. Operator runs `nim-remote-swap.sh reset`
7. User sends the same prompt → back to cloud model

The user sees the model change in real time. The agent never notices.

---

## Step 7: Monitor with OpenShell TUI

```bash
openshell term
```

You will see:

- The inference provider/model update when the gateway re-routes
- Inference requests flowing to the new remote endpoint

### Monitor the GPU box (optional)

```bash
ssh nim-gpu 'watch -n2 nvidia-smi'
```

---

## Demo Flow Cheat Sheet


| Step | Where   | Action                                      | What to Show                        |
| ---- | ------- | ------------------------------------------- | ----------------------------------- |
| 1    | CPU+GPU | Set up SSH, pull images, register providers | One-time setup                      |
| 2    | CPU box | `nim-remote-swap.sh switch qwen`            | Gateway re-routes to remote Qwen    |
| 3    | CPU box | `nemoclaw <name> connect` → test prompt     | Inference works through remote NIM  |
| 4    | CPU box | `nim-remote-swap.sh switch glm`             | Swap to different remote model      |
| 5    | Phone   | Telegram: same prompt as step 3             | Response now from GLM               |
| 6    | CPU box | `nim-remote-swap.sh reset`                  | Reset to cloud                      |
| 7    | Phone   | Telegram: same prompt                       | Response from cloud model again     |
| 8    | CPU box | `openshell term`                            | Watch gateway re-route in real time |


---

## Talking Points

1. **Two-box split**: The CPU instance (cheap, always-on) handles the
  agent, sandbox, and gateway. The GPU instance only runs inference
   containers.
2. **Operator-controlled hot-swap**: The operator decides which model
  is active via `openshell inference set`. The agent is model-agnostic
   — it calls `inference.local` and gets whatever model the gateway
   points to. The sandbox never controls its own inference backend.
3. **Cloud ↔ self-hosted**: Switch between the default cloud provider
  and self-hosted models on the GPU box. `switch` goes remote, `reset`
   goes back to cloud. No sandbox restart needed.
4. **Instant via OpenShell**: `openshell inference set` re-routes the
  gateway in place. No restart, no reconnect.
5. **Works with any OpenAI-compatible endpoint**: This demo uses NVIDIA
  NIMs, but the same pattern works with vLLM, SGLang, TGI, or any
   server exposing `/v1/chat/completions`.

---

## Troubleshooting

- **SSH from CPU to GPU fails**: Verify key-based auth:
  ```bash
  ssh nim-gpu 'echo ok'
  ```
- **NIM health check times out**: Large models can take 5–10 minutes to
load. Increase `HEALTH_TIMEOUT` in `nim-swap.sh`. Check container logs:
  ```bash
  ssh nim-gpu 'docker logs -f nim-qwen'
  ```
- **Gateway can't reach remote endpoint**: Ensure inference ports are
open on the GPU instance. Test from the CPU box:
  ```bash
  curl http://<gpu-ip>:8000/v1/models
  ```
- **OOM during model start**: Ensure previous containers are stopped
before starting large models:
  ```bash
  ssh nim-gpu 'nvidia-smi'
  ```
- **Telegram bridge not forwarding**: Confirm `nemoclaw start` is running:
  ```bash
  tail -f /tmp/nemoclaw-services-<sandbox>/telegram-bridge.log
  ```

---

## What This Demo Does NOT Use

- `**nemoclaw deploy**` — Being sunset. The demo uses manual GPU
provisioning and standard NemoClaw install on the CPU box only.
- **NemoClaw on the GPU box** — The GPU instance is a bare Docker host.
No OpenShell, no sandbox, no gateway.
- **Agent-triggered swaps** — `openshell` is not available inside the
sandbox. The operator controls the model from the host. This is
intentional: the sandbox should not control its own inference backend.
- **SSH tunnels** — Not needed. Providers are registered with `base_url`
pointing directly to the GPU instance.

