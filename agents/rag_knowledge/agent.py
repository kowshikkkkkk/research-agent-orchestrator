# agents/rag_knowledge/agent.py
#
# Direct RAG implementation — no MCP layer. This agent owns the embedding
# model and the Qdrant client itself. Three stages, matching the standard
# RAG pipeline (Indexing -> Retrieval -> Generation):
#
#   INDEXING (runs once per document, triggered by ingest_document):
#     document -> chunk -> embed -> store in Qdrant
#
#   RETRIEVAL (runs on every query, triggered by run_rag_research):
#     query -> embed -> cosine similarity search in Qdrant -> top-k chunks
#
#   GENERATION (runs on every query, immediately after retrieval):
#     top-k chunks + query -> LLM prompt -> grounded, cited answer

import os
from dotenv import load_dotenv
from pathlib import Path
from langchain_groq import ChatGroq
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

load_dotenv(Path(__file__).parent.parent.parent / '.env')

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

# ── CONFIG ──────────────────────────────────────────────────────────────────
COLLECTION_NAME = "research_knowledge_base"
VECTOR_SIZE = 384          # matches all-MiniLM-L6-v2's output dimension
CHUNK_SIZE = 500           # characters per chunk
CHUNK_OVERLAP = 50         # overlap so sentences spanning chunk boundaries
                           # are still fully represented in at least one chunk
TOP_K = 5

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

# Lazy-loaded singletons. The embedding model (~90MB) and the Qdrant
# connection are both expensive to set up — load once on first use,
# not on every function call.
_embedder = None
_qdrant = None


def get_embedder():
    global _embedder
    if _embedder is None:
        print("[RAG Agent] Loading embedding model (all-MiniLM-L6-v2)...")
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        print("[RAG Agent] Embedding model loaded.")
    return _embedder


def get_qdrant():
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        ensure_collection_exists(_qdrant)
    return _qdrant


def ensure_collection_exists(client: QdrantClient):
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )
        print(f"[RAG Agent] Created collection: {COLLECTION_NAME}")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Fixed-size sliding-window chunking with overlap. Chunks under 100
    characters are dropped — a trailing 30-character fragment isn't
    useful as an independent retrieval unit.
    """
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(text), step):
        chunk = text[i:i + chunk_size]
        if len(chunk) > 100:
            chunks.append(chunk)
    return chunks


# ── INDEXING ──────────────────────────────────────────────────────────────────

def ingest_document(text: str, source: str, metadata: dict = {}) -> dict:
    print(f"[RAG Agent] Ingesting document from: {source}")

    chunks = chunk_text(text)
    if not chunks:
        return {"error": "Document too short to ingest", "status": "failed"}

    embedder = get_embedder()
    qdrant = get_qdrant()

    vectors = embedder.encode(chunks).tolist()

    collection_info = qdrant.get_collection(COLLECTION_NAME)
    current_count = collection_info.points_count or 0

    points = [
        PointStruct(
            id=current_count + i + 1,
            vector=vector,
            payload={"text": chunk, "source": source, "chunk_index": i, "metadata": metadata}
        )
        for i, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"[RAG Agent] Ingested {len(chunks)} chunks from {source}")

    return {"status": "success", "chunks_ingested": len(chunks), "source": source}


# ── RETRIEVAL + GENERATION ──────────────────────────────────────────────────

def run_rag_research(query: str) -> dict:
    print(f"[RAG Agent] Searching knowledge base for: {query}")

    embedder = get_embedder()
    qdrant = get_qdrant()

    query_vector = embedder.encode(query).tolist()
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=TOP_K,
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
