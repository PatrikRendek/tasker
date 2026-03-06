import json
import hashlib
from typing import List, Dict, Any
import os
from django.conf import settings
from decimal import Decimal, ROUND_HALF_UP

VAT_MULTIPLIER = Decimal('1.21')

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
    if price_vat_excl is None or not isinstance(price_vat_excl, (int, float, Decimal, str)):
        price_vat_incl = 0.0 # Or potentially None if we want to skip it later
    else:
        try:
            # Convert to Decimal for precise financial calculation
            price_dec = Decimal(str(price_vat_excl))
            if price_dec < 0:
                price_vat_incl = 0.0
            else:
                # Calculate, round to 2 decimal places using standard Half-Up rounding, and convert back to float
                calc_val = (price_dec * VAT_MULTIPLIER).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                price_vat_incl = float(calc_val)
        except (ValueError, TypeError, float.InvalidOperation):
            price_vat_incl = 0.0
            
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
