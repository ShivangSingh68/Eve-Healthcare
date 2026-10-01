# EVE Healthcare Backend

A small, production-minded backend for **diagnostic test bookings**, **simulated payments** and
**idempotent payment webhooks**, plus a tiny demo UI.

**Contents:** [Overview](#overview) · [1. Running locally](#1-how-to-run-the-project-locally) ·
[2. API endpoints & examples](#2-api-endpoints-and-example-requests) ·
[3. Database / schema design](#3-database-and-schema-design) ·
[4. Assumptions](#4-important-assumptions) · [5. Improvements](#5-what-i-would-improve-with-more-time) ·
[Design notes](#design-notes) · [Testing](#running-the-tests)

## Overview

* Users sign up / log in (JWT) and book a test at a diagnostic centre.
* Each centre sets its own price per test; the **server** snapshots that price onto the booking, so
  the client can never choose the amount and later price changes don't rewrite history.
* A booking is paid through a simulated provider (`POST /payments/`) or by a signed provider
  webhook. Booking status follows a strict state machine.
* Webhooks are idempotent: delivering the same event many times, even concurrently, has the effect
  of delivering it once.

**Stack:** Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy 2.x (sync), Alembic, Pydantic v2, PyJWT,
Argon2, pytest, Docker. Sync SQLAlchemy is deliberate: the workload is short, DB-bound
request/response, FastAPI runs sync handlers in a thread pool, and async would add complexity
without a measurable benefit here.

```
Client (browser UI / curl / payment provider)
  |
  v
FastAPI ── api/routes/*      thin HTTP layer: validate -> call service -> shape response
  |         api/dependencies  get_db, get_current_user, require_admin, webhook signature check
  v
services/*                   business rules, transactions, state machine
  |                          auth, catalog, booking, payment, webhook
  v
models/* + db/*              SQLAlchemy models and DB constraints
  |
  v
PostgreSQL                   final authority for uniqueness and integrity
```

---

## 1. How to run the project locally

Pick **one** option. Both give you the API at `http://localhost:8000`, Swagger at `/docs`, and the
demo UI at `/ui/`.

### Option A — Docker (recommended; only Docker needed)

```bash
cp .env.example .env     # then edit: JWT_SECRET (32+ chars), WEBHOOK_SECRET, POSTGRES_PASSWORD
docker compose up --build
```

`docker compose up` starts PostgreSQL, waits until it is healthy, runs `alembic upgrade head`, then
starts the API. In another terminal, load sample data (and an admin user):

```bash
docker compose exec backend python -m app.scripts.seed
```

Stop with `docker compose down` (add `-v` to also delete the database volume).

### Option B — Python on your machine

Requires Python 3.12+ and a PostgreSQL 16 database.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env            # set DATABASE_URL, JWT_SECRET, WEBHOOK_SECRET
docker compose up -d postgres   # optional: easiest way to get a local Postgres on :5432

alembic upgrade head            # create the schema from the migrations
python -m app.scripts.seed      # sample centres/tests + admin (uses ADMIN_EMAIL / ADMIN_PASSWORD)
uvicorn app.main:app --reload
```

`.env` is loaded automatically by the app and by Alembic. To use its values in your shell (needed
for the signed-webhook curl example below): `set -a; source .env; set +a`.

### Configuration (environment variables)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/dbname` |
| `JWT_SECRET` | HS256 signing key, **min 32 chars** (generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
| `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | Defaults `HS256`, `60` |
| `WEBHOOK_SECRET` | Shared with the payment provider to verify webhook HMAC signatures (min 16 chars) |
| `PAYMENT_SUCCESS_RATE` | Chance (0–1) the *simulated* payment succeeds. Default `0.8`; use `1` for demos |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Optional, only read by the seed script to create an admin |
| `LOG_LEVEL` | Default `INFO` |

No secret is hard-coded; `.env` is git-ignored and `.env.example` holds placeholders only.

### Demo UI

Open **http://localhost:8000/ui/** (`/` redirects there): sign up / log in, browse centres with
their prices, book a test, pay (simulated) and cancel. It is plain HTML/JS in `frontend/`, served by
FastAPI itself (same origin, no CORS, no build step). The webhook has no UI (server-to-server).

---

## 2. API endpoints and example requests

Interactive docs: **Swagger UI `/docs`**, ReDoc `/redoc`, OpenAPI JSON `/openapi.json`. In Swagger,
call `POST /auth/login`, click **Authorize** and paste the token.

| Method & path | Auth | Purpose | Success |
|---------------|------|---------|---------|
| `POST /auth/signup` | – | Create account | 201 |
| `POST /auth/login` | – | Exchange credentials for a JWT | 200 |
| `GET /auth/me` | user | Current user | 200 |
| `GET /centers`, `GET /centers/{id}` | – | Centres; detail includes offered tests **with price** | 200 |
| `GET /tests`, `GET /tests/{id}` | – | Tests; detail lists the centres offering it with price | 200 |
| `POST /centers`, `POST /tests` | admin | Create centre / test | 201 |
| `PUT /centers/{id}/tests/{test_id}` | admin | Offer a test at a centre / change its price | 201 / 200 |
| `POST /bookings` | user | Create a `PENDING` booking (amount decided by server) | 201 |
| `GET /bookings`, `GET /bookings/{id}` | user | **Own** bookings only | 200 |
| `POST /bookings/{id}/cancel` | user | Cancel if the state transition is valid | 200 |
| `POST /payments/` | user | Simulated payment for own booking | 201 |
| `POST /payments/webhook/` | HMAC signature | Payment-provider event (idempotent) | 200 |
| `GET /health` | – | Liveness | 200 |

List endpoints accept `limit` (1–100, default 50) and `offset`.

### Example requests (curl)

The examples use the seed data: *Apollo Diagnostics* (id 1) offers *CBC* (id 1) at 500.00.
Responses are trimmed; timestamps are illustrative.

```bash
BASE=http://localhost:8000
```

**1. Sign up** → `201`
```bash
curl -s -X POST $BASE/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"jane@example.com","password":"secret123","full_name":"Jane Doe"}'
# {"id":1,"email":"jane@example.com","full_name":"Jane Doe","created_at":"2026-10-02T09:00:00Z"}
```
Passwords need 8+ chars with a letter and a digit. A duplicate email (any letter case) → `409`.

**2. Log in** → `200`
```bash
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"jane@example.com","password":"secret123"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
# response body: {"access_token":"eyJ...","token_type":"bearer"}
```

**3. List centres, then one centre with its tests and prices** → `200`
```bash
curl -s $BASE/centers
# [{"id":1,"name":"Apollo Diagnostics","location":"Delhi"},{"id":2,"name":"LifeCare Labs","location":"Mumbai"}]
curl -s $BASE/centers/1
# {"id":1,"name":"Apollo Diagnostics","location":"Delhi",
#  "tests":[{"id":1,"name":"CBC","price":500.0},{"id":2,"name":"Lipid Profile","price":800.0}]}
```

**4. Create a booking** → `201` (note: no `amount` is sent; if a client sends one it is ignored)
```bash
curl -s -X POST $BASE/bookings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"center_id":1,"test_id":1,"appointment_at":"2027-10-05T10:30:00Z"}'
# {"id":1,"user_id":1,"center_id":1,"test_id":1,"appointment_at":"2027-10-05T10:30:00Z",
#  "amount":500.0,"status":"PENDING", ...}
```
Errors: centre or test missing → `404`; centre doesn't offer that test → `422`; past or
timezone-less `appointment_at` → `422`; no/invalid token → `401`.

**5a. Pay (simulated)** → `201`
```bash
curl -s -X POST $BASE/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id":1}'
# {"id":1,"booking_id":1,"provider_payment_id":"sim_9f2c...","amount":500.0,
#  "status":"SUCCESS","booking_status":"CONFIRMED","created_at":"..."}
```
Paying again → `409`. Someone else's or a non-existent booking → `404`. Set
`PAYMENT_SUCCESS_RATE=1` for a guaranteed success (a failure sets the booking to `FAILED`).

**5b. Payment-provider webhook** (use a *second, unpaid* booking, here id 2) → `200`
```bash
curl -s -X POST $BASE/bookings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"center_id":1,"test_id":1,"appointment_at":"2027-10-06T10:30:00Z"}' >/dev/null

# The provider signs the exact body with WEBHOOK_SECRET (HMAC-SHA256, hex):
BODY='{"event_id":"evt_12345","provider_payment_id":"pay_12345","booking_id":2,"status":"SUCCESS","amount":500}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')

curl -s -X POST $BASE/payments/webhook/ -H "X-Webhook-Signature: $SIG" \
  -H 'Content-Type: application/json' -d "$BODY"
# {"event_id":"evt_12345","booking_id":2,"result":"processed"}

# Send the identical request again -> still 200, nothing changes:
# {"event_id":"evt_12345","booking_id":2,"result":"duplicate"}
```

**6. Cancel a booking** → `200`
```bash
curl -s -X POST $BASE/bookings/1/cancel -H "Authorization: Bearer $TOKEN"
# {"id":1, ..., "status":"CANCELLED"}   (cancelling again -> 409 invalid_state_transition)
```

**Admin-only** (create the admin with the seed script, log in as that user): `POST /centers`,
`POST /tests`, `PUT /centers/{id}/tests/{test_id}` with `{"price": 700}`. Regular users get `403`.

### Error format and status codes

Every error is JSON: `{"detail": "human readable", "code": "machine_code"}` (validation errors use
FastAPI's standard `422` body).

| Code | Used for |
|------|----------|
| 200 / 201 | Success / created |
| 401 | Missing, invalid or expired JWT; bad login; bad webhook signature |
| 403 | Authenticated but not an admin (catalogue writes) |
| 404 | Resource missing **or not owned by the caller** |
| 409 | Duplicate email, invalid state transition, duplicate payment, webhook state conflict |
| 422 | Schema validation, test not offered by centre, webhook amount mismatch |

**Authorization strategy:** another user's booking returns **404**, identical to a non-existent one,
so IDs cannot be probed. 403 is used only for role checks.

---

## 3. Database and schema design

```
users 1──* bookings *──1 center_tests *──1 diagnostic_centers
                │        UNIQUE(center_id, test_id)
                │        price > 0   *──1 diagnostic_tests
                1
                │
                *
            payments                 payment_webhook_events   (event_id UNIQUE)
```

| Table | Columns / constraints |
|-------|-----------------------|
| `users` | `email` **UNIQUE** + `CHECK (email = lower(email))`, `password_hash` (Argon2id), `full_name`, `is_admin`, timestamps |
| `diagnostic_centers` | `name`, `location`, timestamps |
| `diagnostic_tests` | `name` UNIQUE, `description`, timestamps |
| `center_tests` | Join table with a payload: `center_id`, `test_id`, **`price`**. `UNIQUE(center_id, test_id)`, `CHECK price > 0`, FKs. Lets each centre charge its own price for the same test. |
| `bookings` | `user_id`, `center_id`, `test_id`, `appointment_at`, **`amount`**, `status`. **Composite FK** `(center_id, test_id) → center_tests`, so the DB rejects a booking for a test the centre doesn't offer. `CHECK amount > 0`. Index `(user_id, created_at)` for "my bookings". |
| `payments` | `booking_id` FK, `provider_payment_id` **UNIQUE** (nullable), `amount`, `status`. **Partial unique index `UNIQUE(booking_id) WHERE status = 'SUCCESS'`**. |
| `payment_webhook_events` | `event_id` **UNIQUE**, `provider_payment_id`, `payload` (JSONB), `payload_hash`, `processed_at`, `created_at` |

**Design decisions**

* **Price snapshot.** `bookings.amount` is copied from `center_tests.price` at booking time and never
  recomputed. Changing a price affects only future bookings.
* **Money** is `NUMERIC(10,2)` / `Decimal`, never float (the API renders it as a JSON number).
* **Invariants live in the database**, not only in Python: unique email, unique `event_id`, unique
  `provider_payment_id`, at most one `SUCCESS` payment per booking, positive prices/amounts, valid
  statuses (CHECK on `VARCHAR`; a native PG enum is harder to migrate), valid centre+test pair.
* **Migrations:** Alembic (`alembic/versions/0001_initial_schema.py`); the app never calls
  `create_all()`. Constraint names follow a naming convention for clean future migrations.
* Foreign keys use `RESTRICT` for bookings/payments so financial history can't be deleted by accident.

### Booking state machine

```
              ┌── payment SUCCESS ──> CONFIRMED ── cancel ──> CANCELLED
PENDING ──────┼── payment FAILED  ──> FAILED        (final)
              └── cancel ───────────> CANCELLED     (final)
```

| From | Allowed to |
|------|-----------|
| PENDING | CONFIRMED, FAILED, CANCELLED |
| CONFIRMED | CANCELLED |
| FAILED, CANCELLED | – (final) |

Anything else → `409 invalid_state_transition`. The table is `booking_service.ALLOWED_TRANSITIONS`
and `transition()` is the **only** function that changes `booking.status`; payment, webhook and
cancel all use it.

---

## Design notes

### Payment (`POST /payments/`)
One transaction: lock the user's booking row (`SELECT … FOR UPDATE`) → require `PENDING` → simulate
outcome → insert `Payment` → move booking to `CONFIRMED`/`FAILED` → commit. Concurrent attempts are
serialised by the lock, so the loser sees a non-`PENDING` booking and gets `409`. The partial unique
index is the backstop that makes a second `SUCCESS` payment impossible even if the code were wrong.

### Webhook idempotency (`services/webhook_service.py`)
**Authenticity:** the provider sends `X-Webhook-Signature` = hex HMAC-SHA256 of the raw body keyed
with `WEBHOOK_SECRET`; missing/invalid → `401` (checked before body validation).

**Duplicate protection:**
1. `INSERT` into `payment_webhook_events` first. `UNIQUE(event_id)` lets only one transaction claim an id.
2. On `IntegrityError` → roll back, load the stored event, compare `payload_hash`: same → `200
   duplicate` (no change); different → `409` (event id reused with a different body).
3. Otherwise lock the booking, validate, create the payment, update the booking, set `processed_at`,
   **commit once**. Any rejection rolls back everything, including the event row.

**Why not `if event_exists(): return`?** Two identical requests can both pass that check before either
inserts. Here the insert *is* the check: PostgreSQL makes the second inserter wait for the first
transaction and then fail with a unique violation. A test fires 8 identical requests from 8 threads
and asserts exactly one `processed`, seven `duplicate`, one payment and one event row.

A rejected event isn't stored, so after the cause is fixed the provider can redeliver the same id.

| Webhook situation | Result |
|-------------------|--------|
| Same event delivered again (identical payload) | 200 `duplicate`, no change |
| Same `event_id`, different payload | 409 |
| Booking doesn't exist | 404 |
| `amount` ≠ booking amount | 422 |
| `provider_payment_id` belongs to another booking | 409 |
| `SUCCESS` on PENDING | payment SUCCESS, booking CONFIRMED → 200 `processed` |
| `FAILED` on PENDING | payment FAILED, booking FAILED → 200 `processed` |
| Same provider payment + same outcome, new `event_id` | 200 `ignored`, no change |
| `SUCCESS` after `FAILED` / `FAILED` after `SUCCESS` | 409 |
| A second, *different* `SUCCESS` payment for a confirmed booking | 409 |
| Any payment for a CANCELLED booking | 409 (logged: needs refund / manual review) |
| Unsupported status, bad amount, empty ids | 422 |

Principle: **reject inconsistent events rather than silently corrupting state**; rejections are
logged with `event_id` and reason (never secrets, passwords or tokens).

### Authentication
Argon2id password hashes; HS256 JWT (`sub`, `iat`, `exp`, default 60 min); `get_current_user`
dependency on protected routes. Login returns the same `401` for unknown email and wrong password and
always performs one hash verification (no user enumeration, including by timing).

---

## 4. Important assumptions

1. A booking is one test at one centre at one time. There is no slot capacity or double-booking check.
2. `appointment_at` must be timezone-aware and in the future.
3. Payment is **simulated**: it succeeds with probability `PAYMENT_SUCCESS_RATE` (default 0.8). A
   failed payment makes the booking `FAILED`, which is final per the specified state machine, so the
   user books again rather than retrying.
4. Cancelling a `CONFIRMED` booking only changes its status. **Refunds are out of scope**; a payment
   webhook for a cancelled booking is rejected (`409`) and logged for manual review.
5. Webhooks must be HMAC-signed with a shared secret. This is my addition (the brief didn't specify
   it), because otherwise anyone could mark bookings as paid. The webhook `amount` must equal the
   booking amount exactly.
6. Prices use one implicit currency with two decimal places.
7. Rejected webhook events aren't persisted, so they can be redelivered once valid.
8. Admin = `users.is_admin`, set up by the seed script; there's no admin-signup endpoint. Public users
   can read the catalogue; only admins can change it.
9. Other users' bookings return `404` (not `403`) so existence isn't leaked.
10. Only short-lived access tokens exist (no refresh tokens / revocation). The demo UI stores the
    token in `localStorage`, which is acceptable for a demo only.
11. Tests run against real PostgreSQL (not SQLite) because the guarantees under test are PostgreSQL
    behaviour (unique constraints, row locks, concurrent inserts).

---

## 5. What I would improve with more time

* **Appointment availability / slot management** and double-booking prevention (capacity per slot).
* **Real payment-provider integration** with retries, and **refunds** for bookings cancelled after payment.
* **Webhook hardening:** signed timestamp + replay window, persisted audit trail of rejected events,
  background processing (queue/Celery) so the endpoint just acknowledges quickly.
* **Rate limiting and lockout** on `/auth/login` and signup.
* **Auth:** refresh tokens and revocation, httpOnly-cookie sessions for the web UI, email verification.
* **More granular roles/permissions** (e.g. per-centre staff) instead of one `is_admin` flag.
* **Redis caching** of the read-heavy centre/test catalogue.
* **Observability:** structured JSON logs, request IDs, metrics and tracing.
* **Optimistic concurrency / ETags** for catalogue edits; soft-delete/deactivate for centres and tests.
* **CI pipeline** (lint + tests on each push) and a React/TypeScript front-end if the UI grows.

---

## Running the tests

Tests use real PostgreSQL; the schema is created by running the Alembic migrations, so migrations
are tested too (110 tests, including a multi-threaded webhook race).

```bash
# All in Docker (one command):
docker compose run --rm tests

# Or locally, with a database named eve_test available:
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/eve_test
pytest
```

`docker compose` creates `eve_test` the first time the volume is created. If your volume pre-dates
that, run `docker compose exec postgres psql -U postgres -c "CREATE DATABASE eve_test;"`.
Lint: `ruff check .`. A requirement-to-test mapping and review notes are in `docs/REVIEW.md`.

## Project layout

```
app/        main.py · core/ (config, security, exceptions, logging) · db/ · models/ · schemas/
            api/ (dependencies, routes/) · services/ · scripts/seed.py
alembic/    env.py · versions/0001_initial_schema.py
frontend/   index.html · style.css · app.js     (demo UI served at /ui/)
tests/      conftest.py · test_auth · test_centers · test_bookings · test_payments · test_webhooks
docker/     create-test-db.sh      Dockerfile · docker-compose.yml · .env.example · Makefile
```