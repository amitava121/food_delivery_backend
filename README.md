# QR Based Fast Food Ordering System — Backend

FastAPI backend matching the provided diagram.

## Related repositories

- Customer website: https://github.com/amitava121/food_delivery_website
- Admin panel: https://github.com/amitava121/food_delivery_admin

## Quick start

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open API docs: http://localhost:8000/docs

## Environment

Copy `.env.example` to `.env` and adjust. By default SQLite is used.

## Tests

```bash
pytest
```

Tests live in `tests/` and run against a disposable SQLite file (`test_api.db`), never the configured database.

## Frontends

- [food_delivery_website](https://github.com/amitava121/food_delivery_website) — customer-facing site. Update `api.js` (`BASE`) with the backend URL.
- [food_delivery_admin](https://github.com/amitava121/food_delivery_admin) — staff/admin panel. Update `api.js` (`BASE`) with the backend URL.
