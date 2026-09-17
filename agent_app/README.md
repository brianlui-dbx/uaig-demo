# MapleChain agent (AppKit beta)

An enterprise React/TypeScript chat application built with Databricks AppKit `0.57.0` and its
beta `agents()` plugin. AppKit owns streaming, conversation threads, cancellation, retries, and
agent event parsing; the UI renders only user-facing answer deltas and shows safe tool activity
instead of chain-of-thought or raw JSON envelopes.

The AppKit agent uses its chat-completions adapter against the deterministic Unity AI Gateway
Model Service derived as `<UC_CATALOG>.<UC_SCHEMA>.maplechain_custom_ms` (Sonnet with Haiku
fallback). This is the demo's single, deterministic Model Service, avoiding provider-specific
tool-call behavior in interactive turns.
Governed MapleChain data access is
provided by the AppKit Genie plugin. Location values are injected by the root bundle; do not
hardcode workspace URLs, catalog names, or IDs.

The bundle sets `GENIE_TIMEOUT_MS=600000` (10 minutes). Genie may remain in `ASKING_AI` for more
than two minutes while its SQL warehouse starts or it plans a complex query, so the AppKit
plugin's 120-second default is too short for this demo. The agent tool deadline is automatically
set 30 seconds higher than the Genie deadline. If a target needs a different limit, change the
bundle-managed environment value; keep the tool deadline higher than the plugin deadline.

This hybrid is intentional: in this workspace AppKit `0.57.0`'s managed Supervisor adapter rejects
both direct foundation-model names and this demo's routed Model Service. The chat-completions
adapter preserves Model Service routing while the Genie toolkit avoids the beta MCP connector's
same-origin/private-DNS bug.

## Local development

```bash
cp .env.example .env
# Set DATABRICKS_CONFIG_PROFILE, DATABRICKS_HOST, UC_CATALOG, UC_SCHEMA, and GENIE_SPACE_ID.
npm install
npm run dev
```

Run `npm run typecheck`, `npm run lint`, and `npm run build` before deployment.

## Bundle deployment

From the repository root, always pass the intended profile and the same bundle variables used by
setup:

```bash
databricks bundle deploy -t dev --profile <profile> --var 'catalog=<catalog>' \
  --var 'genie_space_id=<id>' --var 'experiment_id=<id>'
databricks bundle run maplechain_agent -t dev --profile <profile> \
  --var 'catalog=<catalog>' --var 'genie_space_id=<id>' --var 'experiment_id=<id>'
```

`bundle run` is required because it applies the bundle-managed environment and starts the App.
The bundle enables `dashboards.genie` user authorization. The UI truthfully discloses that Genie
runs on behalf of the signed-in user while model inference runs as the App service principal.

After deleting and recreating the App, the first `bundle run` may spend several minutes creating
compute before its source snapshot becomes active. If it ends without a deployment, rerun the same
command. If a deployment fails, inspect `databricks apps logs maplechain-agent --profile <profile>`;
after a full bundle sync, it is also safe to redeploy the bundle-managed source path directly.

Keep the AppKit-generated dependency versions and lockfile intact. In this workspace, adding a
package through npm's legacy peer resolver caused the Databricks Apps npm 10.9.2 builder to hang
and end with `Exit handler never called`; the answer formatter intentionally has no extra runtime
dependency.
