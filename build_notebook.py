#!/usr/bin/env python3
"""Generate setup.ipynb for the MapleChain Unity AI Gateway demo.

Keeping the notebook in one Python source keeps every cell reviewable and lets us
regenerate clean nbformat 4.5 JSON. Run:  python build_notebook.py
Cells are appended via md()/code(); the theme, idempotency, and verified API
shapes all live here.
"""
import json

CELLS = []


def _id():
    # Stable notebook ids keep regeneration byte-for-byte reproducible. Random UUIDs
    # made an unchanged build_notebook.py rewrite every cell in setup.ipynb.
    return f"cell-{len(CELLS) + 1:02d}"


def md(src: str):
    CELLS.append({
        "cell_type": "markdown",
        "id": _id(),
        "metadata": {},
        "source": src.strip("\n").splitlines(keepends=True),
    })


def code(src: str):
    CELLS.append({
        "cell_type": "code",
        "id": _id(),
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": src.strip("\n").splitlines(keepends=True),
    })


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
md(r"""
# MapleChain — Unity AI Gateway end-to-end demo

**MapleChain** is a fictional Canadian food-supply business (ambiguously a grocery
retailer *or* a CPG company) whose customers are Canadian restaurants. This single
notebook stands up an **idempotent** demo of the **new Unity AI Gateway** — where the
gateway is a set of **first-class Unity Catalog securables** governed alongside your data. It
creates all four object types — **Model Service, Model Provider Service, MCP Service, and Agent
Service**. The Microsoft Foundry provider example is optional and parameter-driven. Re-run any
cell — or the whole notebook — safely.

> This is the **new** gateway (`w.ai_gateway.*` → UC objects), **not** the legacy
> per-endpoint `serving-endpoints put-ai-gateway` config. Routing is **keyless** (across the
> workspace's `system.ai.*` pay-per-token model services) — no serving endpoint, no secrets.

| Section | UAIG capability shown |
|---|---|
| §1 | UC foundation + mock supply-chain data |
| §2 | **MCP Services in UC** (managed: UC functions + Genie; custom: an App-hosted MCP server → UC HTTP connection → **MCP Service**) + **service policies** (guardrail UDFs + grants) |
| §3 | **Model Service** (UC object): routing / A-B split, fallback, rate limits, usage tracking, inference table |
| §3b | Optional Microsoft Foundry **Model Provider Service** |
| §4 | Register a supplier-risk **ML model** + deploy the agent App + wrap it as an **Agent Service** |
| §5 | Exercise the Model Service (`/ai-gateway/mlflow/v1`, request tags, rate limit) + query the agent |
| §6 | Observability (`system.ai_gateway.usage` + inference table) + governance recap |

**Maturity** — GA: Model / Model Provider / MCP Services, rate limits, usage tracking,
inference tables, traffic split / fallback, UC classical-model registration. *Beta*: Service
Policies (attachment is UI-only), Agent Service, `external_model_spend`. *Public Preview*:
Genie programmatic create. Beta/Preview steps degrade gracefully so the notebook always completes.
""")

# ---------------------------------------------------------------------------
# §0 params + bootstrap
# ---------------------------------------------------------------------------
md(r"""
## §0 — Parameters & bootstrap

Everything is parameterized by `catalog` / `schema`. The other widgets name the
demo assets so re-runs are stable. Missing libraries (`mlflow`, `databricks-agents`,
`databricks-langchain`) are installed in-session.
""")

code(r"""
# `catalog`/`schema` are the only location-specific knobs. The canonical run is
# `databricks bundle run setup` (see databricks.yml), which passes them as base_parameters from
# the single bundle var.catalog/var.schema — so these defaults only apply to manual/interactive runs.
dbutils.widgets.text("catalog", "brlui", "Catalog")
dbutils.widgets.text("schema", "uaig_demo", "Schema")
dbutils.widgets.text("model_service", "maplechain_custom_ms", "Model Service name (in schema)")
dbutils.widgets.text("ml_model", "supplier_risk_model", "Classical ML model name (in schema)")
dbutils.widgets.text("genie_space_title", "MapleChain Supply Chain", "Genie space title")
dbutils.widgets.text("warehouse_id", "", "SQL warehouse id (blank = auto-pick)")
dbutils.widgets.text("secret_scope", "maplechain_demo", "Secret scope (SP OAuth client secret)")
dbutils.widgets.text("gateway_sp", "maplechain-gateway-sp", "Gateway service principal name")
dbutils.widgets.text("foundry_base_url", "", "Microsoft Foundry inference/project base URL")
dbutils.widgets.text("foundry_model", "", "Microsoft Foundry model/deployment target")
dbutils.widgets.text("foundry_secret_scope", "", "Secret scope containing the Foundry API key")
dbutils.widgets.text("foundry_secret_key", "", "Secret key containing the Foundry API key")
dbutils.widgets.text("azure_openai_base_url", "", "Azure OpenAI resource base URL")
dbutils.widgets.text("azure_openai_model", "", "Azure OpenAI deployment/model target")
dbutils.widgets.text("azure_openai_secret_scope", "", "Secret scope containing the Azure OpenAI API key")
dbutils.widgets.text("azure_openai_secret_key", "", "Secret key containing the Azure OpenAI API key")
""")

code(r"""
# %pip install is a no-op on re-run if versions already satisfied.
# databricks-sdk is PINNED to ==0.125.0 — that's where the w.ai_gateway UC objects
# (Model/MCP/**Agent** Services) all live in databricks.sdk.service.catalog. This must be an
# EXACT pin, not a floor: a bare ">=0.125" with -U resolves to the newest SDK, and newer
# releases (verified: 0.136.0) have REMOVED the Beta AgentService classes from that module, so
# §4-agent-service fails with `ImportError: cannot import name 'AgentService'`. 0.125.0 resolves
# cleanly alongside databricks-agents>=1.9 (dry-run verified). Bump this pin only after
# re-verifying that the target SDK still exports AgentService/AgentServiceConfig from catalog.
%pip install -qU "mlflow>=3.10" "databricks-agents>=1.9" "databricks-langchain>=0.17" "langgraph>=1.1" "databricks-sdk==0.125.0" openai faker
dbutils.library.restartPython()
""")

code(r"""
import json, time
from databricks.sdk import WorkspaceClient

catalog        = dbutils.widgets.get("catalog")
schema         = dbutils.widgets.get("schema")
ms_name        = dbutils.widgets.get("model_service")          # Model Service id (in schema)
ml_model       = dbutils.widgets.get("ml_model")
genie_title    = dbutils.widgets.get("genie_space_title")
secret_scope   = dbutils.widgets.get("secret_scope")           # holds the SP OAuth client secret
gateway_sp     = dbutils.widgets.get("gateway_sp")             # SP that the HTTP connections authenticate as
foundry_base_url = dbutils.widgets.get("foundry_base_url").strip()
foundry_model = dbutils.widgets.get("foundry_model").strip()
foundry_secret_scope = dbutils.widgets.get("foundry_secret_scope").strip()
foundry_secret_key = dbutils.widgets.get("foundry_secret_key").strip()
azure_openai_base_url = dbutils.widgets.get("azure_openai_base_url").strip()
azure_openai_model = dbutils.widgets.get("azure_openai_model").strip()
azure_openai_secret_scope = dbutils.widgets.get("azure_openai_secret_scope").strip()
azure_openai_secret_key = dbutils.widgets.get("azure_openai_secret_key").strip()
FQ             = f"`{catalog}`.`{schema}`"                      # backtick-quoted for SQL
FQN            = f"{catalog}.{schema}"                          # plain, for names/URLs
MS_FQN         = f"{FQN}.{ms_name}"                             # Model Service fully-qualified name
MS_RES         = f"model-services/{MS_FQN}"                     # UC resource name (get/update/delete)
GW_BASE        = None                                          # set below: OpenAI-compatible gateway base

w = WorkspaceClient()
host = w.config.host.rstrip("/")
GW_BASE = f"{host}/ai-gateway/mlflow/v1"
TOKEN_ENDPOINT = f"{host}/oidc/v1/token"                       # OAuth M2M token endpoint for HTTP connections
me   = w.current_user.me().user_name
print(f"Workspace    : {host}")
print(f"User         : {me}")
print(f"Target       : {FQN}")
print(f"Model Service: {MS_FQN}")
print(f"Gateway base : {GW_BASE}")

# Warehouse: use the widget, else first available.
warehouse_id = dbutils.widgets.get("warehouse_id").strip()
if not warehouse_id:
    whs = list(w.warehouses.list())
    # Genie supports PRO / serverless SQL warehouses, but not the serverless RT
    # (REYDEN) warehouse that can appear first in list results.
    supported = [wh for wh in whs if str(getattr(wh, "warehouse_type", "")).upper().endswith("PRO")]
    warehouse_id = (supported[0].id if supported else (whs[0].id if whs else None))
print(f"Warehouse    : {warehouse_id}")
""")

