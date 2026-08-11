"""FastAPI + FastMCP application for the MapleChain custom MCP server.

Exposes supply-chain tools (carbon footprint estimates, supplier certifications, seasonal
sourcing guidance) over the MCP protocol so they can be governed in Unity Catalog as an HTTP
connection and consumed by the MapleChain agent. Deployed as a Databricks App.
"""
from fastapi import FastAPI
from fastmcp import FastMCP

from .tools import load_tools

mcp_server = FastMCP(name="maplechain-mcp")
load_tools(mcp_server)

# Stateless HTTP so clients that don't send mcp-session-id (e.g. the Databricks Assistant)
# and horizontally scaled App replicas both work. `path="/mcp"` makes the transport serve at
# exactly /mcp (mounting the app under a prefix would double-nest to /mcp/mcp).
mcp_http = mcp_server.http_app(path="/mcp", stateless_http=True)

app = FastAPI(
    title="MapleChain MCP Server",
    description="Custom supply-chain tools for the MapleChain demo",
    version="0.1.0",
    lifespan=mcp_http.lifespan,
)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "healthy", "server": "maplechain-mcp"}


# Mount at root so the MCP protocol is reachable at /mcp (matches the UC connection base_path).
app.mount("/", mcp_http)
combined_app = app
