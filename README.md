# Research Agent Orchestrator

A multi-agent AI system that answers complex business research queries by orchestrating specialized agents — each running as an independent microservice, communicating via Google's A2A protocol, and coordinated end-to-end through a LangGraph state machine. Sits behind a full authenticated API layer with per-user history, caching, rate limiting, retries, and per-user long-term memory.

**Ask it:** *"What is the competitive landscape for fintech lending in Southeast Asia?"*
**It returns:** A structured, cited, quality-evaluated business intelligence report — combining live web data, curated knowledge base retrieval, quantitative market statistics, and (if relevant) the user's own past research on related topics.

---

## 🚀 Features

- 🤖 **Specialized Agents** — dedicated microservices for web research, knowledge-base retrieval, quantitative market data, and report synthesis, each independently deployable and scalable
- 🎯 **LLM-Driven Tool Selection** — the Web Research agent discovers available MCP tools at runtime and lets the model choose between `web_search`, `news_search`, and `wikipedia_background` per query, instead of hardcoded branching
- 📚 **Direct RAG Integration** — the Knowledge agent owns its own embedding model (`all-MiniLM-L6-v2`) and Qdrant client, chunking, embedding, and retrieving without an extra network hop
- 🔁 **Critique-Aware Retry Loop** — a Critic node scores every report on specificity, named entities, structure, and vague language; scores below 0.7 route back to Report Synthesis with the critique carried forward in state, capped at 2 retries
- 🔐 **Full Auth & Multi-User Support** — JWT-based register/login, bcrypt password hashing, per-user rate limiting, per-user chat history, all backed by Postgres
- 🔄 **Automatic Retries** — every LLM call and every inter-agent HTTP call retries with exponential backoff on transient failures (rate limits, timeouts, connection errors) via a shared `tenacity`-based helper
- ⚡ **Exact-Match Response Caching** — identical queries within a 10-minute window skip the entire pipeline and return instantly from Redis
- 🧠 **Per-User Agent Memory** — completed research sessions are embedded and stored in a dedicated Qdrant collection, scoped by `user_id`; relevant past sessions are retrieved and injected as context for related future queries
- 🛡️ **Layered Guardrails** — every A2A boundary passes through PII detection (Presidio, via Guardrails AI, running locally), LLM-as-judge prompt-injection detection, and credential-leak pattern matching
- 🔭 **Dual-Layer Observability** — LangSmith for LLM-specific tracing (per-call cost, token counts, full prompt/response inspection, proven parallel-execution timing), plus OpenTelemetry/Jaeger and Prometheus/Grafana for infrastructure-level metrics
- 🧪 **Load-Tested** — Locust-driven concurrency testing surfaced real findings: agent-level contention under concurrent requests, and Groq's daily token quota as a hard external ceiling (see [Load Testing Findings](#load-testing-findings))
- 🔁 **Distributed Session Memory** — LangGraph's `RedisSaver` checkpoints full graph state after every node, so a crashed process resumes where it left off
- 🌐 **One-Command Deployment** — Docker Compose brings up all services (4 agents, MCP server, Postgres, Redis, Qdrant, Jaeger, Prometheus, Grafana) in dependency order, health-checked; the orchestrator API and UI run as local processes for hot-reload during development

---

## 📋 Requirements

