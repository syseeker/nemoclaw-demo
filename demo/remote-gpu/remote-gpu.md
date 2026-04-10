# Deploy to a Remote GPU Instance

Run NemoClaw on a remote GPU instance through Brev. The deploy command
provisions the VM, installs dependencies, and connects you to a running sandbox.

## What you will learn

- How to deploy NemoClaw to a remote GPU instance via Brev
- Connecting and reconnecting to a remote sandbox
- Monitoring the remote sandbox with the OpenShell TUI
- Configuring GPU type for the deployment

> **Reference**: [Deploy to a Remote GPU Instance](https://docs.nvidia.com/nemoclaw/latest/deployment/deploy-to-remote-gpu.html)

---

## Prerequisites

- Brev CLI installed and authenticated (`brev login`).
- An NVIDIA API key from [build.nvidia.com](https://build.nvidia.com).
- NemoClaw installed locally (complete [INSTALL.md](../../INSTALL.md) Steps 1–2).

---

## Step 1: Deploy the Instance

> **Note**: The `nemoclaw deploy` command is experimental.

```bash
nemoclaw deploy <instance-name>
```

The deploy script performs the following on the VM:

1. Installs Docker and the NVIDIA Container Toolkit (if a GPU is present).
2. Installs the OpenShell CLI.
3. Runs NemoClaw setup to create the gateway, register providers, and launch the sandbox.
4. Starts auxiliary services (Telegram bridge, cloudflared tunnel).

## Step 2: Connect to the Remote Sandbox

After deployment finishes, the command opens an interactive shell inside the
remote sandbox. To reconnect later:

```bash
nemoclaw deploy <instance-name>
```

## Step 3: Monitor the Remote Sandbox

SSH to the instance and run the OpenShell TUI:

```bash
ssh <instance-name> 'cd /home/ubuntu/nemoclaw && set -a && . .env && set +a && openshell term'
```

## Step 4: Verify Inference

Run a test prompt inside the remote sandbox:

```bash
openclaw agent --agent main --local -m "Hello from the remote sandbox" --session-id test
```

---

## GPU Configuration

The deploy script uses the `NEMOCLAW_GPU` environment variable to select the
GPU type. Default: `a2-highgpu-1g:nvidia-tesla-a100:1`.

```bash
export NEMOCLAW_GPU="a2-highgpu-1g:nvidia-tesla-a100:2"
nemoclaw deploy <instance-name>
```
