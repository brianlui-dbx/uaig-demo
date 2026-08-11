"""Verify the new-gateway Model Service §3 code in isolation before wiring into the notebook.

Builds catalog.schema.maplechain_custom_ms idempotently (create-else-update), invokes it via
/ai-gateway/mlflow/v1, then re-runs to prove idempotency. Run twice:
    .venv/bin/python tasks/verify_model_service.py
"""
import sys

from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import (
    ModelService, ModelServiceConfig, ModelServiceConfigRoutingConfig,
    ModelServiceConfigDestinationConfig,
    ModelServiceConfigDestinationConfigDestinationType as DT,
    ModelServiceConfigPayPerTokenConfig, ModelServiceConfigFallbackConfig,
    InferenceTableConfig, RateLimit,
    RateLimitRateLimitKey as RLK, RateLimitRateLimitRenewalPeriod as RLP)
from openai import OpenAI

PROFILE = "dbw-brlui-sandbox"
CATALOG, SCHEMA = "catalog_sandbox_y049iu", "uaig_demo"
SVC_ID = "maplechain_custom_ms"
PARENT = f"schemas/{CATALOG}.{SCHEMA}"
FQN = f"{CATALOG}.{SCHEMA}.{SVC_ID}"
RES_NAME = f"model-services/{FQN}"

w = WorkspaceClient(profile=PROFILE)


def resolve_model_refs():
    """Map short model keywords -> real 'models/system.ai.<ref>' from live system services."""
    refs = []
    for ms in w.ai_gateway.list_model_services():
        if not ms.name.startswith("model-services/system.ai."):
            continue
        try:
            full = w.ai_gateway.get_model_service(name=ms.name)
            for d in (full.config.routing.destinations or []):
                if d.pay_per_token_config:
                    refs.append(d.pay_per_token_config.model)
        except Exception:
            pass
    return refs


def pick(refs, *keywords):
    for kw in keywords:
        for r in refs:
            if kw in r:
                return r
    return None


def build_service():
    refs = resolve_model_refs()
    primary = pick(refs, "databricks-claude-sonnet-5", "databricks-claude-sonnet-4-5", "sonnet")
    secondary = pick(refs, "gpt-oss-120b", "llama-4-maverick", "gpt-oss")
    fallback = pick(refs, "databricks-claude-haiku", "haiku")
    assert primary and secondary and fallback, f"missing refs: {primary},{secondary},{fallback}"
    print(f"primary={primary}\nsecondary={secondary}\nfallback={fallback}")

    def dest(name, model_ref, pct):
        return ModelServiceConfigDestinationConfig(
            name=name, destination_type=DT.DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL,
            traffic_percentage=pct,
            pay_per_token_config=ModelServiceConfigPayPerTokenConfig(model=model_ref))

    return ModelService(comment="MapleChain gateway model service (demo)", config=ModelServiceConfig(
        routing=ModelServiceConfigRoutingConfig(
            destinations=[dest("primary", primary, 70), dest("secondary", secondary, 30)],
            fallback=ModelServiceConfigFallbackConfig(destinations=[dest("fallback", fallback, 100)])),
        rate_limits=[
            RateLimit(key=RLK.RATE_LIMIT_KEY_USER_DEFAULT,
                      renewal_period=RLP.RATE_LIMIT_RENEWAL_PERIOD_MINUTE, requests=60),
            RateLimit(key=RLK.RATE_LIMIT_KEY_SERVICE,
                      renewal_period=RLP.RATE_LIMIT_RENEWAL_PERIOD_MINUTE, requests=1000),
        ],
        inference_table=InferenceTableConfig(parent=PARENT, table_name_prefix=SVC_ID)))


def upsert():
    svc = build_service()
    try:
        w.ai_gateway.get_model_service(name=RES_NAME)
        exists = True
    except NotFound:
        exists = False

    if not exists:
        try:
            created = w.ai_gateway.create_model_service(
                model_service=svc, parent=PARENT, model_service_id=SVC_ID)
            print("CREATED:", created.name)
        except Exception as e:
            if "already exists" in str(e).lower():
                # Orphaned inference payload table from a prior/deleted service.
                spark = DatabricksSession.builder.profile(PROFILE).serverless(True).getOrCreate()
                spark.sql(f"DROP TABLE IF EXISTS `{CATALOG}`.`{SCHEMA}`.{SVC_ID}_payload")
                created = w.ai_gateway.create_model_service(
                    model_service=svc, parent=PARENT, model_service_id=SVC_ID)
                print("CREATED (after orphan drop):", created.name)
            else:
                raise
    else:
        from databricks.sdk.service.catalog import FieldMask
        updated = w.ai_gateway.update_model_service(
            name=RES_NAME, model_service=svc, update_mask=FieldMask(field_mask=["config"]))
        print("UPDATED:", updated.name)


def invoke():
    host = w.config.host.rstrip("/")
    auth = w.config.authenticate().get("Authorization", "").replace("Bearer ", "")
    client = OpenAI(base_url=f"{host}/ai-gateway/mlflow/v1", api_key=auth)
    r = client.chat.completions.create(
        model=FQN, messages=[{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=8)
    print("INVOKE OK ->", repr(str(r.choices[0].message.content)[:40]))


if __name__ == "__main__":
    if "--delete" in sys.argv:
        try:
            w.ai_gateway.delete_model_service(name=RES_NAME)
            print("deleted", RES_NAME)
        except Exception as e:
            print("delete:", e)
        sys.exit(0)
    upsert()
    got = w.ai_gateway.get_model_service(name=RES_NAME)
    dests = got.config.routing.destinations
    fb = got.config.routing.fallback.destinations if got.config.routing.fallback else []
    print("routing:", [(d.name, d.traffic_percentage) for d in dests])
    print("fallback:", [d.name for d in fb])
    print("rate_limits:", [(r.key.value, r.requests) for r in (got.config.rate_limits or [])])
    print("api_types:", got.supported_api_types)
    invoke()
    print("\nverify_model_service PASSED")
