# MapleChain custom MCP server

A FastMCP + FastAPI server exposing supply-chain tools for the MapleChain demo, deployed as
a Databricks App and registered in Unity Catalog as an HTTP **connection** (see the repo
root `README.md`, §2c).

## Tools

| Tool | Purpose |
|------|---------|
| `carbon_footprint_estimate` | kg CO2e for a shipment given weight, storage class, origin, destination |
| `supplier_certifications` | Food-safety / sustainability certs held by a supplier |
| `seasonal_sourcing` | Whether a category is in peak Canadian season |

The MCP protocol is served at **`/mcp`** (matches the UC connection `base_path`). A plain
`/health` route is provided for readiness checks.

## Run locally

```bash
uv run maplechain-mcp            # serves on http://localhost:8000/mcp
```

## Deploy as a Databricks App

From the repo root (the bundle defines this app as `mcp-maplechain`):

```bash
databricks bundle deploy -t dev --profile <your-profile>
databricks bundle run    maplechain_mcp -t dev --profile <your-profile>
```

Then re-run **§2c** of `setup.ipynb` to register/refresh the UC HTTP connection now that the
App URL exists.
