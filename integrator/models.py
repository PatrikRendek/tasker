from django.db import models

class ProductSyncState(models.Model):
    """
    Model for tracking the synchronization state of products from ERP.
    Used for Delta Sync to avoid unnecessary API calls.
    """
    sku = models.CharField(max_length=255, primary_key=True, help_text="Stock Keeping Unit from ERP")
    data_hash = models.CharField(max_length=64, help_text="SHA-256 hash of the transformed product data")
    last_sync_at = models.DateTimeField(auto_now=True, help_text="Timestamp of the last successful sync check")

    def __str__(self):
        return f"{self.sku} (Last synced: {self.last_sync_at.strftime('%Y-%m-%d %H:%M:%S') if self.last_sync_at else 'Never'})"
