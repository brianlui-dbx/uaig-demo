# MapleChain — Unity AI Gateway end-to-end demo

A single, **idempotent** demo of the **new Unity AI Gateway** — where the gateway is a set of
**first-class Unity Catalog securables** governed alongside your data. This demo creates three of
the four gateway object types — **Model Service, MCP Service, and Agent Service**. The fourth,
**Model Provider Service** (bring-your-own-key external providers such as OpenAI/Anthropic), is
out of scope here because routing is **keyless** across `system.ai.*` models. Themed around
**MapleChain**, a fictional Canadian food-supply business (ambiguously a grocery retailer *or* a
CPG company) whose customers are Canadian restaurants.

> **New vs legacy gateway.** This demo uses `w.ai_gateway.*` → UC objects (docs:
> [learn.microsoft.com/azure/databricks/ai-gateway](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/)).
> It does **not** use the legacy per-endpoint `serving-endpoints put-ai-gateway` config.
> Routing is **keyless** — across the workspace's `system.ai.*` pay-per-token model services;
> no serving endpoint and no secrets.

Run [`setup.ipynb`](./setup.ipynb) top-to-bottom in a Databricks workspace. Every step is safe
to re-run — UC objects use `CREATE OR REPLACE` / `IF NOT EXISTS`, and gateway objects are
create-else-update.

## What it demonstrates

| Capability | Where | Maturity |
|---|---|---|
| **Managed MCP** — UC functions (auto-governed, no registration) | §2a | GA |
| **Managed MCP** — Genie space (auto-governed; *cannot* be an MCP Service) | §2b | Genie create: Public Preview |
| **MCP Service** — custom App server → UC HTTP connection (OAuth M2M) → MCP Service | §2c, `mcp_app/` | Connections/MCP Service GA (connection scripted via OAuth M2M) |
| **Service policies** (guardrail UDFs) + grants + GA column mask | §2d | Column mask/grants GA; Service Policies Beta (attach UI-only) |
| **Model Service** — routing / A-B split | §3 | GA |
| Fallback across destinations | §3 | GA |
| Rate limits (USER_DEFAULT + SERVICE) | §3 | GA |
| Usage tracking + inference table + request tags | §3, §5, §6 | GA |
| **Register an agent in UC** (MLflow model) | §4 | GA |
| Deploy the agent as a Databricks App | §4, `agent_app/` | GA |
| Wrap the agent as a gateway **Agent Service** | §4 | Beta |

## Architecture

![MapleChain Unity AI Gateway architecture](./docs/architecture.png)

The **agent App** (with a built-in chat UI) sends every turn's LLM call through the **Model
Service** (`/ai-gateway/mlflow/v1`, `use_ai_gateway=True`), which routes keyless across
`system.ai.*` models — **70%** `databricks-claude-sonnet-5`, **30%** `gpt-oss-120b`, with
`databricks-claude-haiku-4-5` as **fallback**. The agent's **tools** come from three MCP sources,
each loaded independently: (1) managed **UC functions** (`/api/2.0/mcp/functions/…/{fn}`), (2) the
managed **Genie** MCP (`/api/2.0/mcp/genie/{id}`), and (3) the custom **MCP Service**
(`/ai-gateway/mcp-services/…`), which the gateway proxies to the `mcp-maplechain` App via its UC
HTTP connection. Guardrail **service policies** attach to the Model/MCP Service in the UI (Beta).

> Diagram source: [`docs/architecture.mmd`](./docs/architecture.mmd) (Mermaid). Regenerate the
> PNG with `mmdc -i docs/architecture.mmd -o docs/architecture.png -b white -s 2`.

## Prerequisites

- Databricks workspace in a **Unity AI Gateway supported region** (not Azure Government). Built
  and verified against the **`dbw-brlui-sandbox`** profile (Azure).
- Permission to create UC objects, gateway services (`CREATE SERVICE`), and apps.
- `databricks-sdk >= 0.125` — that's where `w.ai_gateway` lands (the notebook pins it).

## Run order

1. Open `setup.ipynb`, set the `catalog` / `schema` widgets, run all cells.
   - §3 creates the **Model Service** (`catalog.schema.maplechain_custom_ms`) — a UC object, no
     serverless endpoint to wait on.
   - §5 exercises it via `/ai-gateway/mlflow/v1`; a service-policy "block" only fires if you've
     attached the policy in the UI (§2d), so it may simply answer.
