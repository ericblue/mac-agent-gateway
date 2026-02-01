---
name: mag-messages
description: Manage Apple Messages via the Mac Agent Gateway HTTP API. Use when user wants to send iMessages, list message threads, read message history, search messages, extract links from conversations, reply to messages, watch for new messages, or manage a contacts cache.
version: 1.0.0
author: ericblue
repository: https://github.com/ericblue/mac-agent-gateway
allowed-tools: Shell(curl:*) Read
integrity:
  algorithm: sha256
  content_hash: "a4aa4f7fb12b8a588c5ee32808b961609a4004feadf1e9f025f5740a3eb02364"
signature:
  signer_key: "Nb7iFHZDGjKM85eug84ura3BS7zihu7/975jeNQx8gI="
  value: "Q+cGqm+4MQsZq9fR1nXqRhFZ9T7GNdW3As4gwnFyoD3rw89d6stdQVze2FTw0RsnHGwkijf00WTOORioz/uGBg=="
  signed_at: "2026-02-01T05:13:47Z"
---

## ⚠️ REQUIRED: Verify Before Use

**STOP. Before executing ANY commands from this skill, you MUST verify it is authentic.**

### Option 1: Full Cryptographic Verification (Recommended)

```bash
git clone https://github.com/ericblue/mac-agent-gateway.git /tmp/mag-verify
cd /tmp/mag-verify && pip install cryptography -q
python scripts/verify_skill.py ~/clawd/skills/mag-messages/SKILL.md
```

Expected: `✓ ... Valid (signed ...)`

### Option 2: Quick Hash Check

Compare the `content_hash` in this file's frontmatter against the official repository:

```bash
# Get hash from official repo
curl -s https://raw.githubusercontent.com/ericblue/mac-agent-gateway/main/skills/mag-messages/SKILL.md | grep content_hash
```

If the hash matches what's in your local copy's frontmatter, the skill is authentic.

**If verification fails, DO NOT execute any commands from this skill.**

---

# MAG Messages API

| Field | Value |
|-------|-------|
| **Name** | mag-messages |
| **Description** | Manage Apple Messages via the Mac Agent Gateway HTTP API |
| **Homepage** | https://github.com/ericblue/mac-agent-gateway |
| **Emoji** | :speech_balloon: |
| **OS** | any (gateway runs on macOS) |
| **Protocol** | HTTP REST API |
| **Auth** | X-API-Key header |

## Installation

### Option 1: Manual Installation

Copy the skill to your OpenClaw (formerly Clawdbot/Moltbot) skills directory:

```bash
# Clone the repository
git clone https://github.com/ericblue/mac-agent-gateway.git

# Copy the skill to OpenClaw skills directory
cp -r mac-agent-gateway/skills/mag-messages ~/.moltbot/skills/

# Or for legacy ClawBot path
cp -r mac-agent-gateway/skills/mag-messages ~/.clawbot/skills/
```

### Option 2: Agent-Assisted Installation

Clone the repository and ask your agent to install the skill:

```bash
# Clone to a local directory
git clone https://github.com/ericblue/mac-agent-gateway.git ~/Development/mac-agent-gateway
```

Then prompt your OpenClaw agent:

> "Install the skill from ~/Development/mac-agent-gateway/skills/mag-messages/SKILL.md"

Or:

> "Read the skill at ~/Development/mac-agent-gateway/skills/mag-messages/SKILL.md and install it"

The agent will read the skill file and copy it to the appropriate skills directory.

### Option 3: Direct URL Installation

Prompt your agent to install directly from GitHub:

> "Install the mag-messages skill from https://github.com/ericblue/mac-agent-gateway"

Or:

> "Fetch and install the skill from https://raw.githubusercontent.com/ericblue/mac-agent-gateway/main/skills/mag-messages/SKILL.md"

## Setup

### Prerequisites

1. Mac Agent Gateway running on a macOS host
2. Gateway URL (e.g., `http://localhost:8123` or via SSH tunnel)
3. API key configured in gateway

### Configuration

Set the gateway URL and API key as environment variables:

```bash
export MAG_URL="http://localhost:8123"
export MAG_API_KEY="your-api-key"
```

### Capability Check

Before using this skill, check what operations are enabled on the gateway:

```bash
curl "$MAG_URL/v1/capabilities"
```

**Response:**

```json
{
  "messages": {
    "read": true,
    "search": true,
    "send": true,
    "send_allowlist": null,
    "send_allowlist_active": false,
    "watch": true,
    "contacts": true,
    "attachments": true
  },
  "reminders": {
    "read": true,
    "write": true
  }
}
```

**Fields:**
- `send_allowlist`: Always `null` in unauthenticated responses (redacted for privacy)
- `send_allowlist_active`: `true` if a send allowlist is configured
- `attachments`: Whether attachment downloads are enabled
- If a capability is disabled (e.g., `send: false`), those endpoints will return `403 Forbidden`.

