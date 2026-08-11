"""Probe put_ai_gateway inference-table idempotency.

Q: does re-applying inference_table_config to the SAME endpoint reuse the table (idempotent),
or does it error 'already exists'? Also cleans up the orphaned smoke-test payload table.
    .venv/bin/python tasks/verify_inftable.py
"""
import time

from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput, ServedEntityInput, ExternalModel, ExternalModelProvider,
    DatabricksModelServingConfig, TrafficConfig, Route,
    AiGatewayUsageTrackingConfig, AiGatewayInferenceTableConfig)

CATALOG, SCHEMA = "catalog_sandbox_y049iu", "uaig_demo"
EP = "maplechain-inftable-probe"
SCOPE = "maplechain_demo"

w = WorkspaceClient(profile="dbw-brlui-sandbox")
spark = DatabricksSession.builder.profile("dbw-brlui-sandbox").serverless(True).getOrCreate()
host = w.config.host.rstrip("/")

# Clean the orphaned table from the earlier smoke test.
spark.sql(f"DROP TABLE IF EXISTS `{CATALOG}`.`{SCHEMA}`.maplechain_gw_payload")
print("dropped orphaned maplechain_gw_payload (if any)")

tok = w.tokens.create(comment="mc-inftable", lifetime_seconds=3600)
w.secrets.put_secret(scope=SCOPE, key="routing_token", string_value=tok.token_value)
ref = "{{secrets/%s/routing_token}}" % SCOPE

core = EndpointCoreConfigInput(
    name=EP,
    served_entities=[ServedEntityInput(name="primary", external_model=ExternalModel(
        name="databricks-claude-sonnet-5", provider=ExternalModelProvider.DATABRICKS_MODEL_SERVING,
        task="llm/v1/chat", databricks_model_serving_config=DatabricksModelServingConfig(
            databricks_workspace_url=host, databricks_api_token=ref)))],
    traffic_config=TrafficConfig(routes=[Route(served_model_name="primary", traffic_percentage=100)]))

try:
    w.serving_endpoints.get(EP)
except Exception:
    w.serving_endpoints.create(name=EP, config=core)
for _ in range(120):
    st = w.serving_endpoints.get(EP).state
    if getattr(st.ready, "value", st.ready) == "READY":
        break
    time.sleep(3)
print("endpoint ready")


def apply():
    w.serving_endpoints.put_ai_gateway(
        name=EP,
        usage_tracking_config=AiGatewayUsageTrackingConfig(enabled=True),
        inference_table_config=AiGatewayInferenceTableConfig(
            enabled=True, catalog_name=CATALOG, schema_name=SCHEMA,
            table_name_prefix="maplechain_probe"))


print("apply #1 ...")
apply()
print("  OK")
print("apply #2 (idempotency) ...")
try:
    apply()
    print("  OK — put_ai_gateway is idempotent for inference tables on the same endpoint")
except Exception as e:
    print(f"  FAILED on re-apply: {type(e).__name__}: {e}")

# Cleanup.
w.serving_endpoints.delete(EP)
spark.sql(f"DROP TABLE IF EXISTS `{CATALOG}`.`{SCHEMA}`.maplechain_probe_payload")
print("cleaned up probe endpoint + table")
