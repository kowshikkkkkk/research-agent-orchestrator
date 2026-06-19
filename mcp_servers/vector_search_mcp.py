import os
import sys
import json
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

load_dotenv(Path(__file__).parent.parent / '.env')

app = Server("vector-search-mcp-server")

COLLECTION_NAME = "research_knowledge_base"
VECTOR_SIZE = 384

# Lazy globals — not loaded at import time
embedder = None
qdrant = None

def get_embedder():
    global embedder
    if embedder is None:
        print("[Vector MCP] Loading embedding model...", file=sys.stderr)
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer("all-MiniLM-L6-v2")
        print("[Vector MCP] Model loaded.", file=sys.stderr)
    return embedder

def get_qdrant():
    global qdrant
    if qdrant is None:
        qdrant = QdrantClient(host="localhost", port=6333)
        collections = [c.name for c in qdrant.get_collections().collections]
        if COLLECTION_NAME not in collections:
            from qdrant_client.models import Distance, VectorParams
            qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
            )
            print(f"[Vector MCP] Created collection: {COLLECTION_NAME}", file=sys.stderr)
        else:
            print(f"[Vector MCP] Collection exists: {COLLECTION_NAME}", file=sys.stderr)
    return qdrant

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="vector_search",
            description="Search the knowledge base for relevant document chunks using semantic similarity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "top_k": {"type": "integer", "description": "Number of results to return (default: 5)", "default": 5}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="ingest_document",
            description="Ingest a text document into the knowledge base by chunking and embedding it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The document text to ingest"},
                    "source": {"type": "string", "description": "Source identifier for the document"},
                    "metadata": {"type": "object", "description": "Optional metadata to store with the document"}
                },
                "required": ["text", "source"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    if name == "vector_search":
        query = arguments.get("query", "")
        top_k = arguments.get("top_k", 5)
        print(f"[Vector MCP] Searching for: {query}", file=sys.stderr)

        emb = get_embedder()
        db = get_qdrant()
        query_vector = emb.encode(query).tolist()
        results = db.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True
        )

        if not results:
            return [types.TextContent(type="text", text=json.dumps({
                "results": [], "message": "No relevant documents found in knowledge base"
            }))]

        formatted = []
        for r in results:
            formatted.append({
                "text": r.payload.get("text", ""),
                "source": r.payload.get("source", ""),
                "score": round(r.score, 4),
                "metadata": r.payload.get("metadata", {})
            })

        return [types.TextContent(type="text", text=json.dumps({
            "results": formatted, "result_count": len(formatted)
        }))]

    elif name == "ingest_document":
        text = arguments.get("text", "")
        source = arguments.get("source", "unknown")
        metadata = arguments.get("metadata", {})
        print(f"[Vector MCP] Ingesting document from: {source}", file=sys.stderr)

        emb = get_embedder()
        db = get_qdrant()

        chunk_size = 500
        overlap = 50
        chunks = []
        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if len(chunk) > 100:
                chunks.append(chunk)

        if not chunks:
            return [types.TextContent(type="text", text=json.dumps({"error": "Document too short to ingest"}))]

        vectors = emb.encode(chunks).tolist()
        collection_info = db.get_collection(COLLECTION_NAME)
        current_count = collection_info.points_count or 0

        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            points.append(PointStruct(
                id=current_count + i + 1,
                vector=vector,
                payload={"text": chunk, "source": source, "chunk_index": i, "metadata": metadata}
            ))

        db.upsert(collection_name=COLLECTION_NAME, points=points)

        return [types.TextContent(type="text", text=json.dumps({
            "status": "success", "chunks_ingested": len(chunks), "source": source
        }))]

    else:
        return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

async def main():
    print("[Vector MCP] Server starting...", file=sys.stderr)
    print("[Vector MCP] Tools registered: vector_search, ingest_document", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())