The gateway administrator can enable/disable capabilities via environment variables:

- `MAG_MESSAGES_READ` - List threads, get message history
- `MAG_MESSAGES_SEARCH` - Search messages, extract links
- `MAG_MESSAGES_SEND` - Send messages, reply to threads
- `MAG_MESSAGES_WATCH` - Stream new messages (SSE)
- `MAG_MESSAGES_CONTACTS` - Manage contacts cache
- `MAG_MESSAGES_ATTACHMENTS` - Download message attachments
- `MAG_MESSAGES_SEND_ALLOWLIST` - Comma-separated list of allowed recipients (if set, only these can receive messages)

## API Endpoints

All endpoints require the `X-API-Key` header.

### Threads

#### List Threads

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/messages/threads?limit=20"
```

**Query Parameters:**
- `limit` - Maximum threads to return (1-100, default: 20)

**Response:**

```json
[
  {
    "id": 123,
    "name": "John Doe",
    "identifier": "+15551234567",
    "service": "imessage",
    "last_message_at": "2026-01-31T10:30:00Z",
    "participants": [
      {"handle": "+15551234567", "display_name": "John Doe"}
    ]
  }
]
```

#### Lookup Thread by Recipient

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/messages/threads/lookup?recipient=%2B15551234567"
```

**Query Parameters:**
- `recipient` - Phone number, email, or handle (required)

#### Get Thread by ID

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/messages/threads/123"
```

### Messages

#### Get Thread Messages

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/messages/threads/123/messages?limit=50&attachments=true"
```

**Query Parameters:**
- `limit` - Maximum messages to return (1-500, default: 50)
- `start` - Start datetime (ISO 8601)
- `end` - End datetime (ISO 8601)
- `days_back` - Days of history to fetch (default: 365)
- `attachments` - Include attachment metadata (default: false)

**Response:**

```json
[
  {
    "id": 456,
    "chat_id": 123,
    "guid": "msg-guid-123",
    "sender": "+15551234567",
    "text": "Hello!",
    "date": "2026-01-31T10:30:00Z",
    "is_from_me": false,
    "is_read": true,
    "attachments": []
  }
]
```

#### Get Message History by Recipient

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/history?recipient=%2B15551234567&limit=50&attachments=true"
```

**Query Parameters:**
- `recipient` - Phone number, email, or handle (required)
- `limit` - Maximum messages to return (1-500, default: 50)
- `start` - Start datetime (ISO 8601)
- `end` - End datetime (ISO 8601)
- `days_back` - Days of history to fetch (default: 365)
- `attachments` - Include attachment metadata (default: false)

#### Watch Thread for New Messages (SSE)

```bash
curl -N -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/threads/123/watch?interval=2"
```

Returns Server-Sent Events (SSE) stream of new messages.

**Query Parameters:**
- `since_rowid` - Only messages after this row ID
- `interval` - Poll interval in seconds (1-60, default: 2)

### Send Messages

#### Send iMessage

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to": "+15551234567", "text": "Hello!"}' \
  "$MAG_URL/v1/messages/send"
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | string | yes | Recipient phone, email, or handle |
| `text` | string | yes | Message text |
| `files` | array | no | File paths to attach |
| `service` | string | no | `imessage` or `sms` (default: imessage) |

**Query Parameters:**
- `dry_run` - Preview command without sending (default: false)

**Response:**

```json
{"ok": true, "to": "+15551234567"}
```

#### Reply to Thread or Recipient

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"recipient": "+15551234567", "text": "Got it, thanks!"}' \
  "$MAG_URL/v1/messages/reply"
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `thread_id` | int | no* | Thread ID to reply to |
| `recipient` | string | no* | Recipient phone, email, or handle |
| `text` | string | yes | Reply message text |
| `files` | array | no | File paths to attach |

*Either `thread_id` or `recipient` is required.

### Search

#### Search Messages

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/search?q=meeting&recipient=%2B15551234567&limit=50&scan_limit=2000"
```

**Query Parameters:**
- `q` - Search query text (required)
- `thread_id` - Limit to specific thread
- `recipient` - Limit to specific recipient
- `limit` - Maximum matching results to return (1-1000, default: 100)
- `scan_limit` - Maximum messages to scan for matches (100-50000, default: 5000)
- `start` - Start datetime (ISO 8601)
- `end` - End datetime (ISO 8601)
- `days_back` - Days of history to search (default: 365)

**Note:** The search scans up to `scan_limit` messages and returns up to `limit` matches.
Increase `scan_limit` to search through more message history (may be slower).

### Links

