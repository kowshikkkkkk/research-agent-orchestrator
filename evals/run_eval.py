# evals/run_eval.py
#
# End-to-end eval harness. Runs every query in golden_queries.json through
# the REAL orchestrator graph (the exact same build_graph() used in
# production, orchestrator/orchestrator.py) — not a mock, not a shortcut.
# Each query gets its own thread_id so runs never share Redis checkpoint
# state. Requires all 4 agents, both MCP servers, Redis, and Qdrant to be
# running (e.g. via `docker compose up`).
#
# This is a REGRESSION HARNESS, not a rigorous benchmark: the 8 golden
# queries are hand-authored, not sampled from real usage, so a good score
# here means "didn't regress against our own fixed checkpoints" — not
# "proven good at research in general." Treat it as pytest for prompts.
#
# Usage:
#   python -m evals.run_eval
#   python -m evals.run_eval --limit 3        # quick smoke test on first 3 queries
#   python -m evals.run_eval --query q1_fintech  # run a single query by id
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / '.env')
import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langgraph.checkpoint.redis import RedisSaver

from orchestrator.orchestrator import build_graph, REDIS_URL
from evals.metrics import run_deterministic_checks
from evals.judge import judge_report

GOLDEN_QUERIES_PATH = Path(__file__).parent / "golden_queries.json"
RESULTS_DIR = Path(__file__).parent / "results"

PASS_THRESHOLDS = {
    "min_section_completeness": 1.0,
    "min_judge_composite": 0.6,
    "min_keyword_coverage": 0.5,
}


def load_golden_queries(limit: int | None = None, query_id: str | None = None) -> list[dict]:
    queries = json.loads(GOLDEN_QUERIES_PATH.read_text())
    if query_id:
        queries = [q for q in queries if q["id"] == query_id]
        if not queries:
            raise ValueError(f"No golden query with id '{query_id}'")
    if limit:
        queries = queries[:limit]
    return queries


def run_single_query(graph, golden_query: dict) -> dict:
    query_id = golden_query["id"]
    query_text = golden_query["query"]
    expected_keywords = golden_query.get("expected_keywords", [])

    print(f"\n{'='*70}\nRunning: {query_id} — {query_text}\n{'='*70}")

    thread_id = f"eval-{query_id}-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    start = time.time()
    try:
        state = graph.invoke({
            "query": query_text,
            "web_results": "",
            "rag_results": "",
            "market_data": "",
            "report": "",
            "critique": "",
            "quality_score": 0.0,
            "retry_count": 0,
            "final_output": "",
        }, config)
        elapsed_ms = round((time.time() - start) * 1000, 2)
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "id": query_id,
            "category": golden_query.get("category"),
            "query": query_text,
            "status": "pipeline_error",
            "error": str(e),
            "execution_time_ms": elapsed_ms,
        }

    report = state.get("final_output", "")
    orchestrator_score = state.get("quality_score", 0.0)
    retry_count = state.get("retry_count", 0)

    deterministic = run_deterministic_checks(report, expected_keywords)
    judge_scores = judge_report(query_text, report)

    passed = (
        deterministic["section_completeness"]["completeness_ratio"] >= PASS_THRESHOLDS["min_section_completeness"]
        and judge_scores["composite_score"] >= PASS_THRESHOLDS["min_judge_composite"]
        and deterministic["keyword_coverage"]["keyword_coverage_ratio"] >= PASS_THRESHOLDS["min_keyword_coverage"]
    )

    return {
        "id": query_id,
        "category": golden_query.get("category"),
        "query": query_text,
        "status": "passed" if passed else "failed",
        "orchestrator_quality_score": orchestrator_score,
        "orchestrator_retry_count": retry_count,
        "execution_time_ms": elapsed_ms,
        "deterministic_checks": deterministic,
        "judge_scores": judge_scores,
        "report_preview": report[:300],
    }


def summarize(results: list[dict]) -> dict:
    valid = [r for r in results if r["status"] != "pipeline_error"]
    passed = [r for r in valid if r["status"] == "passed"]

    def avg(key_path):
        vals = []
        for r in valid:
            d = r
            for k in key_path:
                d = d.get(k, {}) if isinstance(d, dict) else {}
            if isinstance(d, (int, float)):
                vals.append(d)
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "total_queries": len(results),
        "pipeline_errors": len(results) - len(valid),
        "passed": len(passed),
        "failed": len(valid) - len(passed),
        "pass_rate": round(len(passed) / len(valid), 3) if valid else 0.0,
        "avg_orchestrator_quality_score": avg(["orchestrator_quality_score"]),
        "avg_judge_composite_score": avg(["judge_scores", "composite_score"]),
        "avg_section_completeness": avg(["deterministic_checks", "section_completeness", "completeness_ratio"]),
        "avg_execution_time_ms": avg(["execution_time_ms"]),
        "avg_retry_count": avg(["orchestrator_retry_count"]),
    }


def print_summary_table(results: list[dict], summary: dict):
    print(f"\n{'='*70}\nEVAL SUMMARY\n{'='*70}")
    print(f"{'ID':<20} {'Status':<10} {'OrchScore':<10} {'JudgeScore':<11} {'Sections':<9} {'Retries':<8} {'Time(ms)'}")
    for r in results:
        if r["status"] == "pipeline_error":
            print(f"{r['id']:<20} {'ERROR':<10} {'-':<10} {'-':<11} {'-':<9} {'-':<8} {r['execution_time_ms']}")
            continue
        oscore = r["orchestrator_quality_score"]
        jscore = r["judge_scores"]["composite_score"]
        sections = r["deterministic_checks"]["section_completeness"]["completeness_ratio"]
        print(f"{r['id']:<20} {r['status']:<10} {oscore:<10} {jscore:<11} {sections:<9} {r['orchestrator_retry_count']:<8} {r['execution_time_ms']}")

    print(f"\n{'-'*70}")
    for k, v in summary.items():
        print(f"{k:<32}: {v}")
    print(f"{'-'*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Run the research-agent-orchestrator eval harness")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N golden queries")
    parser.add_argument("--query", type=str, default=None, help="Run a single golden query by id")
    args = parser.parse_args()

    golden_queries = load_golden_queries(limit=args.limit, query_id=args.query)
    print(f"Loaded {len(golden_queries)} golden queries.")

    RESULTS_DIR.mkdir(exist_ok=True)

    with RedisSaver.from_conn_string(REDIS_URL) as checkpointer:
        checkpointer.setup()
        graph = build_graph().compile(checkpointer=checkpointer)

        results = [run_single_query(graph, gq) for gq in golden_queries]

    summary = summarize(results)
    print_summary_table(results, summary)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = RESULTS_DIR / f"eval_run_{timestamp}.json"
    output_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(f"Full results written to: {output_path}")


if __name__ == "__main__":
    main()
