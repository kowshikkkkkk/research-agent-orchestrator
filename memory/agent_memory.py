import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

MEMORY_COLLECTION_NAME = "agent_memory"
VECTOR_SIZE = 384  # matches all-MiniLM-L6-v2's output dimension
TOP_K_MEMORIES = 3

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

_embedder = None
_qdrant = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def get_qdrant():
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        _ensure_memory_collection(_qdrant)
    return _qdrant


def _ensure_memory_collection(client: QdrantClient):
    collections = [c.name for c in client.get_collections().collections]
    if MEMORY_COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=MEMORY_COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )

def store_memory(user_id: str, query: str, report: str, thread_id: str) -> None:
    """Stores a compact, embeddable summary of a completed research session,
    scoped to one user. We embed just the query + a short excerpt of the
    report (not the full text) so the vector captures the session's core
    topic rather than an averaged-out blend of every section."""
    embedder = get_embedder()
    qdrant = get_qdrant()

    summary_text = f"{query}\n\n{report[:500]}"
    vector = embedder.encode(summary_text).tolist()

    collection_info = qdrant.get_collection(MEMORY_COLLECTION_NAME)
    point_id = (collection_info.points_count or 0) + 1

    qdrant.upsert(
        collection_name=MEMORY_COLLECTION_NAME,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "user_id": user_id,
                    "query": query,
                    "report": report,
                    "thread_id": thread_id,
                }
            )
        ]
    )

def retrieve_relevant_memories(user_id: str, query: str) -> list[dict]:
    """Searches this user's past research sessions for anything semantically
    similar to the new query. Returns an empty list if nothing relevant is
    found, or if this is the user's first-ever query (collection empty)."""
    embedder = get_embedder()
    qdrant = get_qdrant()

    query_vector = embedder.encode(query).tolist()

    results = qdrant.query_points(
        collection_name=MEMORY_COLLECTION_NAME,
        query=query_vector,
        query_filter=Filter(
            must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
        ),
        limit=TOP_K_MEMORIES,
        with_payload=True
    ).points

    return [
        {
            "query": r.payload.get("query", ""),
            "report": r.payload.get("report", ""),
            "score": r.score,
        }
        for r in results
    ]