# ---------------------------------------------------------------------------
# §1 UC foundation + mock data
# ---------------------------------------------------------------------------
md(r"""
## §1 — Unity Catalog foundation + mock supply-chain data

Creates the catalog/schema (idempotent) and six deterministic MapleChain tables via
`CREATE OR REPLACE TABLE ... AS SELECT` over inline literals — no external data, no
randomness, so every re-run yields identical rows.
""")

code(r"""
# Catalog (CREATE CATALOG has no IF NOT EXISTS on all DBRs -> check-then-create)
existing = [r[0] for r in spark.sql("SHOW CATALOGS").collect()]
if catalog not in existing:
    spark.sql(f"CREATE CATALOG `{catalog}`")
    print(f"Created catalog: {catalog}")
else:
    print(f"Catalog exists: {catalog}")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQ}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {FQ}.`docs`")
print(f"Ready: {FQN} (+ volume `docs`)")
""")

code(r'''
# Six tables, deterministic literals. Themed for a Canadian food-supply business.
spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.suppliers AS SELECT * FROM VALUES
  ('SUP-001','Prairie Grain Collective','Dry Goods','Regina, SK',       0.12,'CAN-ORG-2019',4.6),
  ('SUP-002','Okanagan Orchards Ltd',   'Produce',  'Kelowna, BC',      0.28,'CAN-GAP-2021',4.2),
  ('SUP-003','Maritime Catch Co',       'Proteins', 'Halifax, NS',      0.41,'MSC-2020',    3.9),
  ('SUP-004','Laurentian Dairy Coop',   'Dairy',    'Trois-Rivieres, QC',0.19,'CAN-ORG-2018',4.7),
  ('SUP-005','Golden Horseshoe Greens', 'Produce',  'Leamington, ON',   0.33,'CAN-GAP-2022',4.0),
  ('SUP-006','Rocky Mountain Beef',     'Proteins', 'Calgary, AB',      0.22,'CRSB-2021',   4.5),
  ('SUP-007','Fraser Valley Poultry',   'Proteins', 'Abbotsford, BC',   0.37,'CAN-GAP-2020',3.8),
  ('SUP-008','Ontario Craft Mills',     'Dry Goods','Kitchener, ON',    0.15,'CAN-ORG-2023',4.4)
  AS t(supplier_id, supplier_name, category, location, risk_score, certification, quality_rating)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.products AS SELECT * FROM VALUES
  ('SKU-1001','Organic Red Fife Flour 20kg','Dry Goods','SUP-001', 42.50,'ambient'),
  ('SKU-1002','Gala Apples Case 18kg',      'Produce',  'SUP-002', 38.00,'refrigerated'),
  ('SKU-1003','Atlantic Salmon Fillet 5kg', 'Proteins', 'SUP-003', 96.75,'frozen'),
  ('SKU-1004','Salted Butter Blocks 10kg',  'Dairy',    'SUP-004', 71.20,'refrigerated'),
  ('SKU-1005','Greenhouse Tomatoes 10kg',   'Produce',  'SUP-005', 29.90,'refrigerated'),
  ('SKU-1006','AAA Ground Beef 10kg',       'Proteins', 'SUP-006', 88.40,'frozen'),
  ('SKU-1007','Whole Chicken Case 12kg',    'Proteins', 'SUP-007', 64.30,'frozen'),
  ('SKU-1008','Steel-Cut Oats 15kg',        'Dry Goods','SUP-008', 33.10,'ambient'),
  ('SKU-1009','Aged Cheddar Wheel 8kg',     'Dairy',    'SUP-004',102.60,'refrigerated'),
  ('SKU-1010','Mixed Salad Greens 6kg',     'Produce',  'SUP-005', 24.75,'refrigerated')
  AS t(sku, product_name, category, supplier_id, unit_cost_cad, storage)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.restaurant_customers AS SELECT * FROM VALUES
  ('CUST-501','Le Bistro Boreal',      'Montreal, QC', 'Fine Dining','contact@bistroboreal.ca','514-555-0142'),
  ('CUST-502','Maple & Oak Grill',     'Toronto, ON',  'Casual',     'orders@mapleoak.ca',     '416-555-0198'),
  ('CUST-503','Pacific Rim Noodle Bar','Vancouver, BC','Fast Casual','hello@pacrimnoodle.ca',  '604-555-0176'),
  ('CUST-504','Prairie Fire Steakhouse','Calgary, AB', 'Fine Dining','book@prairiefire.ca',    '403-555-0121'),
  ('CUST-505','Cafe Deux Rivieres',    'Ottawa, ON',   'Cafe',       'bonjour@deuxrivieres.ca','613-555-0155'),
  ('CUST-506','Harbourside Fish House','Halifax, NS',  'Casual',     'eat@harbourside.ca',     '902-555-0188')
  AS t(customer_id, restaurant_name, location, segment, contact_email, contact_phone)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.orders AS SELECT * FROM VALUES
  ('ORD-9001','CUST-501','SKU-1003', 12, DATE'2026-07-02','delivered'),
  ('ORD-9002','CUST-501','SKU-1004',  6, DATE'2026-07-02','delivered'),
  ('ORD-9003','CUST-502','SKU-1006', 20, DATE'2026-07-05','delivered'),
  ('ORD-9004','CUST-502','SKU-1001',  8, DATE'2026-07-06','in_transit'),
  ('ORD-9005','CUST-503','SKU-1007', 15, DATE'2026-07-08','in_transit'),
  ('ORD-9006','CUST-503','SKU-1010', 10, DATE'2026-07-08','processing'),
  ('ORD-9007','CUST-504','SKU-1006', 25, DATE'2026-07-09','processing'),
  ('ORD-9008','CUST-505','SKU-1002',  9, DATE'2026-07-10','processing'),
  ('ORD-9009','CUST-506','SKU-1003', 18, DATE'2026-07-11','pending'),
  ('ORD-9010','CUST-501','SKU-1009',  4, DATE'2026-07-12','pending')
  AS t(order_id, customer_id, sku, quantity, order_date, status)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.shipments AS SELECT * FROM VALUES
  ('SHP-7001','ORD-9001','Halifax, NS',  'Montreal, QC',  DATE'2026-07-03', 2,'delivered'),
  ('SHP-7002','ORD-9003','Calgary, AB',  'Toronto, ON',   DATE'2026-07-06', 3,'delivered'),
  ('SHP-7003','ORD-9004','Regina, SK',   'Toronto, ON',   DATE'2026-07-08', 2,'in_transit'),
  ('SHP-7004','ORD-9005','Abbotsford, BC','Vancouver, BC',DATE'2026-07-09', 1,'in_transit'),
  ('SHP-7005','ORD-9007','Calgary, AB',  'Calgary, AB',   DATE'2026-07-10', 1,'scheduled'),
  ('SHP-7006','ORD-9009','Halifax, NS',  'Halifax, NS',   DATE'2026-07-12', 1,'scheduled')
  AS t(shipment_id, order_id, origin, destination, ship_date, transit_days, status)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.inventory AS SELECT * FROM VALUES
  ('Toronto, ON',   'SKU-1001', 140),('Toronto, ON',   'SKU-1006', 60),
  ('Montreal, QC',  'SKU-1003',  30),('Montreal, QC',  'SKU-1004', 85),
  ('Vancouver, BC', 'SKU-1007',  45),('Vancouver, BC', 'SKU-1010',120),
  ('Calgary, AB',   'SKU-1006',  25),('Calgary, AB',   'SKU-1002', 70),
  ('Toronto, ON',   'SKU-1009',  18),('Vancouver, BC', 'SKU-1005', 95)
  AS t(warehouse, sku, units_on_hand)
""")

for t in ["suppliers","products","restaurant_customers","orders","shipments","inventory"]:
    n = spark.table(f"{FQ}.{t}").count()
    print(f"  {t:22s} {n:3d} rows")
print("MapleChain tables ready.")
''')

# ---------------------------------------------------------------------------
# §2 MCP objects + MCP policies
# ---------------------------------------------------------------------------
md(r"""
## §2 — MCP objects in Unity Catalog + MCP policies

Two ways an MCP server becomes governable in UC, both shown here:

1. **Managed MCP servers** *(Public Preview)* — no object to create; Databricks exposes
   existing UC securables as MCP tools over stable URLs, governed by ordinary UC grants:
   - UC functions → `…/api/2.0/mcp/functions/{catalog}/{schema}/{function}`
   - Genie space  → `…/api/2.0/mcp/genie/{space_id}`
2. **Custom MCP server** — the `mcp_app/` FastMCP server, deployed as a Databricks App and
   **registered in UC as an HTTP `connection`** (a first-class UC securable).

**MCP policies** = the governance around those tools: `GRANT EXECUTE` on the functions/
connection, plus an **ABAC policy** *(Public Preview)* on the schema.
""")

md(r"""
### §2a — Supply-chain UC functions (managed MCP tools)

`CREATE OR REPLACE FUNCTION` is idempotent. Each function is a governable UC object and is
automatically reachable through the managed MCP functions server.
""")

