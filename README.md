# EVE Healthcare Backend

## Overview

A small, production-minded backend for **diagnostic test bookings** with **simulated payments**
and **idempotent payment webhooks**.

* Users sign up / log in (JWT) and book a test at a diagnostic centre.
* Each centre sets its own price per test; the **server** snapshots that price onto the booking.
* Users pay for a booking through a simulated provider, or a payment provider can call the
  signed webhook. Booking state moves through a strict state machine.
* Webhooks are safe to deliver any number of times, even concurrently.

Stack: Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy 2.x (sync), Alembic, Pydantic v2,
PyJWT, Argon2 password hashing, pytest, Docker.

> **Why sync SQLAlchemy?** The workload is short, DB-bound request/response. FastAPI runs sync
> handlers in a thread pool, which is simple to reason about and fully adequate here. Async would
> add complexity (async driver, async sessions) without a measurable benefit.

## Architecture

```
Client
  |
  v
FastAPI  (app/main.py: routers + one exception handler)
  |
  +---- api/routes/*        thin HTTP layer: parse -> call service -> map to response schema
  |        |  api/dependencies.py: get_db, get_current_user, require_admin, webhook signature
  |        v
  +---- services/*          business rules, transactions, state machine
  |        auth_service, catalog_service, booking_service, payment_service, webhook_service
  |        v
  +---- models/* + db/*     SQLAlchemy models, constraints, session
           |
           v
       PostgreSQL           the final authority for uniqueness / integrity
```

