"""Live smoke test for the MapleChain gateway mechanism (§3).

Creates a throwaway endpoint `maplechain-smoke-test` with a two-destination external-model
traffic split routed to in-workspace Foundation Models, applies the full AI Gateway config,
queries it once, then (optionally) tears it down. Verifies the riskiest part of the notebook
against the real sandbox before we rely on it. Run:
    .venv/bin/python tasks/smoke_gateway.py [--teardown]
"""
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput, ServedEntityInput, ExternalModel, ExternalModelProvider,
    DatabricksModelServingConfig, TrafficConfig, Route,
    AiGatewayUsageTrackingConfig, AiGatewayInferenceTableConfig,
    AiGatewayRateLimit, AiGatewayRateLimitKey, AiGatewayRateLimitRenewalPeriod,
    AiGatewayGuardrails, AiGatewayGuardrailParameters, AiGatewayGuardrailPiiBehavior,
    AiGatewayGuardrailPiiBehaviorBehavior, FallbackConfig)

EP = "maplechain-smoke-test"
SCOPE = "maplechain_demo"
CATALOG, SCHEMA = "catalog_sandbox_y049iu", "uaig_demo"

w = WorkspaceClient(profile="dbw-brlui-sandbox")
host = w.config.host.rstrip("/")

if "--teardown" in sys.argv:
    try:
        w.serving_endpoints.delete(EP)
        print(f"deleted {EP}")
    except Exception as e:
        print("teardown:", e)
    sys.exit(0)

try:
    w.secrets.create_scope(scope=SCOPE)
    print("scope created")
except Exception as e:
    print("scope:", str(e)[:60])

tok = w.tokens.create(comment="mc-smoke", lifetime_seconds=3600)
w.secrets.put_secret(scope=SCOPE, key="routing_token", string_value=tok.token_value)
ref = "{{secrets/%s/routing_token}}" % SCOPE


def ent(n, fm):
    return ServedEntityInput(name=n, external_model=ExternalModel(
        name=fm, provider=ExternalModelProvider.DATABRICKS_MODEL_SERVING, task="llm/v1/chat",
        databricks_model_serving_config=DatabricksModelServingConfig(
            databricks_workspace_url=host, databricks_api_token=ref)))


core = EndpointCoreConfigInput(
    name=EP,
    served_entities=[ent("primary", "databricks-claude-sonnet-5"),
                     ent("secondary", "databricks-gpt-oss-120b")],
    traffic_config=TrafficConfig(routes=[
        Route(served_model_name="primary", traffic_percentage=70),
        Route(served_model_name="secondary", traffic_percentage=30)]))

try:
    w.serving_endpoints.get(EP)
    w.serving_endpoints.update_config(
        name=EP, served_entities=core.served_entities, traffic_config=core.traffic_config)
    print("updated")
except Exception:
    w.serving_endpoints.create(name=EP, config=core)
    print("creating")

for _ in range(180):
    st = w.serving_endpoints.get(EP).state
    r = getattr(st.ready, "value", st.ready)
    cu = getattr(st.config_update, "value", st.config_update)
    if r == "READY" and cu in ("NOT_UPDATING", None):
        break
    time.sleep(3)
print("state:", w.serving_endpoints.get(EP).state)

w.serving_endpoints.put_ai_gateway(
    name=EP,
    usage_tracking_config=AiGatewayUsageTrackingConfig(enabled=True),
    inference_table_config=AiGatewayInferenceTableConfig(
        enabled=True, catalog_name=CATALOG, schema_name=SCHEMA, table_name_prefix="maplechain_gw"),
    rate_limits=[
        AiGatewayRateLimit(calls=1000, key=AiGatewayRateLimitKey.ENDPOINT,
                           renewal_period=AiGatewayRateLimitRenewalPeriod.MINUTE),
        AiGatewayRateLimit(calls=5, key=AiGatewayRateLimitKey.USER,
                           renewal_period=AiGatewayRateLimitRenewalPeriod.MINUTE)],
    guardrails=AiGatewayGuardrails(
        input=AiGatewayGuardrailParameters(
            safety=True,
            pii=AiGatewayGuardrailPiiBehavior(behavior=AiGatewayGuardrailPiiBehaviorBehavior.MASK),
            invalid_keywords=["competitor_pricing", "insider"],
            valid_topics=["supply chain", "logistics", "inventory"]),
        output=AiGatewayGuardrailParameters(safety=True)),
    fallback_config=FallbackConfig(enabled=True))
print("GATEWAY OK")

client = w.serving_endpoints.get_open_ai_client()
r = client.chat.completions.create(
    model=EP, messages=[{"role": "user", "content": "Say OK in one word."}], max_tokens=10)
print("QUERY OK ->", r.choices[0].message.content[:50])
print("\nSmoke test passed. Tear down with:  .venv/bin/python tasks/smoke_gateway.py --teardown")
