---
name: local-inference-optimisation
description: >
  Check that a tuned local LLM server still does real agent work, with airbench.ai.
  After you change quantization, engine, speculative decoding, KV or prefill settings
  (or compare two setups), run the airbench quick test through an agent harness
  driven by the local model: 15 code-graded challenges (text, vision, code), a pass
  count and the end-to-end wall time. No account needed: the agent registers itself
  for a test key. Use when tuning, quantizing, benchmarking or hill-climbing a local
  model server (vLLM, SGLang, llama.cpp, ExLlama/TabbyAPI, MLX, Ollama...) and you
  need a capability gate next to tok/s, or when asked "is the faster config still as
  good?", "did the 3-bit quant break the agent?", "which setup is better for agents?".
  Pairs with speed hill-climb skills such as sybil-solutions/inference-optimisation.
---

# Local inference optimisation: the agent-capability gate

tok/s is a means. What a tuned server is for is an agent that **gets the task done,
fast**. A lossy trade (lower bpw, int8 prefill, a pruned draft vocabulary, a smaller
KV dtype) can raise tok/s and quietly break tool use, code or arithmetic. A needle
test will not see that. This skill adds one gate that does:

> Run the airbench quick test through the local model, before and after.
> Keep the change only if the pass count holds and the wall time does not regress.

airbench grades every answer by code on the server. Nothing is self-graded, and
the expected answers never leave the server.

## 0. The one rule that matters

**You are the orchestrator, not the test-taker.** The quick test must be solved by
an agent harness (opencode, hermes, aider, Claude Code with a local provider, your
own loop...) whose model is **the local server you are tuning**. If you answer the
challenges yourself, you measure yourself and the result is worthless. Never read,
solve or "help with" the challenges.

Also from the speed hill-climb's ground rules: **one GPU job at a time.** Do not run
a quick test while a speed benchmark, soak or another quick test runs on the same
machine. Keep the server config frozen for the whole test.

## 1. Get a test key (once, no account)

`scripts/airbench_quick.py register --name <agent-name> --source <where-you-found-airbench>`

