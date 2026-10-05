# QR Based Fast Food Ordering System — Backend API

Production-ready FastAPI backend powering the Spice Route restaurant ordering, kitchen dispatch, stock management, and administrative platform.

## Related Repositories

- **Customer Website**: [food_delivery_website](https://github.com/amitava121/food_delivery_website) (Port 3000)
- **Admin & Kitchen Panel**: [food_delivery_admin](https://github.com/amitava121/food_delivery_admin) (Port 3001)

---

## Technology Stack

- **Framework**: FastAPI (Python 3.11+)
- **Database & ORM**: SQLAlchemy 2.0 (Async) + aiosqlite (Local) / asyncpg (PostgreSQL in production)
- **Authentication**: JWT (OAuth2 Password Bearer) with role-based access control (RBAC)
- **Real-Time**: WebSockets (`/ws/orders` with token authentication, `/ws/menu`)
- **Testing**: Pytest + AnyIO + Selenium (Edge headless)

---

## Quick Start & Installation

### 1. Setup Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\activate   # Windows
# or: source venv/bin/activate  # macOS / Linux
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```
Default `.env` configuration uses local SQLite:
```ini
DATABASE_URL=sqlite+aiosqlite:///./qr_orders.db
SECRET_KEY=change-me-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=1440
ALGORITHM=HS256
```

### 4. Seed Database (Optional / First Run)
```powershell
python seed.py
```
This initializes sample categories, dishes, demo users, and restaurants.

### 5. Start the Server
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- Interactive API Documentation: http://127.0.0.1:8000/docs
- Alternative ReDoc: http://127.0.0.1:8000/redoc

---

## Roles & Demo Accounts

| Role | Demo Email | Demo Password | Responsibilities |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `owner@demo.com` | `demo123` | Full authority, administrator account management, store configuration |
| **Admin** | `admin@demo.com` | `demo123` | Menu CRUD, category CRUD, user management, order dispatch, reports |
| **Kitchen / Chef** | `chef@demo.com` | `demo123` | Live kitchen queue, preparation flow (`confirmed` → `preparing` → `ready`) |
| **Customer** | `customer@demo.com` | `demo123` | Browsing menu, cart, checkout, delivery/pickup tracking, order history |

---

## Order State Machine

The order pipeline enforces strict forward progression and state validity:
- **Pickup Flow**:
  `pending` → `confirmed` → `preparing` → `ready` → `picked_up`
- **Delivery Flow**:
  `pending` → `confirmed` → `preparing` → `ready` → `out_for_delivery` → `delivered`
- **Cancellation & Stock Rule**:
  Stock is restored only if cancelled in `pending` or `confirmed` status. Once preparation starts (`preparing`), stock is preserved to prevent artificial inventory inflation.
- **Terminal States**: `picked_up`, `delivered`, `cancelled` (cannot be transitioned or reopened by any role).

---

## Testing & Verification

### Run Complete Pytest Suite
```powershell
pytest -v
```
Runs 19 comprehensive tests against an isolated, disposable SQLite database (`test_api.db`):
- `tests/api/test_api.py` (Core endpoints, root, health)
- `tests/api/test_orders.py` (Authoritative pricing, stock deduction, BOLA, idempotency)
- `tests/api/test_phase2_hardening.py` (Concurrency, query profiling, rollback, WebSocket isolation, state machine)
- `tests/api/test_role_separation.py` (RBAC, Super Admin vs Admin rules)

### Run Live Browser Automation Verification
```powershell
python -u verify_browser_full.py
```
Automates Customer, Chef, and Admin workflows in headless Edge with responsive verification across 375px, 390px, 768px, 1024px, and 1440px viewports.
