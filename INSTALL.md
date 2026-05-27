# Installation Guide

[NVIDIA NemoClaw](https://docs.nvidia.com/nemoclaw/latest/index.html) is an open source reference stack that simplifies running [OpenClaw](https://openclaw.ai/) always-on assistants more safely. It installs the NVIDIA OpenShell runtime, part of NVIDIA Agent Toolkit, an environment designed for executing claws with additional security, and open source models like NVIDIA Nemotron.

This installation guide walks you through getting NemoClaw running end to end with different setup options. The installation process consists of 3 main steps.

1. **Step 01:** Environmental setup
2. **Step 02:** Install NemoClaw
3. **Step 03:** [Optional post-install setup](INSTALL-OPTIONAL.md) — policy presets, models, remote GPU

---

## General Prerequisites

To run NemoClaw, you need an LLM (Large Language Model) backend. NemoClaw itself acts as the orchestrator and gateway, but it requires a model provider to handle actual inference. Here are the main ways to provide an LLM backend:

- **Cloud-Hosted LLM (Recommended for Most Users):**
  - Use NVIDIA NIM (Nemotron Inference Microservice) via the `nvidia-nim` provider. This is the simplest option; you just need an [NVIDIA API key](https://build.nvidia.com) and internet access. Supported models include Nemotron 3 Super (120B) and others. No GPU or heavy local compute required.
  - Example environment setup:
    ```bash
    export NVIDIA_API_KEY=nvapi-xxxx
    ```
- **Self-Hosted Local LLMs:**
  - You can configure NemoClaw/OpenShell to use a locally-hosted LLM such as [Ollama](https://ollama.com/) or [vLLM](https://vllm.ai/) as the backend. This requires a machine with sufficient GPU/CPU resources. See the OpenShell and NemoClaw documentation for details on connecting to local inference endpoints.
  - After starting your local LLM, you can select it as the provider during installation or via runtime configuration.
  - Example for running Ollama:
    ```bash
    # On your host
    ollama run llama3
    ```
- **Custom Providers:**
  - Advanced users can integrate custom or enterprise LLM endpoints by implementing the appropriate provider interface. Refer to OpenShell’s provider documentation for details.

**Note:** When running installation or connecting a sandbox, you will be prompted to choose a provider. Choose the one that matches your setup.

If you’re not sure, start with the cloud (NIM) option for the most frictionless experience.



---

## Step 1: Set Up Your Environment

Pick one of the options below, then continue to [Step 2](#step-2-install-nemoclaw).

You can choose your desired installation option from below: 

- **Option A:** Brev NemoClaw Launchable - Complete browser-based development environment
- **Option B:** Brev NemoClaw Launchable - Connect to Cursor IDE (Linux host machine)
- **Option C:** Brev NemoClaw Launchable - Connect to Cursor IDE with WSL (Windows host machine)
- **Option D:** Setup NemoClaw on DGX Spark

---

### Option A: Brev NemoClaw Launchable - Complete browser-based development environment

1. Go to the [NemoClaw Launchable](https://brev.nvidia.com/launchable/deploy?launchableID=env-3Azt0aYgVNFEuz7opyx3gscmowS&ncid=no-ncid) page to launch a NemoClaw Launchable instance.
2. Click **Deploy Launchable**.
3. Wait for the VM to be built and the setup script to complete. You should see **Built** and **script Completed** status badges:
  Brev Launchable ready
4. Click **Code-Server** to open a browser-based IDE, then follow the NemoClaw installation `README.md` inside the instance.
5. **[OPTIONAL]** Install the Claude Code extension inside Code-Server as a developer companion. If you prefer a native Cursor setup instead, see [Option B](#option-b-brev--ubuntu--cursor).

---

### Option B: Brev NemoClaw Launchable - Connect to Cursor IDE/ VSCode IDE (Linux host machine)

> Requires completion of [Option A](#option-a-brev-nemoclaw-launchable) steps 1–3, and [Cursor](https://www.cursor.com/) installed on your local machine.

**First-time setup** — install the Brev CLI on your local Linux terminal:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/brevdev/brev-cli/main/bin/install-latest.sh)"
```

**Login** to your Brev account:

```bash
brev login
```

**Open** your Brev instance in Cursor:

```bash
brev open <instance-name> cursor
```

If you using VSCode as your IDE, you can use the following shell script to connect the Brev instance to VSCode.

**Open** your Brev instance in VSCode:

```bash
brev open <instance-name> code
```

Cursor/ VSCode will connect to the remote instance via SSH. From there, continue to [Step 2](#step-2-install-nemoclaw).

---

### Option C: Brev NemoClaw Launchable - Connect to Cursor IDE with WSL (Windows host machine)

#### Setting Up WSL and Cursor (Windows Host)

Follow these steps to set up Windows Subsystem for Linux (WSL) and install Cursor on your Windows machine.

**Install WSL (Windows Subsystem for Linux):**

Open **PowerShell** as Administrator and run:

```powershell
wsl --install
```

- This will install the latest Ubuntu LTS version by default.
- When the install completes, **restart your computer** if prompted.
- On first launch, create a UNIX username and password for Ubuntu.

> If `wsl --install` fails, see [Microsoft’s WSL install docs](https://learn.microsoft.com/en-us/windows/wsl/install) for troubleshooting and detailed instructions.

**Install and Launch Ubuntu:**

- After your system restarts, launch the Ubuntu app from the Start Menu.
- Complete the initial UNIX user setup if you haven’t already.

**(Optional) Update WSL & Ubuntu packages:**

Inside your Ubuntu terminal, run:

```bash
sudo apt update && sudo apt upgrade -y
```

**Download and Install Cursor:**

- Download the Cursor installer for Windows from the [Cursor website](https://www.cursor.com/download).
- Run the installer and follow the prompts to complete installation.


Once WSL and Cursor are ready, proceed with:

- Completing [Option A](#option-a-brev-nemoclaw-launchable) steps 1–3 if you haven’t already.
- Then connect to your Brev instance in Cursor (from WSL terminal):

    ```bash
    brev open <instance-name> cursor
    ```

You are now ready to follow [Step 2](#step-2-install-nemoclaw) to install and launch NemoClaw!

---

### Option D: Setup NemoClaw on DGX Spark

@TODO: Jovan

---

## Step 2: Install NemoClaw

> If you are using Code-Server (Option A), the install script runs automatically.
> on first launch — just make your choices when prompted.

If you are using Cursor (Options B, C, or D), run the installation steps manually:

```bash
cd ~/NemoClaw
bash ./install.sh
```

> **Make sure you have your NVIDIA API key ready.**  
> If you don't have one yet, follow the steps described earlier in this guide to obtain your API key from [build.nvidia.com](https://build.nvidia.com).

When asked, choose:

- **Provider**: `nvidia-nim` (cloud) — or `ollama` / `vllm` if running a local LLM
- **Model**: `nvidia/nemotron-3-super-120b-a12b`
- **Policy**: `suggested` (to see approval flow)


## Verify NemoClaw Installation

Before heading to the demo, make sure NemoClaw is installed and functioning as expected:

1. **Check NemoClaw CLI availability:**

    ```bash
    nemoclaw --version
    ```

    You should see the installed version printed (e.g., `NemoClaw CLI vX.Y.Z`).

2. **Verify the agent can be listed:**

    ```bash
    nemoclaw list
    ```

    This should show your available sandboxes (or `No sandboxes found` if you haven't created any yet).

3. **Check installation health:**

    ```bash
    nemoclaw status
    ```

    This will show the health and status of core services. All statuses should indicate `running` or `healthy` if everything is set up correctly.

If all the above commands complete without errors, you are ready to move on to the demo!

Once installation is complete, head to [demo/basic/basic.md](demo/basic/basic.md) to run your first demo.

---

## Step 3: Post-install (optional)

For optional tasks after install—**policy presets** (for example Telegram), **switching models** at runtime, and **remote or local GPU** inference with Ollama or vLLM—see **[INSTALL-OPTIONAL.md](INSTALL-OPTIONAL.md)**.