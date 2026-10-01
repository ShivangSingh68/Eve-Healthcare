# Final Review

## Requirement -> implementation -> test

| Requirement | Implementation | Test(s) |
|-------------|----------------|---------|
| Signup | `POST /auth/signup`, `auth_service.signup` | `test_signup_success_normalizes_email_and_hides_password`, `test_signup_validation_errors` |
| Duplicate email -> 409 | `UNIQUE(email)` + `IntegrityError` -> `ConflictError` | `test_duplicate_signup_returns_409_even_with_different_case` |
| Login | `POST /auth/login` | `test_login_success_returns_bearer_token`, `test_login_wrong_password_and_unknown_user_look_identical` |
| JWT auth | `get_current_user` dependency | `test_protected_endpoint_requires_token`, `..._rejects_garbage_and_expired_tokens`, `test_token_signed_with_other_secret_is_rejected` |
| Secure password hashing | Argon2id (`core/security.py`) | `test_password_is_stored_hashed` |
| List/get centres & tests with prices | `routes/centers.py`, `routes/tests.py` | `test_centers.py` |
| Admin-only catalogue writes | `require_admin` | `test_regular_user_cannot_modify_catalog`, `test_admin_can_create_center_test_and_offering` |
| Booking creation, server-side amount | `booking_service.create_booking` (no `amount` in schema) | `test_create_booking_success`, `test_amount_is_decided_by_server_and_client_value_is_ignored` |
| Centre/test validation | 404 / 404 / 422 + composite FK | `test_nonexistent_center_404`, `test_nonexistent_test_404`, `test_test_not_offered_by_center_422` |
| Historical price | `bookings.amount` snapshot | `test_historical_price_is_preserved_when_center_changes_price` |
| Ownership (bookings) | `get_owned_booking` filters by `user_id` -> 404 | `test_user_only_sees_own_bookings`, `test_other_users_booking_is_404_not_leaked` |
| Cancellation + state machine | `ALLOWED_TRANSITIONS`, `transition()` | `test_cancel_*`, `test_valid_transitions`, `test_invalid_transitions`, `test_terminal_states_have_no_exits` |
| Simulated payment | `payment_service.pay_for_booking` | `test_successful_payment_confirms_booking`, `test_failed_payment_fails_booking` |
| Payment authorization / duplicates | row lock + status check + partial unique index | `test_cannot_pay_for_someone_elses_booking`, `test_duplicate_payment_rejected`, `test_database_rejects_second_successful_payment_for_a_booking` |
| Webhook | `webhook_service.process_webhook` | `test_success_webhook_confirms_booking`, `test_failed_webhook_fails_booking` |
| Webhook idempotency | `UNIQUE(event_id)` insert inside the transaction | `test_duplicate_event_is_acknowledged_without_side_effects`, `test_concurrent_identical_webhooks_create_exactly_one_payment` |
| Conflicting event | `payload_hash` comparison | `test_same_event_id_with_different_payload_conflicts` |
| Webhook edge cases | state rules in `_apply_event` | `test_nonexistent_booking_404...`, `test_amount_mismatch_422...`, `test_success_after_failed_is_rejected`, `test_failed_after_success_is_rejected`, `test_provider_payment_id_cannot_be_shared_between_bookings`, `test_invalid_payload_422` |
| Transactions | single `commit()` per service operation; rollback on error | `test_rejected_event_can_be_redelivered...`, `test_concurrent_different_events_for_same_booking_confirm_once` |
| Alembic | `alembic/versions/0001_initial_schema.py` (verified with `alembic check`) | the test session runs `downgrade base` + `upgrade head` |
| Swagger/OpenAPI | `/docs`, summaries, response models, error responses | manual check |
| Docker / compose | `Dockerfile`, `docker-compose.yml` | **not executed in the authoring sandbox** (see below) |
| Logging (no secrets) | `logging` in services, key=value messages | - |

## Findings from the self-review

**Fixed during development**
* Signature verification runs *before* body validation (a test pins this), so unsigned callers learn nothing about the payload schema.
* Money serialises as a JSON number but is `Decimal` internally and `NUMERIC(10,2)` in the DB.
* Emails: lower-casing in the schema layer plus a DB CHECK so no code path can store a mixed-case email.

**Known limitations / trade-offs (deliberate)**
* Webhooks have HMAC authentication but **no timestamp/replay window**; replays are harmless because of idempotency, but a signed old event is still accepted once.
* No rate limiting on `/auth/login`.
* Rejected webhook events are not persisted (good for redelivery, but there is no audit trail of rejections other than logs).
* Cancelling a CONFIRMED booking does not refund; a late payment event for a cancelled booking is rejected (409) and logged.
* A FAILED booking is final per the specified state machine, so users must create a new booking to retry payment.
* JWTs cannot be revoked before expiry.
* Docker files were written and reviewed but could not be built in the authoring sandbox (no Docker daemon); the same commands (`alembic upgrade head`, `uvicorn`, `pytest`) were run directly against PostgreSQL 16.

**Unnecessary complexity check:** one service, five small service modules, no repository layer, no
background workers, no Redis. The only additions beyond the brief are `is_admin`, webhook HMAC
verification, `payload_hash`, and a seed script - each explained above.

## Interview talking points

1. **Layers.** Routes are thin; services hold business rules and own the transaction; Postgres is
   the last line of defence (constraints).
2. **Money safety.** The client never sends an amount. The server snapshots the price on the booking;
   payments and webhooks are validated against that snapshot.
3. **State machine.** One table, one `transition()` function. Payment, webhook and cancel all use it,
   so there is no path that skips validation.
4. **Defence in depth for duplicates.** App check (status must be PENDING) + row lock (serialises
   concurrent actions) + partial unique index (DB refuses a second SUCCESS payment).
5. **Webhook idempotency.** Insert-first with `UNIQUE(event_id)` instead of check-then-insert, so the
   race is resolved by the database. Same id + same payload = duplicate (200). Same id + different
   payload = 409.
6. **Atomicity.** Event row + payment row + booking update commit together or not at all.
7. **Authorization.** Every booking query is scoped by `user_id`; other users' resources are 404 so
   IDs leak nothing. Role checks (admin) are the only 403s.
8. **Testing choices.** Real PostgreSQL, schema from migrations, a real multi-threaded race test.
9. **What I'd do next.** Slot availability, refunds, rate limiting, replay window, structured logs.
