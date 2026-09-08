# MapleChain agent (LangGraph)

A LangGraph `ResponsesAgent` for the MapleChain demo, customized from the
databricks/app-templates `agent-langgraph` template. Deployed as a Databricks App and also
registered in Unity Catalog as a model (see repo root `README.md`, §4).

**UI:** opening the App URL shows a built-in chat page. The upstream template's `enable_chat_proxy`
expects a *separate* Next.js frontend (`e2e-chatbot-app-next`) on port 3000 — which needs Node at
runtime and a git clone at startup, fragile inside Databricks Apps (with no frontend running, `/`
returns 503). Instead we set `enable_chat_proxy=False` and serve a self-contained
`agent_server/static/index.html` from the FastAPI app itself (mounted at `/`), which POSTs to the
same `/invocations` endpoint. One process, no Node, no clone.

## Demo wiring (two things worth noticing)

- **LLM = the Model Service** (`MODEL_SERVICE`, a UC gateway object; **derived** from
  `UC_CATALOG`+`UC_SCHEMA` as `<catalog>.<schema>.maplechain_custom_ms`), reached with
  `ChatDatabricks(model=MODEL_SERVICE, use_ai_gateway=True)`. Every turn goes through the Unity
  AI Gateway, so routing, fallback, and rate limits apply automatically.
- **Tools = three MCP sources**, each loaded independently so one failing endpoint can't drop the
  rest: (1) managed **UC functions** by **per-function** MCP URLs
  (`/api/2.0/mcp/functions/{catalog}/{schema}/{fn}` — the schema-level URL breaks on the VARIANT
  service-policy UDFs); (2) the managed **Genie** MCP (`/api/2.0/mcp/genie/{GENIE_SPACE_ID}`) for
  natural-language data Q&A (the App SP needs `CAN_RUN` on the space); (3) the custom **MCP
  Service** (`/ai-gateway/mcp-services/{MCP_SERVICE}`) — the mcp_app/ tools governed through the UC
  MCP Service, with the AI Gateway injecting the connection's credentials.

Configuration is via env vars, defined once in the bundle (`databricks.yml` → `variables` +
`config.env`): `UC_CATALOG`, `UC_SCHEMA`, `GENIE_SPACE_ID`, `MLFLOW_EXPERIMENT_ID`. `MODEL_SERVICE`
and `MCP_SERVICE` are derived from `UC_CATALOG`+`UC_SCHEMA` (override the env var only to point at a
differently named service). The static `app.yaml` carries only the `command` + MLflow tracking
vars; location config is applied at deploy time by `bundle run`. For local dev, set the vars in a
`.env` (see `.env.example`).

## Run locally

```bash
cp .env.example .env    # fill in DATABRICKS_CONFIG_PROFILE + MLFLOW_EXPERIMENT_ID
uv run start-server     # serves /invocations on http://localhost:8000
```

## Deploy as a Databricks App

From the repo root:

```bash
databricks bundle deploy -t dev --profile <your-profile>
databricks bundle run    maplechain_agent -t dev --profile <your-profile>   # applies config.env + starts
```
