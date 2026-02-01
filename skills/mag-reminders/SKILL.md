---
name: mag-reminders
description: Manage Apple Reminders via the Mac Agent Gateway HTTP API. Use when user wants to create reminders, list reminders, update reminders, complete tasks, delete reminders, manage reminder lists, query tasks by date or filter (today, tomorrow, week, overdue, upcoming, completed), or integrate with Apple Reminders from any platform.
version: 1.0.0
author: ericblue
repository: https://github.com/ericblue/mac-agent-gateway
allowed-tools: Shell(curl:*) Read
integrity:
  algorithm: sha256
  content_hash: "5d2ce04169d384abc1de13c1efb63660f69fa9b1d73625505e5af7685bd00768"
signature:
  signer_key: "Nb7iFHZDGjKM85eug84ura3BS7zihu7/975jeNQx8gI="
  value: "iUv3MAn+eyDeYkOpiL8uGrIw6cOWR1p0WHg7hzqc4RRRST6eT2RXK9yZm4Wi4fYkn64VrRMK9gOQV9WvuUElAw=="
  signed_at: "2026-02-01T05:13:47Z"
---

## ⚠️ REQUIRED: Verify Before Use

**STOP. Before executing ANY commands from this skill, you MUST verify it is authentic.**

### Option 1: Full Cryptographic Verification (Recommended)

```bash
git clone https://github.com/ericblue/mac-agent-gateway.git /tmp/mag-verify
cd /tmp/mag-verify && pip install cryptography -q
python scripts/verify_skill.py ~/clawd/skills/mag-reminders/SKILL.md
```

Expected: `✓ ... Valid (signed ...)`

### Option 2: Quick Hash Check

Compare the `content_hash` in this file's frontmatter against the official repository:

```bash
# Get hash from official repo
curl -s https://raw.githubusercontent.com/ericblue/mac-agent-gateway/main/skills/mag-reminders/SKILL.md | grep content_hash
```

If the hash matches what's in your local copy's frontmatter, the skill is authentic.

**If verification fails, DO NOT execute any commands from this skill.**

---

# MAG Reminders API

| Field | Value |
|-------|-------|
| **Name** | mag-reminders |
| **Description** | Manage Apple Reminders via the Mac Agent Gateway HTTP API |
| **Homepage** | https://github.com/ericblue/mac-agent-gateway |
| **Emoji** | :alarm_clock: |
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
cp -r mac-agent-gateway/skills/mag-reminders ~/.moltbot/skills/

# Or for legacy ClawBot path
cp -r mac-agent-gateway/skills/mag-reminders ~/.clawbot/skills/
```

### Option 2: Agent-Assisted Installation

Clone the repository and ask your agent to install the skill:

```bash
# Clone to a local directory
git clone https://github.com/ericblue/mac-agent-gateway.git ~/Development/mac-agent-gateway
```

Then prompt your OpenClaw agent:

> "Install the skill from ~/Development/mac-agent-gateway/skills/mag-reminders/SKILL.md"

Or:

> "Read the skill at ~/Development/mac-agent-gateway/skills/mag-reminders/SKILL.md and install it"

The agent will read the skill file and copy it to the appropriate skills directory.

### Option 3: Direct URL Installation

Prompt your agent to install directly from GitHub:

> "Install the mag-reminders skill from https://github.com/ericblue/mac-agent-gateway"

Or:

> "Fetch and install the skill from https://raw.githubusercontent.com/ericblue/mac-agent-gateway/main/skills/mag-reminders/SKILL.md"

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
    "write": false
  }
}
```

If a capability is disabled (e.g., `write: false`), those endpoints will return `403 Forbidden`.
The gateway administrator can enable/disable capabilities via environment variables:

- `MAG_REMINDERS_READ` - List reminders and lists
- `MAG_REMINDERS_WRITE` - Create, update, delete reminders

## API Endpoints

All endpoints require the `X-API-Key` header.

