# agents/web_research/agent.py

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

def run_web_research(query: str) -> dict:
    print(f"[Web Research Agent] Searching for: {query}")

    search_response = tavily.search(
        query=query,
        max_results=5,
        search_depth="advanced"
    )

    results = search_response.get("results", [])
    sources = [r.get("url", "") for r in results]
    raw_content = "\n\n".join([
        f"Source: {r.get('url', '')}\nContent: {r.get('content', '')}"
        for r in results
    ])

    prompt = f"""You are a web research specialist for business intelligence.

Based on the following web search results, provide a structured research summary.

Original Query: {query}

Search Results:
{raw_content}

Provide:
1. Key findings from the web (bullet points)
2. Recent developments or news
3. Notable companies or players mentioned
4. Data points or statistics found

Be specific and cite which source each finding comes from."""

    response = llm.invoke(prompt)

    return {
        "query": query,
        "synthesis": response.content,
        "sources": sources,
        "raw_results_count": len(results)
    }
