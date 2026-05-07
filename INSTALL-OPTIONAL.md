# Optional Post-Install Setup (Step 3)

**Great job finishing the main installation!** 🎉  
The following steps are **optional**, but they can help you get even more out of NemoClaw.  
They show you how to:  
- Add policy presets for network access
- Switch between large language models easily
- Connect NemoClaw to a local or remote GPU for faster inference

---

## 1. Add a Policy Preset

Policy presets make it easy to give your AI controlled access to external services like Telegram, Slack, or finance APIs, without setting up a custom policy from scratch.

**To add a policy preset:**
1. Open the terminal.
2. Run:
    ```bash
    nemoclaw <your-agent-name> policy-add
    ```
3. When prompted, pick a preset from the list. For example, to allow Telegram integration, select `telegram`.

The `telegram` preset enables the Telegram bridge in NemoClaw, so your agent can access the Telegram API right away. For a full step-by-step Telegram setup, check out [demo/telegram-bridge/telegram-bridge.md](demo/telegram-bridge/telegram-bridge.md).

> **Tip:**  
> You can also create your own policies, like a custom finance policy for getting stock prices, or limiting access to certain sites only. See [demo/basic/basic.md](demo/basic/basic.md) for a walkthrough on making your own, manually or with the help of an AI coding companion.

---

## 2. Switch Models at Runtime

Want to experiment with a faster or more powerful model? You can swap models on the fly—no need to restart anything!

**Examples:**
```bash
# Switch to a smaller/faster Nemotron 3 Nano (30B parameters)
openshell inference set --provider nvidia-nim --model nvidia/nemotron-3-nano-30b-a3b

# Or go back to the larger Nemotron 3 Super (120B parameters)
openshell inference set --provider nvidia-nim --model nvidia/nemotron-3-super-120b-a12b
```

**That's it!** Your agent switches models instantly, with no downtime.

---

## 3. Use a Local or Remote GPU for Faster Inference

Sometimes, you want to run models on your own GPU—on your machine or a cloud VM—to save time or money.

Here's how:

**A. Use a local Ollama provider (for running models locally):**
```bash
openshell inference set --provider ollama --model <model-name>
```
*(Replace `<model-name>` with the name of the Ollama-supported model you want to use)*

**B. Use a vLLM setup:**
```bash
openshell inference set --provider vllm --model <model-name>
```
*(Works with any model vLLM supports!)*

For a detailed, step-by-step guide (including how to set up an H200 GPU instance on Brev with self-hosted NIM hot-swapping), see [demo/remote-gpu/remote-gpu.md](demo/remote-gpu/remote-gpu.md).

---

**Need more help or want to try another integration?**  
Check the [demo/](demo/) folder for more real-world examples.