| Layer | Responsibility |
|-------|----------------|
| **API (routes)** | HTTP concerns only: status codes, request/response schemas, auth dependencies. |
| **Schemas (Pydantic)** | Input validation (email, password strength, future appointment, positive money, enums). |
| **Services** | Business logic: ownership checks, price snapshot, state transitions, payment + webhook rules. Each service function owns its transaction (`db.commit()`). |
| **Models / DB** | Tables, foreign keys, CHECK and UNIQUE constraints (including a partial unique index). |
| **core/** | Settings, JWT/password/HMAC helpers, domain exceptions, logging. |

Domain errors (`NotFoundError`, `ConflictError`, ...) are raised by services and turned into JSON
`{"detail": "...", "code": "..."}` by one handler in `main.py`, so route handlers have no
try/except noise.

### Authentication

* `POST /auth/signup` stores an **Argon2id** hash (never the password). Emails are lower-cased and
  unique (DB `UNIQUE` + `CHECK (email = lower(email))`).
* `POST /auth/login` returns an HS256 JWT (`sub` = user id, `iat`, `exp`; default 60 min).
* Protected endpoints use the `get_current_user` dependency (`Authorization: Bearer <token>`).
  Missing/invalid/expired token -> **401** with `WWW-Authenticate: Bearer`.
* Login returns the same 401 for "unknown email" and "wrong password" and always performs one
  hash verification, to avoid user enumeration (including by timing).
* Catalogue **write** endpoints need `users.is_admin = true` (otherwise **403**). Admins are
  created with the seed script, never through the API.

## Database Schema

```
users 1---* bookings *---1 center_tests *---1 diagnostic_centers
                 |             (center_id, test_id) UNIQUE, price > 0
                 |                              *---1 diagnostic_tests
                 1
                 |
                 *
              payments            payment_webhook_events (event_id UNIQUE)
```

| Table | Key points |
|-------|-----------|
| `users` | `email` UNIQUE + lower-case CHECK, `password_hash`, `is_admin`. |
| `diagnostic_centers` | name, location. |
| `diagnostic_tests` | unique name, description. |
| `center_tests` | A centre offers a test at a **price** (`CHECK price > 0`, `UNIQUE(center_id, test_id)`). Different centres can charge differently. |
| `bookings` | `user_id`, `center_id`, `test_id`, `appointment_at`, **`amount` (price snapshot)**, `status`. A **composite FK** `(center_id, test_id) -> center_tests` means the DB itself rejects a booking for a test the centre does not offer. |
| `payments` | `booking_id`, `provider_payment_id` (**UNIQUE**, nullable), `amount`, `status`. **Partial unique index** `UNIQUE (booking_id) WHERE status = 'SUCCESS'` -> a booking can never have two successful payments, even if app code has a bug. |
| `payment_webhook_events` | `event_id` **UNIQUE**, `provider_payment_id`, `payload` (JSONB), `payload_hash`, `processed_at`, `created_at`. |

Money is `NUMERIC(10,2)` / `Decimal`, never float. (JSON responses render it as a number.)
Statuses are Python `StrEnum`s stored as `VARCHAR` with a CHECK constraint (no native PG enum, so
adding a status later is a simple migration).

**Historical price preservation:** `bookings.amount` is copied from `center_tests.price` when the
booking is created and is never recomputed. Changing a centre's price affects only *future*
bookings (covered by `test_historical_price_is_preserved_when_center_changes_price`).

## Booking Flow

```
Booking created
  |
  v
PENDING
  |
  +---- Payment SUCCESS ---> CONFIRMED ---- cancel ---> CANCELLED
  |
  +---- Payment FAILED ----> FAILED          (final)
  |
  +---- Cancel -----------> CANCELLED        (final)
```

Allowed transitions (anything else -> **409 `invalid_state_transition`**):

| From | To |
|------|----|
| PENDING | CONFIRMED, FAILED, CANCELLED |
| CONFIRMED | CANCELLED |
| FAILED | - |
| CANCELLED | - |

The transition table lives in `booking_service.ALLOWED_TRANSITIONS`; `transition()` is the **only**
function that changes `booking.status`. Payment, webhook and cancel all go through it.

**Payment (`POST /payments/`)** — in one transaction: lock the booking row
(`SELECT ... FOR UPDATE`, scoped to the current user), require `PENDING`, simulate the outcome,
insert the `Payment`, move the booking to `CONFIRMED`/`FAILED`, commit. Two simultaneous payment
attempts are serialised by the row lock; the loser sees a non-PENDING booking and gets 409. The
charged amount is always `booking.amount`.

## Webhook Idempotency

`POST /payments/webhook/` (also accepted without the trailing slash).

**Authenticity:** the provider signs the raw body with HMAC-SHA256 using `WEBHOOK_SECRET` and sends
the hex digest in `X-Webhook-Signature`. Missing/invalid -> 401. (Without this, anyone could confirm
bookings for free.)

**How duplicates are prevented** (`services/webhook_service.py`):

1. Start a transaction and `INSERT` a row into `payment_webhook_events`. `event_id` has a database
   `UNIQUE` constraint, so only one transaction can ever claim a given `event_id`.
2. If the insert raises `IntegrityError` the event was already accepted. We roll back, load the
   stored event and compare `payload_hash`:
   * same hash -> **200 `{"result": "duplicate"}`**, nothing is changed;
   * different hash -> **409** (`event_id` reused with a different body).
3. Otherwise lock the booking (`FOR UPDATE`), validate, create the `Payment`, update the booking,
   set `processed_at`, and **commit once**. Any rejection raises, which rolls back everything
   including the event row.

**Why not `if event_exists(): return`?** Two identical requests can both run the check before either
inserts, and both would proceed. Here the *insert itself* is the check: in PostgreSQL the second
inserter blocks until the first transaction finishes and then fails with a unique violation, so
exactly one request does the work. `test_concurrent_identical_webhooks_create_exactly_one_payment`
fires 8 identical requests from 8 threads and asserts exactly one `processed`, seven `duplicate`,
one payment and one event row.

A rejected event is **not** recorded (the transaction rolls back), so after the cause is fixed
(e.g. the booking is created) the provider can redeliver the same `event_id`.

### Webhook state rules

| Situation | Result |
|-----------|--------|
| Same event delivered again (identical payload) | 200 `duplicate`, no change |
| Same `event_id`, different payload | 409 |
| Booking does not exist | 404 |
| `amount` != booking amount | 422 |
| `provider_payment_id` already belongs to another booking | 409 |
| `SUCCESS` on PENDING | payment SUCCESS, booking CONFIRMED -> 200 `processed` |
| `FAILED` on PENDING | payment FAILED, booking FAILED -> 200 `processed` |
| Same provider payment, same outcome, but new `event_id` | 200 `ignored`, no change |
| `SUCCESS` after `FAILED` | 409 (FAILED is final) |
| `FAILED` after `SUCCESS` | 409 (a confirmed booking is not failed by a late event) |
| A *second, different* `SUCCESS` payment for a confirmed booking | 409 (no duplicate payments) |
| Any payment on a CANCELLED booking | 409 (logged as a warning: needs refund / manual review) |
| Unsupported `status`, bad amount, empty ids | 422 |

Principle: **reject inconsistent events rather than silently corrupting state**. Rejections are
logged with `event_id` and reason.

## HTTP status codes

| Code | Used for |
|------|----------|
| 200 | Reads, cancel, webhook (processed / duplicate / ignored), login |
| 201 | Signup, booking, payment, admin creates |
| 401 | Missing/invalid/expired JWT, bad login, bad webhook signature |
| 403 | Authenticated but not admin (catalogue writes) |
| 404 | Resource missing **or not owned by the caller** (bookings, payments) |
| 409 | Duplicate email, invalid state transition, duplicate payment, webhook state conflict |
| 422 | Schema validation errors, test not offered by centre, webhook amount mismatch |

**Ownership strategy:** another user's booking returns **404**, identical to a non-existent one, so
IDs cannot be probed. (403 is used only for role checks.) Errors look like
`{"detail": "...", "code": "invalid_state_transition"}`.

## Frontend

A small no-build UI (plain HTML/CSS/JS in `frontend/`) is served by FastAPI itself at
**http://localhost:8000/ui/** (`/` redirects there), so there is no CORS setup and nothing extra to run.
It supports sign up / log in, browsing centres with per-centre prices, booking a test, paying
(simulated) and cancelling, with status badges. The JWT is kept in `localStorage`; all API data is
rendered with `textContent` (no `innerHTML`). Run the seed script first so there are centres to book.
The webhook is a server-to-server endpoint and intentionally has no UI.

## API documentation

Swagger UI: `http://localhost:8000/docs` - ReDoc: `/redoc` - OpenAPI JSON: `/openapi.json`.
Log in via `POST /auth/login`, click **Authorize**, and paste the token.

| Method & path | Auth | Purpose |
|---------------|------|---------|
| POST `/auth/signup` | - | Create account |
| POST `/auth/login` | - | Get JWT |
| GET `/auth/me` | user | Current user |
| GET `/centers`, `/centers/{id}` | - | Centres; detail includes tests + price |
| GET `/tests`, `/tests/{id}` | - | Tests; detail lists centres + price |
| POST `/centers`, POST `/tests`, PUT `/centers/{id}/tests/{test_id}` | admin | Manage catalogue / prices |
| POST `/bookings` | user | Create PENDING booking (server-side amount) |
| GET `/bookings`, `/bookings/{id}` | user | Own bookings only |
| POST `/bookings/{id}/cancel` | user | Cancel if transition is valid |
| POST `/payments/` | user | Simulated payment |
| POST `/payments/webhook/` | HMAC signature | Provider events (idempotent) |
| GET `/health` | - | Liveness |

## Running Locally

Requires Python 3.12+ and a PostgreSQL 16 database.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env            # then edit secrets / DATABASE_URL
export $(grep -v '^#' .env | xargs)   # or just keep .env in the project root (it is auto-loaded)

alembic upgrade head            # create the schema from migrations
python -m app.scripts.seed      # optional: sample centres/tests + admin (ADMIN_EMAIL/ADMIN_PASSWORD)
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Quick Postgres without installing anything: `docker compose up -d postgres`.

## Docker

```bash
cp .env.example .env            # set JWT_SECRET, WEBHOOK_SECRET, POSTGRES_PASSWORD
docker compose up --build       # postgres + backend; migrations run automatically
docker compose exec backend python -m app.scripts.seed   # optional sample data + admin
```

API: `http://localhost:8000`, docs: `http://localhost:8000/docs`. Stop with
`docker compose down` (add `-v` to delete the database volume).

## Running Tests

The tests need PostgreSQL (unique constraints, row locks and concurrent inserts are Postgres
behaviour). The schema is created by running the Alembic migrations, so migrations are tested too.

```bash
# Everything in Docker (one command, no local setup):
docker compose run --rm tests

# Or locally, with a postgres database named eve_test available:
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/eve_test
pytest
```

`docker compose` creates the `eve_test` database automatically the first time the volume is
created (if your volume pre-dates this, run
`docker compose exec postgres psql -U postgres -c "CREATE DATABASE eve_test;"`).
Lint: `ruff check .`

## API Examples

```bash
BASE=http://localhost:8000

# 1. Sign up
curl -s -X POST $BASE/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"jane@example.com","password":"secret123","full_name":"Jane Doe"}'

# 2. Log in (keep the token)
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"jane@example.com","password":"secret123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 3. List centres, then look at one (tests + prices)
curl -s $BASE/centers
curl -s $BASE/centers/1

# 4. Create a booking (amount is NOT sent; the server decides it)
curl -s -X POST $BASE/bookings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"center_id":1,"test_id":1,"appointment_at":"2027-10-05T10:30:00Z"}'

# 5a. Simulated payment
curl -s -X POST $BASE/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id":1}'

# 5b. ...or a provider webhook (sign the exact body with WEBHOOK_SECRET)
BODY='{"event_id":"evt_12345","provider_payment_id":"pay_12345","booking_id":1,"status":"SUCCESS","amount":500}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')
curl -s -X POST $BASE/payments/webhook/ -H "X-Webhook-Signature: $SIG" \
  -H 'Content-Type: application/json' -d "$BODY"
# send it again -> {"event_id":"evt_12345","booking_id":1,"result":"duplicate"}
```

(Use a booking you have not already paid for in 5b. The seed data creates Apollo Diagnostics with
CBC at 500.00.) Set `PAYMENT_SUCCESS_RATE=1` to make the simulated payment always succeed.

## Assumptions

1. A booking is for one test at one centre at one time; there is no slot capacity or double-booking
   check (see future improvements).
2. Appointment time must be timezone-aware and in the future.
3. The simulated payment succeeds with probability `PAYMENT_SUCCESS_RATE` (default 0.8). A FAILED
   payment makes the booking FAILED (final, per the specified state machine), so the user books
   again rather than retrying.
4. Cancelling a CONFIRMED booking only changes its status; **refunds are out of scope**. A payment
   webhook arriving for a cancelled booking is rejected (409) and logged for manual review.
5. Webhooks must be HMAC-signed (my addition; the assignment did not specify authentication).
   The webhook `amount` must equal the booking amount exactly.
6. Prices are in a single implicit currency with 2 decimal places.
7. Rejected webhook events are not stored, so they can be redelivered after the cause is fixed.
8. Admin = `users.is_admin`, created via the seed script. There is no admin signup endpoint.
9. Lists are paginated with `limit` (1-100, default 50) and `offset`.
10. Tokens are short-lived access tokens only; no refresh tokens or revocation.

## Future Improvements (not implemented)

* Appointment availability / slot management and double-booking prevention
* Real payment-provider integration, refunds for cancelled-after-paid bookings
* Background processing (Celery/queue) for webhook side-effects; webhook replay-window check
* Rate limiting (especially `/auth/login`) and account lockout
* Redis caching of the read-heavy centre/test catalogue
* Structured JSON logging, request IDs, metrics/tracing (observability)
* More granular roles / permissions, refresh tokens and token revocation
* Optimistic concurrency / `ETag`s for catalogue edits