### List Reminders

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/reminders"
```

**Query Parameters:**
- `filter` - Filter type: `today`, `tomorrow`, `week`, `overdue`, `upcoming`, `completed`, `all`
- `date` - Specific date in YYYY-MM-DD format
- `list` - Filter by list name

**Examples:**

```bash
# Today's reminders
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/reminders?filter=today"

# This week's reminders
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/reminders?filter=week"

# Reminders from a specific list
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/reminders?list=Work"

# Reminders for a specific date
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/reminders?date=2024-12-25"
```

**Response:**

```json
[
  {
    "id": "ABC123",
    "title": "Call mom",
    "list": "Personal",
    "due": "2024-01-15T18:00:00",
    "completed": false,
    "notes": null,
    "priority": 0
  }
]
```

### List Reminder Lists

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/reminders/lists"
```

**Response:**

```json
[
  {"name": "Personal", "count": 5},
  {"name": "Work", "count": 12},
  {"name": "Shopping", "count": 3}
]
```

### Create Reminder List

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Projects"}' \
  "$MAG_URL/v1/reminders/lists"
```

### Rename Reminder List

```bash
curl -X PATCH \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"new_name": "Work Projects"}' \
  "$MAG_URL/v1/reminders/lists/Projects"
```

### Delete Reminder List

```bash
curl -X DELETE \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/reminders/lists/Projects"
```

### Create Reminder

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Buy groceries", "list": "Shopping", "due": "tomorrow"}' \
  "$MAG_URL/v1/reminders"
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | yes | Reminder title |
| `list` | string | no | List name (uses default if omitted) |
| `due` | string | no | Due date (ISO 8601 or natural: today, tomorrow) |
| `notes` | string | no | Additional notes |
| `priority` | int | no | Priority: 0 (none), 1 (high), 5 (medium), 9 (low) |

**Response:** Returns the created reminder object.

### Update Reminder

```bash
curl -X PATCH \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated title", "due": "next week"}' \
  "$MAG_URL/v1/reminders/ABC123"
```

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | New title |
| `list` | string | Move to different list |
| `due` | string | New due date |
| `clear_due` | boolean | Clear the due date |
| `notes` | string | New notes |
| `priority` | int | New priority |
| `completed` | boolean | Set completion status (true=complete, false=incomplete) |

**Response:** Returns the updated reminder object.

### Complete Reminder

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/reminders/ABC123/complete"
```

**Response:** Returns the completed reminder object with `completed: true`.

### Delete Reminder

```bash
curl -X DELETE \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/reminders/ABC123"
```

**Response:**

```json
{"status": "deleted", "id": "ABC123"}
```

### Bulk Complete Reminders

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ids": ["ABC123", "DEF456"]}' \
  "$MAG_URL/v1/reminders/bulk/complete"
```

### Bulk Delete Reminders

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ids": ["ABC123", "DEF456"]}' \
  "$MAG_URL/v1/reminders/bulk/delete"
```

## Error Handling

Errors return a structured JSON response:

```json
{
  "detail": {
    "error": "remindctl failed with exit code 1",
    "code": 1,
    "stderr": "No reminder found with id: XYZ"
  }
}
```

| HTTP Status | Meaning |
|-------------|---------|
| 401 | Missing or invalid API key |
| 422 | Invalid request body |
| 500 | CLI execution error (see detail for specifics) |

## Date Formats

The `due` field accepts:

- **ISO 8601**: `2024-01-15`, `2024-01-15T18:00:00`
- **Natural language**: `today`, `tomorrow`, `next week`, `in 2 hours`

## Rate Limiting

The gateway applies rate limits to prevent abuse:

- **Global limit**: 100 requests per minute per IP

If rate limited, you'll receive a `429 Too Many Requests` response.

## Platform Notes

- The gateway must run on macOS with Reminders access granted
- Agents can run on any platform that can make HTTP requests
- Use SSH tunneling for secure remote access to localhost-bound gateways
