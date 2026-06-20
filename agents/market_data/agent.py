# agents/market_data/agent.py

import os
from dotenv import load_dotenv
from pathlib import Path
from tavily import TavilyClient
from langchain_groq import ChatGroq

load_dotenv(Path(__file__).parent.parent.parent / '.env')

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def run_market_data_research(query: str) -> dict:
    """
    Searches specifically for quantitative market data.
    Unlike the Web Research Agent which returns broad findings,
    this agent focuses on numbers — market size, growth rates,
    funding amounts, valuations, statistics.
    Structured numerical data is what makes reports credible.
    """
    print(f"[Market Data Agent] Fetching market data for: {query}")

    # We append "market size statistics data" to bias Tavily
    # toward quantitative sources like reports and filings
    market_query = f"{query} market size statistics growth rate funding data 2024"

    search_response = tavily.search(
        query=market_query,
        max_results=5,
        search_depth="advanced"
    )

    results = search_response.get("results", [])
    sources = [r.get("url", "") for r in results]
    raw_content = "\n\n".join([
        f"Source: {r.get('url', '')}\nContent: {r.get('content', '')}"
        for r in results
    ])

    prompt = f"""You are a market data specialist. Extract only quantitative data from the search results.

Original Query: {query}

Search Results:
{raw_content}

Extract and structure the following if available:
1. Market size figures (with currency and year)
2. Growth rates (CAGR, YoY percentages)
3. Funding amounts raised by companies
4. User/customer counts
5. Transaction volumes
6. Any other specific numerical data points

Format as clean bullet points with source citations.
If no quantitative data is found for a category, skip it.
Do not include vague statements — numbers only."""

    response = llm.invoke(prompt)

    return {
        "query": query,
        "market_data": response.content,
        "sources": sources,
        "data_points_found": len(results)
    }