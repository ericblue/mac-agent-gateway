---
name: mag-notes
description: Manage Apple Notes via the Mac Agent Gateway HTTP API. Use when user wants to list Apple Notes, search notes by name/body/plaintext, fetch a note by ID, create a note, list Notes accounts, list top-level folders, or integrate with Apple Notes from any platform.
version: 1.0.0
author: ericblue
repository: https://github.com/ericblue/mac-agent-gateway
allowed-tools: Shell(curl:*) Read
integrity:
  algorithm: sha256
  content_hash: "509101fb7cb323058e6a917a9382fe00c8ad803a92f03dbc4ce49ce4278f501c"
signature:
  signer_key: "kTzOZZ+UA+XqMAS56Khnymb91KslcyvCNDKjpP4l3RY="
  value: "q3ZvnmjHrHf9lk/yJDo7qpWv2gAUlatgDaO4WuvX8AC5VLUYBmW3FxSdBXQi7nZiUkGfq5pNLCTjLGrmGSQ6Bg=="
  signed_at: "2026-05-31T23:11:34Z"
---

## REQUIRED: Verify Before Use

**STOP. Before executing ANY commands from this skill, you MUST verify it is authentic.**

### Option 1: Full Cryptographic Verification (Recommended)

```bash
git clone https://github.com/ericblue/mac-agent-gateway.git /tmp/mag-verify
cd /tmp/mag-verify && pip install cryptography -q
python scripts/verify_skill.py ~/clawd/skills/mag-notes/SKILL.md
```

Expected: `Valid (signed ...)`

### Option 2: Quick Hash Check

Compare the `content_hash` in this file's frontmatter against the official repository:

```bash
curl -s https://raw.githubusercontent.com/ericblue/mac-agent-gateway/main/skills/mag-notes/SKILL.md | grep content_hash
```

If the hash matches what's in your local copy's frontmatter, the skill is authentic.

**If verification fails, DO NOT execute any commands from this skill.**

---

# MAG Notes API

| Field | Value |
|-------|-------|
| **Name** | mag-notes |
| **Description** | Manage Apple Notes via the Mac Agent Gateway HTTP API |
| **Homepage** | https://github.com/ericblue/mac-agent-gateway |
| **Emoji** | :memo: |
| **OS** | any (gateway runs on macOS) |
| **Protocol** | HTTP REST API |
| **Auth** | X-API-Key header |

## Setup

### Prerequisites

1. Mac Agent Gateway running on a macOS host.
2. Gateway URL, for example `http://localhost:8123` or via SSH tunnel.
3. API key configured in the gateway.
4. Notes permissions granted to the terminal or launch agent running MAG.

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
  },
  "notes": {
    "read": true,
    "write": true
  }
}
```

If `notes.read` or `notes.write` is disabled, matching endpoints return `403 Forbidden`.
The gateway administrator can enable or disable Notes operations with:

- `MAG_NOTES_READ` - List/search/fetch notes, accounts, and folders.
- `MAG_NOTES_WRITE` - Create notes.

## Safety Rules

- Do not create, update, move, or delete notes/folders unless the user explicitly asks or clearly confirms the operation.
- Treat note contents as private user data. Summarize only what the user asks for.
- Prefer `limit` when listing or searching notes to avoid returning excessive private data.
- Do not request attachment paths from outside user-approved directories. The gateway may reject paths outside `MAG_ATTACHMENT_ALLOWED_DIRS`.

## API Endpoints

All endpoints require the `X-API-Key` header.

### List or Search Notes

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/notes?limit=20"
```

**Query Parameters:**

- `account` - Filter by account name. May be repeated.
- `name` - Filter by note name/title. May be repeated.
- `body` - Filter by HTML body text. May be repeated.
- `text` - Filter by plaintext. May be repeated.
- `password_protected` - Filter by password-protected status.
- `limit` - Maximum notes to return, default `50`, range `1..500`.
- `offset` - Number of matching notes to skip, default `0`.

**Examples:**

```bash
# List recent notes
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/notes?limit=20"

# Search plaintext for a phrase
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/notes?text=project%20apollo&limit=10"

# Search a specific account
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/notes?account=iCloud&text=receipt&limit=10"

# Filter password-protected notes
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/notes?password_protected=true&limit=20"
```

