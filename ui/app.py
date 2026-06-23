# ui/app.py

import os
import streamlit as st
import httpx
import time
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from orchestrator.orchestrator import build_graph
from langgraph.checkpoint.redis import RedisSaver

# ── URL CONFIGURATION ─────────────────────────────────────────────────────────
# Defaults to localhost for local development.
# In Docker Compose these are overridden via environment variables
# to use service names: http://web_research:8001 etc.

WEB_RESEARCH_URL = os.getenv("WEB_RESEARCH_URL", "http://localhost:8001")
RAG_KNOWLEDGE_URL = os.getenv("RAG_KNOWLEDGE_URL", "http://localhost:8002")
MARKET_DATA_URL = os.getenv("MARKET_DATA_URL", "http://localhost:8003")
REPORT_SYNTHESIS_URL = os.getenv("REPORT_SYNTHESIS_URL", "http://localhost:8004")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Enterprise Research Intelligence Platform",
    page_icon="🔬",
    layout="wide"
)

# ── HEADER ────────────────────────────────────────────────────────────────────

st.title("🔬 Enterprise Research Intelligence Platform")
st.markdown("*Multi-agent AI system powered by LangGraph, Groq, Qdrant, and A2A protocol*")
st.divider()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ System Status")

    # In Docker, check agents via internal service names
    # In local dev, use localhost
    health_agents = {
        "Web Research Agent": f"{WEB_RESEARCH_URL}/health",
        "RAG Knowledge Agent": f"{RAG_KNOWLEDGE_URL}/health",
        "Market Data Agent": f"{MARKET_DATA_URL}/health",
        "Report Synthesis Agent": f"{REPORT_SYNTHESIS_URL}/health",
    }

    for agent_name, health_url in health_agents.items():
        try:
            response = httpx.get(health_url, timeout=2.0)
            if response.status_code == 200:
                st.success(f"✅ {agent_name}")
            else:
                st.error(f"❌ {agent_name}")
        except:
            st.error(f"❌ {agent_name} (offline)")

    st.divider()
    st.header("📚 Knowledge Base")

    # ── TEXT INGEST ───────────────────────────────────────────────────────────
    st.subheader("Ingest Text")
    ingest_text = st.text_area(
        "Document text",
        height=100,
        placeholder="Paste document content here..."
    )
    ingest_source = st.text_input(
        "Source name",
        placeholder="e.g. company_report_2024"
    )

    if st.button("Ingest Document", type="secondary"):
        if ingest_text and ingest_source:
            with st.spinner("Ingesting..."):
                try:
                    response = httpx.post(
                        f"{RAG_KNOWLEDGE_URL}/tasks/send",
                        json={
                            "task_id": f"ingest-{int(time.time())}",
                            "input": {
                                "query": "ingest",
                                "ingest": {
                                    "text": ingest_text,
                                    "source": ingest_source,
                                    "metadata": {}
                                }
                            }
                        },
                        timeout=30.0
                    )
                    result = response.json()
                    if result["status"] == "completed":
                        st.success(f"✅ Ingested {result['output'].get('chunks_ingested', 0)} chunks")
                    else:
                        st.error(f"Failed: {result['output'].get('error', 'Unknown')}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
        else:
            st.warning("Please provide both text and source name")

    st.divider()

    # ── PDF INGEST ────────────────────────────────────────────────────────────
    st.subheader("Ingest PDF")
    uploaded_file = st.file_uploader("Upload PDF", type="pdf")

    if uploaded_file is not None:
        if st.button("Ingest PDF", type="secondary"):
            with st.spinner("Extracting and ingesting PDF..."):
                try:
                    import pypdf
                    reader = pypdf.PdfReader(uploaded_file)
                    full_text = ""
                    for page in reader.pages:
                        extracted = page.extract_text()
                        if extracted:
                            full_text += extracted + "\n"

                    if not full_text.strip():
                        st.error("Could not extract text from PDF")
                    else:
                        response = httpx.post(
                            f"{RAG_KNOWLEDGE_URL}/tasks/send",
                            json={
                                "task_id": f"ingest-pdf-{int(time.time())}",
                                "input": {
                                    "query": "ingest",
                                    "ingest": {
                                        "text": full_text,
                                        "source": uploaded_file.name.replace(".pdf", ""),
                                        "metadata": {"type": "pdf", "filename": uploaded_file.name}
                                    }
                                }
                            },
                            timeout=60.0
                        )
                        result = response.json()
                        if result["status"] == "completed":
                            st.success(f"✅ Ingested {result['output'].get('chunks_ingested', 0)} chunks from {uploaded_file.name}")
                        else:
                            st.error(f"Failed: {result['output'].get('error', 'Unknown')}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    st.divider()
    st.header("🔗 Architecture")
    st.markdown("""
    **Agents:**
    - 🌐 Web Research (Tavily)
    - 📚 RAG Knowledge (Qdrant)
    - 📊 Market Data
    - 📝 Report Synthesis
    - ⚖️ Critic (Quality Gate)

    **Infrastructure:**
    - LangGraph Orchestrator
    - Redis Session Memory
    - Guardrails AI Security
    - LangSmith Observability
    - A2A Protocol
    """)

# ── MAIN INTERFACE ────────────────────────────────────────────────────────────

col1, col2 = st.columns([2, 1])

with col1:
    query = st.text_input(
        "Research Query",
        placeholder="e.g. What is the competitive landscape for fintech lending in Southeast Asia?",
        help="Enter any business research question"
    )

with col2:
    session_id = st.text_input(
        "Session ID",
        value="research-session-001",
        help="Same session ID = Redis memory across queries"
    )

run_button = st.button("🚀 Run Research", type="primary", use_container_width=True)

# ── RESEARCH EXECUTION ────────────────────────────────────────────────────────

if run_button and query:

    progress_bar = st.progress(0)
    status_text = st.empty()

    st.subheader("🤖 Agent Pipeline")
    col_web, col_rag, col_market, col_synthesis, col_critic = st.columns(5)

    with col_web:
        web_status = st.empty()
        web_status.info("⏳ Web Research")
    with col_rag:
        rag_status = st.empty()
        rag_status.info("⏳ RAG Knowledge")
    with col_market:
        market_status = st.empty()
        market_status.info("⏳ Market Data")
    with col_synthesis:
        synthesis_status = st.empty()
        synthesis_status.info("⏳ Synthesis")
    with col_critic:
        critic_status = st.empty()
        critic_status.info("⏳ Critic")

    st.divider()

    try:
        with RedisSaver.from_conn_string(REDIS_URL) as checkpointer:
            checkpointer.setup()
            graph = build_graph().compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id}}

            initial_state = {
                "query": query,
                "web_results": "",
                "rag_results": "",
                "market_data": "",
                "report": "",
                "critique": "",
                "quality_score": 0.0,
                "retry_count": 0,
                "final_output": ""
            }

            status_text.text("Starting research pipeline...")
            progress_bar.progress(10)
            web_status.warning("🔄 Web Research")

            result = graph.invoke(initial_state, config)

            web_status.success("✅ Web Research")
            progress_bar.progress(40)
            rag_status.success("✅ RAG Knowledge")
            progress_bar.progress(60)
            market_status.success("✅ Market Data")
            progress_bar.progress(75)
            synthesis_status.success("✅ Synthesis")
            progress_bar.progress(90)

            score = result.get('quality_score', 0)
            retries = result.get('retry_count', 0)

            if score >= 0.7:
                critic_status.success(f"✅ Critic ({score})")
            else:
                critic_status.warning(f"⚠️ Critic ({score})")

            progress_bar.progress(100)
            status_text.text("Research complete!")

            st.subheader("📊 Research Metrics")
            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

            with metric_col1:
                st.metric(
                    "Quality Score",
                    f"{score:.2f}",
                    delta="above threshold" if score >= 0.7 else "below threshold"
                )
            with metric_col2:
                st.metric("Retries", retries)
            with metric_col3:
                st.metric("Session", session_id[:20])
            with metric_col4:
                st.metric("Agents Used", "4")

            st.divider()

            st.subheader("📋 Research Report")
            st.markdown(result.get('final_output', 'No output generated'))

            st.divider()

            with st.expander("🌐 Web Research Results"):
                st.markdown(result.get('web_results', 'No web results'))

            with st.expander("📚 Knowledge Base Results"):
                st.markdown(result.get('rag_results', 'No RAG results'))

            with st.expander("📊 Market Data"):
                st.markdown(result.get('market_data', 'No market data'))

            with st.expander("⚖️ Critic Feedback"):
                st.markdown(result.get('critique', 'No critique'))

    except Exception as e:
        st.error(f"Pipeline error: {str(e)}")
        progress_bar.progress(0)

elif run_button and not query:
    st.warning("Please enter a research query")

# ── FOOTER ────────────────────────────────────────────────────────────────────

st.divider()
st.markdown(
    "*Built with LangGraph · Groq · Qdrant · FastAPI · Redis · Guardrails AI · LangSmith · A2A Protocol*"
)