code(r'''
spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.get_supplier_risk(p_supplier_id STRING)
RETURNS TABLE(supplier_name STRING, category STRING, risk_score DOUBLE, certification STRING)
COMMENT 'Risk profile + certification for a MapleChain supplier.'
RETURN SELECT supplier_name, category, risk_score, certification
       FROM {FQ}.suppliers WHERE supplier_id = p_supplier_id
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.check_inventory(p_sku STRING)
RETURNS TABLE(warehouse STRING, units_on_hand INT)
COMMENT 'On-hand units of a SKU across MapleChain warehouses.'
RETURN SELECT warehouse, units_on_hand FROM {FQ}.inventory WHERE sku = p_sku
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.estimate_delivery_eta(p_order_id STRING)
RETURNS TABLE(order_id STRING, destination STRING, ship_date DATE, eta DATE, status STRING)
COMMENT 'Estimated delivery date for an order based on its shipment transit time.'
RETURN SELECT s.order_id, s.destination, s.ship_date,
              date_add(s.ship_date, s.transit_days) AS eta, s.status
       FROM {FQ}.shipments s WHERE s.order_id = p_order_id
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.lookup_restaurant_order_history(p_customer_id STRING)
RETURNS TABLE(order_id STRING, sku STRING, quantity INT, order_date DATE, status STRING)
COMMENT 'Recent orders placed by a restaurant customer.'
RETURN SELECT order_id, sku, quantity, order_date, status
       FROM {FQ}.orders WHERE customer_id = p_customer_id ORDER BY order_date DESC
""")

mcp_functions = ["get_supplier_risk","check_inventory","estimate_delivery_eta","lookup_restaurant_order_history"]
print("Created UC functions:", ", ".join(mcp_functions))

# Smoke-test one function so the demo shows real output.
display(spark.sql(f"SELECT * FROM {FQ}.get_supplier_risk('SUP-003')"))

# Managed MCP URL for the UC-functions server (scoped to this schema).
mcp_functions_url = f"{host}/api/2.0/mcp/functions/{catalog}/{schema}"
print("Managed MCP (functions):", mcp_functions_url)
''')

md(r"""
### §2b — Genie space over the MapleChain data (managed MCP tool) — *Public Preview*

Programmatic Genie-space creation is the least-stable surface here, so it is best-effort:
on failure the notebook prints manual steps and keeps going.

> **Managed vs. registered MCP.** A Genie space is a **Databricks-managed** MCP server —
> exposed automatically at `/api/2.0/mcp/genie/{space_id}` and already governed by Unity
> Catalog. You **cannot** (and need not) register it as an `MCP Service`: `create_mcp_service`
> is only for **external/custom** MCP servers reached through a UC HTTP connection (that's the
> `mcp_app/` server in §2c). Managed MCP servers (Genie, UC functions, Vector Search) have no
> connection and are consumed directly at their managed URLs.
""")

code(r'''
genie_space_id = None
try:
    # list_spaces() is PAGINATED — walk all pages so the idempotency check can't miss an
    # existing space (and create a duplicate) just because it's on a later page.
    existing, _tok = {}, None
    while True:
        _resp = w.genie.list_spaces(page_token=_tok) if _tok else w.genie.list_spaces()
        for s in (_resp.spaces or []):
            existing[s.title] = s.space_id
        _tok = getattr(_resp, "next_page_token", None)
        if not _tok:
            break
    if genie_title in existing:
        genie_space_id = existing[genie_title]
        print(f"Genie space exists: {genie_title} ({genie_space_id})")
    else:
        # serialized_space is a versioned Genie *export* proto, NOT a free-form config:
        #   - top-level "version" is required (1 or 2),
        #   - tables go under data_sources.tables as {"identifier": "cat.sch.table"},
        #   - the tables list MUST be sorted by identifier,
        #   - title/description are separate args (they are NOT valid inside serialized_space).
        idents = sorted(f"{FQN}.{t}" for t in
            ["suppliers","products","restaurant_customers","orders","shipments","inventory"])
        serialized = json.dumps({
            "version": 1,
            "data_sources": {"tables": [{"identifier": i} for i in idents]},
        })
        created = w.genie.create_space(
            warehouse_id=warehouse_id,
            serialized_space=serialized,
            title=genie_title,
            description="Natural-language Q&A over MapleChain supply-chain tables.",
        )
        genie_space_id = created.space_id
        print(f"Created Genie space: {genie_title} ({genie_space_id})")
except Exception as e:
    print("Genie space auto-create skipped (Public Preview API).")
    print(f"  reason: {type(e).__name__}: {e}")
    print(f"  Manual: Genie > New space > warehouse {warehouse_id} > add tables from {FQN}")

if genie_space_id:
    print("Genie space UI :", f"{host}/genie/rooms/{genie_space_id}")
    print("Managed MCP (genie):", f"{host}/api/2.0/mcp/genie/{genie_space_id}")
''')

md(r"""
### §2c-sp — Gateway service principal + OAuth secret (for the App-backed connections)

The custom MCP server and the agent App are both **Databricks Apps**, reached over HTTPS with
an OAuth login. To let the gateway's UC **HTTP connections** call them, we use **OAuth
Machine-to-Machine** (client-credentials): a dedicated service principal, its client secret
stored once in a **secret scope**, and referenced from `CREATE CONNECTION` via `secret(...)`
— so **no plaintext token is ever embedded** in the connection object.

> This is fully scriptable — no UI OAuth handshake. (Only the *interactive* DCR / User-to-Machine
> auth types are UI-only; **bearer token** and **OAuth M2M** are creatable from SQL/SDK/CLI.)
> Idempotent: the SP, scope, secret, and app grants are all get-else-create / merge, and a new
> OAuth secret is minted **only** when the scope key is missing (mints are limited & write-once).
""")

code(r'''
from databricks.sdk.service import apps as _apps

APP_MCP   = "mcp-maplechain"      # Databricks App names (databricks.yml, name_prefix="")
APP_AGENT = "maplechain-agent"

# 1) Resolve the gateway service principal created by tasks/bootstrap_gateway_auth.py.
gw_sp = next((s for s in w.service_principals.list() if s.display_name == gateway_sp), None)
if gw_sp is None:
    raise RuntimeError(
        f"Missing {gateway_sp}. Run tasks/bootstrap_gateway_auth.py locally before setup."
    )
print(f"Service principal exists: {gateway_sp} (app_id={gw_sp.application_id})")
gw_sp_app_id = gw_sp.application_id

# 2) Verify the locally bootstrapped secret scope and keys. A serverless notebook runtime is not
# authorized to mint account-level service-principal credentials.
existing_keys = {s.key for s in (w.secrets.list_secrets(scope=secret_scope) or [])}
missing_keys = {"sp_client_id", "sp_secret"} - existing_keys
if missing_keys:
    raise RuntimeError(
        f"Missing {secret_scope} keys {sorted(missing_keys)}. "
        "Run tasks/bootstrap_gateway_auth.py locally before setup."
    )
print(f"OAuth credentials present in secret scope {secret_scope} (reusing)")

# 3) Grant the SP CAN_USE on both Apps so its token is accepted by the App backends.
for app_name in (APP_MCP, APP_AGENT):
    try:
        w.apps.update_permissions(app_name=app_name, access_control_list=[
            _apps.AppAccessControlRequest(service_principal_name=gw_sp_app_id,
                                          permission_level=_apps.AppPermissionLevel.CAN_USE)])
        print(f"Granted CAN_USE on app '{app_name}' to {gateway_sp}")
    except Exception as e:
        print(f"(grant on '{app_name}' skipped — deploy the app first: {type(e).__name__})")

# 4) Reusable helper: idempotent UC HTTP connection to a Databricks App via OAuth M2M.
def ensure_app_http_connection(conn_name, app_name, base_path):
    """Get-else-create a UC HTTP connection to <app_name>'s URL (OAuth M2M via secret()).
    Connections are metastore-level securables -> the resource name is 'connections/<name>'
    (NOT catalog.schema-qualified). Returns that resource name, or None if the App isn't up."""
    app = next((a for a in w.apps.list() if a.name == app_name), None)
    app_url = (getattr(app, "url", None) or "").rstrip("/") if app else ""
    if not app_url:
        print(f"App '{app_name}' not deployed yet — skipping connection '{conn_name}'.")
        return None
    try:
        w.connections.get(name=conn_name)
        print(f"UC connection exists: {conn_name} -> {app_url}{base_path}")
        return f"connections/{conn_name}"
    except Exception:
        pass
    host_only = app_url.replace("https://", "").replace("http://", "")
    # secret() keeps the client secret OUT of the connection object (referenced, not embedded).
    spark.sql(f"""
        CREATE CONNECTION `{conn_name}` TYPE HTTP
        OPTIONS (
          host 'https://{host_only}', port '443', base_path '{base_path}',
          client_id secret('{secret_scope}','sp_client_id'),
          client_secret secret('{secret_scope}','sp_secret'),
          oauth_scope 'all-apis',
          token_endpoint '{TOKEN_ENDPOINT}'
        )
    """)
    print(f"Created UC connection: {conn_name} -> {app_url}{base_path} (OAuth M2M)")
    return f"connections/{conn_name}"
''')

