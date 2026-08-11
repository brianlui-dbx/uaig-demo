"""Verify §1 (tables) + §2a (functions) + §2d (grants) run and are idempotent.

Executes the notebook's SQL logic against the sandbox via databricks-connect serverless.
Run it twice — the second run must succeed with no errors (CREATE OR REPLACE / IF NOT EXISTS).
    .venv/bin/python tasks/verify_uc.py
"""
from databricks.connect import DatabricksSession

CATALOG, SCHEMA = "catalog_sandbox_y049iu", "uaig_demo"
FQ = f"`{CATALOG}`.`{SCHEMA}`"

spark = DatabricksSession.builder.profile("dbw-brlui-sandbox").serverless(True).getOrCreate()

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FQ}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {FQ}.`docs`")

spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.suppliers AS SELECT * FROM VALUES
  ('SUP-001','Prairie Grain Collective','Dry Goods','Regina, SK',       0.12,'CAN-ORG-2019',4.6),
  ('SUP-003','Maritime Catch Co',       'Proteins', 'Halifax, NS',      0.41,'MSC-2020',    3.9)
  AS t(supplier_id, supplier_name, category, location, risk_score, certification, quality_rating)
""")
spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.inventory AS SELECT * FROM VALUES
  ('Toronto, ON','SKU-1006', 60),('Calgary, AB','SKU-1006', 25)
  AS t(warehouse, sku, units_on_hand)
""")
spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.orders AS SELECT * FROM VALUES
  ('ORD-9002','CUST-501','SKU-1004', 6, DATE'2026-07-02','delivered')
  AS t(order_id, customer_id, sku, quantity, order_date, status)
""")
spark.sql(f"""
CREATE OR REPLACE TABLE {FQ}.shipments AS SELECT * FROM VALUES
  ('SHP-7003','ORD-9004','Regina, SK','Toronto, ON',DATE'2026-07-08',2,'in_transit')
  AS t(shipment_id, order_id, origin, destination, ship_date, transit_days, status)
""")
print("tables OK")

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
print("functions OK")

# Call a TABLE function to prove it works.
rows = spark.sql(f"SELECT * FROM {FQ}.get_supplier_risk('SUP-003')").collect()
print("get_supplier_risk('SUP-003') ->", rows)
inv = spark.sql(f"SELECT * FROM {FQ}.check_inventory('SKU-1006')").collect()
print("check_inventory('SKU-1006') ->", inv)

for fn in ["get_supplier_risk", "check_inventory", "estimate_delivery_eta"]:
    spark.sql(f"GRANT EXECUTE ON FUNCTION {FQ}.{fn} TO `account users`")
print("grants OK")

grants = spark.sql(f"SHOW GRANTS ON FUNCTION {FQ}.get_supplier_risk").collect()
print("SHOW GRANTS ->", [(r[0], r[1], r[2]) for r in grants][:5])
print("\nverify_uc PASSED")