2. Deploy the two apps (needs the local CLI + this repo). Apps must be **started** before a
   source deploy, and deploy needs an explicit `--source-code-path` (the bundle upload path):
   ```bash
   databricks bundle deploy -t dev --profile dbw-brlui-sandbox
   databricks apps start  mcp-maplechain   --profile dbw-brlui-sandbox
   databricks apps start  maplechain-agent --profile dbw-brlui-sandbox
   BASE=/Workspace/Users/<you>/.bundle/uaig-demo/dev/files
   databricks apps deploy mcp-maplechain   --source-code-path "$BASE/mcp_app"   --profile dbw-brlui-sandbox
   databricks apps deploy maplechain-agent --source-code-path "$BASE/agent_app" --profile dbw-brlui-sandbox
   ```
   Opening **`maplechain-agent`**'s URL shows a built-in **chat UI** (served from the FastAPI app;
   see `agent_app/README.md`). **`mcp-maplechain`** is an **MCP endpoint only** — like the upstream
   hello-world template it has no web page, so `/` returns 404 by design; it's consumed by the
   agent and the MCP Service, not opened in a browser. Its protocol lives at `/mcp`.
3. Run the notebook's **§4-grants** cell — grants the agent's service principal UC schema access,
   **`EXECUTE` on the Model Service**, **`CAN_RUN` on the Genie space** (so its Genie MCP tool
   works), and CAN_MANAGE on its MLflow experiment (without these the agent App crashes on startup
   or gets `INSUFFICIENT_PERMISSIONS`/`PERMISSION_DENIED` on tool calls). Wire the printed
   experiment id into `MLFLOW_EXPERIMENT_ID` and the Genie space id (from §2b) into `GENIE_SPACE_ID`
   (`agent_app/app.yaml` + bundle env). `MCP_SERVICE` defaults to the custom MCP Service; the agent
   reaches it through the AI Gateway, so no extra grant is needed.
4. Re-run **§2c-sp → §2c** (and **§4-agent-service**) so the Apps register as UC HTTP connections
   (OAuth M2M) **and** first-class MCP / Agent Services. These no-op cleanly before the Apps exist,
   so the first full pass creates them once the Apps are deployed.

## Manual / UI-based steps (to complete the end-to-end demo)

The notebook automates everything the API allows, but a few things are either **UI-only** (Beta
surfaces with no API) or **environment-specific values** you wire in by hand. Do these to get the
full experience:

1. **Attach a service policy (guardrail) — UI-only, Beta.** §2d *creates* the policy UDFs
   (`deny_competitor_pricing`, `ask_before_bulk_delete`) and lists the built-ins
   (`system.ai.block_unsafe_content` / `block_jailbreak` / `block_hallucination`), but **attaching**
   one has no API yet. In the workspace: **AI Gateway → the Model Service (or MCP Service) →
   Policies → New policy →** pick a built-in or `catalog.schema.deny_competitor_pricing` → set the
   phase (request/response), rank, and principals → **Save**. Until you do this, §5's "guardrail"
   call just answers normally — nothing is blocked.
2. **Set the environment-specific env vars, then redeploy the agent.** After the first notebook run
   prints them, put these in `agent_app/app.yaml` **and** the `databricks.yml` agent env, then
   `bundle deploy` + `apps deploy maplechain-agent`:
   - `GENIE_SPACE_ID` — the id printed by **§2b** (workspace-specific; blank disables the Genie tool).
   - `MLFLOW_EXPERIMENT_ID` — the id printed by **§4-grants**.
   - `MCP_SERVICE` / `CUSTOM_MCP_URL` — `MCP_SERVICE` defaults to `catalog.schema.maplechain_mcp`; leave `CUSTOM_MCP_URL` blank (legacy path).
3. **Deploy & (re)deploy the two Apps from the local CLI.** App create/start/deploy is not done by
   the notebook — run the `bundle deploy` + `apps start` + `apps deploy --source-code-path` block in
   **Run order §2** from this repo. (Apps must be **started** before a source deploy.)