md(r"""
### §2c — Custom MCP server → UC HTTP connection → **MCP Service**

The `mcp_app/` server is deployed as a Databricks App (§4/README). It becomes a first-class
gateway object in two steps: (1) the UC **HTTP connection** from §2c-sp (`ensure_app_http_connection`),
then (2) an **MCP Service** (`w.ai_gateway.create_mcp_service`) wrapping that connection. Both are
idempotent get-else-create and no-op cleanly if the App isn't deployed yet. We also list the
system MCP Services (`system.ai.github`, …) to show the shared object model.
""")

code(r'''
from databricks.sdk.service.catalog import (
    McpService, McpServiceConfig, McpServiceConfigSourceConnection)

# System MCP Services already governed as UC objects:
sys_mcp = [m.name.split("/")[-1] for m in w.ai_gateway.list_mcp_services()
           if m.name.startswith("mcp-services/system.ai.")]
print("System MCP Services:", sys_mcp[:8])

mcp_conn_name = "maplechain_custom_mcp"           # UC connection id (metastore-level)
mcp_svc_id    = "maplechain_mcp"                  # MCP Service id (in schema)
conn_res = ensure_app_http_connection(mcp_conn_name, APP_MCP, "/mcp")

if conn_res:
    mcp_svc_res = f"mcp-services/{FQN}.{mcp_svc_id}"
    try:
        w.ai_gateway.get_mcp_service(name=mcp_svc_res)
        print(f"MCP Service exists: {FQN}.{mcp_svc_id}")
    except Exception:
        mcp_svc = McpService(config=McpServiceConfig(
            source_connection=McpServiceConfigSourceConnection(name=conn_res),
            include_tool_selectors=["*"]))
        w.ai_gateway.create_mcp_service(mcp_service=mcp_svc, parent=f"schemas/{FQN}",
                                        mcp_service_id=mcp_svc_id)
        print(f"Created MCP Service (UC object): {FQN}.{mcp_svc_id}")
    # Grant EXECUTE so it's usable + visible in Catalog Explorer (owner-only default hides it).
    try:
        from databricks.sdk.service.catalog import PermissionsChange, Privilege
        w.grants.update(securable_type="mcp_service", full_name=f"{FQN}.{mcp_svc_id}",
                        changes=[PermissionsChange(principal=me, add=[Privilege.EXECUTE])])
        print(f"Granted EXECUTE on MCP Service to {me}")
    except Exception as e:
        print(f"(MCP Service grant skipped: {type(e).__name__})")
    print("Custom MCP endpoint:", f"{host}/api/2.0/mcp/... (via connection {mcp_conn_name})")
''')

md(r"""
### §2d — MCP policies: grants + fine-grained governance

Governance over the gateway tools, at three levels:

1. **`GRANT EXECUTE`** on the functions — managed MCP inherits these grants, so a principal
   can only invoke tools it can execute.
2. **Column mask** *(GA)* — a UC masking function bound to `restaurant_customers.contact_email`
   so PII is redacted for non-admins even when reached through an MCP tool (idempotent SET MASK).
3. **Service Policies** *(Beta — guardrails)* — the new gateway governs request/response content
   with policies that return `ALLOW` / `DENY` / `ASK`. Custom policies are SQL UDFs
   (`event VARIANT → VARIANT`); built-ins live in `system.ai.block_*`. We **create** the custom
   policy UDFs here; **attaching** them to a Model/MCP Service is currently **UI-only** (the
   notebook prints the exact steps). Nothing here asserts a block, since attachment is manual.
""")

code(r'''
demo_principal = "account users"
for fn in mcp_functions:
    try:
        spark.sql(f"GRANT EXECUTE ON FUNCTION {FQ}.{fn} TO `{demo_principal}`")
    except Exception as e:
        print(f"  grant on {fn} skipped: {e}")
print(f"Granted EXECUTE on {len(mcp_functions)} functions to `{demo_principal}`.")

# (2) GA column mask on restaurant PII.
spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.mask_email(email STRING)
RETURNS STRING
COMMENT 'Column-mask helper: hides contact email from non-admins.'
RETURN CASE WHEN is_account_group_member('admins') THEN email ELSE '***REDACTED***' END
""")
spark.sql(f"ALTER TABLE {FQ}.restaurant_customers ALTER COLUMN contact_email DROP MASK")
spark.sql(f"ALTER TABLE {FQ}.restaurant_customers "
          f"ALTER COLUMN contact_email SET MASK {FQ}.mask_email")
print("Applied GA column mask on restaurant_customers.contact_email.")
display(spark.sql(f"SELECT customer_id, contact_email FROM {FQ}.restaurant_customers LIMIT 3"))

# (3) Service Policies (Beta guardrails) as SQL UDFs. Creating them is fully supported;
# attaching is UI-only during Beta.
spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.deny_competitor_pricing(event VARIANT)
RETURNS VARIANT
COMMENT 'Service policy: block requests probing competitor pricing / insider info.'
RETURN CASE
  WHEN lower(event:content::string) LIKE '%competitor_pricing%'
    OR lower(event:content::string) LIKE '%insider%'
  THEN to_variant_object(named_struct('result','DENY','reason','Competitor/insider queries are not permitted.'))
  ELSE to_variant_object(named_struct('result','ALLOW','reason',''))
END
""")
spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.ask_before_bulk_delete(event VARIANT)
RETURNS VARIANT
COMMENT 'Service policy: require human approval before a delete-style tool call.'
RETURN CASE
  WHEN event:context.tool.name::string LIKE '%delete%'
  THEN to_variant_object(named_struct('result','ASK','reason','Deletion requires human approval.'))
  ELSE to_variant_object(named_struct('result','ALLOW','reason',''))
END
""")
print("Created custom service-policy UDFs: deny_competitor_pricing, ask_before_bulk_delete")
print("Built-in guardrail policies available: system.ai.block_unsafe_content, "
      "system.ai.block_jailbreak, system.ai.block_hallucination")
print("Attach (Beta, UI-only): AI Gateway > <service> > Policies > New policy > "
      f"pick built-in or {FQN}.deny_competitor_pricing > set phase/rank/principals.")
''')

# ---------------------------------------------------------------------------
# §3 Model Service (NEW Unity AI Gateway)
# ---------------------------------------------------------------------------
md(r"""
## §3 — Model Service (the core — a Unity Catalog object)

A **Model Service** is a first-class UC securable (`catalog.schema.name`) created via
`w.ai_gateway.create_model_service(...)`. Ours, `maplechain_custom_ms`, routes **keyless**
across the workspace's `system.ai.*` pay-per-token models — no serving endpoint, no secrets:

- **Deterministic routing** — one tool-capable primary model for reliable agent turns.
- **Fallback** — `routing.fallback.destinations` (ordered) if the primary path fails.
- **Rate limits** — `USER_DEFAULT` 60/min + `SERVICE` 1000/min.
- **Usage tracking + inference table** — payload logging to `<prefix>_payload`.

Query it at `https://<host>/ai-gateway/mlflow/v1` with `model="<catalog.schema.name>"`.
""")

code(r'''
from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import (
    ModelService, ModelServiceConfig, ModelServiceConfigRoutingConfig,
    ModelServiceConfigDestinationConfig,
    ModelServiceConfigDestinationConfigDestinationType as DT,
    ModelServiceConfigPayPerTokenConfig, ModelServiceConfigFallbackConfig,
    InferenceTableConfig, RateLimit,
    RateLimitRateLimitKey as RLK, RateLimitRateLimitRenewalPeriod as RLP, FieldMask)

PARENT = f"schemas/{FQN}"

# Resolve valid keyless model refs from the live system.ai.* model services (names are
# irregular, e.g. databricks-claude-sonnet-5 vs gpt-oss-120b — never hard-code them).
def _system_model_refs():
    refs = []
    for ms in w.ai_gateway.list_model_services():
        if not ms.name.startswith("model-services/system.ai."):
            continue
        try:
            for d in (w.ai_gateway.get_model_service(name=ms.name).config.routing.destinations or []):
                if d.pay_per_token_config:
                    refs.append(d.pay_per_token_config.model)
        except Exception:
            pass
    return refs

def _pick(refs, *keywords):
    for kw in keywords:
        for r in refs:
            if kw in r:
                return r
    return None

refs = _system_model_refs()
primary   = _pick(refs, "databricks-claude-sonnet-5", "databricks-claude-sonnet-4-5", "sonnet")
fallback  = _pick(refs, "databricks-claude-haiku", "haiku")
assert primary and fallback, f"could not resolve model refs: {primary},{fallback}"
print(f"primary (100%): {primary}")
print(f"fallback      : {fallback}")

def _dest(name, model_ref, pct):
    return ModelServiceConfigDestinationConfig(
        name=name, destination_type=DT.DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL,
        traffic_percentage=pct,
        pay_per_token_config=ModelServiceConfigPayPerTokenConfig(model=model_ref))

svc = ModelService(comment="MapleChain gateway model service (demo)", config=ModelServiceConfig(
    routing=ModelServiceConfigRoutingConfig(
        destinations=[_dest("primary", primary, 100)],
        fallback=ModelServiceConfigFallbackConfig(destinations=[_dest("fallback", fallback, 100)])),
    rate_limits=[
        RateLimit(key=RLK.RATE_LIMIT_KEY_USER_DEFAULT,
                  renewal_period=RLP.RATE_LIMIT_RENEWAL_PERIOD_MINUTE, requests=60),
        RateLimit(key=RLK.RATE_LIMIT_KEY_SERVICE,
                  renewal_period=RLP.RATE_LIMIT_RENEWAL_PERIOD_MINUTE, requests=1000),
    ],
    inference_table=InferenceTableConfig(parent=PARENT, table_name_prefix=ms_name)))
''')

