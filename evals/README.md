# Eval Harness

A **regression harness**, not a rigorous benchmark. It runs a fixed set
of 8 hand-authored queries through the real pipeline (the actual
`build_graph()` from `orchestrator/orchestrator.py`) and scores the
output two independent ways, so prompt changes can be checked against
a before/after baseline instead of eyeballed.

## Scope, honestly

The 8 golden queries are hand-written, not sampled from real usage —
there's no production traffic yet to sample from. That means a good
score here proves "didn't regress against our own fixed checkpoints,"
not "proven good at research in general." Think of it as pytest for
prompts: useful for catching breakage, not a claim about real-world
quality across arbitrary user queries.

## Why not just reuse the orchestrator's own Critic score?

`orchestrator/orchestrator.py::critic_node` already scores every report
at runtime and can trigger a retry — but it's a single, self-referential
opinion (same pipeline, same author, scoring its own output, one report
at a time, no memory of past runs). Reusing it here would just measure
"does the Critic agree with itself." `judge.py` is a separate rubric
(groundedness / coverage / genericness) run independently, so the two
scores can be compared — and sometimes disagree, which is itself a
useful signal.

## What gets checked

1. **Deterministic checks** (`metrics.py`) — free, instant, no LLM:
   section completeness, quantitative density, vague-language detection,
   keyword coverage, minimum length.
2. **Independent LLM judge** (`judge.py`) — groundedness, coverage,
   genericness, each 0.0–1.0.
3. **Orchestrator's own signals**, reported alongside for comparison —
   `quality_score` and `retry_count` from the live Critic node.

## Requirements

The full stack must be running (this hits real services, not mocks):
```bash
docker compose up
```

## Running it

```bash
python -m evals.run_eval                    # full golden set
python -m evals.run_eval --limit 3           # smoke test, first 3 queries
python -m evals.run_eval --query q1_fintech  # single query by id
```

Results print as a table and get written to
`evals/results/eval_run_<timestamp>.json`.

## Pass criteria

All three, or it fails:
- All 5 report sections present
- Independent judge composite score >= 0.6
- Keyword coverage >= 0.5

Thresholds are in `PASS_THRESHOLDS` at the top of `run_eval.py` —
starting points to calibrate once you have a baseline run, not settled
science.

## Extending the golden set

Add to `golden_queries.json`:
```json
{
  "id": "unique_id",
  "category": "short_label",
  "query": "the actual research question",
  "expected_keywords": ["topic1", "topic2"]
}
```
