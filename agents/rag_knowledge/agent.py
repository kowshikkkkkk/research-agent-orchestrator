# agents/rag_knowledge/agent.py

import os
from dotenv import load_dotenv
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from langchain_groq import ChatGroq

load_dotenv(Path(__file__).parent.parent.parent / '.env')

print("[RAG Agent] Loading embedding model...")
embedder = SentenceTransformer("all-MiniLM-L6-v2")
qdrant = QdrantClient(host="localhost", port=6333)
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

COLLECTION_NAME = "research_knowledge_base"
VECTOR_SIZE = 384

def ensure_collection_exists():
    collections = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE
            )
        )
        print(f"[RAG Agent] Created collection: {COLLECTION_NAME}")
    else:
        print(f"[RAG Agent] Collection exists: {COLLECTION_NAME}")

ensure_collection_exists()

def ingest_document(text: str, source: str, metadata: dict = {}) -> dict:
    print(f"[RAG Agent] Ingesting document from: {source}")
    chunk_size = 500
    overlap = 50
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunk = text[i:i + chunk_size]
        if len(chunk) > 100:
            chunks.append(chunk)
    if not chunks:
        return {"error": "Document too short to ingest"}
    vectors = embedder.encode(chunks).tolist()
    collection_info = qdrant.get_collection(COLLECTION_NAME)
    current_count = collection_info.points_count or 0
    points = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        points.append(PointStruct(
            id=current_count + i + 1,
            vector=vector,
            payload={
                "text": chunk,
                "source": source,
                "chunk_index": i,
                "metadata": metadata
            }
        ))
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"[RAG Agent] Ingested {len(chunks)} chunks from {source}")
    return {
        "status": "success",
        "chunks_ingested": len(chunks),
        "source": source
    }

def run_rag_research(query: str) -> dict:
    print(f"[RAG Agent] Searching knowledge base for: {query}")
    query_vector = embedder.encode(query).tolist()

    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=5,
        with_payload=True
    ).points

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
            f"[Source: {r.payload.get('source', '')} | Score: {round(r.score, 4)}]\n"
            f"{r.payload.get('text', '')}"
        )
        src = r.payload.get("source", "")
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
