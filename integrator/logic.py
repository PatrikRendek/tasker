import json
import hashlib
from typing import List, Dict, Any
import os
from django.conf import settings

# Rate limits settings for future API calls
ESHOP_API_BASE_URL = "https://api.fake-eshop.cz/v1"
ESHOP_API_KEY = "symma-secret-token"
MAX_REQUESTS_PER_SECOND = 5


def load_erp_data() -> List[Dict[Any, Any]]:
    """Loads ERP data from the local JSON file."""
    file_path = os.path.join(settings.BASE_DIR, 'erp_data.json')
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def calculate_hash(data: dict) -> str:
    """Calculates SHA-256 hash of a dictionary (must be sortable JSON)."""
    data_string = json.dumps(data, sort_keys=True)
    return hashlib.sha256(data_string.encode('utf-8')).hexdigest()

def transform_product(raw_product: dict) -> dict:
    """
    Transforms raw ERP product data into the format expected by the e-shop.
    - Aggregates stocks.
    - Adds 21% VAT to price.
    - Ensures color is set or defaults to 'N/A'.
    """
    # 1. Price calculation (+21% VAT)
    price_vat_excl = raw_product.get('price_vat_excl')
    
    # Handle missing or invalid prices
    if price_vat_excl is None or not isinstance(price_vat_excl, (int, float)) or price_vat_excl < 0:
        price_vat_incl = 0.0 # Or potentially None if we want to skip it later
    else:
        price_vat_incl = round(price_vat_excl * 1.21, 2)
        
    # 2. Stock aggregation
    stocks = raw_product.get('stocks', {})
    total_stock = 0
    if isinstance(stocks, dict):
        for loc, qty in stocks.items():
            if isinstance(qty, (int, float)):
                 total_stock += qty
                 
    # 3. Attributes (color fallback)
    attributes = raw_product.get('attributes')
    color = "N/A"
    if isinstance(attributes, dict):
        color = attributes.get('color', 'N/A')

    return {
        "sku": raw_product.get("id"),
        "title": raw_product.get("title"),
        "price_vat_incl": price_vat_incl,
        "total_stock": total_stock,
        "color": color
    }