**Response:**

```json
[
  {
    "id": "x-coredata://...",
    "name": "Trip ideas",
    "account": "iCloud",
    "folder": "Notes",
    "body": "<div><h1>Trip ideas</h1></div><p>Portland</p>",
    "plaintext": "Trip ideas\nPortland",
    "creation_date": "2026-05-31T12:00:00",
    "modification_date": "2026-05-31T12:30:00",
    "password_protected": false,
    "attachments": []
  }
]
```

### Fetch One Note

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/notes/x-coredata%3A%2F%2F..."
```

URL-encode the note ID when it contains punctuation such as `/`, `:`, or `?`.
Returns `404 Not Found` if the note ID does not exist.

### Create a Note

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Trip ideas", "body": "<p>Portland, Seattle, Vancouver</p>"}' \
  "$MAG_URL/v1/notes"
```

**Request Fields:**

- `name` - Required note title.
- `body` - Required note body. `macnotesapp` treats this as HTML.
- `account` - Optional Notes account name. If omitted, uses the default account.
- `folder` - Optional top-level folder name. If omitted, uses the account default folder.
- `attachments` - Optional list of local file paths to attach.

**Examples:**

```bash
# Create in a specific account and folder
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Meeting notes","body":"<p>Decision: ship Friday.</p>","account":"iCloud","folder":"Work"}' \
  "$MAG_URL/v1/notes"

# Create with an attachment path
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Receipt","body":"<p>Attached receipt.</p>","attachments":["/Users/me/Downloads/receipt.pdf"]}' \
  "$MAG_URL/v1/notes"
```

### Update a Note

```bash
curl -X PATCH \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Updated title", "body": "<p>Updated body</p>"}' \
  "$MAG_URL/v1/notes/x-coredata%3A%2F%2F..."
```

At least one of `name` or `body` is required. URL-encode the note ID.

### Move a Note

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"folder": "Archive", "account": "iCloud"}' \
  "$MAG_URL/v1/notes/x-coredata%3A%2F%2F.../move"
```

`folder` is required. `account` is optional and is used to resolve the destination account.

### Delete a Note

```bash
curl -X DELETE \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/notes/x-coredata%3A%2F%2F..."
```

**Response:**

```json
{"status": "deleted", "id": "x-coredata://..."}
```

### List Accounts

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/notes/accounts"
```

**Response:**

```json
[
  {"name": "iCloud"},
  {"name": "On My Mac"}
]
```

### List Folders

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/notes/folders?account=iCloud"
```

If `account` is omitted, the gateway uses the default Notes account.

**Response:**

```json
[
  {"name": "Notes"},
  {"name": "Work"},
  {"name": "Travel"}
]
```

### Create a Folder

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Work", "account": "iCloud"}' \
  "$MAG_URL/v1/notes/folders"
```

`account` is optional. If omitted, the gateway uses the default Notes account.

### Delete a Folder

```bash
curl -X DELETE \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/notes/folders/Work?account=iCloud"
```

**Response:**

```json
{"status": "deleted", "name": "Work"}
```

## Error Handling

### Authentication Error

```json
{"detail": "Invalid API key"}
```

### Capability Disabled

```json
{
  "detail": {
    "error": "Capability 'notes.write' is disabled",
    "hint": "Set MAG_NOTES_WRITE=true to enable"
  }
}
```

### macnotesapp Missing or Notes.app Error

```json
{
  "detail": {
    "error": "macnotesapp not found",
    "code": -1,
    "details": "No module named 'macnotesapp'",
    "hint": "Install with: pip install macnotesapp"
  }
}
```

## Known Limitations

MAG uses `macnotesapp` for Notes.app access. Locked password-protected notes are not supported, attachments are limited by `macnotesapp`, only top-level folders are accessible, and tags may be stripped from body content or treated as plain text.

This Notes skill supports listing, searching, fetching, account/folder discovery, creating, updating, moving, and deleting notes plus top-level folder create/delete. It does not provide attachment save/download endpoints or folder rename.