code(r'''
# Idempotent create-or-update. On first run the inference-table create can hit an orphaned
# <prefix>_payload table left by a prior/deleted service — drop it once and retry.
def _create_service():
    return w.ai_gateway.create_model_service(
        model_service=svc, parent=PARENT, model_service_id=ms_name)

try:
    w.ai_gateway.get_model_service(name=MS_RES)
    exists = True
except NotFound:
    exists = False

if exists:
    w.ai_gateway.update_model_service(
        name=MS_RES, model_service=svc, update_mask=FieldMask(field_mask=["config"]))
    print(f"Updated Model Service: {MS_FQN}")
else:
    try:
        _create_service()
    except Exception as e:
        if "already exists" in str(e).lower():
            orphan = f"{FQ}.{ms_name}_payload"
            print(f"Dropping orphaned payload table {orphan} and retrying...")
            spark.sql(f"DROP TABLE IF EXISTS {orphan}")
            _create_service()
        else:
            raise
    print(f"Created Model Service: {MS_FQN}")

got = w.ai_gateway.get_model_service(name=MS_RES)
r = got.config.routing
print("  routing   :", [(d.name, d.traffic_percentage) for d in (r.destinations or [])])
print("  fallback  :", [d.name for d in (r.fallback.destinations if r.fallback else [])])
print("  rate_limit:", [(rl.key.value, rl.requests) for rl in (got.config.rate_limits or [])])
print("  api_types :", got.supported_api_types)

# Consolidation migration: remove the former agent-only duplicate if an earlier version created it.
AGENT_MS_NAME = "maplechain_agent_ms"
AGENT_MS_FQN = f"{FQN}.{AGENT_MS_NAME}"
AGENT_MS_RES = f"model-services/{AGENT_MS_FQN}"
try:
    w.ai_gateway.get_model_service(name=AGENT_MS_RES)
    w.ai_gateway.delete_model_service(name=AGENT_MS_RES)
    print(f"Removed superseded Model Service: {AGENT_MS_FQN}")
except NotFound:
    pass

# Grant EXECUTE on the Model Service to a demo principal (UC governance). Model services are
# not yet SQL-grantable (no `GRANT ... ON MODEL SERVICE`), so use the grants API with
# securable_type="model_service".
try:
    from databricks.sdk.service.catalog import PermissionsChange, Privilege
    w.grants.update(securable_type="model_service", full_name=MS_FQN,
                    changes=[PermissionsChange(principal="account users", add=[Privilege.EXECUTE])])
    print("  granted EXECUTE on the Model Service to `account users`")
except Exception as e:
    print(f"  EXECUTE grant note: {type(e).__name__}: {str(e)[:120]}")
''')

# ---------------------------------------------------------------------------
# §3b Microsoft Foundry Model Provider Service
# ---------------------------------------------------------------------------
md(r"""
### §3b — Microsoft Foundry Model Provider Service *(optional)*

This example is created when all four deployment inputs are supplied: Foundry base URL, model
target, and the Databricks secret scope/key holding the Foundry API key. The credential is read
at runtime and sent over the authenticated Databricks API; it is never written into this notebook
or bundle state. Leaving the inputs blank safely skips this optional resource.
""")

code(r'''
foundry_inputs = {
    "foundry_base_url": foundry_base_url,
    "foundry_model": foundry_model,
    "foundry_secret_scope": foundry_secret_scope,
    "foundry_secret_key": foundry_secret_key,
}
provided = [k for k, v in foundry_inputs.items() if v]
if provided and len(provided) != len(foundry_inputs):
    missing = [k for k, v in foundry_inputs.items() if not v]
    raise ValueError(f"Microsoft Foundry configuration is partial; missing: {', '.join(missing)}")

if not provided:
    print("Microsoft Foundry provider service skipped (pass all foundry_* bundle variables to enable it).")
else:
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service.catalog import (
        FieldMask, ModelProviderService, ModelProviderServiceConfig,
        ModelProviderServiceConfigExternalModelProviderType as ProviderType,
        ModelProviderServiceConfigMicrosoftFoundryProviderConfig,
        ModelProviderServiceConfigMicrosoftFoundryProviderDirectConfig,
        ModelProviderServiceConfigModelTargetConfig,
        ModelProviderServiceConfigProviderSecret,
    )
    provider_id = "maplechain_foundry"
    provider_fqn = f"{FQN}.{provider_id}"
    provider_res = f"model-provider-services/{provider_fqn}"
    api_key = dbutils.secrets.get(scope=foundry_secret_scope, key=foundry_secret_key)
    provider = ModelProviderService(
        comment="MapleChain Microsoft Foundry model provider (bundle-managed example)",
        config=ModelProviderServiceConfig(
            provider_type=ProviderType.EXTERNAL_MODEL_PROVIDER_TYPE_MICROSOFT_FOUNDRY,
            microsoft_foundry=ModelProviderServiceConfigMicrosoftFoundryProviderConfig(
                direct=ModelProviderServiceConfigMicrosoftFoundryProviderDirectConfig(
                    base_url=foundry_base_url,
                    api_key=ModelProviderServiceConfigProviderSecret(plaintext=api_key),
                )
            ),
            targets=[ModelProviderServiceConfigModelTargetConfig(model=foundry_model)],
        ),
    )
    try:
        w.ai_gateway.get_model_provider_service(name=provider_res)
        w.ai_gateway.update_model_provider_service(
            name=provider_res, model_provider_service=provider,
            update_mask=FieldMask(field_mask=["comment", "config"]),
        )
        action = "Updated"
    except NotFound:
        w.ai_gateway.create_model_provider_service(
            model_provider_service=provider, parent=f"schemas/{FQN}",
            model_provider_service_id=provider_id,
        )
        action = "Created"
    print(f"{action} Microsoft Foundry Model Provider Service: {provider_fqn}")
''')

# ---------------------------------------------------------------------------
# §3c Azure OpenAI Model Provider Service
# ---------------------------------------------------------------------------
md(r"""
### §3c — Azure OpenAI Model Provider Service *(optional)*

This reproduces `maplechain_azure_mps` when all four `azure_openai_*` deployment inputs are
provided. The API key is read from a Databricks secret at runtime and is never stored in source
or bundle state. The service forwards headers, query parameters, and unmanaged paths; restrict
the configured target explicitly; records an inference table; and applies the same service/user
token limits as the reference deployment.
""")

