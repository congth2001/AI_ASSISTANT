# Authentication

The API uses `guest`, `staff`, and `admin` roles with short-lived HS256 access tokens and
rotating, database-backed refresh tokens.

## Setup

Configure a unique secret (at least 32 characters) in `config/local.yml`:

```yaml
auth:
  jwt_secret: "replace-with-a-long-random-secret"
  jwt_issuer: business-chatbot
  jwt_audience: business-chatbot-web
  access_token_minutes: 15
  refresh_token_days: 30
```

Apply the schema migration before starting the API:

```powershell
cd backend
.\env\Scripts\python.exe -m alembic upgrade head
```

Create the first administrator from the backend directory:

```powershell
.\env\Scripts\python.exe create_admin.py --email admin@example.com --name "Administrator"
```

The migration intentionally sets legacy `conversations.user_id` values to `NULL`, because
those values predate authenticated identities. They remain in the database but are not
visible to authenticated users.

## Endpoints

- `POST /api/v1/auth/guest` — creates an anonymous guest session; no login required
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/staff` — admin only; creates a staff account

All chat, conversation, and document-search endpoints require:

```http
Authorization: Bearer <access_token>
```

Refresh tokens are single-use. Refreshing consumes the old token and returns a new token
pair; logging out revokes the current refresh token.

Guests are represented by database users without an email or password so their conversations
remain isolated and can survive a browser refresh. Only staff and admins can log in. Public
registration is intentionally unavailable.

## Chat authorization matrix

| Capability | Guest | Staff | Admin |
|---|---:|---:|---:|
| Stateless single-message chat | Yes | No | No |
| Conversation-based chat | No | Yes, own only | Yes, own only |
| Create conversations | No | Yes | Yes |
| Read conversation history | No | Own only | All users |
| Rename/delete conversations | No | Own only | Own only |
| Query store business data through SQL/RAG | No | Yes | Yes |
| Create staff accounts | No | No | Yes |

Guest requests run through a separate stateless response path with no repository, SQL, RAG,
cache, or conversation-history access. Queries classified as requiring business tools return
HTTP 403 before response streaming starts.

Admins have global read access for auditing, but a conversation owned by another account is
strictly read-only. Continuing chat, renaming, or deleting it returns HTTP 403.
