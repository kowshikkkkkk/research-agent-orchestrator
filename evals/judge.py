# evals/judge.py
#
# Independent LLM-as-judge, deliberately separate from the orchestrator's
# own Critic node (orchestrator/orchestrator.py::critic_node). Reusing the
# Critic here would just measure "does the Critic agree with itself" — not
# a real quality signal. This judge uses a different, more specific rubric
# and asks for strict JSON output so scores are easy to aggregate.

import os
import json
import re
from dotenv import load_dotenv
from pathlib import Path
from langchain_groq import ChatGroq

load_dotenv(Path(__file__).parent.parent / '.env')

judge_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.0  # deterministic scoring, not creative
)

JUDGE_PROMPT_TEMPLATE = """You are an independent quality auditor reviewing a business research report.
You are NOT the author or the original reviewer — score this strictly and skeptically.

Original Query: {query}

Report to audit:
{report}

Score the report on these three dimensions, each from 0.0 to 1.0:

1. groundedness: Are claims backed by specific, checkable details (named companies,
   dollar figures, percentages, dates) rather than assertions with nothing behind them?

2. coverage: Does the report actually answer what was asked, comprehensively,
   rather than drifting into adjacent or generic territory?

3. genericness_penalty: How much of the report is filler that could be pasted into
   any report on any topic (e.g. "the market is growing", "many players compete")
   without changing a word? 1.0 = no filler at all, 0.0 = mostly filler.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"groundedness": 0.0, "coverage": 0.0, "genericness_penalty": 0.0, "rationale": "one sentence"}}"""


def _extract_json(text: str) -> dict:
    """
    Models occasionally wrap JSON in markdown fences or add a stray
    sentence despite instructions. Try a direct parse first, then fall
    back to extracting the first {...} block before giving up.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {
        "groundedness": 0.0,
        "coverage": 0.0,
        "genericness_penalty": 0.0,
        "rationale": f"JUDGE_PARSE_FAILURE: could not parse model output: {text[:200]}",
    }


def judge_report(query: str, report: str) -> dict:
    prompt = JUDGE_PROMPT_TEMPLATE.format(query=query, report=report)
    response = judge_llm.invoke(prompt)
    scores = _extract_json(response.content)

    for key in ("groundedness", "coverage", "genericness_penalty"):
        scores[key] = float(scores.get(key, 0.0))

    scores["composite_score"] = round(
        (scores["groundedness"] + scores["coverage"] + scores["genericness_penalty"]) / 3, 3
    )
    return scores
