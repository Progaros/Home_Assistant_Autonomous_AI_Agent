# Home Assistant Autonomous AI Agent

A proactive, LLM-powered smart home agent that runs entirely within Home Assistant's `python_script` sandbox. It analyzes context (weather, calendar, sensors), maintains memory, and **autonomously controls devices** or sends alerts.

## Features
*   **Autonomous Loop:** Analyzes data and executes multi-step actions without user intervention.
*   **Tool System:** Can check S-Bahn times, weather, read sensor states, and control devices.
*   **Memory:** Persists user facts and corrections via template sensors (long-term learning).
*   **Proactive:** Triggers urgent alerts (e.g., high CO2) or helpful reminders based on context.
*   **Sandboxed:** Runs without external Python imports, fully compatible with HA's restricted environment.

## Requirements
*   **Home Assistant** with `python_script` integration enabled.
*   **LLM Integration:** An entity (e.g., `ai_task.qwen3_instruct`) provided by an integration like `ollama` or `ai_task`.
*   **Template Sensors:** Required for storing agent memory and state.

## Installation

1.  **Enable Python Scripts:**
    Add `python_script:` to your `configuration.yaml` and restart HA.

2.  **Deploy Agent:**
    Copy `agent.py` to your `/config/python_scripts/` folder.
    *   *Configuration:* Edit the `PERSONAL CONFIGURATION` section in `agent.py` (User Name, Language, Entity IDs).

3.  **Setup Memory & State:**
    Copy the template sensors from `config.yaml` into your HA `configuration.yaml` (under `template:`). These store the agent's "Learned Facts" and history.

4.  **Automation:**
    Use `automation.yaml` as a template. It handles:
    *   Waking up the local PC (if hosting the LLM).
    *   Triggering `python_script.agent` on a schedule.
    *   Shutting down the PC after completion.

## Usage

**Manual Trigger:**
Call the service in Developer Tools:
```yaml
service: python_script.agent
data:
  max_iterations: 10
  entity_memory: sensor.ai_memory_store
  llm_entity: ai_task.qwen3_instruct
```

**Logic Flow:**
1.  **Gather Context:** Reads weather, calendar, and memory.
2.  **Think:** Sends prompt to LLM.
3.  **Act:** LLM chooses a tool (e.g., `CONTROL_DEVICE`, `GET_SBAHN`).
4.  **Repeat:** Loops until task is finished or max iterations reached.