4. **Complete OAuth for a connection only if you change its auth type.** The demo uses **OAuth M2M**
   (fully scripted). If you instead switch a connection to **DCR** or **User-to-Machine** auth, that
   requires a one-time **Login** in Catalog Explorer → the connection → **Login**.

## Repo layout

```
setup.ipynb        Idempotent orchestrator (§0–§6). Generated by build_notebook.py.
build_notebook.py  Source of truth for setup.ipynb — edit here, then regenerate.
mcp_app/           Custom MCP server (FastMCP) → Databricks App → UC connection → MCP Service.
agent_app/         LangGraph ResponsesAgent → Databricks App (built-in chat UI at /); LLM = Model Service.
databricks.yml     Bundle defining both apps.
tasks/             Build notes + standalone verify scripts (verify_model_service.py, verify_uc.py, …).
```

## Notes & caveats (verified live)

- **Keyless routing**: the Model Service routes across `system.ai.*` pay-per-token model
  services via `pay_per_token_config` — no keys, no secrets, no serving endpoint. Model refs are
  irregular (`databricks-claude-sonnet-5` vs `gpt-oss-120b`), so the notebook **resolves them
  dynamically** from `list_model_services()`.
- **Invoke a Model Service** at `https://<host>/ai-gateway/mlflow/v1` with
  `model="<catalog.schema.name>"` (OpenAI-compatible). `ChatDatabricks(model=FQN,
  use_ai_gateway=True)` does this for the agent.
- **Service Policies are Beta and attach only in the UI.** The notebook *creates* the custom
  guardrail UDFs (`event VARIANT → VARIANT` returning ALLOW/DENY/ASK) and prints the built-in
  `system.ai.block_*` names + attach steps; it does not assert a block.
- **VARIANT policy UDFs break the schema-level managed MCP server** ("Unsupported parameter type:
  VARIANT"). So for the UC-function tools the agent registers each function by its **per-function**
  MCP URL (`/api/2.0/mcp/functions/{cat}/{sch}/{fn}`) rather than the schema-level URL. (This is one
  of the agent's three tool sources — the Genie MCP and custom MCP Service are the other two.)
- **Custom MCP / Agent Service connections are scripted via OAuth M2M** — no UI handshake. The
  App backends require an OAuth login, so §2c-sp provisions a dedicated service principal
  (`maplechain-gateway-sp`), mints its OAuth secret into the `maplechain_demo` secret scope, and
  grants it `CAN_USE` on both Apps. The UC HTTP connections then use client-credentials
  (`client_secret secret('maplechain_demo','sp_secret')`) — the secret is **referenced, never
  embedded** in the connection object. Only the *interactive* DCR / User-to-Machine connection
  auth types are UI-only; **bearer token and OAuth M2M are creatable from SQL/SDK/CLI**.
- **Connection resource names are metastore-level**: reference a connection as
  `connections/<name>` (single-level), **not** `connections/<catalog>.<schema>.<name>`.
- **Agent Service `model_service` is not yet settable on create** (Beta, SASP-8317). The Agent
  Service is registered with its `source_connection` + `system_prompt` + `base_path`; the agent
  App still routes its LLM through the Model Service via `ChatDatabricks(use_ai_gateway=True)`.
- **Agent Services are Beta and hidden from global search.** A created Agent Service won't appear
  in Catalog **search**; open it by navigating directly to its schema in Catalog Explorer, and
  only if you hold `READ_METADATA`/`EXECUTE` on it (grant those — the owner-only default hides it).
- **Managed MCP servers cannot be registered as MCP Services.** `create_mcp_service` is only for
  **external/custom** MCP servers reached via a UC HTTP connection (the `mcp_app/` server).
  Databricks-managed MCP — **UC functions, Genie spaces, Vector Search** — is already governed and
  consumed directly at its managed URL (`/api/2.0/mcp/genie/{id}`, `/api/2.0/mcp/functions/…`);
  there is no connection and nothing to register.
- **Agent ↔ gateway**: `disable_streaming=True` (the gateway rejects streaming when a policy is
  attached); the agent is best-effort and returns a friendly message if a guardrail 400 fires.
- **Usage / inference tables** populate within ~1 h of the first request — re-run §6 later.

## Regenerating the notebook

```bash
python build_notebook.py
```
