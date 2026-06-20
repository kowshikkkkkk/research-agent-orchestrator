# agents/report_synthesis/agent.py

import os
from dotenv import load_dotenv
from pathlib import Path
from langchain_groq import ChatGroq

load_dotenv(Path(__file__).parent.parent.parent / '.env')

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

def run_report_synthesis(
    query: str,
    web_results: str,
    rag_results: str,
    market_data: str,
    critique: str = "",
    retry_count: int = 0
) -> dict:
    """
    Synthesizes all agent outputs into a structured report.
    As an independent service it can use a different model
    than the research agents — separation of concerns.
    On retries it receives the Critic's feedback and
    specifically addresses the identified gaps.
    """
    print(f"[Report Synthesis Agent] Synthesizing report (attempt {retry_count + 1})")

    critique_context = ""
    if critique and retry_count > 0:
        critique_context = f"""
IMPORTANT: Previous version was rejected by quality review.
Critic feedback:
{critique}

You must specifically address these issues in this version.
"""

    prompt = f"""You are a senior business intelligence analyst producing a professional research report.
{critique_context}
Query: {query}

RESEARCH INPUTS:

Web Research (real-time data):
{web_results}

Knowledge Base (curated documents):
{rag_results}

Market Data (quantitative):
{market_data}

Write a comprehensive, well-structured report with these exact sections:

## Executive Summary
2-3 sentences summarizing the key answer to the query.

## Key Findings
5-7 specific bullet points with named companies, statistics, and data points.
Every bullet must be specific — no vague statements.

## Market Analysis
3-4 paragraphs covering market size, key players, competitive dynamics,
and growth drivers. Include specific numbers wherever available.

## Competitive Landscape
Named competitors with their positioning, strengths, and market focus.

## Conclusion
2-3 sentences on outlook and implications.

Requirements:
- Include specific company names, funding amounts, market sizes
- Cite which source (web research, knowledge base, or market data) each finding comes from
- No vague statements like "significant growth" without a number attached"""

    response = llm.invoke(prompt)

    return {
        "query": query,
        "report": response.content,
        "synthesis_attempt": retry_count + 1
    }