"""MapleChain supply-chain agent (LangGraph ResponsesAgent).

Customized from the databricks/app-templates `agent-langgraph` template. Two demo-specific
wirings:

1. **LLM = the MapleChain Model Service** (`MODEL_SERVICE`, a UC gateway object), reached with
   `ChatDatabricks(use_ai_gateway=True)` so every turn goes through the Unity AI Gateway's
   routing, fallback, and rate limits.
2. **Tools = three MapleChain MCP sources**, each loaded independently (one flaky endpoint can't
   drop the rest): (a) managed **UC functions** (per-function MCP URLs), (b) the managed **Genie**
   MCP (`GENIE_SPACE_ID`) for natural-language data Q&A, and (c) the custom **MCP Service**
   (`MCP_SERVICE`) — the mcp_app/ tools, governed through the UC MCP Service via the AI Gateway.

Model Service / catalog / schema / GENIE_SPACE_ID / MCP_SERVICE come from env vars set in
`app.yaml` so the same code works across catalogs without edits.
"""
import logging
import os
from datetime import datetime
from typing import AsyncGenerator, Optional

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_langchain import (
    ChatDatabricks,
    DatabricksMCPServer,
    DatabricksMultiServerMCPClient,
)
from langchain.agents import create_agent
from langchain_core.tools import tool
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    to_chat_completions_input,
)

from agent_server.utils import (
    get_databricks_host_from_env,
    get_session_id,
    process_agent_astream_events,
)

logger = logging.getLogger(__name__)
mlflow.langchain.autolog()
logging.getLogger("mlflow.utils.autologging_utils").setLevel(logging.ERROR)
sp_workspace_client = WorkspaceClient()

# Demo configuration. The catalog/schema are the ONLY location-specific knobs — set them once
# (bundle var.catalog/var.schema → databricks.yml config.env). Everything below is DERIVED from
# them, so retargeting a workspace/catalog never means editing a service name in two places.
UC_CATALOG = os.environ.get("UC_CATALOG", "main")
UC_SCHEMA = os.environ.get("UC_SCHEMA", "uaig_demo")
# MODEL_SERVICE is the new-gateway Model Service FQN (catalog.schema.name); ChatDatabricks routes
# to it through the Unity AI Gateway via use_ai_gateway=True. Derived from catalog/schema + the
# fixed asset name; override the env var only to point at a differently named service.
MODEL_SERVICE = os.environ.get("MODEL_SERVICE") or f"{UC_CATALOG}.{UC_SCHEMA}.maplechain_custom_ms"
# Custom MCP server, reached through its UC MCP Service (the AI Gateway proxies auth via the
# service's connection). Prefer the gateway MCP-Service endpoint over the raw App URL so the
# call is governed by the UC object. Derived like MODEL_SERVICE; blank env value = skip.
MCP_SERVICE = os.environ.get("MCP_SERVICE") if "MCP_SERVICE" in os.environ else f"{UC_CATALOG}.{UC_SCHEMA}.maplechain_mcp"
# Genie space id → managed Genie MCP server (/api/2.0/mcp/genie/{id}). Blank = skip.
GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "")
# Optional: raw custom-MCP App URL (legacy path). Prefer MCP_SERVICE above; kept for flexibility.
CUSTOM_MCP_URL = os.environ.get("CUSTOM_MCP_URL", "")

SYSTEM_PROMPT = (
    "You are the MapleChain supply-chain assistant for a Canadian food-supply business "
    "serving Canadian restaurants. Answer questions about suppliers, products, inventory, "
    "orders, shipments, and delivery ETAs. Use the available tools to look up real data "
    "before answering. Be concise and cite the SKU / order / supplier ids you used."
)


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().isoformat()


# The MapleChain tool functions exposed via managed MCP. We register them by their
# per-function URLs rather than the schema-level URL: the schema also contains VARIANT-param
# service-policy UDFs (deny_competitor_pricing, ...), and the schema-level MCP functions
# server rejects the whole schema with "Unsupported parameter type: VARIANT".
MCP_FUNCTIONS = [
    "get_supplier_risk",
    "check_inventory",
    "estimate_delivery_eta",
    "lookup_restaurant_order_history",
]


