"""MapleChain custom MCP tools.

These complement the managed MCP UC-function tools (§2a) with logic that isn't a simple
table lookup — carbon-footprint math, certification checks, and seasonal sourcing guidance
for a Canadian food-supply business. Self-contained (no warehouse dependency) so the App
stays cheap and always-on.
"""
from datetime import date

# Rough kg CO2e per kg of product by storage class + transit — illustrative demo values.
_CO2_PER_KG = {"ambient": 0.4, "refrigerated": 1.1, "frozen": 2.3}
_CO2_PER_KM = 0.00012  # per kg per km, truck freight

# Distance (km) between MapleChain hub cities — illustrative.
_DISTANCE = {
    ("Halifax, NS", "Montreal, QC"): 1250,
    ("Calgary, AB", "Toronto, ON"): 3430,
    ("Regina, SK", "Toronto, ON"): 2780,
    ("Abbotsford, BC", "Vancouver, BC"): 70,
    ("Calgary, AB", "Calgary, AB"): 15,
    ("Halifax, NS", "Halifax, NS"): 15,
}

_CERTS = {
    "SUP-001": ["CAN-ORG-2019", "Non-GMO Project"],
    "SUP-002": ["CAN-GAP-2021"],
    "SUP-003": ["MSC-2020", "Ocean Wise"],
    "SUP-004": ["CAN-ORG-2018", "SQF"],
    "SUP-005": ["CAN-GAP-2022"],
    "SUP-006": ["CRSB-2021"],
    "SUP-007": ["CAN-GAP-2020"],
    "SUP-008": ["CAN-ORG-2023", "Kosher"],
}

# Peak-freshness months for Canadian-sourced categories (month numbers).
_SEASON = {
    "Produce": [7, 8, 9, 10],
    "Dairy": list(range(1, 13)),
    "Proteins": list(range(1, 13)),
    "Dry Goods": list(range(1, 13)),
}


def load_tools(mcp_server):
    """Register MapleChain tools with the FastMCP server."""

    @mcp_server.tool
    def carbon_footprint_estimate(
        weight_kg: float, storage: str, origin: str, destination: str
    ) -> dict:
        """Estimate the carbon footprint (kg CO2e) of shipping a product.

        Args:
            weight_kg: Shipment weight in kilograms.
            storage: One of "ambient", "refrigerated", "frozen".
            origin: Origin city, e.g. "Calgary, AB".
            destination: Destination city, e.g. "Toronto, ON".

        Returns:
            dict with storage_co2e, transit_co2e, total_co2e (kg) and the distance used.
        """
        storage_factor = _CO2_PER_KG.get(storage.lower(), 0.8)
        distance = _DISTANCE.get((origin, destination)) or _DISTANCE.get(
            (destination, origin), 1500
        )
        storage_co2e = round(weight_kg * storage_factor, 2)
        transit_co2e = round(weight_kg * distance * _CO2_PER_KM, 2)
        return {
            "storage_co2e_kg": storage_co2e,
            "transit_co2e_kg": transit_co2e,
            "total_co2e_kg": round(storage_co2e + transit_co2e, 2),
            "distance_km": distance,
        }

    @mcp_server.tool
    def supplier_certifications(supplier_id: str) -> dict:
        """Return the food-safety / sustainability certifications held by a supplier.

        Args:
            supplier_id: MapleChain supplier id, e.g. "SUP-003".

        Returns:
            dict with the supplier_id and its list of certifications.
        """
        return {
            "supplier_id": supplier_id,
            "certifications": _CERTS.get(supplier_id, []),
        }

    @mcp_server.tool
    def seasonal_sourcing(category: str, month: int = 0) -> dict:
        """Advise whether a product category is in peak Canadian season.

        Args:
            category: One of "Produce", "Dairy", "Proteins", "Dry Goods".
            month: Month number 1-12; 0 (default) uses the current month.

        Returns:
            dict indicating in_season and the peak months for the category.
        """
        m = month if 1 <= month <= 12 else date.today().month
        peak = _SEASON.get(category, list(range(1, 13)))
        return {
            "category": category,
            "month": m,
            "in_season": m in peak,
            "peak_months": peak,
        }
