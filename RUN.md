# Running AgentSociety 2 on Windows

This project has **agentsociety2 2.8.2** installed in `.venv`, made to run on
Windows (the package officially targets Linux/macOS). Paper: arXiv 2502.08691.
**Status: verified running end-to-end on Windows**, both the single-agent
`example_ask.py` demo and a real 2-agent, 4-step-type full experiment (below).

## Easiest: AgentSociety Studio (no command line, no file editing)

Double-click **`Start AgentSociety Studio.bat`** in this folder. A black window
opens (leave it open: it is the Studio's engine) and your browser opens
<http://127.0.0.1:8765>. Everything below the Studio heading in this file is the
manual route; you don't need it if you use the Studio.

| Page | What you do there |
|---|---|
| **LLM settings** | Choose a provider (OpenRouter / OpenAI / Ollama / custom), paste a key, pick a model, **Test connection**, **Save**. The key is stored in `.env` and only its last 4 characters are shown. **Stop the Studio** is also here. |
| **Paper studies** | The 7 studies of the AgentSociety 2 paper. Pick **Smoke test** (a few cents, minutes) or **Paper scale** (slow, costs more, asks you to confirm), set a seed, press **Run** (or **Check config (free)** first). Studies that can't run on this PC say why. |
| **My experiments** | **New experiment** → name it, add people (name, age, occupation, personality), then build a timeline: *Let time pass*, *Ask the society*, *Intervene*, *Survey everyone*. **Save & check** validates it without spending anything; **Save & run** starts it. |
| **Runs** | Every run with live progress, its log, **Stop**, **Delete**, and links to results/answers. Runs keep going if you close the browser tab (not if you close the black window). |
| **Results** | Paper studies: charts plus a side-by-side comparison with the paper's numbers. Your experiments: each question's answer and each survey as a table, one row per agent with the reason. |

Files the Studio writes: experiments you design go in
`paper_experiments\my_experiments\<name>\`, and each run goes in
`<experiment>\runs\<preset>_seed<N>\` (`console.log` holds the full log).
The Studio only listens on `127.0.0.1`, so other computers can't reach it.

## Quick start (3 steps)

### 1. Add your LLM credentials
```powershell
Copy-Item .env.example .env
notepad .env
```
`.env` needs three variables. **agentsociety2 wraps your model as `openai/<MODEL>`
and calls `{API_BASE}/chat/completions`**, so:
- `AGENTSOCIETY_LLM_API_BASE` must be an **OpenAI-compatible** endpoint and must
  **not** end in `/chat/completions` (litellm appends it; a trailing one → 404).
- `AGENTSOCIETY_LLM_MODEL` must be the **exact model id that endpoint expects**
  (a plain slug), not a litellm `provider/model` id.
- Both `API_KEY` and `API_BASE` are validated at **import time** (required).

Working example (OpenRouter):
```dotenv
AGENTSOCIETY_LLM_API_KEY=sk-or-...
AGENTSOCIETY_LLM_API_BASE=https://openrouter.ai/api/v1
AGENTSOCIETY_LLM_MODEL=openai/gpt-4o-mini
```

> The agent GENERATES Python to introspect the world, so a weak model yields
> buggy code / empty results (gpt-4o-mini often fails the introspection step).
> Use a capable model — e.g. `openai/gpt-4o` or `anthropic/claude-3.5-sonnet`
> via OpenRouter — for real answers. You can also set `AGENTSOCIETY_CODER_LLM_MODEL`
> to use a strong model just for code generation.

### 2. Activate the virtual environment
```powershell
& ".\.venv\Scripts\Activate.ps1"
```

### 3. Run the example
```powershell
python example_ask.py
```
Ray starts a local instance, the agent generates observe/statistics code, builds
a plan, executes it, and prints an answer. Replay + trace data land in `run/`.

## Running full experiments (CLI)

A "full experiment" is multi-agent, multi-step, and driven by two files instead
of a Python script: `init_config.json` (who exists) and `steps.yaml` (what
happens, in order). A worked, verified example lives in [experiment/](experiment/).

**agentsociety2.society.cli does not load `.env` itself** (only its unrelated
web backend does), so use the [run_experiment.py](run_experiment.py) wrapper
in this project root instead of calling the module directly — it just loads
`.env` then delegates to the real CLI (every `--flag` is identical):

```powershell
python run_experiment.py --config experiment\init_config.json --steps experiment\steps.yaml --run-dir experiment\run --log-level INFO
```

`python run_experiment.py --help` lists all flags (`--resume`, `--batch-size`,
`--replay-disable`, ...).

### `init_config.json` — who exists
```json
{
  "env_modules": [
    { "module_type": "SimpleSocialSpace",
      "kwargs": { "agent_id_name_pairs": [[1, "Alice"], [2, "Bob"]] } }
  ],
  "agents": [
    { "agent_id": 1, "agent_type": "PersonAgent",
      "kwargs": { "id": 1, "name": "Alice", "age": 28,
                  "personality": "friendly and curious",
                  "bio": "A software engineer who loves hiking." } },
    { "agent_id": 2, "agent_type": "PersonAgent",
      "kwargs": { "id": 2, "name": "Bob", "age": 34,
                  "personality": "reserved and analytical",
                  "bio": "A data analyst who enjoys chess and reading sci-fi." } }
  ],
  "codegen_router": { "final_summary_enabled": true }
}
```
`env_modules[].module_type` and `agents[].agent_type` must be names from the
built-in registry (`python -c "from agentsociety2.registry import get_registered_env_modules as e, get_registered_agent_modules as a; print([n for n,_ in e()]); print([n for n,_ in a()])"`).
`SimpleSocialSpace` + `PersonAgent` is the general-purpose pairing used above;
the rest (`PrisonersDilemmaEnv`+`PrisonersDilemmaAgent`, `TrustGameEnv`+`TrustGameAgent`,
`PublicGoodsEnv`, `CommonsTragedyEnv`, ...) are specific game-theory scenarios,
each requiring its matching agent type.

### `steps.yaml` — what happens, in order
Four step types (`type` field), run top to bottom:
```yaml
start_t: "2026-01-01T09:00:00"      # ISO datetime, the simulation clock's t=0
steps:
  - type: run                        # advance the simulation
    num_steps: 1                     # how many ticks
    tick: 3600                       # seconds of simulated time per tick
  - type: ask                        # read-only Q&A over current state
    question: "What has each agent been doing this morning?"
  - type: intervene                  # inject an event / instruction
    instruction: "Tell Bob that Alice invited him to go hiking this weekend."
  - type: questionnaire              # structured survey, saved as JSON
    questionnaire_id: "mood_check"
    title: "Quick mood check-in"
    questions:
      - id: "mood"
        prompt: "On a scale of 1-10, how would you rate your mood right now?"
        response_type: integer       # text | integer | float | choice | json
      - id: "plans"
        prompt: "What are you planning to do next?"
        response_type: text
```
`run` actually simulates agent behavior (each agent reasons/acts per tick — the
expensive step, cost/time scale with `num_steps × num_agents`). `ask` /
`intervene` invoke the same plan-execute `AgentSocietyHelper` as `example_ask.py`.
`questionnaire` asks every `target_agent_ids` (default: all) each question directly
(no planning) and writes structured per-agent answers.

### Expected console output
```
[...] INFO   Environment validation passed
[...] INFO   Loading config from ...\init_config.json
[...] INFO   Loading steps from ...\steps.yaml
... INFO worker.py:2024 -- Started a local Ray instance.
[...] INFO   Registered 16 env modules and 7 agents from built-in modules
[...] INFO   AgentSociety initialized
[...] INFO   Executing 4 steps...
[...] INFO   Running 1/1 steps with tick=3600
(step_agent_batch pid=...) WARNING Agent 2: ReAct tool failed: action=execute_skill_script ...
  ============================================================
  AgentSocietyHelper Starting (Ask Mode)
  Task: What has each agent been doing this morning?
  ============================================================
  📋 Initial Plan (2 steps):
    1. Retrieve the list of all agents currently in the society.
    2. Ask all retrieved agents what they have been doing this morning.
  [Step 1/2] ...
    ✓ Result: {"agent_ids": [1, 2]}
  [Step 2/2] ...
    ✗ Error: agent_ids must be a list of known integer agent ids, got '<output from previous step>'. ...
  🔄 Replanning (attempt 1/2)...
    Updated Plan (1 steps):
      1. Ask all retrieved agents ... using the correct format for agent_ids.
  [Step 1/1] ...
    ✓ Result: {"answers": {"1": "done", "2": "This morning, I've been attempting to check my mailbox..."}}
  ✓ Completed (3 steps executed)
  Final Answer: This morning, agent 1 stated they were 'done', while agent 2 reported ...
  ============================================================
[...] INFO   Ask result saved to ...\run\artifacts\ask_step_1_20260101_100000.md
[...] INFO   Intervening: Tell Bob that Alice invited him to go hiking this weekend.
  [... AgentSocietyHelper Starting (Intervene Mode) — same plan/execute/replan shape ...]
[...] INFO   Intervene result saved to ...\run\artifacts\intervene_step_2_20260101_100000.md
[...] INFO   Running questionnaire mood_check with 2 questions
[...] INFO   Questionnaire result saved to ...\run\artifacts\questionnaire_step_3_20260101_100000.json
[...] INFO   Experiment completed successfully
```
The `ReAct tool failed: ... execute_skill_script ... Script not found: plan`
warnings during `run` steps are normal — agents probing for optional skill
scripts that don't exist in this minimal setup. Not fatal; safe to ignore.
Each `📋 Initial Plan` / `🔄 Replanning` block is one LLM-driven `ask`/`intervene`
call — expect real wall-clock time (tens of seconds each) and real API cost.

### Expected files (`run_dir` after completion)
```
experiment/run/
  pid.json                    status/progress (poll while running; "completed"/"failed" at end)
  SOCIETY.json                world snapshot: agent specs, env module config, steps.yaml hash
  SOCIETY_STEP.json           simulation clock + step-count checkpoint (used by --resume)
  agents/agent_0001/          per-agent workspace (one per agent)
    AGENT.json                 profile + current state snapshot
    MEMORY.md                  agent's own long-term memory notes (starts empty)
    TODO.json, config.json
    memory/episodes.jsonl, memory/state.json
  env/SimpleSocialSpace/state/ENV_STATE.json   environment module's persisted state
  artifacts/                  ← the actual results you asked for
    ask_step_1_<simtime>.md          question + answer, Markdown
    intervene_step_2_<simtime>.md    instruction + result, Markdown
    questionnaire_step_3_<simtime>.json   structured per-agent answers, JSON
  replay/*.jsonl, replay/_schema.json    full event log (sharded JSONL + schema catalog)
  trace/*.jsonl                          span/timing traces for debugging
```
**`artifacts/` is what you actually read.** Everything else is simulation
state/observability. Re-running the same `--run-dir` without `--resume`
overwrites agent/env state (the CLI logs a warning but proceeds).

> **Read artifacts, don't just trust the one-line "Final Answer."** The
> summarizer LLM call synthesizes from `execution_history`, and with a weak
> model it can produce a fluent-sounding answer even when the underlying step
> results were messy (e.g. an agent's raw reply leaking internal reasoning
> instead of prose). If correctness matters, check the specific `Result:` /
> artifact content, not just the final sentence.

## What was done to make v2 run on Windows

1. **Compatibility shim** — `.venv\Lib\site-packages\sitecustomize.py` (auto-loaded
   by Python at startup, covers scripts + CLI + Ray workers). It:
   - forces **UTF-8 stdout/stderr** (Windows cp1252 can't encode the emoji the
     library prints → `UnicodeEncodeError`);
   - supplies **`os.pathconf`** (POSIX-only) with the library's intended 4096 fallback;
   - supplies a Windows **`fcntl.flock`** via `msvcrt` byte-range locks (verified
     to give real mutual exclusion).

2. **Three upstream bug fixes** (real library bugs, not Windows-specific — would
   crash on Linux/macOS too) in `.venv\Lib\site-packages\agentsociety2\`:
   - `env\router_codegen.py` lines 1865 & 1886 read module-level constants off
     `self` (`self.OBSERVE_INSTRUCTION` / `self.STATISTICS_INSTRUCTION`) →
     `AttributeError` in `init()`. Changed to the module globals.
   - `society\helper.py` `_tool_ask_agents` (~line 949) did
     `[int(i) for i in agent_ids if int(i) in known_ids]` with no validation,
     crashing (`invalid literal for int() with base 10: 'o'` / `'<'`) whenever
     a tool call passed a non-numeric `agent_ids`. Patched to skip unparseable
     entries; if *all* entries are unparseable (garbage input, not a
     legitimately-empty filter result) it now raises a clear `ValueError`
     instead — this still lets the existing replanning loop in `_run` catch it
     (replanning only triggers on an exception, so silently swallowing the bad
     input would have disabled the library's own self-correction).
   - `society\helper.py` `_register_tools` had no tool to list all agent ids —
     only `filter_agents_by_profile` (a *matching* tool, returns empty if the
     field doesn't apply) produced `agent_ids`, and the planning prompt never
     lists the roster. So any question not mapping to a profile field made the
     planner invent a filter that always returned nothing. Added a
     `list_all_agents` tool (`_tool_list_all_agents`) and tightened
     `filter_agents_by_profile`'s description to stop it being misused as a
     fake "get everyone" call.
   - `society\helper.py` `_run`'s plan-execute loop computed
     `step_index = len(execution_history)` — a counter that keeps growing across
     the *entire* `ask()`/`intervene()` call. When a step failed and replanning
     produced a new (shorter) `plan`, the very next loop iteration saw
     `step_index >= len(new_plan)` and hit the "all steps completed" break
     *immediately*, without ever running the new plan. Confirmed via a real 2-agent
     run: "Updated Plan" printed, then straight to "Completed" with zero
     `[Step x/y]` lines for it — and for `intervene()`, the final-answer LLM call
     still produced a fluent "success"-sounding sentence despite the actual
     delivery step never having run. **This made replanning silently decorative
     — it never fixed anything — which is especially risky for `intervene()`,
     where you could believe a side effect happened when it didn't.** Patched by
     tracking `plan_start` (reset to `len(execution_history)` when a new plan is
     adopted) so `step_index` is computed relative to the *current* plan.
     Re-verified on the same 2-agent experiment: replanned steps now actually
     execute and the final answers are grounded in real results.
   - `society\helper.py` `_build_planning_prompt` / `_build_replanning_prompt`
     now include the real agent-id roster (`_agent_ids_note`). Because plan args
     are fixed upfront (see below), "ask each person…" plans used to guess ids and
     often asked only agent 1.
   - `agent\base\agent.py` ReAct `ask_env`: the code-template cache is used only
     for **readonly calls with `variables`**. Before, a cached template could replay
     another agent's literal answers (e.g. every agent submitted identical prices
     in the endowment-effect task). `person_prompt.py` / `tool_schema.py` text was
     updated to match.

   The `sitecustomize.py` shim also retries `os.replace` on `PermissionError`,
   because OneDrive briefly locks files it is syncing and that killed a long run.

3. **litellm pinned to 1.91.3** — `litellm 1.92.0` is source-only and won't build
   on Windows (needs Rust). 1.91.3 has a wheel and satisfies `>=1.83.7`.

> ⚠️ Item 2's edits live inside `agentsociety2`'s source; re-apply after
> `pip install -U agentsociety2`. The `sitecustomize.py` shim (item 1 in the
> list above) and the litellm pin survive upgrades. Recreating the venv loses
> everything patched.

## Known limitation: plan arguments are committed upfront

`AgentSocietyHelper` (the `ask`/`intervene` plan-execute engine) generates the
**entire** multi-step plan — including every step's tool `args` — in one LLM
call *before* any step runs. A step's args are never re-bound to an earlier
step's actual result (`_execute_step` just does `args = step.args`). So e.g.
step 2 asking agents by id is really the planner *predicting* what step 1 will
return, not consuming its real output — we've seen it plan args like literally
`"<output from previous step>"` or `["Bob's ID"]` instead of real values.

The planner is now given the list of agent ids, so plans that address everyone
use real ids. This is also **much less costly** than it used to be, because replanning is
fixed (see bug list above) and actually re-executes on failure — in every
2-agent test run so far, the replan step correctly recovers and produces a
real, grounded answer. It's still an extra LLM round-trip (slower, costs more) and still bounded by
`AgentSocietyHelper`'s `max_replans` (2 by default, not a CLI flag — a code-level
constructor default), so it's not free, and a stronger model (`gpt-4o`,
`claude-3.5-sonnet`) will need to replan less often.
This upfront-args behavior itself is a real architectural property of
agentsociety2 2.8.2, not something patched here — replanning is the library's
own designed mitigation for it, and that mitigation now actually works.

## If you hit further Windows issues
agentsociety2 is officially Linux/macOS-only. You have **WSL Ubuntu**
(`wsl -d Ubuntu`) — the fully-supported environment, no shim/patches needed.

## Notes
- `.venv` (~2 GB) sits in a OneDrive-synced folder; consider excluding it from sync.
- v1 (`agentsociety`, matching the paper) was uninstalled — its `numpy<2`/`protobuf<=4.24`
  pins conflict with v2. Use a separate venv if you want both.