def mcp_server_urls() -> list[tuple[str, str]]:
    """The (name, url) of every MCP server exposed to the agent, all Databricks MCP endpoints:

    1. **Managed UC functions** — one per-function server (the schema-level server chokes on the
       VARIANT service-policy UDFs), the deterministic supply-chain lookups.
    2. **Managed Genie MCP** (if GENIE_SPACE_ID set) — natural-language Q&A over the MapleChain
       tables via /api/2.0/mcp/genie/{id}. The App SP needs CAN_RUN on the space.
    3. **Custom MCP Service** (if MCP_SERVICE set) — the mcp_app/ tools, governed through the UC
       MCP Service at /ai-gateway/mcp-services/{fqn} (gateway injects the connection's creds).
    4. **Raw custom MCP App URL** (if CUSTOM_MCP_URL set) — legacy direct path; usually unset in
       favor of MCP_SERVICE.
    """
    host_name = get_databricks_host_from_env()
    servers = [
        (f"fn-{fn}", f"{host_name}/api/2.0/mcp/functions/{UC_CATALOG}/{UC_SCHEMA}/{fn}")
        for fn in MCP_FUNCTIONS
    ]
    if GENIE_SPACE_ID:
        servers.append(("genie", f"{host_name}/api/2.0/mcp/genie/{GENIE_SPACE_ID}"))
    if MCP_SERVICE:
        servers.append(("maplechain-mcp-service", f"{host_name}/ai-gateway/mcp-services/{MCP_SERVICE}"))
    if CUSTOM_MCP_URL:
        servers.append(("maplechain-custom", f"{CUSTOM_MCP_URL.rstrip('/')}/mcp"))
    return servers


async def init_agent(workspace_client: Optional[WorkspaceClient] = None):
    wc = workspace_client or sp_workspace_client
    tools = [get_current_time]
    # Load each MCP server INDEPENDENTLY: one flaky/slow endpoint must not drop every tool
    # (a single get_tools() over all servers is all-or-nothing — a transient error on one
    # server left the agent with no tools at all).
    for name, url in mcp_server_urls():
        try:
            client = DatabricksMultiServerMCPClient(
                [DatabricksMCPServer(name=name, url=url, workspace_client=wc)])
            server_tools = await client.get_tools()
            tools.extend(server_tools)
            logger.info("MCP server %s: loaded %d tool(s)", name, len(server_tools))
        except Exception:
            logger.warning("MCP server %s failed to load; skipping it.", name, exc_info=True)
    # use_ai_gateway=True routes ChatDatabricks(model=<Model Service FQN>) through the new
    # Unity AI Gateway (/ai-gateway/mlflow/v1). disable_streaming=True because the gateway
    # rejects streaming when a service policy is attached; LangChain still surfaces the result
    # through astream() as a single chunk.
    return create_agent(
        tools=tools,
        model=ChatDatabricks(model=MODEL_SERVICE, use_ai_gateway=True, disable_streaming=True),
        system_prompt=SYSTEM_PROMPT,
    )


@invoke()
async def invoke_handler(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    outputs = [
        event.item
        async for event in stream_handler(request)
        if event.type == "response.output_item.done"
    ]
    return ResponsesAgentResponse(output=outputs)


@stream()
async def stream_handler(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    if session_id := get_session_id(request):
        mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})

    agent = await init_agent()
    messages = {"messages": to_chat_completions_input([i.model_dump() for i in request.input])}

    # Best-effort guardrails: the AI Gateway returns HTTP 400 when an input guardrail
    # (safety / PII / topic / keyword) fires. Surface that as a normal assistant message
    # instead of crashing the invocation with a 500.
    import uuid
    from mlflow.types.responses import ResponsesAgentStreamEvent
    try:
        async for event in process_agent_astream_events(
            agent.astream(input=messages, stream_mode=["updates", "messages"])
        ):
            yield event
    except Exception as e:
        msg = str(e)
        if "guardrail" in msg.lower() or "BAD_REQUEST" in msg:
            note = ("This request was blocked or modified by a Unity AI Gateway guardrail "
                    "(safety / PII / topic / keyword policy). Please rephrase without "
                    "sensitive data or off-topic content.")
        else:
            note = f"The agent could not complete the request: {msg[:300]}"
        item = {"type": "message", "role": "assistant", "id": str(uuid.uuid4()),
                "content": [{"type": "output_text", "text": note}]}
        yield ResponsesAgentStreamEvent(type="response.output_item.done", item=item)