code(r'''
azure_inputs = {
    "azure_openai_base_url": azure_openai_base_url,
    "azure_openai_model": azure_openai_model,
    "azure_openai_secret_scope": azure_openai_secret_scope,
    "azure_openai_secret_key": azure_openai_secret_key,
}
azure_provided = [k for k, v in azure_inputs.items() if v]
if azure_provided and len(azure_provided) != len(azure_inputs):
    missing = [k for k, v in azure_inputs.items() if not v]
    raise ValueError(f"Azure OpenAI configuration is partial; missing: {', '.join(missing)}")

if not azure_provided:
    print("Azure OpenAI provider service skipped (pass all azure_openai_* bundle variables to enable it).")
else:
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service.catalog import (
        FieldMask, InferenceTableConfig, ModelProviderService, ModelProviderServiceConfig,
        ModelProviderServiceConfigAzureOpenAiProviderConfig,
        ModelProviderServiceConfigAzureOpenAiProviderDirectConfig,
        ModelProviderServiceConfigExternalModelProviderType as ProviderType,
        ModelProviderServiceConfigModelTargetConfig,
        ModelProviderServiceConfigProviderSecret, RateLimit,
        RateLimitRateLimitKey as RLK, RateLimitRateLimitRenewalPeriod as RLP,
    )
    azure_provider_id = "maplechain_azure_mps"
    azure_provider_fqn = f"{FQN}.{azure_provider_id}"
    azure_provider_res = f"model-provider-services/{azure_provider_fqn}"
    azure_api_key = dbutils.secrets.get(
        scope=azure_openai_secret_scope, key=azure_openai_secret_key)
    azure_provider = ModelProviderService(
        comment="MapleChain Azure OpenAI model provider (bundle-managed example)",
        config=ModelProviderServiceConfig(
            provider_type=ProviderType.EXTERNAL_MODEL_PROVIDER_TYPE_AZURE_OPENAI,
            azure_openai=ModelProviderServiceConfigAzureOpenAiProviderConfig(
                direct=ModelProviderServiceConfigAzureOpenAiProviderDirectConfig(
                    base_url=azure_openai_base_url,
                    api_key=ModelProviderServiceConfigProviderSecret(plaintext=azure_api_key),
                )),
            allow_all_targets=False,
            forward_headers=True,
            forward_query_parameters=True,
            forward_unmanaged_paths=True,
            targets=[ModelProviderServiceConfigModelTargetConfig(
                model=azure_openai_model,
                native_api_types=["openai/v1/chat/completions", "openai/v1/responses"],
            )],
            inference_table=InferenceTableConfig(
                parent=f"schemas/{FQN}", table_name_prefix=azure_provider_id, disabled=False),
            rate_limits=[
                RateLimit(key=RLK.RATE_LIMIT_KEY_SERVICE,
                          renewal_period=RLP.RATE_LIMIT_RENEWAL_PERIOD_HOUR,
                          tokens=1_000_000),
                RateLimit(key=RLK.RATE_LIMIT_KEY_USER_DEFAULT,
                          renewal_period=RLP.RATE_LIMIT_RENEWAL_PERIOD_MINUTE,
                          tokens=1_000),
            ],
        ),
    )
    try:
        w.ai_gateway.get_model_provider_service(name=azure_provider_res)
        w.ai_gateway.update_model_provider_service(
            name=azure_provider_res, model_provider_service=azure_provider,
            update_mask=FieldMask(field_mask=["comment", "config"]),
        )
        azure_action = "Updated"
    except NotFound:
        w.ai_gateway.create_model_provider_service(
            model_provider_service=azure_provider, parent=f"schemas/{FQN}",
            model_provider_service_id=azure_provider_id,
        )
        azure_action = "Created"
    print(f"{azure_action} Azure OpenAI Model Provider Service: {azure_provider_fqn}")
''')

# ---------------------------------------------------------------------------
# §4 register classical ML model + deploy agent app
# ---------------------------------------------------------------------------
md(r"""
## §4 — Register a classical ML model + deploy the agent as a Databricks App

Two complementary artifacts:

1. **UC-registered ML model** — a scikit-learn regression pipeline registered as
   `catalog.schema.<ml_model>`, with alias `@prod`. It predicts supplier risk from MapleChain's
   supplier attributes and demonstrates conventional governed ML without representing the agent
   as a model.
2. **Deployed App** — the `agent_app/` LangGraph agent, deployed as a Databricks App. Its LLM is
   the **Model Service** (via `/ai-gateway/mlflow/v1`), and its tools are **all three** MCP
   sources from §2: the managed **UC functions** (per-function), the managed **Genie** MCP
   (`GENIE_SPACE_ID`), and the custom **MCP Service** (`MCP_SERVICE`, gateway-governed).
3. **Gateway Agent Service** — the deployed App is also wrapped as a UC **Agent Service**.

The conversational agent remains application code in `agent_app/` and is exposed through the
gateway Agent Service; it is intentionally not registered as a UC model.
""")

code(r'''
import mlflow, mlflow.sklearn
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

mlflow.set_registry_uri("databricks-uc")
model_fqn = f"{FQN}.{ml_model}"
training = spark.table(f"{FQN}.suppliers").select(
    "category", "location", "certification", "quality_rating", "risk_score"
).toPandas()
X = training.drop(columns=["risk_score"])
X["quality_rating"] = X["quality_rating"].astype(float)
y = training["risk_score"].astype(float)
categorical = ["category", "location", "certification"]
pipeline = Pipeline([
    ("features", ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical),
    ], remainder="passthrough")),
    ("regressor", RandomForestRegressor(n_estimators=80, max_depth=4, random_state=42)),
])
pipeline.fit(X, y)

with mlflow.start_run(run_name="maplechain-supplier-risk"):
    predictions = pipeline.predict(X)
    mlflow.log_metric("training_mae", float(abs(predictions - y).mean()))
    info = mlflow.sklearn.log_model(
        sk_model=pipeline, name="supplier_risk_model", input_example=X.head(3),
        registered_model_name=model_fqn,
        # This model is trained in this cell from repo-owned deterministic data. MLflow 3.10's
        # skops serializer requires these two reviewed sklearn implementation types explicitly.
        skops_trusted_types=[
            "sklearn.compose._column_transformer._RemainderColsList",
            "sklearn.tree._tree.Tree",
        ],
    )

version = info.registered_model_version
MlflowClient(registry_uri="databricks-uc").set_registered_model_alias(model_fqn, "prod", version)
print(f"Registered classical ML model: {model_fqn} v{version} (alias @prod)")
''')

md(r"""
### Deploy the agent + custom-MCP as Databricks Apps

App deploy needs the local source + CLI, so run these from a terminal in this repo. Apps must
be **started** before source deploy, and deploy needs an explicit `--source-code-path` (the
bundle upload path). After the apps exist, this notebook grants their service principals the
access they need (§4-grants cell) and §2c registers the custom MCP UC connection.

```bash
databricks bundle deploy -t dev --profile dbw-brlui-sandbox
databricks apps start  mcp-maplechain   --profile dbw-brlui-sandbox
databricks apps start  maplechain-agent --profile dbw-brlui-sandbox
BASE=/Workspace/Users/<you>/.bundle/uaig-demo/dev/files
databricks apps deploy mcp-maplechain   --source-code-path "$BASE/mcp_app"   --profile dbw-brlui-sandbox
databricks apps deploy maplechain-agent --source-code-path "$BASE/agent_app" --profile dbw-brlui-sandbox
```
""")

code(r'''
# Show current app status.
for app_name in ["maplechain-agent", "mcp-maplechain"]:
    try:
        app = w.apps.get(name=app_name)
        st = app.app_status.state if app.app_status else "?"
        print(f"  {app_name}: {getattr(app, 'url', '(no url yet)')}  [{st}]")
    except Exception:
        print(f"  {app_name}: not deployed yet")
''')

md(r"""
### §4-grants — give the agent's service principal the access it needs

The deployed agent runs as its own service principal. It must be able to (a) read/execute the
demo schema (to reach the MCP UC functions), (b) **`EXECUTE` the Model Service**, and (c) use
its MLflow experiment. Idempotent; safe to re-run. No-ops if the agent App isn't deployed.
""")

code(r'''
# Create the experiment independently of App availability so first-time bundle setup always
# returns a usable experiment id and can seed traces before the App shell exists.
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
exp_path = f"/Users/{me}/maplechain-agent-exp"
try:
    exp_id = w.experiments.get_by_name(experiment_name=exp_path).experiment.experiment_id
except Exception:
    exp_id = w.experiments.create_experiment(name=exp_path).experiment_id
print(f"Agent MLflow experiment: {exp_id}")

try:
    agent_app = w.apps.get(name="maplechain-agent")
    sp = agent_app.service_principal_client_id
    print(f"Agent SP: {sp}")

    # (a) UC access to the demo schema (so managed-MCP UC functions execute).
    for stmt in [
        f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{sp}`",
        f"GRANT USE SCHEMA ON SCHEMA {FQ} TO `{sp}`",
        f"GRANT SELECT ON SCHEMA {FQ} TO `{sp}`",
        f"GRANT EXECUTE ON SCHEMA {FQ} TO `{sp}`",
    ]:
        try: spark.sql(stmt)
        except Exception as e: print(f"  {stmt.split(' ON ')[0]} skipped: {str(e)[:80]}")
    print("  granted UC catalog/schema/select/execute to agent SP")

    # (b) EXECUTE on the Model Service (new gateway) via the grants API.
    from databricks.sdk.service.catalog import PermissionsChange, Privilege
    w.grants.update(securable_type="model_service", full_name=MS_FQN,
                    changes=[PermissionsChange(principal=sp, add=[Privilege.EXECUTE])])
    print("  granted EXECUTE on the MapleChain Model Service to agent SP")

    # (c) MLflow experiment the agent App logs to (MLFLOW_EXPERIMENT_ID in app.yaml). The SP
    # must be able to read it, or the AgentServer crashes on startup.
    w.experiments.set_permissions(
        experiment_id=exp_id,
        access_control_list=[AccessControlRequest(
            service_principal_name=sp, permission_level=PermissionLevel.CAN_MANAGE)])
    print(f"  agent MLflow experiment: {exp_id} (set MLFLOW_EXPERIMENT_ID in agent_app/app.yaml)")
    print("  granted CAN_MANAGE on experiment to agent SP")

    # (d) Genie space CAN_RUN — so the agent's Genie MCP tool (GENIE_SPACE_ID in app.yaml) works.
    # Without this the managed Genie MCP returns PERMISSION_DENIED for the App SP.
    if genie_space_id:
        w.permissions.update(
            request_object_type="genie", request_object_id=genie_space_id,
            access_control_list=[AccessControlRequest(
                service_principal_name=sp, permission_level=PermissionLevel.CAN_RUN)])
        print(f"  granted CAN_RUN on Genie space {genie_space_id} to agent SP "
              f"(set GENIE_SPACE_ID={genie_space_id} in agent_app/app.yaml)")
    else:
        print("  (no Genie space id — skip Genie grant; §2b did not create one)")
    # The custom MCP Service is reached via the AI Gateway, which proxies auth through the
    # service's own connection — the agent SP needs no extra grant on the MCP Service to call it.
except Exception as e:
    print(f"Agent-SP grants skipped (deploy the agent App first): {type(e).__name__}: {str(e)[:120]}")

# The documented headless /invocations flow authenticates as the gateway SP. AppKit preserves
# that caller identity for Genie, so it needs the same data and space permissions as an
# interactive user. Keep these grants independent of agent-App creation so clean deployments
# and automated smoke tests work before a browser has ever opened the App.
for stmt in [
    f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{gw_sp_app_id}`",
    f"GRANT USE SCHEMA ON SCHEMA {FQ} TO `{gw_sp_app_id}`",
    f"GRANT SELECT ON SCHEMA {FQ} TO `{gw_sp_app_id}`",
]:
    try: spark.sql(stmt)
    except Exception as e: print(f"  headless {stmt.split(' ON ')[0]} skipped: {str(e)[:80]}")
print("  granted UC catalog/schema/select to gateway SP for headless Genie calls")

if genie_space_id:
    w.permissions.update(
        request_object_type="genie", request_object_id=genie_space_id,
        access_control_list=[AccessControlRequest(
            service_principal_name=gw_sp_app_id, permission_level=PermissionLevel.CAN_RUN)])
    print(f"  granted CAN_RUN on Genie space {genie_space_id} to gateway SP")
''')

