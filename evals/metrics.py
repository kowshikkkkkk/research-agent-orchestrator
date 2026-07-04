# evals/metrics.py
#
# Deterministic (non-LLM) checks against a final report. These are cheap,
# instant, and 100% reproducible — they catch structural regressions
# (missing sections, empty reports, no numbers at all) without spending
# a single token. The LLM judge (judge.py) handles the fuzzier questions
# these checks can't answer, like "is this actually grounded."

import re

REQUIRED_SECTIONS = [
    "Executive Summary",
    "Key Findings",
    "Market Analysis",
    "Competitive Landscape",
    "Conclusion",
]

# Matches things like: $4.2B, 38%, 12,000 users, 3.5x, 2024
NUMERIC_PATTERN = re.compile(
    r"(\$\s?\d[\d,\.]*\s?[BMK]?\b)"      # currency amounts: $4.2B, $500M
    r"|(\b\d[\d,\.]*\s?%)"                # percentages: 38%, 12.5%
    r"|(\b\d[\d,\.]*\s?(?:x|X)\b)"        # multipliers: 3.5x
    r"|(\b\d{2,}(?:,\d{3})*\b)"           # bare large numbers: 12,000
)

VAGUE_PHRASES = [
    "significant growth",
    "rapidly growing",
    "many companies",
    "various players",
    "several factors",
    "a number of",
]


def check_section_completeness(report: str) -> dict:
    found = [s for s in REQUIRED_SECTIONS if f"## {s}" in report]
    missing = [s for s in REQUIRED_SECTIONS if s not in found]
    return {
        "sections_found": found,
        "sections_missing": missing,
        "completeness_ratio": round(len(found) / len(REQUIRED_SECTIONS), 2),
    }


def check_quantitative_density(report: str) -> dict:
    words = report.split()
    word_count = len(words)
    matches = NUMERIC_PATTERN.findall(report)
    numeric_count = sum(1 for m in matches if any(m))
    density_per_100_words = round((numeric_count / word_count) * 100, 2) if word_count else 0.0
    return {
        "word_count": word_count,
        "numeric_mentions": numeric_count,
        "density_per_100_words": density_per_100_words,
    }


def check_vague_language(report: str) -> dict:
    lowered = report.lower()
    hits = [p for p in VAGUE_PHRASES if p in lowered]
    return {
        "vague_phrases_found": hits,
        "vague_phrase_count": len(hits),
    }


def check_keyword_coverage(report: str, expected_keywords: list[str]) -> dict:
    lowered = report.lower()
    found = [k for k in expected_keywords if k.lower() in lowered]
    return {
        "keywords_found": found,
        "keyword_coverage_ratio": round(len(found) / len(expected_keywords), 2) if expected_keywords else 1.0,
    }


def check_minimum_length(report: str, min_words: int = 250) -> dict:
    word_count = len(report.split())
    return {
        "word_count": word_count,
        "meets_minimum_length": word_count >= min_words,
    }


def run_deterministic_checks(report: str, expected_keywords: list[str]) -> dict:
    """Runs every check above and bundles the results into one dict."""
    return {
        "section_completeness": check_section_completeness(report),
        "quantitative_density": check_quantitative_density(report),
        "vague_language": check_vague_language(report),
        "keyword_coverage": check_keyword_coverage(report, expected_keywords),
        "minimum_length": check_minimum_length(report),
    }