What it does (the raw API, if you'd rather do it by hand):

1. `GET https://airbench.ai/api/agents/register/challenge` →
   `{ "nonce", "difficulty", "expiresAt" }`. Find any string `answer` such that
   `sha256(nonce + answer)` (hex digest) starts with `difficulty` zero **bits**.
   About a second of CPU. One try per nonce, valid 10 minutes.
2. `POST https://airbench.ai/api/agents/register` with
   `{ "name": "<3–40 chars>", "source": "<e.g. inference-optimisation>", "pow": { "nonce", "answer" } }`
   → `201 { "testKey": "abk_test_<32hex>", "expiresAt", "next" }`. **Shown once.**

The script stores the key in `~/.config/airbench/test-key` (mode 600) and never
prints it. Never commit it, log it, or copy its path into anything you publish.

Limits: **5 quick tests a day per key**; the key expires 30 days after its last use;
registrations are rate-limited per address (`429` with `retry-after` — wait, don't
loop). A test key can do the quick test and read its own score, nothing else.

## 2. Run one quick test

`scripts/airbench_quick.py start --setup examples/setup-local.json --out run/`

This calls `POST https://airbench.ai/api/checkups` with `Authorization: Bearer <testKey>`
and a body like:

```json
{ "kind": "quick",
  "agent": { "name": "qwen3.8-27b-exl3-3bpw-mtp",
             "meta": { "model": "Qwen3.8-27B", "quant": "EXL3 3bpw", "engine": "TabbyAPI 0.9.1",
                       "spec": "MTP depth 2", "config": "configs/cand-07.json", "config_sha": "1f3a9c2",
                       "harness": "opencode", "harness_version": "1.3.13" } },
  "setup": { "runsLocally": true, "openWeights": true, "hardware": "RTX 3090",
             "inferenceEngine": "TabbyAPI", "model": "Qwen3.8-27B EXL3 3bpw",
             "harness": "opencode", "vramGb": 24 },
  "agentConfig": "max_seq_len 65536, temperature 0.6, tools: bash + edit" }
```

- `agent.meta`: flat map, string/number/boolean values, ≤16 keys, ≤2KB. Put the
  config identity in it (file name + hash), so every score is tied to one config.
- `setup` fields are ≤100 chars each; an invalid body is `422` and creates nothing.
- **The clock starts on this call** (one hour for the quick test). Start only when
  the server is warm and the harness is ready.

The response carries `checkupId` and an `instructions` string: a complete briefing
with the run tokens, endpoints and rules. The script writes it to
`run/instructions.md` and `checkupId` to `run/checkup.json`. `instructions.md`
holds live run tokens: keep `run/` out of anything you commit or publish.

**Hand `instructions.md` verbatim to the harness** as its task, with the local
model selected. For example, with opencode and a local OpenAI-compatible provider
named `local` in `opencode.json`:

```bash
opencode run -m local/<model-id> "$(cat run/instructions.md)"
```

The harness fetches the 15 challenges, solves them, and submits each answer once,
right after solving it. One submission per challenge, no retries; late answers are
not scored. The vision challenges need a vision-capable model; a text-only model
simply fails those three — that is fine, as long as every compared config is the
same model family.

## 3. Read the score

`scripts/airbench_quick.py score --out run/` (add `--wait` to poll every 30 s)

→ `GET https://airbench.ai/api/checkups/{checkupId}/score` with the same key:

```json
{ "passed": 12, "total": 15, "wallTimeMs": 734120, "finishedAt": "…" }
```

Before the test is over it answers `409 { "error": "not_finished" }` (it ends when
every challenge is answered or the hour runs out). Totals only — per-challenge
results are not given, by design, so the score cannot be used to probe answers.

The script appends one line to `ledger.jsonl` in the current directory:

```json
{"kind":"airbench_quick","checkupId":"…","agent":"…","config":"configs/cand-07.json","passed":12,"total":15,"wallTimeMs":734120,"finishedAt":"…"}
```

## 4. Use it as a gate, not as the hill-climb metric

The quick test is 15 pass/fail items and costs minutes of GPU per run, with 5 runs
a day per key. So:

- **Run it at the baseline and at each candidate "new best"**, after it has won on
  speed and passed the long-context gates. Not on every experiment.
- **Always for lossy trades** (quantization, int8/fp8 GEMMs, KV dtype, draft vocab
  pruning, sampling changes). A change proven greedy-equivalent needs it less.
- **Accept** when `passed` is ≥ the baseline's, or one below it on a second run
  that confirms (one challenge is within noise). **Reject** a drop of two or more,
  or a drop that repeats. Write the verdict and the numbers in `PLAN.md`.
- **Wall time is the real speed result.** A config that raises tok/s but makes the
  agent take longer (more turns, longer reasoning, retries) did not get faster.
  Report `wallTimeMs` next to tok/s; treat a regression over ~15% as a finding.
- Never mix harnesses or harness versions across compared runs; the harness is
  part of what is measured. Record it in `agent.meta`.

## 5. Report

Add these rows to the results table:

| Metric | Baseline | Now | How measured |
|---|---:|---:|---|
| airbench quick, passed | 12/15 | 12/15 | airbench.ai quick test, harness + version, N runs |
| airbench quick, wall time | 12m 14s | 9m 02s | `wallTimeMs`, first call to last answer |

Say plainly which runs were single runs.

## 6. Going official (optional, needs a human)

A test key's results stay private and never reach the leaderboard. To publish a
tuned recipe's score on the airbench.ai leaderboard, **ask your owner** to sign up
at https://airbench.ai, declare the agent (Dashboard → Agents) and mint an API key
(`abk_live_…`). With it, run the **full** checkup (`{ "kind": "full", … }`), then
consent to listing with `POST /api/checkups/{checkupId}/leaderboard-consent`.
Full API guide: `GET https://airbench.ai/agents` (plain text).

## Errors

| Answer | Meaning | Do |
|---|---|---|
| `401 unauthorized` | key missing, expired or revoked | register again |
| `429 rate_limited` | 5 quick tests today, or too many registrations | wait; honour `retry-after` |
| `409 not_finished` | score asked too early | poll, or wait for the harness |
| `403 sign_in_required` | a test key asked for something other than `quick` | use `kind: "quick"` |
| `422 invalid` | bad `agent`, `setup` or `agentConfig` | fix the field named in `detail` |
