# Sovchi.app — Backend (`aynanai`)

Backend for **Sovchi.app**, a values-based matrimonial / dating platform.
Django + DRF REST API, Django Channels WebSockets for real-time chat, calls and
presence, Celery for background work, and a three-channel notification system
(in-app, Firebase push, Telegram bot).

The app is served both as a **Telegram Mini App** (`tg_app`) and a native
**mobile app** (`mobile`); much of the domain logic branches on this distinction.

---

## Tech Stack

| Area | Technology |
|------|------------|
| Language / runtime | Python ≥ 3.13, managed with **uv** |
| Web framework | **Django 5.2**, **Django REST Framework 3.16** |
| Realtime | **Django Channels 4** + **channels-redis**, ASGI via **Daphne / uvicorn** |
| Background jobs | **Celery 5** (broker + result backend on Redis) |
| Database | **PostgreSQL** (`psycopg2`) + **pgvector** (embeddings for AI matching) |
| Cache / presence / broker | **Redis** |
| Auth | **djangorestframework-simplejwt** (JWT; `USER_ID_FIELD = id`) |
| Push notifications | **firebase-admin** (FCM HTTP v1) |
| Media storage | **boto3** (S3) |
| Images | **Pillow** + **pillow-heif** (HEIC → JPEG) |
| Face verification | DeepFace / AWS Rekognition |
| AI features | **OpenAI** |
| Config | **python-decouple** (`.env`) |
| API docs | **drf-spectacular** (OpenAPI) |
| Telegram | `pyTelegramBotAPI` (client + team bots) |

---

## Apps

| App | Responsibility |
|-----|----------------|
| `users` | Custom user model, multi-method auth, profile, photos, privacy, face verification, account deletion/restore |
| `matching` | Discovery feed, likes, compatibility scoring, AI recommendations, boosts, daily limits |
| `chat` | Real-time chat, chat requests (pending flow), calls (WebRTC signaling), match-confirmation popups |
| `community` | Social feed: posts, comments, likes, views, reports, blocks |
| `notification` | Central notification service: in-app + WebSocket, FCM push, Telegram bot; device registration |
| `guardian` | "Valiy" (guardian/parent) feature — a guardian browses candidates for their child |
| `payments` | Subscription plans (free/premium), daily services, Click/Payme providers |
| `bot` | Telegram bots (client + team), bot-link login |
| `admin_panel` | Custom admin API with its own `AdminUser` auth and permissions |
| `stats` | Analytics and reporting dashboards |
| `ai` | AI profiles / portraits |
| `reports` | User/content reporting |
| `integrations` | External API integrations |
| `utils` | Shared helpers: secure config, Redis presence, photo blur, validators |

`Aynanai/` is the project package (settings, ASGI/WSGI, root URLconf, routing).

---

## Important Logic

### 1. Authentication & identity

- `CustomUser` extends `AbstractUser` but the `username` field is **removed**
  (`username = None`); the login identifier is **`public_id`**
  (`USERNAME_FIELD = 'public_id'`), an always-generated unique short code.
  Users are looked up publicly by `public_id`, never by primary key or username.
- Auth methods (`auth_method`): `telegram` (Mini App `init_data`), `phone` (OTP),
  `google`, `email` (OTP), plus **`auth_with_telegram`** / **`telegram_to_mobile`**
  for the Telegram-bot → mobile login (a WebSocket + bot `/start` token exchange).
- `platform` (`tg_app` | `mobile`) tracks where the user currently is. Every
  mobile login path calls `mark_mobile_login()` which flips a stale `tg_app`
  user to `mobile` — this is what routes notifications correctly (see §5).
- One account = one role (`account_type`: `user` | `guardian`), enforced before
  OTP is even sent (`account_type_mismatch`).

### 2. Matching & discovery

- Discovery serves candidates (top/main/near, plus a v1 endpoint) filtered by the
  viewer's `Preferences`, excluding blocked users and existing matches.
- **Compatibility score** is computed (psychological / lifestyle / demographic)
  and cached in `CompatibilityScore`.
- A `Like` is one-directional; a mutual like creates a `Match`.
- **Seeing *who* liked you requires premium** (`SubscriptionPlan.can_see_likes`).
  `LikesReceivedView` returns `restricted: true` for non-premium users, and the
  like **notification is only sent to users who can see likes** (`can_see_likes`).

### 3. Chat initiation (direct vs request)

`ChatRoom` normalises participants so **`user1` is always male, `user2` always
female**. Whether a chat starts `active` or as a `pending` request is decided by
`can_send_direct_message` — **gender-neutral**:

