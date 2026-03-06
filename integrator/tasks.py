from celery import shared_task
import requests
import time
import logging
from django.db import transaction
from django.core.cache import cache

from .models import ProductSyncState
from .logic import (
    load_erp_data, 
    transform_product, 
    calculate_hash,
    ESHOP_API_BASE_URL,
    ESHOP_API_KEY
)

logger = logging.getLogger(__name__)

# To comply with 5 requests/second, we should sleep at least 0.2s between requests.
SLEEP_TIME_BETWEEN_REQUESTS = 0.2

@shared_task(bind=True, max_retries=5)
def sync_erp_to_eshop(self):
    """
    Main background task handling the synchronization between ERP JSON data and the e-shop API.
    Utilizes Delta Sync to minimize outgoing requests.
    """
    logger.info("Starting ERP to e-shop synchronization...")
    
    try:
        raw_data = load_erp_data()
    except Exception as e:
        logger.error(f"Failed to load ERP data: {e}")
        return "Failed to load ERP data."

    synced_count = 0
    skipped_count = 0
    failed_count = 0

    for raw_product in raw_data:
        try:
            # 1. Transform raw ERP data
            transformed_data = transform_product(raw_product)
            sku = transformed_data.get('sku')
            
            if not sku:
                logger.warning(f"Product missing SKU, skipping: {raw_product}")
                failed_count += 1
                continue

            # 2. Calculate Hash for Delta Sync
            new_hash = calculate_hash(transformed_data)

            # 3. Check Redis Cache First (Fast path - no DB hits needed)
            cache_key = f"product_hash_{sku}"
            cached_hash = cache.get(cache_key)

            if cached_hash == new_hash:
                skipped_count += 1
                logger.debug(f"SKU {sku} unchanged (cache hit), skipping.")
                continue

            # 4. Check DB if sync is needed (in case cache expired or is empty)
            # We use select_for_update to avoid race conditions if sync runs concurrently
            with transaction.atomic():
                sync_state, created = ProductSyncState.objects.select_for_update().get_or_create(sku=sku)
                
                if not created and sync_state.data_hash == new_hash:
                    # Data hasn't changed since last successful sync, populate cache
                    cache.set(cache_key, new_hash, timeout=None) # Keep in cache indefinitely
                    skipped_count += 1
                    logger.debug(f"SKU {sku} unchanged (DB hit), skipping.")
                    continue
                
                # 5. Data has changed or product is new. Send to API.
                success = send_to_eshop_api(sku, transformed_data, created, task_instance=self)
                
                if success:
                    # 6. Success -> Update the Hash in DB and Cache so we don't sync it next time
                    sync_state.data_hash = new_hash
                    sync_state.save()
                    cache.set(cache_key, new_hash, timeout=None)
                    synced_count += 1
                else:
                    failed_count += 1
                    
        except Exception as e:
            logger.error(f"Error processing product {raw_product.get('id', 'UNKNOWN')}: {e}")
            failed_count += 1

    result_msg = f"Sync finished. Synced: {synced_count}, Skipped (Delta Sync): {skipped_count}, Failed: {failed_count}."
    logger.info(result_msg)
    return result_msg


def send_to_eshop_api(sku: str, data: dict, is_new: bool, task_instance=None, _sync_retries_left: int = 3) -> bool:
    """
    Sends a single product to the e-shop API. Handles rate limiting and retries on 429.
    Returns True if successful, False otherwise.
    """
    headers = {
        'X-Api-Key': ESHOP_API_KEY,
        'Content-Type': 'application/json'
    }
    
    # Adhere to basic 5 req/s limit before actually making the call
    time.sleep(SLEEP_TIME_BETWEEN_REQUESTS)
    
    if is_new:
        method = requests.post
        url = f"{ESHOP_API_BASE_URL}/products/"
    else:
        method = requests.patch
        url = f"{ESHOP_API_BASE_URL}/products/{sku}/"

    try:
        response = method(url, json=data, headers=headers)
        
        if response.status_code in [200, 201]:
            logger.info(f"Successfully synced {sku}")
            return True
        elif response.status_code == 429:
            logger.warning(f"Rate limited (429) for SKU {sku}. Re-queueing via Celery retry mechanism.")
            # If we pass task_instance, we can leverage Celery's auto-retry
            if task_instance:
                # Exponential backoff e.g. 2s, 4s, 8s...
                retry_countdown = 2 ** task_instance.request.retries
                raise task_instance.retry(exc=Exception("429 Too Many Requests"), countdown=retry_countdown)
            elif _sync_retries_left > 0:
                # Fallback synchronous retry with bounded recursion depth
                time.sleep(2)
                logger.info(f"Retrying synchronously for {sku} ({_sync_retries_left} retries left)...")
                return send_to_eshop_api(sku, data, is_new, task_instance=None, _sync_retries_left=_sync_retries_left - 1)
            else:
                logger.error(f"Max synchronous retries exhausted for {sku}.")
                return False
                
        else:
            logger.error(f"Failed to sync {sku}. API responded with {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error syncing {sku}: {e}")
        # Could also trigger a celery retry here if desired
        return False
