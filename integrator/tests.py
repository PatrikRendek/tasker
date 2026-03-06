from django.test import TestCase
from unittest.mock import patch, MagicMock
from integrator.logic import transform_product, calculate_hash
from integrator.models import ProductSyncState
from integrator.tasks import sync_erp_to_eshop, send_to_eshop_api
import json

class TransformationTests(TestCase):
    def test_transform_product_normal(self):
        raw = {
            "id": "SKU-TEST-1",
            "title": "Kávovar",
            "price_vat_excl": 1000,
            "stocks": {"sklad1": 5, "sklad2": 10},
            "attributes": {"color": "červená"}
        }
        res = transform_product(raw)
        self.assertEqual(res['sku'], "SKU-TEST-1")
        self.assertEqual(res['price_vat_incl'], 1210.0) # 1000 * 1.21
        self.assertEqual(res['total_stock'], 15)
        self.assertEqual(res['color'], "červená")

    def test_transform_product_missing_color(self):
        raw = {
            "id": "SKU-TEST-2",
            "title": "Hrnček",
            "price_vat_excl": 100,
            "stocks": {"sklad1": 5},
            "attributes": None
        }
        res = transform_product(raw)
        self.assertEqual(res['color'], "N/A")
        
    def test_transform_product_negative_price(self):
        raw = {
            "id": "SKU-TEST-3",
            "price_vat_excl": -50,
        }
        res = transform_product(raw)
        self.assertEqual(res['price_vat_incl'], 0.0)


class SyncTaskTests(TestCase):
    @patch('integrator.tasks.cache')
    @patch('integrator.tasks.load_erp_data')
    @patch('integrator.tasks.send_to_eshop_api')
    def test_sync_new_product(self, mock_send, mock_load, mock_cache):
        # Arrange
        mock_load.return_value = [{
            "id": "SKU-NEW", 
            "title": "Novinka", 
            "price_vat_excl": 500,
            "stocks": {"x": 1},
            "attributes": {}
        }]
        mock_send.return_value = True
        mock_cache.get.return_value = None # Cache miss
        
        # Act
        sync_erp_to_eshop()
        
        # Assert
        self.assertTrue(ProductSyncState.objects.filter(sku="SKU-NEW").exists())
        mock_send.assert_called_once()
        mock_cache.set.assert_called_once() # Should cache after DB save
        
    @patch('integrator.tasks.cache')
    @patch('integrator.tasks.load_erp_data')
    @patch('integrator.tasks.send_to_eshop_api')
    def test_sync_existing_unchanged_product_delta_sync_cache_hit(self, mock_send, mock_load, mock_cache):
        # Arrange: Setup DB with existing hash
        raw_data = {
            "id": "SKU-EXIST", 
            "title": "Starinka", 
            "price_vat_excl": 500,
            "stocks": {"x": 1},
            "attributes": {}
        }
        transformed = transform_product(raw_data)
        hashed = calculate_hash(transformed)
        # We don't even need to create DB state because Cache hits first
        # ProductSyncState.objects.create(sku="SKU-EXIST", data_hash=hashed)
        
        mock_load.return_value = [raw_data]
        mock_cache.get.return_value = hashed # Cache Hit
        
        # Act
        sync_erp_to_eshop()
        
        # Assert: API should NOT be called because hash matches
        mock_send.assert_not_called()
        
    @patch('integrator.tasks.cache')
    @patch('integrator.tasks.load_erp_data')
    @patch('integrator.tasks.send_to_eshop_api')
    def test_sync_existing_unchanged_product_delta_sync_db_hit(self, mock_send, mock_load, mock_cache):
        # Arrange: Setup DB with existing hash
        raw_data = {
            "id": "SKU-EXIST", 
            "title": "Starinka", 
            "price_vat_excl": 500,
            "stocks": {"x": 1},
            "attributes": {}
        }
        transformed = transform_product(raw_data)
        hashed = calculate_hash(transformed)
        ProductSyncState.objects.create(sku="SKU-EXIST", data_hash=hashed)
        
        mock_load.return_value = [raw_data]
        mock_cache.get.return_value = None # Cache Miss, fallback to DB
        
        # Act
        sync_erp_to_eshop()
        
        # Assert: API should NOT be called because DB hash matches
        mock_send.assert_not_called()
        mock_cache.set.assert_called_once() # We repopulated the cache
        

class ApiCallTests(TestCase):
    @patch('integrator.tasks.requests.post')
    @patch('integrator.tasks.time.sleep') # prevent test from actually sleeping
    def test_api_post_success(self, mock_sleep, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp
        
        success = send_to_eshop_api("SKU-X", {"k": "v"}, is_new=True)
        self.assertTrue(success)
        mock_post.assert_called_once()
        
    @patch('integrator.tasks.requests.patch')
    @patch('integrator.tasks.time.sleep')
    def test_api_patch_429_retry(self, mock_sleep, mock_patch):
        # Fake task instance to test retry exception throwing
        mock_task = MagicMock()
        mock_task.request.retries = 1
        mock_task.retry = MagicMock(side_effect=Exception("RetryTriggered"))
        
        # Fake 429 response
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_patch.return_value = mock_resp
        
        # Act & Assert
        with self.assertRaises(Exception) as context:
            send_to_eshop_api("SKU-Y", {"k": "v"}, is_new=False, task_instance=mock_task)
            
        self.assertEqual(str(context.exception), "RetryTriggered")
        mock_patch.assert_called_once()
        mock_task.retry.assert_called_once()
