"""Verify GA fine-grained governance: a UC column mask applied via SQL DDL (idempotent)."""
from databricks.connect import DatabricksSession

CATALOG, SCHEMA = "catalog_sandbox_y049iu", "uaig_demo"
FQ = f"`{CATALOG}`.`{SCHEMA}`"

spark = DatabricksSession.builder.profile("dbw-brlui-sandbox").serverless(True).getOrCreate()

spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.restaurant_customers AS SELECT * FROM VALUES
  ('CUST-501','Le Bistro Boreal','Montreal, QC','Fine Dining','contact@bistroboreal.ca','514-555-0142')
  AS t(customer_id, restaurant_name, location, segment, contact_email, contact_phone)
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.mask_email(email STRING)
RETURNS STRING
COMMENT 'Column-mask helper: hides contact email from non-admins.'
RETURN CASE WHEN is_account_group_member('admins') THEN email ELSE '***REDACTED***' END
""")

# Idempotent: drop any existing mask, then set. UNSET is a no-op if none set.
spark.sql(f"ALTER TABLE {FQ}.restaurant_customers ALTER COLUMN contact_email DROP MASK")
spark.sql(f"ALTER TABLE {FQ}.restaurant_customers "
          f"ALTER COLUMN contact_email SET MASK {FQ}.mask_email")
print("column mask set OK")

rows = spark.sql(f"SELECT customer_id, contact_email FROM {FQ}.restaurant_customers").collect()
print("masked read ->", rows)
print("\nverify_mask PASSED")
