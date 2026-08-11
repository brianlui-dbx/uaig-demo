"""Verify a real ABAC column-mask policy can be created (idempotently) on the sandbox.

Masks restaurant_customers.contact_email for non-owners via a UC masking function + an ABAC
POLICY_TYPE_COLUMN_MASK policy. Run twice to confirm idempotency.
    .venv/bin/python tasks/verify_abac.py
"""
from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import PolicyInfo, PolicyType, ColumnMask, SecurableType

CATALOG, SCHEMA = "catalog_sandbox_y049iu", "uaig_demo"
FQ = f"`{CATALOG}`.`{SCHEMA}`"
FQN = f"{CATALOG}.{SCHEMA}"

spark = DatabricksSession.builder.profile("dbw-brlui-sandbox").serverless(True).getOrCreate()
w = WorkspaceClient(profile="dbw-brlui-sandbox")

# Table the policy protects.
spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.restaurant_customers AS SELECT * FROM VALUES
  ('CUST-501','Le Bistro Boreal','Montreal, QC','Fine Dining','contact@bistroboreal.ca','514-555-0142')
  AS t(customer_id, restaurant_name, location, segment, contact_email, contact_phone)
""")

# Masking function (scalar): returns REDACTED unless the caller owns the data.
spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.mask_email(email STRING)
RETURNS STRING
COMMENT 'ABAC column-mask helper: hides email from non-owners.'
RETURN CASE WHEN is_account_group_member('admins') THEN email ELSE '***REDACTED***' END
""")
print("table + mask function OK")

policy_name = "maplechain_email_mask"
mask = ColumnMask(function_name=f"{FQN}.mask_email", using_column_names=["contact_email"])
info = PolicyInfo(
    name=policy_name,
    policy_type=PolicyType.POLICY_TYPE_COLUMN_MASK,
    on_securable_type=SecurableType.TABLE,
    on_securable_fullname=f"{FQN}.restaurant_customers",
    for_securable_type=SecurableType.TABLE,
    to_principals=["account users"],
    column_mask=mask,
    comment="Mask restaurant contact email from non-admins (MapleChain MCP governance).",
)

try:
    existing = {p.name for p in w.policies.list_policies(
        on_securable_type="table", on_securable_fullname=f"{FQN}.restaurant_customers")}
    if policy_name in existing:
        print(f"ABAC policy exists: {policy_name}")
    else:
        w.policies.create_policy(policy_info=info)
        print(f"Created ABAC policy: {policy_name}")
except Exception as e:
    print(f"ABAC policy error: {type(e).__name__}: {e}")

# Show it.
try:
    pols = list(w.policies.list_policies(
        on_securable_type="table", on_securable_fullname=f"{FQN}.restaurant_customers"))
    print("policies on table:", [(p.name, p.policy_type) for p in pols])
except Exception as e:
    print("list err:", e)
print("\nverify_abac DONE")
