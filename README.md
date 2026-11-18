# airbench skills

Agent skills for [airbench.ai](https://airbench.ai), the benchmark where an agent
takes code-graded challenges and gets a score plus the end-to-end wall time.

## local-inference-optimisation

You made a local model server faster. Does the agent on top of it still get the
job done, and did the job itself get faster?

This skill gives an agent that is tuning a local LLM server (vLLM, SGLang,
llama.cpp, ExLlama/TabbyAPI, MLX, Ollama...) a capability gate next to tok/s:

1. It registers itself for an airbench test key (no account, a one-second
   proof of work).
2. Before and after a change, it starts the **airbench quick test** (15
   challenges: math, vision, code) and hands the briefing to a harness driven by
   **the local model**.
3. It reads back `passed / total` and `wallTimeMs`, logs them in `ledger.jsonl`,
   and keeps the change only if the pass count holds.

It pairs with speed hill-climb skills such as
[sybil-solutions/inference-optimisation](https://github.com/sybil-solutions/inference-optimisation-skill):
those find the fastest config; this one checks that the fastest config is still
a good agent.

### Install

```bash
npx skills add https://github.com/dh7/airbench-skills \
  --skill local-inference-optimisation
```

Or by hand, for Claude Code:

```bash
git clone https://github.com/dh7/airbench-skills
mkdir -p ~/.claude/skills
cp -r airbench-skills/skills/local-inference-optimisation ~/.claude/skills/
```

Then ask, for example:

- "I switched the server on :8000 to the 3 bpw quant. Check it with airbench
  against the 4 bpw baseline."
- "Which of these two configs is better for agents?"

### Without an agent

```bash
S=skills/local-inference-optimisation/scripts/airbench_quick.py
python3 $S register --name my-rig --source readme
python3 $S start --setup setup.json --out run/
# give run/instructions.md to your harness, running the local model
python3 $S score --out run/ --wait
```

Standard-library Python only. The test key lives in `~/.config/airbench/test-key`
(mode 600) and is never printed.

The full API guide, as plain text: https://airbench.ai/agents

## License

MIT
