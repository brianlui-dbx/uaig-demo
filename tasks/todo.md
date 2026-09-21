# UAIG Demo — teardown + redeploy on `dbw-brlui-stable-cc`

Profile: `dbw-brlui-stable-cc` (ws 7405615135791589) · catalog `brlui` · schema `uaig_demo`.
Plan: `~/.claude/plans/fizzy-wishing-snail.md`. Azure-OpenAI-only; Foundry off.
**Preserve** secret scope `maplechain_demo` + SP `maplechain-gateway-sp` (required by §2c-sp).

## Teardown — DONE (verified)
- [x] 1. Delete gateway services (agent_svc, mcp, model_provider azure_mps, model_service)
- [x] 2. Delete UC HTTP connections (maplechain_agent_conn, maplechain_custom_mcp)
- [x] 3. Delete Genie space + MLflow experiment
- [x] 4. `bundle destroy -t dev` (apps + app SPs + setup job + synced files)
- [x] 5. Delete schema `brlui.uaig_demo` (SDK `schemas.delete force=True`; aitools query rejects DDL)
- [x] 6. Confirmed: scope `maplechain_demo` + SP `maplechain-gateway-sp` present; all else gone

## Redeploy (README run order) — DONE
- [x] 0. bootstrap_gateway_auth.py → SP + secret reused (not re-minted) · 0b Azure key present → skipped
- [x] 1. bundle deploy -t dev --var catalog=brlui (transient token-refresh on 1st try; retry OK)
- [x] 1b. bundle sync --full -t dev
- [x] 2. bundle run setup → genie_space_id=01f1b2cc501b15ef864ca852145cf3a3, experiment_id=424212272403636
- [x] 3. bundle deploy with genie_space_id + experiment_id
- [x] 4. bundle run maplechain_mcp + maplechain_agent (both started)
- [x] 5. bundle run setup (idempotent — same ids returned; services bound to live apps)

## Verify — DONE
- [x] 4 gateway services back under brlui.uaig_demo (Model, MCP, Agent, Model-Provider azure_mps)
- [x] schema repopulated (9 tables, 7 functions, supplier_risk_model, docs volume)
- [x] both apps ACTIVE
- [x] end-to-end: Model Service invocation via /ai-gateway/mlflow/v1 → HTTP 200, keyless routing OK

## Review — COMPLETE (2026-09-17)
Full teardown + clean redeploy of the MapleChain UAIG demo on `dbw-brlui-stable-cc`
(catalog `brlui`, schema `uaig_demo`), Azure-OpenAI-only, Foundry off.

**Teardown:** deleted 4 gateway services (SDK `w.ai_gateway.delete_*`), 2 UC HTTP connections,
Genie space, MLflow experiment, both apps + their app SPs + setup job (`bundle destroy`), and the
`brlui.uaig_demo` schema (`w.schemas.delete force=True` — the aitools query tool rejects `DROP`
DDL). **Preserved** (required by §2c-sp / reused by redeploy): secret scope `maplechain_demo`
(`sp_secret`/`sp_client_id`/`azure_openai_api_key`) + SP `maplechain-gateway-sp`.

**Redeploy:** README run order 0→5. Bootstrap reused the SP/secret (no re-mint). First
`bundle deploy` hit a transient OAuth token-refresh error (exit status 45) that cleared on retry.
Two setup runs returned the same `genie_space_id`/`experiment_id` → confirmed idempotent.

**Validation note:** user's premise "no SP needed, only the API key" is not how the current repo
works — App→UC connections still use OAuth M2M via `maplechain-gateway-sp`; the `azure_openai_api_key`
is a separate secret for the Azure provider service only. Making the demo SP-free would be a
`build_notebook.py` change (not done — out of scope for "redeploy per README").

**Manual, UI-only remaining (documented, optional):** attach a guardrail service policy (Beta).
