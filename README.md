# Symmy Tasker: E-Shop Integrator

A synchronization microservice (bridge) between a simulated ERP system (local JSON repository) and a fictitious e-shop API, built using Django, Celery asynchronous tasks, Redis, and a PostgreSQL database.

## Key Features
- **Delta Sync + Redis Cache**: Only products that have undergone any change are sent to the external e-shop API. This is determined using SHA-256 hashes of the JSON transformations. Hashes are stored and checked against a fast **Redis internal cache** first to avoid thousands of unnecessary PostgreSQL queries, defaulting to DB locks only when changes are detected.
- **Asynchrony and Stability**: The process is delegated to the background (Celery worker), which does not block other parts of the application. The rate limit of 5 requests/s per e-shop API call is enforced via a synchronous delay between requests, which is sufficient for serial processing within a single worker. For distributed multi-worker setups, this could be upgraded to a shared Token Bucket pattern backed by Redis.
- **Auto-Retries (HTTP 429)**: When the API returns "Too Many Requests", the Celery task schedules a retry utilizing "Exponential Backoff", ensuring delivery after the stream slows down.
- **Data Processing and Business Rules**: Automatic summation of stocks across multiple warehouses, exact calculation of the final price (+21% VAT) using `Decimal` precision to prevent floating-point rounding errors, and fallback logic for missing attributes (`color: "N/A"`).

## Architecture and Dependencies
- **Django**: The main application framework and mapping of the model to the database to maintain the synchronization state (`ProductSyncState`).
- **PostgreSQL**: Persistent, transactional storage of the identifiers of the transferred products and their hash.
- **Redis**: A fast memory broker serving two purposes: asynchronous queues in Celery and blazing-fast in-memory Cache for `django.core.cache`.
- **Celery**: Background execution of `sync_erp_to_eshop` tasks and throttling retries.
- The core code of the integrator is located in the Django app `integrator` (`integrator/tasks.py` and `integrator/logic.py`).

---

## 🚀 Quick Start and Execution

The project is ready to run smoothly in a Docker ecosystem.

**1. Starting the infrastructure (DB, Redis, Web Server, Celery worker)**
```bash
docker-compose up -d --build
```
At this point, 4 containers will spin up. Note that the DB container may take a few seconds to initialize. The application automatically applies database migrations on startup. If not, you can run:

```bash
docker-compose exec web python manage.py migrate
```

**2. Starting the synchronization process (Simulation)**
In your local terminal, launch an interactive Django shell connected to the web container:
```bash
docker-compose exec web python manage.py shell
```
In the shell, trigger the asynchronous task:
```python
from integrator.tasks import sync_erp_to_eshop
sync_erp_to_eshop.delay()
```
This sends a command to the Redis queue. The Celery Worker (running in the `worker` container) picks it up and begins sending POST and PATCH requests. You can monitor the worker logs using:
```bash
docker-compose logs -f worker
```

---

## 🛡️ Testing
Unit and integration test coverage is applied, utilizing both `unittest.mock` and the `responses` library for HTTP-level mocking of external API calls. This ensures off-grid stability of transformation processes, Rate Limit retry logic, and prevention of unnecessary network requests (Delta Sync).

To run locally inside the Docker container:
```bash
docker-compose exec web python manage.py test integrator
```

---
*Repository generated for the Symmy task purposes.*