md(r"""
### §4-traces — seed representative MapleChain agent traces and evaluation assets

Writes 20 deterministic, nested traces to the same experiment used by the deployed agent,
including multi-turn sessions. It also creates a managed evaluation dataset and registers
built-in, custom-code, and custom LLM-judge scorers with the experiment.
They make the MLflow tracing UI useful immediately in a brand-new workspace and demonstrate
agent, tool, and chat-model spans without requiring the App to be invoked first.
""")

code(r'''
import mlflow
from mlflow.entities import SpanType
from mlflow.tracking import MlflowClient

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(experiment_id=exp_id)
seed_tag = "maplechain.seed_traces_version"
seed_version = "2"
already_seeded = (mlflow.get_experiment(exp_id).tags or {}).get(seed_tag) == seed_version
base_examples = [
    ("What is the risk score for SUP-003?", "get_supplier_risk",
     {"p_supplier_id": "SUP-003"}, {"supplier_name": "Maritime Catch Co", "risk_score": 0.41},
     "SUP-003 (Maritime Catch Co) has a supplier risk score of 0.41."),
    ("Where is SKU-1006 in stock?", "check_inventory", {"p_sku": "SKU-1006"},
     [{"warehouse": "Toronto, ON", "units_on_hand": 60},
      {"warehouse": "Calgary, AB", "units_on_hand": 25}],
     "SKU-1006 has 60 units in Toronto and 25 units in Calgary."),
    ("Estimate delivery for ORD-9004", "estimate_delivery_eta", {"p_order_id": "ORD-9004"},
     {"destination": "Toronto, ON", "ship_date": "2026-07-08", "eta": "2026-07-10"},
     "ORD-9004 is estimated to arrive in Toronto on July 10, 2026."),
]
seed_examples = [base_examples[i % len(base_examples)] for i in range(20)]
if already_seeded:
    seed_examples = []
    print(f"MapleChain trace seed version {seed_version} already present; skipping.")
for index, (question, tool_name, tool_input, tool_output, answer) in enumerate(seed_examples, 1):
    with mlflow.start_span(name="maplechain_agent", span_type=SpanType.AGENT) as root:
        root.set_inputs({"input": [{"role": "user", "content": question}]})
        mlflow.update_current_trace(tags={
            "environment": "demo", "source": "bundle_seed", "app": "maplechain-agent",
            # Five four-turn sessions demonstrate session-level trace grouping.
            "mlflow.trace.session": f"maplechain-seed-session-{((index - 1) // 4) + 1}",
        })
        with mlflow.start_span(name=tool_name, span_type=SpanType.TOOL) as tool_span:
            tool_span.set_inputs(tool_input)
            tool_span.set_outputs(tool_output)
        with mlflow.start_span(name=MS_FQN, span_type=SpanType.CHAT_MODEL) as model_span:
            model_span.set_inputs({"messages": [{"role": "user", "content": question}]})
            model_span.set_outputs({"role": "assistant", "content": answer})
        root.set_outputs({"output": [{"role": "assistant", "content": answer}]})
MlflowClient().set_experiment_tag(exp_id, seed_tag, seed_version)
print(f"Seeded {len(seed_examples)} MapleChain agent traces in experiment {exp_id}.")

# Managed evaluation dataset (idempotent merge by record identity).
eval_records = [
    {"inputs": {"query": q}, "outputs": {"response": answer},
     "expectations": {"expected_response": answer, "expected_tool": tool}}
    for q, tool, _tool_input, _tool_output, answer in base_examples
]
eval_dataset_name = f"{FQN}.maplechain_agent_evaluation"
try:
    eval_dataset = mlflow.genai.datasets.get_dataset(eval_dataset_name)
except Exception:
    eval_dataset = mlflow.genai.datasets.create_dataset(
        name=eval_dataset_name,
        experiment_id=exp_id,
    )
eval_dataset.merge_records(eval_records)
print(f"Seeded evaluation dataset: {FQN}.maplechain_agent_evaluation")

# Register representative production scorers; registration is idempotent by scorer name/version.
from mlflow.genai.scorers import Safety, Guidelines, scorer
from mlflow.genai.judges import make_judge

@scorer(name="maplechain_has_answer")
def maplechain_has_answer(outputs):
    return bool((outputs or {}).get("response", "").strip())

registered_scorers = [
    Safety().register(name="maplechain_safety", experiment_id=exp_id),
    Guidelines(name="maplechain_professional_tone",
               guidelines="The response must be concise, professional, and directly address the request.").register(
                   experiment_id=exp_id),
    maplechain_has_answer.register(experiment_id=exp_id),
    make_judge(
        name="maplechain_supply_chain_judge",
        instructions=("Given the request {{ inputs }} and response {{ outputs }}, evaluate whether "
                      "the response accurately answers the MapleChain supply-chain request, cites "
                      "relevant business identifiers, and avoids unsupported claims. Return true or false."),
        feedback_value_type=bool,
        model=f"databricks:/{MS_FQN}",
    ).register(experiment_id=exp_id),
]
print("Registered experiment scorers:", [s.name for s in registered_scorers])
''')

md(r"""
### §4-skills — seed project-specific coding-agent skills in Unity Catalog

Creates native `SKILL` securables in the target schema for common maintenance workflows.
These are schema assets, not local editor configuration, and are safe to create repeatedly.
""")

code(r'''
skill_comments = {
    "maplechain_bundle_deployer": "Deploy and validate the MapleChain bundle, setup job, and both XL Databricks Apps.",
    "maplechain_gateway_debugger": "Diagnose MapleChain Model, Provider, MCP, and Agent Services plus Genie connectivity.",
    "maplechain_eval_curator": "Maintain seeded MLflow traces, sessions, evaluation datasets, and experiment scorers.",
}
for skill_id, comment in skill_comments.items():
    try:
        w.api_client.do("GET", f"/api/2.1/unity-catalog/skills/{FQN}.{skill_id}")
        print(f"Coding-agent skill exists: {FQN}.{skill_id}")
    except Exception:
        w.api_client.do("POST", "/api/2.1/unity-catalog/skills",
                        query={"parent": f"schemas/{FQN}", "skill_id": skill_id},
                        body={"comment": comment})
        print(f"Created coding-agent skill: {FQN}.{skill_id}")
''')

md(r"""
### §4-agent-service — wrap the deployed agent App as a gateway Agent Service *(Beta)*

Registers the agent App as a UC **Agent Service** (the 4th gateway object type), referencing the
OAuth M2M HTTP connection to the App (via the §2c-sp helper). Idempotent get-else-create.

> **Beta limitation:** `AgentServiceConfig.model_service` is not yet persisted on create
> (server rejects it — tracked under SASP-8317). We register the Agent Service with its
> `source_connection` + `system_prompt` + `base_path`; the Model Service link is set later
> (UI/API) once the field is supported. The agent App itself already routes its LLM through the
> Model Service via `ChatDatabricks(use_ai_gateway=True)`, so the demo's routing is unaffected.
""")

