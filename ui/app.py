# ui/app.py

import os
import streamlit as st
import httpx
import time
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

ORCHESTRATOR_API_URL = os.getenv("ORCHESTRATOR_API_URL", "http://localhost:8000")

if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "email" not in st.session_state:
    st.session_state.email = None


def auth_headers() -> dict:
    if st.session_state.access_token:
        return {"Authorization": f"Bearer {st.session_state.access_token}"}
    return {}


def do_register(email: str, password: str):
    try:
        resp = httpx.post(
            f"{ORCHESTRATOR_API_URL}/auth/register",
            json={"email": email, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 201:
            data = resp.json()
            st.session_state.access_token = data["access_token"]
            st.session_state.email = email
            st.rerun()
        else:
            st.sidebar.error(resp.json().get("detail", "Registration failed"))
    except Exception as e:
        st.sidebar.error(f"Could not reach orchestrator API: {e}")


def do_login(email: str, password: str):
    try:
        resp = httpx.post(
            f"{ORCHESTRATOR_API_URL}/auth/login",
            json={"email": email, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.access_token = data["access_token"]
            st.session_state.email = email
            st.rerun()
        else:
            st.sidebar.error(resp.json().get("detail", "Login failed"))
    except Exception as e:
        st.sidebar.error(f"Could not reach orchestrator API: {e}")


# ── URL CONFIGURATION ─────────────────────────────────────────────────────────
# Defaults to localhost for local development.
# In Docker Compose these are overridden via environment variables
# to use service names: http://web_research:8001 etc.

WEB_RESEARCH_URL = os.getenv("WEB_RESEARCH_URL", "http://localhost:8001")
RAG_KNOWLEDGE_URL = os.getenv("RAG_KNOWLEDGE_URL", "http://localhost:8002")
MARKET_DATA_URL = os.getenv("MARKET_DATA_URL", "http://localhost:8003")
REPORT_SYNTHESIS_URL = os.getenv("REPORT_SYNTHESIS_URL", "http://localhost:8004")

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
    st.header("👤 Account")

    if st.session_state.access_token is None:
        login_tab, register_tab = st.tabs(["Login", "Register"])

        with login_tab:
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            if st.button("Log in", use_container_width=True):
                if login_email and login_password:
                    do_login(login_email, login_password)
                else:
                    st.warning("Enter both email and password")

        with register_tab:
            reg_email = st.text_input("Email", key="reg_email")
            reg_password = st.text_input("Password (min 8 chars)", type="password", key="reg_password")
            if st.button("Create account", use_container_width=True):
                if reg_email and reg_password:
                    do_register(reg_email, reg_password)
                else:
                    st.warning("Enter both email and password")

        st.info("Log in to run research and see your query history.")
    else:
        st.success(f"Logged in as **{st.session_state.email}**")
        if st.button("Log out", use_container_width=True):
            st.session_state.access_token = None
            st.session_state.email = None
            st.rerun()

    st.divider()
    st.header("⚙️ System Status")

    # In Docker, check agents via internal service names
    # In local dev, use localhost
    health_agents = {
        "Orchestrator API": f"{ORCHESTRATOR_API_URL}/health",
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
        except Exception:
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

    # ── CHAT HISTORY ──────────────────────────────────────────────────────────
    if st.session_state.access_token is not None:
        st.header("🕘 Your Research History")
        try:
            resp = httpx.get(
                f"{ORCHESTRATOR_API_URL}/history",
                headers=auth_headers(),
                timeout=10.0,
            )
            if resp.status_code == 200:
                history = resp.json()
                if not history:
                    st.caption("No queries yet.")
                for item in history:
                    label = item["query"][:40] + ("…" if len(item["query"]) > 40 else "")
                    score = item.get("quality_score")
                    score_str = f"{score:.2f}" if score is not None else "—"
                    st.caption(f"**{label}**  \nscore {score_str} · {item['status']} · {item['created_at'][:16]}")
            else:
                st.caption("Could not load history.")
        except Exception:
            st.caption("Orchestrator API unreachable — history unavailable.")

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
    - LangGraph Orchestrator (behind orchestrator_api)
    - Postgres — accounts + chat history
    - Redis — session memory + response cache
    - Qdrant — knowledge base + per-user agent memory
    - Guardrails AI Security (PII + LLM-judge injection detection)
    - LangSmith Observability
    - A2A Protocol
    """)

# ── MAIN INTERFACE ────────────────────────────────────────────────────────────

if st.session_state.access_token is None:
    st.info("👈 Log in or create an account in the sidebar to run research.")
    st.stop()

col1, col2 = st.columns([2, 1])

with col1:
    query = st.text_input(
        "Research Query",
        placeholder="e.g. What is the competitive landscape for fintech lending in Southeast Asia?",
        help="Enter any business research question"
    )

with col2:
    thread_id = st.text_input(
        "Session ID (optional)",
        value="",
        help="Same session ID = LangGraph memory carried across queries. Leave blank to start a new thread."
    )

run_button = st.button("🚀 Run Research", type="primary", use_container_width=True)

# ── RESEARCH EXECUTION ────────────────────────────────────────────────────────

if run_button and query:

    progress_bar = st.progress(0)
    status_text = st.empty()
    status_text.text("Sending request to orchestrator API...")
    progress_bar.progress(20)

    try:
        response = httpx.post(
            f"{ORCHESTRATOR_API_URL}/research",
            json={"query": query, "thread_id": thread_id or None},
            headers=auth_headers(),
            timeout=180.0,
        )
        progress_bar.progress(80)

        if response.status_code == 401:
            st.session_state.access_token = None
            st.error("Your session expired. Please log in again.")
            st.stop()
        elif response.status_code == 429:
            st.error("Rate limit reached — please wait a moment before trying again.")
            st.stop()
        elif response.status_code != 200:
            detail = response.json().get("detail", response.text)
            st.error(f"Request failed: {detail}")
            st.stop()

        result = response.json()
        progress_bar.progress(100)
        status_text.text("Research complete!")

        st.subheader("📊 Research Metrics")
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

        score = result["quality_score"]
        with metric_col1:
            st.metric(
                "Quality Score",
                f"{score:.2f}",
                delta="above threshold" if score >= 0.7 else "below threshold"
            )
        with metric_col2:
            st.metric("Retries", result["retry_count"])
        with metric_col3:
            st.metric("Thread", result["thread_id"][:20])
        with metric_col4:
            st.metric("Agents Used", "4")

        st.caption(f"Full thread ID: `{result['thread_id']}` — reuse it above to continue this session.")

        st.divider()

        st.subheader("📋 Research Report")
        st.markdown(result.get("final_output", "No output generated"))

    except httpx.RequestError as e:
        st.error(f"Could not reach orchestrator API: {e}")
        progress_bar.progress(0)

elif run_button and not query:
    st.warning("Please enter a research query")

# ── FOOTER ────────────────────────────────────────────────────────────────────

st.divider()
st.markdown(
    "*Built with LangGraph · Groq · Qdrant · FastAPI · Postgres · Redis · Guardrails AI · LangSmith · A2A Protocol*"
)