# agents/rag_knowledge/agent.py

import os
import json
from dotenv import load_dotenv
from pathlib import Path
from langchain_groq import ChatGroq
from mcp_servers.mcp_client import call_mcp_tool_sync

load_dotenv(Path(__file__).parent.parent.parent / '.env')

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

# This agent no longer loads SentenceTransformer or talks to Qdrant
# directly. Both the embedding model and the Qdrant client now live
# inside the Vector Search MCP server (mcp_servers/vector_search_mcp.py)
# — this agent process is lighter as a result, and the embedding model
# only has to be loaded once, in one place, instead of once per agent
# that happens to need it.
MCP_VECTOR_SEARCH_URL = os.getenv("MCP_VECTOR_SEARCH_URL", "http://localhost:8011")

def ingest_document(text: str, source: str, metadata: dict = {}) -> dict:
    print(f"[RAG Agent] Ingesting document from: {source}")
    raw = call_mcp_tool_sync(
        MCP_VECTOR_SEARCH_URL,
        "ingest_document",
        {"text": text, "source": source, "metadata": metadata}
    )
    result = json.loads(raw)
    if result.get("status") == "success":
        print(f"[RAG Agent] Ingested {result.get('chunks_ingested', 0)} chunks from {source}")
    return result

def run_rag_research(query: str) -> dict:
    print(f"[RAG Agent] Searching knowledge base for: {query}")

    raw = call_mcp_tool_sync(
        MCP_VECTOR_SEARCH_URL,
        "vector_search",
        {"query": query, "top_k": 5}
    )
    data = json.loads(raw)
    results = data.get("results", [])

    if not results:
        return {
            "query": query,
            "synthesis": "No relevant documents found in the knowledge base.",
            "sources": [],
            "chunks_used": 0
        }

    context_parts = []
    sources = []
    for r in results:
        context_parts.append(
            f"[Source: {r.get('source', '')} | Score: {r.get('score', 0)}]\n"
            f"{r.get('text', '')}"
        )
        src = r.get("source", "")
        if src not in sources:
            sources.append(src)
    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""You are a research analyst with access to a curated knowledge base.

Based ONLY on the following retrieved document chunks, answer the query.
Do not use outside knowledge — only what is in the retrieved context.
If the context does not contain enough information, say so clearly.

Query: {query}

Retrieved Context:
{context}

Provide:
1. Direct answer to the query
2. Supporting evidence from the retrieved chunks
3. Any gaps or limitations in the available knowledge"""

    response = llm.invoke(prompt)
    return {
        "query": query,
        "synthesis": response.content,
        "sources": sources,
        "chunks_used": len(results)
    }