code(r'''
from databricks.sdk.service.catalog import (
    AgentService, AgentServiceConfig,
    AgentServiceConfigSourceConnection, AgentServiceAgentServiceType)

agent_conn   = "maplechain_agent_conn"
agent_svc_id = "maplechain_agent_svc"
agent_conn_res = ensure_app_http_connection(agent_conn, APP_AGENT, "/invocations")

if agent_conn_res:
    res = f"agent-services/{FQN}.{agent_svc_id}"
    try:
        w.ai_gateway.get_agent_service(name=res)
        print(f"Agent Service exists: {FQN}.{agent_svc_id}")
    except Exception:
        # NOTE: model_service intentionally omitted — not yet supported on CreateAgentService (SASP-8317).
        asvc = AgentService(
            agent_service_type=AgentServiceAgentServiceType.AGENT_SERVICE_TYPE_EXTERNAL,
            config=AgentServiceConfig(
                source_connection=AgentServiceConfigSourceConnection(name=agent_conn_res),
                system_prompt="MapleChain supply-chain assistant.",
                base_path="/invocations"))
        w.ai_gateway.create_agent_service(agent_service=asvc, parent=f"schemas/{FQN}",
                                          agent_service_id=agent_svc_id)
        print(f"Created Agent Service (UC object): {FQN}.{agent_svc_id}")
    # Agent Services are Beta and hidden from UC global search — grant READ_METADATA so it's
    # visible when you navigate directly to the schema in Catalog Explorer (owner-only by default).
    try:
        from databricks.sdk.service.catalog import PermissionsChange, Privilege
        w.grants.update(securable_type="agent_service", full_name=f"{FQN}.{agent_svc_id}",
                        changes=[PermissionsChange(principal=me, add=[Privilege.READ_METADATA])])
        print(f"Granted READ_METADATA on Agent Service to {me} "
              f"(Beta: not surfaced in Catalog search — navigate to the schema directly)")
    except Exception as e:
        print(f"(Agent Service grant skipped: {type(e).__name__})")
''')

# ---------------------------------------------------------------------------
# §5 exercise
# ---------------------------------------------------------------------------
md(r"""
## §5 — Exercise the gateway

Four calls that each demonstrate a gateway behavior. Uses the OpenAI-compatible client
pointed at `gateway_endpoint`, so traffic split, fallback, guardrails, and rate limits all
Uses the OpenAI-compatible client pointed at the **Model Service** via `/ai-gateway/mlflow/v1`,
so routing/split, fallback, rate limits, and (if UI-attached) service policies all apply.
Errors are caught and printed. Note: a **service-policy block only fires once you attach the
policy in the AI Gateway UI** (§2d) — until then, the "guardrail" call just answers normally.
""")

code(r'''
import json as _json
from openai import OpenAI

_token = w.config.authenticate().get("Authorization", "").replace("Bearer ", "")
client = OpenAI(base_url=GW_BASE, api_key=_token)   # /ai-gateway/mlflow/v1

def ask(label, content, n=1, tags=None):
    print(f"\n--- {label} ---")
    extra = {"Databricks-Ai-Gateway-Request-Tags": _json.dumps(tags)} if tags else None
    for i in range(n):
        try:
            r = client.chat.completions.create(
                model=MS_FQN,
                messages=[{"role": "user", "content": content}],
                max_tokens=200,
                extra_headers=extra)
            print(f"[{i}] {r.choices[0].message.content[:240]}")
        except Exception as e:
            print(f"[{i}] {type(e).__name__}: {str(e)[:200]}")

# 1) Normal, on-topic supply-chain question (with request tags → usage tracking).
ask("Normal query (+request tags)",
    "A restaurant in Toronto needs AAA ground beef. Which warehouse has stock and how much?",
    tags={"project": "maplechain-demo", "team": "supply-chain"})

# 2) A query the deny_competitor_pricing policy targets — blocks ONLY if the policy is
#    UI-attached (§2d); otherwise it answers normally. Either way the call succeeds/handles.
ask("Service-policy candidate (blocks only if policy attached in UI)",
    "Give me competitor_pricing insider tips for the stock market.")

# 3) Burst → per-user rate limit is 60/min; a tight burst may surface a rate-limit error.
ask("Rate limit (USER_DEFAULT 60/min)", "Say OK.", n=6)
''')

# ---------------------------------------------------------------------------
# §6 observability + governance recap
# ---------------------------------------------------------------------------
md(r"""
## §6 — Observability + governance recap

Usage tracking and the inference table populate within ~1 hour of the first request, so on a
fresh run these may be empty — re-run this section later to see rows. The recap prints the
current state of the four gateway UC objects, grants, service-policy UDFs, and the agent.
""")

code(r'''
# Usage system table (new gateway). endpoint_name is the Model Service FQN.
try:
    df = spark.sql(f"""
        SELECT requester, api_type, input_tokens, output_tokens, status_code,
               request_tags, routing_information
        FROM system.ai_gateway.usage
        WHERE endpoint_name = '{MS_FQN}'
        ORDER BY event_time DESC LIMIT 20""")
    if df.count():
        display(df)
    else:
        print(f"system.ai_gateway.usage: no rows for {MS_FQN} yet (populates within ~1h). Re-run later.")
except Exception as e:
    print(f"system.ai_gateway.usage query skipped: {e}")

# Inference (payload) table — auto-created; payload columns materialize within ~1h, so don't
# assume a schema.
inf_tbl = f"{FQ}.{ms_name}_payload"
try:
    n = spark.table(inf_tbl).count()
    print(f"Inference table {inf_tbl}: {n} row(s), columns: {spark.table(inf_tbl).columns}")
    if n:
        display(spark.table(inf_tbl).limit(10))
    else:
        print("  Payloads populate within ~1h of the first request — re-run to see them.")
except Exception as e:
    print(f"Inference table {inf_tbl} not available yet: {e}")
''')

code(r'''
print("=" * 64)
print("MapleChain — NEW Unity AI Gateway demo — governance recap")
print("=" * 64)
print(f"\nCatalog.schema : {FQN}")

print(f"\nModel Service (UC object): {MS_FQN}")
try:
    ms = w.ai_gateway.get_model_service(name=MS_RES)
    rr = ms.config.routing
    print("  routing :", [(d.name, d.traffic_percentage) for d in (rr.destinations or [])])
    print("  fallback:", [d.name for d in (rr.fallback.destinations if rr.fallback else [])])
    print("  invoke  :", f"{GW_BASE}  model={MS_FQN}")
except Exception as e:
    print("  get_model_service:", str(e)[:120])

print(f"\nMCP Services in UC:")
try:
    mine = [m.name.split('/')[-1] for m in w.ai_gateway.list_mcp_services()
            if m.name.startswith(f'mcp-services/{FQN}.')]
    syst = [m.name.split('/')[-1] for m in w.ai_gateway.list_mcp_services()
            if m.name.startswith('mcp-services/system.ai.')]
    print("  mine  :", mine or "(deploy mcp_app/ + re-run §2c)")
    print("  system:", syst[:6])
except Exception as e:
    print("  list_mcp_services:", str(e)[:120])
print(f"  managed (functions): {host}/api/2.0/mcp/functions/{catalog}/{schema}")
if genie_space_id:
    print(f"  managed (genie)    : {host}/api/2.0/mcp/genie/{genie_space_id}")

print(f"\nService policies (guardrail UDFs, attach in UI): "
      f"{FQN}.deny_competitor_pricing, {FQN}.ask_before_bulk_delete")
print("Built-in: system.ai.block_unsafe_content / block_jailbreak / block_hallucination")

print(f"\nAgent:")
try:
    from mlflow.tracking import MlflowClient
    m = MlflowClient(registry_uri="databricks-uc").get_model_version_by_alias(
        f"{FQN}.{ml_model}", "prod")
    print(f"  UC ML model {FQN}.{ml_model} @prod -> v{m.version}")
except Exception as e:
    print(f"  alias lookup: {str(e)[:100]}")
try:
    asvcs = [a.name.split('/')[-1] for a in w.ai_gateway.list_agent_services()
             if a.name.startswith(f'agent-services/{FQN}.')]
    print("  Agent Service:", asvcs or "(created in §4-agent-service once App connection exists)")
except Exception as e:
    print("  list_agent_services:", str(e)[:100])
print("\nDone. Re-run any section safely — all steps are idempotent.")
''')

# ---------------------------------------------------------------------------
# §7 — Surface IDs for databricks.yml
# ---------------------------------------------------------------------------
md(r"""
## §7 — Bundle variable output

Prints the two workspace-specific IDs that must be passed back to `databricks bundle deploy`
via `--var` flags (or stored as `databricks.yml` defaults for this workspace).
""")

code(r'''
import json as _json
# exp_id is set in §4-grants; genie_space_id in §2b. Both default to "" if those sections
# were skipped, which is handled gracefully by the agent app.
_out = {
    "genie_space_id": genie_space_id or "",
    "experiment_id":  exp_id if "exp_id" in dir() else "",
}
print("=" * 60)
print("Bundle variable output — copy these into your next deploy:")
print(f"  --var 'genie_space_id={_out['genie_space_id']}'")
print(f"  --var 'experiment_id={_out['experiment_id']}'")
print("=" * 60)
dbutils.notebook.exit(_json.dumps(_out))
''')

with open("setup.ipynb", "w") as f:
    json.dump({
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": ".venv", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }, f, indent=1)
print(f"Wrote setup.ipynb with {len(CELLS)} cells")