| Condition | Result |
|-----------|--------|
| Mutual like | direct (`active`) |
| Active premium plan (`can_message_first`) | direct |
| Daily "super message" service remaining | direct |
| otherwise | **`pending` request** (recipient accepts/rejects) |

The stored `initiation_type` is **gendered** (`female_initiated_premium`,
`male_initiated_request`, …) for analytics, while the API response stays generic
(`premium`, `request`, `mutual_like`) so the client contract is unchanged.

### 4. Match confirmation

After a threshold number of messages (`POPUP_THRESHOLDS`), a `MatchConfirmation`
popup asks both users to confirm. If **both confirm** → an official `Match` is
created. If they don't confirm after 3 popups → the chat is **deactivated**
(`deactivation_reason = 'no_match_after_popups'`, `is_active = False`).
Reactivation requires `is_active = True` **and** `status = 'active'`.

### 5. Notifications (three channels)

`notification.services.create_notification` is the hub and routes by
**platform + auth_method**, because the Mini App has no notification screen:

- **Mini-app only** (`platform == 'tg_app'` and `auth_method == 'telegram'`) →
  Telegram bot message (for `like` / `match`); no in-app record, no push.
- **Everyone else (mobile)** → in-app `Notification` row + WebSocket
  `new_notification` + FCM push.

Push tasks always send (the old "skip if online" gate was removed, since presence
can be stale after an unclean WebSocket disconnect).

### 6. Firebase push (FCM)

- `notification.push.send_to_user` lazily initialises `firebase-admin` from
  `FCM_SERVICE_ACCOUNT_FILE`; if the credential is missing, **push is silently
  disabled** (so the app keeps working).
- Per-platform payloads: Android uses `messages_channel` + `collapse_key`; iOS
  uses APNs (`apns-priority`, `thread-id`). Delivered with `send_each`.
- **Dead tokens** (`UNREGISTERED` / `SENDER_ID_MISMATCH` / `INVALID_ARGUMENT`)
  are auto-deleted.
- Devices register via `POST /api/v1/profile/devices/` (`UserDevice`,
  `unique(fcm_token)`, capped active devices, `DELETE` on logout).

### 7. Photo privacy & blur (two stages)

1. **Privacy visibility** (`calculate_is_blurred`): `public` → clear;
   `private` → blurred; `contacts_only` → clear only if the viewer shares a chat.
2. **Moderation** (`photo_blur_state`): unapproved photos are blurred
   (`verification`), the owner always sees their own photos clear.
`resolve_photo_url` then returns the clear or pre-generated `blurred_image` URL.

### 8. Account deletion & restore

Deletion is a **soft delete** (`is_active = False`, `deletion_requested_at` set),
retained ~30 days before hard deletion, and reversible via restore
(`is_active = True`). Content is **filtered, not deleted** — e.g. community feeds
filter on `author__user__is_active`, so a deleted account's posts disappear and
**reappear automatically on restore**.

### 9. Guardian ("valiy")

A guardian account browses/saves/forwards candidates for their child; the child
approves the guardianship. Candidate filtering reuses the child's `Preferences`.

### 10. WebSockets (`Aynanai/routing.py`)

| Route | Consumer | Purpose |
|-------|----------|---------|
| `ws/main/` | `MainConsumer` | Presence, badge counts (likes / unread / pending), `new_notification`, chat/like/call events |
| `ws/chat/<room_id>/` | `ChatConsumer` | Messages, typing, read/delivery receipts, match-confirmation popups |
| `ws/call/<room_id>/` | `CallConsumer` | WebRTC call signaling |
| `ws/support/<chat_id>/`, `ws/admin/` | Admin/support consumers | Support & admin |
| `ws/tg-login/` | `TgLoginConsumer` | Delivers tokens for Telegram-bot → mobile login |

Auth is JWT via `?token=` query param or `Authorization` header
(`chat/middleware.py`).

### 11. Configuration

All settings come from `.env` through `utils/core.py` (`SecureConfig`): **every
key in `_CONFIG_SPEC` is required** and validated at startup, so a misconfigured
deploy fails fast. Sensitive values are masked in error output.

---

## Running (local)

```bash
uv venv --python 3.13
uv sync

# configure .env (DB, Redis, Celery, JWT SECRET_KEY, FCM_SERVICE_ACCOUNT_FILE, ...)

uv run python manage.py migrate

# ASGI server (HTTP + WebSocket)
uv run daphne Aynanai.asgi:application            # or: uv run python manage.py runserver

# background worker (push, notifications, cleanup)
uv run celery -A Aynanai worker -l info
```

Requires **PostgreSQL** (with the `pgvector` extension) and **Redis** running.