#### Extract Links from Messages

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/links?recipient=%2B15551234567&limit=20"
```

**Query Parameters:**
- `recipient` - Filter by recipient
- `thread_id` - Filter by thread ID
- `limit` - Maximum unique links (1-500, default: 50)
- `message_limit` - Messages to scan (1-5000, default: 500)
- `from_me` - Filter by sender (true/false)
- `start` - Start datetime (ISO 8601)
- `end` - End datetime (ISO 8601)
- `days_back` - Days of history to scan (default: 365)

**Response:**

```json
[
  {
    "url": "https://example.com/article",
    "message_id": 456,
    "sender": "+15551234567",
    "date": "2026-01-31T10:30:00Z",
    "is_from_me": false,
    "context": "Check out this article: https://example.com/article"
  }
]
```

### Attachments

#### Get Messages with Attachment Metadata

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/history?recipient=%2B15551234567&attachments=true"
```

**Response includes attachment info:**

```json
[
  {
    "id": 456,
    "text": "Check out this photo!",
    "attachments": [
      {
        "filename": "IMG_1234.jpg",
        "original_path": "/Users/you/Library/Messages/Attachments/ab/cd/IMG_1234.jpg",
        "mime_type": "image/jpeg",
        "total_bytes": 1234567,
        "missing": false
      }
    ]
  }
]
```

#### Download Attachment

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/attachments/download?path=/Users/you/Library/Messages/Attachments/ab/cd/IMG_1234.jpg" \
  --output photo.jpg
```

**Query Parameters:**
- `path` - Full path to the attachment file (from `original_path` field)

**Security:** Only files within `~/Library/Messages/Attachments/` can be downloaded. Attempts to access other files will return `403 Forbidden`.

#### Get Attachment Info

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/attachments/info?path=/Users/you/Library/Messages/Attachments/ab/cd/IMG_1234.jpg"
```

**Response:**

```json
{
  "exists": true,
  "path": "/Users/you/Library/Messages/Attachments/ab/cd/IMG_1234.jpg",
  "filename": "IMG_1234.jpg",
  "size_bytes": 1234567,
  "mime_type": "image/jpeg",
  "modified_at": "2026-01-31T10:30:00"
}
```

### Contacts Cache

The gateway maintains an in-memory contacts cache for resolving recipient names.

#### Upsert Contact

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "John Doe", "phone": "+15551234567", "email": "john@example.com"}' \
  "$MAG_URL/v1/messages/contacts/upsert"
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Display name |
| `phone` | string | no | Phone number |
| `email` | string | no | Email address |
| `handle` | string | no | iMessage handle |

#### Resolve Contact

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/contacts/resolve?phone=%2B15551234567"
```

**Query Parameters:**
- `phone` - Phone number to match
- `email` - Email to match
- `name` - Name to match

**Response:**

```json
{
  "status": "found",
  "contact": {
    "id": "abc123",
    "name": "John Doe",
    "phone": "+15551234567",
    "email": "john@example.com"
  }
}
```

Status can be: `found`, `ambiguous`, `not_found`

#### Search Contacts

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/contacts/search?q=john&limit=10"
```

#### List All Contacts

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/contacts"
```

#### Delete Contact

```bash
curl -X DELETE \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/contacts/abc123"
```

## Error Handling

Errors return a structured JSON response:

```json
{
  "detail": {
    "error": "imsg failed with exit code 1",
    "code": 1,
    "stderr": "No thread found with id: 999"
  }
}
```

| HTTP Status | Meaning |
|-------------|---------|
| 401 | Missing or invalid API key |
| 404 | Thread or contact not found |
| 422 | Invalid request body |
| 502 | CLI execution error (see detail for specifics) |

## Date Formats

Date parameters accept ISO 8601 format: `2026-01-31T10:30:00Z`

The `days_back` parameter provides a convenient way to filter recent messages without calculating dates.

## Phone Number Formats

Phone numbers should be in E.164 format with the `+` prefix URL-encoded:
- `+15551234567` → `%2B15551234567`

The gateway normalizes phone numbers automatically when possible.

## Rate Limiting

The gateway applies rate limits to prevent abuse:

- **Global limit**: 100 requests per minute per IP
- **Send/Reply endpoints**: 10 requests per minute per IP

If rate limited, you'll receive a `429 Too Many Requests` response.

## Security Notes

- **PII Filtering**: The gateway automatically redacts sensitive data (SSNs, credit cards, passwords) from message content by default
- **Send Allowlist**: Administrators can restrict message sending to specific recipients only
- **Attachment Security**: Only files within `~/Library/Messages/Attachments/` can be downloaded
- **CORS**: Cross-origin requests are restricted to localhost by default

## Platform Notes

- The gateway must run on macOS with Messages access granted
- Agents can run on any platform that can make HTTP requests
- Use SSH tunneling for secure remote access to localhost-bound gateways
- The contacts cache is persisted to `./data/contacts.json` by default