- Python 3.11+
- Docker Desktop
- Groq API key ([free tier](https://console.groq.com))
- Tavily API key ([free tier](https://app.tavily.com))
- LangSmith API key (optional but recommended — [smith.langchain.com](https://smith.langchain.com))

---

## 🛠️ Installation

### Option A — Docker Compose + local orchestrator API (recommended)

```bash
git clone https://github.com/kowshikkkkkk/research-agent-orchestrator
cd research-agent-orchestrator

cp .env.example .env
# add GROQ_API_KEY, TAVILY_API_KEY, and a real JWT_SECRET to .env

python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt

docker compose up -d
python -m uvicorn orchestrator.api:app --reload --port 8000
python -m streamlit run ui/app.py
```

Open `http://localhost:8501`, register an account, and run a query.

### Option B — Local development (no Docker)

```bash
python -m venv .venv
source .venv/Scripts/activate

pip install -r requirements.txt

# infrastructure
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 6379:6379 redis:latest
docker run -d -p 5433:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=research_agent postgres:16

# one terminal each, left running
python -m mcp_servers.web_search_mcp          # port 8010
python -m agents.web_research.a2a_server      # port 8001
python -m agents.rag_knowledge.a2a_server     # port 8002
python -m agents.market_data.a2a_server       # port 8003
python -m agents.report_synthesis.a2a_server  # port 8004
python -m uvicorn orchestrator.api:app --reload --port 8000
python -m streamlit run ui/app.py             # port 8501
```

---

## 📝 Configuration

Create `.env` in the project root (see `.env.example`):

```bash
# Required
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key

# Observability (optional but recommended)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=research-agent-orchestrator

# Auth — required for orchestrator_api
JWT_SECRET=a_long_random_value          # generate with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_EXPIRE_MINUTES=1440

# Postgres — accounts + chat history
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/research_agent

# Rate limiting + caching
RATE_LIMIT_PER_MINUTE=10
CACHE_TTL_SECONDS=600

# MCP — used by Web Research + Market Data agents
MCP_WEB_SEARCH_URL=http://localhost:8010      # http://mcp_web_search:8010 in Docker
MCP_WEB_SEARCH_PORT=8010

# Vector database — used by the RAG Knowledge agent and Agent Memory
QDRANT_HOST=localhost                          # qdrant in Docker
QDRANT_PORT=6333
```

Docker Compose overrides the agent service URLs automatically to use container service names instead of `localhost`.

---

## 📁 Project Structure

```text
research-agent-orchestrator/
│
├── orchestrator/
│   ├── orchestrator.py          # LangGraph supervisor: state, nodes, conditional retry edge
│   ├── api.py                    # FastAPI service: auth, rate limiting, caching, memory, /research, /history
│   └── llm_utils.py               # Shared retry helpers: invoke_llm_with_retry, post_with_retry
│
├── auth/
│   ├── security.py                # bcrypt hashing, JWT create/decode
│   └── dependencies.py            # get_current_user FastAPI dependency
│
├── db/
│   ├── session.py                 # SQLAlchemy engine/session, get_db dependency
│   └── models.py                  # User, QueryLog (with foreign key)
│
├── cache/
│   └── cache.py                   # Redis exact-match query cache, TTL-based
│
├── memory/
│   └── agent_memory.py            # Per-user long-term memory: store/retrieve via a dedicated Qdrant collection
│
├── agents/
│   ├── web_research/              # MCP tool discovery + LLM-driven tool selection + Groq synthesis
│   ├── rag_knowledge/              # Direct Qdrant + embedding integration; handles search & ingest
│   ├── market_data/                 # MCP web_search with a deterministic market-biased query
│   └── report_synthesis/            # Multi-source report generation with critique- and memory-aware retry
│       # each agent/ has agent.py (logic) + a2a_server.py (FastAPI + A2A + guardrails)
│
├── mcp_servers/
│   ├── web_search_mcp.py           # MCP server (SSE): web_search + news_search (Tavily), wikipedia_background
│   │                                 # — validates/clamps all tool arguments before they reach Tavily/Wikipedia
│   └── mcp_client.py                # Shared sync MCP client: tool invocation + discovery for bind_tools
│
├── content_safety/
│   └── guardrails.py                # PII detection (Presidio), LLM-judge injection detection, credential regex
│
├── observability/
│   ├── logging_config.py            # Structured JSON logging, trace_id propagation
│   ├── tracing.py                    # OpenTelemetry setup, W3C trace-context propagation
│   ├── a2a_instrumentation.py        # Wraps tracing + metrics + logging around one A2A task handler
│   └── metrics.py                    # Prometheus counters/histograms
│
├── evals/
│   ├── golden_queries.json           # 8 hand-authored queries spanning research domains
│   ├── metrics.py                     # Deterministic checks: structure, keyword coverage, density
│   ├── judge.py                       # Independent LLM judge: groundedness, coverage, genericness
│   └── run_eval.py                     # Harness: runs the real orchestrator graph against the golden set
│
├── ui/
│   └── app.py                          # Streamlit UI: auth, research, history, PDF ingestion, health monitoring
│
├── docs/
│   ├── screenshots/                    # README screenshots
│   └── phase4-load-testing-findings.md # Locust results and root-cause analysis
├── locustfile.py                        # Load test: N unique users, unique queries per request
├── create_load_test_users.py             # One-off script to register load-test accounts
├── Dockerfile                             # Single shared image for agent/UI services
├── docker-compose.yml                      # Infra + agent orchestration (Postgres, Redis, Qdrant, agents, etc.)
├── requirements.txt
└── .env.example
```

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    U["User"] --> UI["Streamlit UI<br/>login / register / query"]
    UI -->|"HTTP + JWT"| API["orchestrator_api (FastAPI)<br/>auth · rate limit · cache · memory"]

    API -->|"cache hit"| UI
    API -->|"cache miss"| GRAPH["LangGraph + Redis Checkpointer"]

    GRAPH -->|"A2A Task"| C["Web Research Agent<br/>Port 8001"]
    C -->|"LLM picks one of 3"| C1["MCP Web Search<br/>SSE · Port 8010"]
    C1 -->|"web_search OR news_search"| C2["Tavily API"]
    C1 -->|"wikipedia_background"| C3["Wikipedia API"]
    C -->|"Update State"| GRAPH

    GRAPH -->|"A2A Task"| D["RAG Knowledge Agent<br/>Port 8002<br/>Direct Qdrant integration"]
    D --> D1["Qdrant<br/>Knowledge Base"]
    D -->|"Update State"| GRAPH

    GRAPH -->|"A2A Task"| E["Market Data Agent<br/>Port 8003"]
    E -->|"Update State"| GRAPH

    C -.->|"synthesis"| L["Groq gpt-oss-120b"]
    D -.->|"synthesis"| L
    E -.->|"extraction"| L

    API -.->|"retrieve/store"| M["Qdrant<br/>Agent Memory (per user)"]
    M -.->|"past_context"| GRAPH

    GRAPH -->|"A2A Task"| F["Report Synthesis Agent<br/>Port 8004"]
    F -.->|"drafting"| L
    F -->|"Generated Report"| G["Critic Node<br/>Quality Evaluation"]
    G -.->|"scoring"| L

    G -->|"Score ≥ 0.7"| H["Return Final Report"]
    G -->|"Score < 0.7 & Retry Available"| I["Increment Retry Counter"]
    I --> F

    API --> PG["Postgres<br/>users + query history"]
```

Research agents run off `START` in parallel (web_research, rag_knowledge, market_data all feed into report_synthesis), and the Critic's conditional edge is what makes the retry loop graph structure rather than application code. Every LLM call and every inter-agent HTTP call in the diagram above goes through a shared retry wrapper (`orchestrator/llm_utils.py`) with exponential backoff, not shown for clarity.


---

## How RAG Works in This System

```mermaid
flowchart TD
    subgraph Indexing["Indexing - one time per document"]
        A1["Document"] --> A2["Chunk\n500 chars, 50 overlap"]
        A2 --> A3["Embed\nall-MiniLM-L6-v2"]
        A3 --> A4["Store in Qdrant"]
    end
    subgraph Retrieval["Retrieval - every query"]
        B1["Query"] --> B2["Embed\nall-MiniLM-L6-v2"]
        B2 --> B3["Cosine similarity search in Qdrant"]
        B3 --> B4["Top 5 chunks"]
    end
    subgraph Generation
        C1["Top 5 chunks + query"] --> C2["LLM prompt"]
        C2 --> C3["Grounded answer with source attribution"]
    end
    A4 -.-> B3
    B4 --> C1
```

Both stages run directly inside the RAG Knowledge agent (`agents/rag_knowledge/agent.py`) — no MCP indirection. The 500-character chunk size with 50-character overlap is deliberate: smaller chunks lose context, larger chunks exceed what fits usefully in a retrieval result, and the overlap ensures sentences spanning chunk boundaries are fully represented in at least one chunk.

**Verified end to end**: ingesting a real 2022 IBM annual report PDF and then asking a targeted financial question produced a report citing specific figures (`$60.5B total revenue`, `$25.0B Software segment`, `$9.3B free cash flow`) with inline citations pointing back to specific line ranges in the ingested source — proof the pipeline retrieves and grounds against real document content, not just the model's general knowledge. A generic, unrelated query against the same knowledge base correctly returns no results, since retrieval is governed by semantic similarity, not by "a document was recently ingested."

---

## How Agent Memory Works

```mermaid
flowchart LR
    A["Completed research session"] --> B["Embed query + report excerpt"]
    B --> C["Store in Qdrant\nagent_memory collection\n(tagged with user_id)"]

    D["New query"] --> E["Embed query"]
    E --> F["Search agent_memory\nfiltered by user_id"]
    F --> G["Top 3 relevant past sessions"]
    G --> H["Injected as past_context\ninto Report Synthesis prompt"]
```

Every completed `/research` call is summarized (query + a truncated excerpt of the report, not the full text) and stored as a new vector in a dedicated `agent_memory` Qdrant collection, tagged with the requesting user's ID. Before running a new query, the same collection is searched for semantically similar past sessions — filtered so a user only ever retrieves their own history, never another user's. If relevant memories are found, they're passed to the Report Synthesis agent as `past_context`, with an explicit prompt instruction to reference them only where genuinely relevant, not to force a connection.

**Verified end to end**: asking "What is the EV battery market in India?" followed by "How does the EV battery market in India compare to China?" (same user) produced a second report that explicitly cited figures from the first query as `"(prior research)"` — confirmed independently by checking Qdrant's `points_count`, which incremented by exactly one after each completed query, matching the number of real pipeline runs rather than cache hits.

---

## How Reliability Works

Every LLM call and every inter-agent HTTP call in this system goes through one of two shared retry wrappers in `orchestrator/llm_utils.py`:

- **`invoke_llm_with_retry`** — retries on `groq.RateLimitError` specifically, with exponential backoff (up to 4 attempts), so a transient per-minute rate limit doesn't fail a whole request outright.
- **`post_with_retry`** — retries on `httpx.ConnectError`/`httpx.TimeoutException` (up to 3 attempts), so a briefly-restarting agent container doesn't fail a request that would have succeeded a second later.

Both were exercised for real during load testing, not just unit-tested: a genuine Groq per-minute rate limit and a genuine agent-container connection timeout both triggered visible retry-and-recover behavior in production logs, not synthetic test conditions.

Failures that exhaust all retries are still handled gracefully — the orchestrator API catches the resulting exception, marks the `QueryLog` row as `failed` (rather than leaving it stuck at `pending`), and returns a clean `502` to the caller instead of crashing or hanging.

---

## Load Testing Findings

Full details in [`docs/phase4-load-testing-findings.md`](docs/phase4-load-testing-findings.md). Summary:

**Finding 1 — agent-level contention under concurrent requests.** Even at 2 simultaneous simulated users, a request to `web_research_agent` queued behind another and hit a `ReadTimeout` after retries were exhausted, because each agent runs as a single synchronous process. Root cause identified precisely (not yet fixed): running each agent with multiple Uvicorn workers, or converting internal HTTP calls to genuinely async, would resolve this.

**Finding 2 — Groq's daily token quota is a hard external ceiling.** A full day of manual and load testing exhausted the 200,000 token/day quota on the model in use. Once exhausted, every LLM call failed with `RateLimitError`; the system correctly returned clean `502`s rather than hanging. Real deployment to multiple users requires either a paid Groq tier or usage-aware throttling ahead of the provider's own limit.

Both findings validate the reliability work above: retries and error handling behaved correctly under genuine failure conditions, not just synthetic tests.

---

## How the Quality Gate Works

```python
def should_retry(state: ResearchState) -> str:
    score = state.get('quality_score', 0)
    retry_count = state.get('retry_count', 0)

    if score < 0.7 and retry_count < 2:
        return "retry"   # → routes back to report_synthesis with critique in state
    else:
        return "accept"  # → routes to final_output
```

The Critic evaluates four dimensions: specificity, named entities and data points, structural completeness, and absence of vague statements. On retry, the critique travels forward in state — the Report Synthesis agent reads it and specifically addresses the identified gaps. This is intelligent retry, not random regeneration — though it's worth being precise that retry only re-runs synthesis, never the research agents, so it can't fix a report that was bad because the underlying research was thin.

The eval harness (`evals/`) runs an *independent* LLM judge with a different rubric on the same reports, specifically so this self-scoring mechanism can be checked against a second opinion rather than trusted blindly.

---

## 📸 Screenshots

**1. Landing page** — system status panel confirms all agents are healthy before a query is even submitted.

![Landing page](docs/screenshots/Screenshot 2026-08-31 172931.png)

**2. Generated report** — structured, cited output with inline per-claim source attribution.

![Research report](docs/screenshots/Screenshot 2026-08-31 172909.png)



---

## 🧩 Key Components

**1. Orchestrator**
Location: `orchestrator/orchestrator.py`
Purpose: LangGraph supervisor — defines `ResearchState`, the node graph, and the Critic's conditional retry edge.

**2. Orchestrator API**
Location: `orchestrator/api.py`
Purpose: FastAPI service owning auth, rate limiting, caching, memory retrieval/storage, and the actual `/research`/`/history` endpoints — the UI's only integration point.

**3. Web Research Agent**
Location: `agents/web_research/agent.py`
Purpose: Discovers MCP tools at request time via `list_tools()`, binds them to the LLM, and lets the model pick `web_search`, `news_search`, or `wikipedia_background` per query.

**4. RAG Knowledge Agent**
Location: `agents/rag_knowledge/agent.py`
Purpose: Chunks (500 chars, 50 overlap), embeds with `all-MiniLM-L6-v2`, indexes into Qdrant, and retrieves via cosine similarity.

**5. Market Data Agent**
Location: `agents/market_data/agent.py`
Purpose: Always calls MCP's `web_search` with a deterministic market-biased query template, then extracts quantitative figures via LLM.

**6. Report Synthesis Agent**
Location: `agents/report_synthesis/agent.py`
Purpose: Drafts the structured report from all three research streams plus any relevant `past_context`; on retry, reads the Critic's critique from state and specifically addresses the gaps it named.

**7. Agent Memory**
Location: `memory/agent_memory.py`
Purpose: Stores and retrieves per-user summaries of past research sessions in a dedicated, `user_id`-filtered Qdrant collection.

**8. Content Safety**
Location: `content_safety/guardrails.py`
Purpose: `guard_a2a_task()` runs at every A2A boundary — PII detection, LLM-judge injection detection, credential-leak regex.

**9. Observability**
Location: `observability/`
Purpose: `a2a_instrumentation.py` wraps every task handler in one context manager that opens an OTel span, binds the trace_id into structured logs, and records Prometheus request metrics on exit.

---

## 🔧 API Endpoints

### Orchestrator API (`:8000`)

| Endpoint | Method | Auth required | Description |
|---|---|---|---|
| `/health` | GET | No | Liveness check |
| `/auth/register` | POST | No | Create an account, returns a JWT |
| `/auth/login` | POST | No | Authenticate, returns a JWT |
| `/auth/me` | GET | Yes | Current user info |
| `/research` | POST | Yes | Run (or retrieve cached) research; rate-limited, memory-aware |
| `/history` | GET | Yes | This user's past queries, newest first |

### Agents (`web_research` :8001, `rag_knowledge` :8002, `market_data` :8003, `report_synthesis` :8004)

| Endpoint | Method | Description |
|---|---|---|
| `/.well-known/agent.json` | GET | AgentCard — capabilities, input/output schema |
| `/health` | GET | Liveness check |
| `/metrics` | GET | Prometheus-format metrics |
| `/tasks/send` | POST | A2A task submission |

The RAG Knowledge agent overloads `/tasks/send`: passing an `ingest` object in the task input triggers document ingestion instead of a search.

The MCP web search server (`:8010`, SSE transport) exposes `list_tools()` and `call_tool()` for `web_search`, `news_search`, and `wikipedia_background`, with all arguments validated before use.

---

## 📖 Documentation

- [`docs/phase4-load-testing-findings.md`](docs/phase4-load-testing-findings.md) — Locust results and root-cause analysis
- `.env.example` — full environment variable reference

---

## 🎯 Use Cases

- **Competitive landscape research** — market sizing, key players, growth trends for a sector or region
- **Due diligence support** — combine live web data with an internal knowledge base for grounded, cited answers, informed by your own past research
- **Market data extraction** — quantitative stats (CAGR, market size, funding volume) pulled and structured automatically
- **Regression-tested prompt iteration** — run `evals/run_eval.py` before and after a prompt change to check whether it actually helped

---

## 🛠️ Technology Stack

| Layer | Technology | Why |
|---|---|---|
| Orchestration | LangGraph | Conditional routing, Redis checkpointing, LangSmith integration |
| API Layer | FastAPI (`orchestrator/api.py`) | Auth, rate limiting, caching, memory — single integration point for any frontend |
| Auth | JWT + bcrypt | Stateless tokens, industry-standard password hashing |
| Accounts & History | Postgres + SQLAlchemy | Durable storage that must survive a restart, unlike Redis/Qdrant |
| Rate Limiting | slowapi + Redis | Per-user request throttling, keyed by JWT subject |
| Caching | Redis | Exact-match query cache with TTL, skips repeat pipeline runs |
| Agent Communication | A2A Protocol | Standardized agent discovery and task delegation |
| LLM | Groq `openai/gpt-oss-120b` | Fast inference, free tier, tool calling |
| Reliability | tenacity | Shared exponential-backoff retry wrappers for LLM and HTTP calls |
| Tool Registry | MCP (SSE transport) | 3 tools, 2 providers; LLM-driven dynamic tool selection; input-validated |
| Web Search | Tavily API | Purpose-built for AI agents, full page extraction |
| Vector Database | Qdrant | Payload filtering enables both curated RAG and per-user agent memory in one instance |
| Embeddings | all-MiniLM-L6-v2 | Local, fast, no API cost, 384-dim cosine similarity |
| Agent Framework | FastAPI | Independent microservices, A2A endpoints |
| Security | Guardrails AI (Presidio) + LLM-as-judge | Real PII detection, injection detection robust to novel phrasing |
| LLM Observability | LangSmith | Per-call cost, tokens, full trace inspection, zero extra code |
| Infra Observability | OpenTelemetry + Jaeger + Prometheus + Grafana | Distributed tracing, infra-level metrics, dashboards |
| Load Testing | Locust | Concurrent multi-user simulation, surfaced real contention and quota findings |
| Session Memory | Redis + RedisSaver | Distributed graph-state persistence across agent processes |
| Long-Term Memory | Qdrant (`agent_memory` collection) | Per-user semantic recall of past research sessions |
| Evaluation | Custom harness | Deterministic checks + independent LLM judge |
| UI | Streamlit | Auth, research, history, PDF ingestion, agent health monitoring |
| Deployment | Docker Compose (infra + agents) + local processes (API + UI) | Health-checked infra startup, hot-reload during active development |

---

## Known Limitations

- Research agents run sequentially in the graph edges from `START` at the LangGraph level, but each individual agent process is single-worker synchronous — under concurrent load, requests queue at the agent, not the orchestrator (see [Load Testing Findings](#load-testing-findings))
- No circuit breaker — a persistently failing dependency is retried per-request rather than temporarily short-circuited across requests
- No per-user data isolation on document ingestion — the RAG knowledge base (`research_knowledge_base` collection) is shared across all users; only agent memory is per-user
- Retry only re-runs Report Synthesis, never the research agents — a low score caused by thin underlying research can't be fixed by retry alone
- Single-node Redis, Postgres, and Qdrant — no replication or failover
- The eval harness's golden set is 8 hand-written queries — a regression tripwire, not a statistically validated benchmark
- `guardrails-ai-detect-jailbreak` (the Hub's ML-based jailbreak classifier) has a confirmed upstream bug incompatible with current `transformers` versions, with no newer package release available — worked around with an LLM-as-judge check instead
- Deployment (hosting, secrets management, HTTPS, a paid Groq tier for real multi-user traffic) is not yet done — this runs locally via Docker Compose + local processes only

---

## 👤 Author

**Kowshik Sai**
PGDM — Research and Business Analytics, Madras School of Economics

- GitHub: [github.com/kowshikkkkkk](https://github.com/kowshikkkkkk)
- LinkedIn: [linkedin.com/in/Kowshik-sai](https://linkedin.com/in/Kowshik-sai)

## 🙏 Acknowledgments

Built with LangGraph · LangChain · FastAPI · Postgres · Qdrant · Tavily · Groq · Guardrails AI · LangSmith · OpenTelemetry

## 🔗 Repository

[github.com/kowshikkkkkk/research-agent-orchestrator](https://github.com/kowshikkkkkk/research-agent-orchestrator)