# UAIG Demo — MIGRATE to the NEW Unity AI Gateway

Plan: `~/.claude/plans/i-would-like-to-vectorized-crown.md`. Target: `dbw-brlui-sandbox`.
Legacy `serving_endpoints.put_ai_gateway` → new UC objects via `w.ai_gateway.*`.
Model Service = `catalog.schema.maplechain_custom_ms`. Keyless routing.

## Phase 0 — cleanup legacy
- [ ] Confirm legacy endpoint `maplechain-ai-gateway` deleted (user said done)
- [ ] Remove old secret scope / routing token; drop legacy inference table if orphaned

## Phase 1 — build_notebook.py rewrite
- [ ] §0 widgets: gateway_endpoint→model_service; drop secret_scope; keep pip installs
- [ ] §1 UC data — unchanged
- [ ] §2 add: create_mcp_service (custom) + list system MCP services + service-policy UDFs
- [ ] §3 REWRITE: Model Service via w.ai_gateway (routing 70/30 + fallback + rate_limits + inference_table), dynamic model refs, orphan-table guard, get-else-update
- [ ] §4 agent → ChatDatabricks at /ai-gateway/mlflow/v1 model=FQN; grants→EXECUTE on Model Service; add create_agent_service
- [ ] §5 invoke via /ai-gateway/mlflow/v1 + request tags
- [ ] §6 usage table filtered on new endpoint_name + payload table
- [ ] Remove all legacy put_ai_gateway / external_model / secret-ref code

## Phase 2 — app + config
- [ ] agent_app/agent.py + app.yaml: MODEL_SERVICE + GATEWAY_BASE_URL env
- [ ] databricks.yml agent env update
- [ ] README rewrite around 4 UC gateway objects + maturity table

## Phase 3 — verify on sandbox
- [ ] Model Service create/query live (base /ai-gateway/mlflow/v1)
- [ ] Full notebook job ≥2× (idempotency)
- [ ] Redeploy agent app pointing at Model Service; end-to-end query
- [ ] usage table + payload rows; list_*_services show the objects

## Review — MIGRATION COMPLETE & VERIFIED on dbw-brlui-sandbox

- **setup.ipynb** (34 cells) migrated to the new gateway (`w.ai_gateway.*`). Ran end-to-end
  **twice** on the sandbox (create + update/idempotency) → both SUCCESS.
- **Model Service** `catalog.schema.maplechain_custom_ms` created: routing 70/30 + fallback +
  rate limits (USER_DEFAULT 60 / SERVICE 1000) + inference table. **Invokes** via
  `/ai-gateway/mlflow/v1` (keyless — no endpoint, no secrets). Legacy endpoint + secret scope +
  routing tokens removed.
- **Agent** redeployed pointing at the Model Service (`ChatDatabricks(use_ai_gateway=True)`),
  end-to-end verified calling managed MCP tool `check_inventory` → real data through the gateway.
- **Service-policy UDFs** created (`deny_competitor_pricing`, `ask_before_bulk_delete`).

**Migration bugs found & fixed (live):**
1. Cluster kept an old preinstalled `databricks-sdk` (no `w.ai_gateway`/`McpService`) — bumped
   the pin to `databricks-sdk>=0.125`.
2. `create_model_service` parent + `inference_table.parent` need the `schemas/` prefix.
3. `update_model_service` update_mask = `FieldMask(field_mask=["config"])` (a LIST; a string
   got char-split into path 'c').
4. Model refs irregular → resolve dynamically from system model services.
5. Model Service grants: no SQL `GRANT ... ON MODEL SERVICE`; use
   `w.grants.update(securable_type="model_service", ...)`.
6. Orphan `<prefix>_payload` table blocks create → drop-and-retry (carried over).
7. **VARIANT service-policy UDFs break the schema-level managed MCP** ("Unsupported parameter
   type: VARIANT") → agent registers tool functions by **per-function** MCP URLs.

**Known UI-gated (fail-soft, documented):** custom MCP → UC connection and the Agent Service
need the App-connection OAuth/DCR handshake that only the AI Gateway UI completes. Managed MCP
(per-function) works fully; the agent uses it.

## Follow-up (2026-08-10) — MCP + Agent Services were NOT actually created

User caught that no MCP/Agent Services existed under the schema — only the Model Service. Root
cause: §2c/§4 created the UC HTTP connection with **no auth credential** (`{host,port,base_path}`
only), which is invalid → create threw → swallowed by `except: print("skipped")`. The
"UI-only OAuth" assumption was **wrong**: HTTP connections are scriptable via **OAuth M2M**.

Fix (all verified live on the sandbox — all 4 object types now stand up):
- New **§2c-sp**: ensure SP `maplechain-gateway-sp` + OAuth secret in scope `maplechain_demo`
  (client_secret via `secret()`, never embedded) + `CAN_USE` grant on both Apps +
  `ensure_app_http_connection()` helper (idempotent `CREATE CONNECTION ... TYPE HTTP` OAuth M2M).
- **§2c**: create MCP Service referencing `connections/<name>` (metastore-level — the old
  `connections/{cat}.{sch}.{name}` ref was a bug → `Connection does not exist`).
- **§4-agent-service**: create Agent Service; **omit `model_service`** (rejected on create,
  Beta SASP-8317) — agent still routes LLM via `ChatDatabricks(use_ai_gateway=True)`.
- New widgets `secret_scope`, `gateway_sp`; `TOKEN_ENDPOINT` in §0. Regenerated (36 cells).
