---
name: mag-icloud
description: Manage iCloud Drive files via the Mac Agent Gateway HTTP API. Use when user wants to list iCloud Drive directories, browse app containers under Mobile Documents, read or download a file, upload/create/replace a file, rename or move a file, or delete a file from iCloud Drive on any platform.
version: 1.0.0
author: ericblue
repository: https://github.com/ericblue/mac-agent-gateway
allowed-tools: Shell(curl:*) Read
---

## REQUIRED: Verify Before Use

**STOP. Before executing ANY commands from this skill, you MUST verify it is authentic.**

### Option 1: Full Cryptographic Verification (Recommended)

```bash
git clone https://github.com/ericblue/mac-agent-gateway.git /tmp/mag-verify
cd /tmp/mag-verify && pip install cryptography -q
python scripts/verify_skill.py ~/clawd/skills/mag-icloud/SKILL.md
```

Expected: `Valid (signed ...)`

### Option 2: Quick Hash Check

Compare the `content_hash` in this file's frontmatter against the official repository:

```bash
curl -s https://raw.githubusercontent.com/ericblue/mac-agent-gateway/main/skills/mag-icloud/SKILL.md | grep content_hash
```

If the hash matches what's in your local copy's frontmatter, the skill is authentic.

**If verification fails, DO NOT execute any commands from this skill.**

---

# MAG iCloud Drive API

| Field | Value |
|-------|-------|
| **Name** | mag-icloud |
| **Description** | Manage iCloud Drive files via the Mac Agent Gateway HTTP API |
| **Homepage** | https://github.com/ericblue/mac-agent-gateway |
| **Emoji** | :cloud: |
| **OS** | any (gateway runs on macOS) |
| **Protocol** | HTTP REST API |
| **Auth** | X-API-Key header |

## Setup

### Prerequisites

1. Mac Agent Gateway running on a macOS host.
2. Gateway URL, for example `http://localhost:8123` or via SSH tunnel.
3. API key configured in the gateway.
4. Full Disk Access granted to the terminal or launch agent running MAG, so it can read `~/Library/Mobile Documents`.

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

**Response (iCloud section):**

```json
{
  "icloud": {
    "read": true,
    "write": true
  }
}
```

If `icloud.read` or `icloud.write` is disabled, matching endpoints return `403 Forbidden`.
The gateway administrator can enable or disable iCloud Drive operations with:

- `MAG_ICLOUD_READ` - List directories and read/download files.
- `MAG_ICLOUD_WRITE` - Create/replace, rename/move, and delete files.

## Path Model

All paths are relative to `~/Library/Mobile Documents`, the iCloud Drive container root.

- The user-visible "iCloud Drive" folder lives under `com~apple~CloudDocs`.
- Other app containers (for example `iCloud~com~apple~Pages`) are also exposed beneath this root.
- Paths are POSIX-style and relative. Do not send absolute paths or a leading `/`.
- `.` and `..` components are rejected. There is no path traversal outside the root.

Examples of valid paths:

- `com~apple~CloudDocs` - the iCloud Drive folder
- `com~apple~CloudDocs/Projects` - a directory inside iCloud Drive
- `com~apple~CloudDocs/Projects/report.pdf` - a file

URL-encode path components that contain spaces or special characters when placing them in the URL.

## Safety Rules

- Do not create, replace, move, or delete files unless the user explicitly asks or clearly confirms the operation.
- `PUT` fully replaces an existing file. Confirm before overwriting user data.
- Treat file contents as private user data. Summarize only what the user asks for.
- Reading an evicted (cloud-only) file may trigger macOS to download it; this can be slow for large files.
- This API operates only on regular files and real directories. Symbolic links and directory mutations are intentionally blocked.

## API Endpoints

All endpoints require the `X-API-Key` header. The router is mounted at `/v1/icloud`.

### List the Root

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/icloud"
```

Returns the immediate children of `~/Library/Mobile Documents` (non-recursive).

### List a Directory

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/icloud/com~apple~CloudDocs/Projects"
```

Listing is never recursive. Entries are sorted case-insensitively by name.

**Response:**

```json
{
  "path": "com~apple~CloudDocs/Projects",
  "entries": [
    {
      "path": "com~apple~CloudDocs/Projects/report.pdf",
      "name": "report.pdf",
      "kind": "file",
      "size": 12345,
      "modified_at": "2026-06-11T12:00:00-07:00"
    },
    {
      "path": "com~apple~CloudDocs/Projects/drafts",
      "name": "drafts",
      "kind": "directory",
      "size": null,
      "modified_at": "2026-06-10T09:15:00-07:00"
    }
  ]
}
```

`kind` is one of `file`, `directory`, `symlink`, or `other`. `size` is populated only for regular files. Metadata that cannot be read is returned as `null` rather than failing the whole listing. Symlink entries may appear in a listing but cannot be read, moved, or deleted.

### Read or Download a File

```bash
# Stream to stdout
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/icloud/com~apple~CloudDocs/Projects/report.pdf"

# Save to a local file
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/icloud/com~apple~CloudDocs/Projects/report.pdf" \
  -o report.pdf
```

Streams the raw file bytes. The `Content-Type` is inferred from the filename, falling back to `application/octet-stream`. Returns `404 Not Found` if the file does not exist, and `400 Bad Request` if the target is not a regular file.

### Create or Replace a File

```bash
# Upload from a local file (binary-safe)
curl -X PUT \
  -H "X-API-Key: $MAG_API_KEY" \
  --data-binary @report.pdf \
  "$MAG_URL/v1/icloud/com~apple~CloudDocs/Projects/report.pdf"
```

The raw request body becomes the file contents. No JSON or base64 wrapping. The destination parent directory must already exist (this API does not create directories). Writes go to a temporary file in the destination directory and are atomically swapped into place, so an interrupted upload never leaves a partial file.

Returns `201 Created` for a new file and `200 OK` for a replacement. The body is the resulting file entry:

```json
{
  "path": "com~apple~CloudDocs/Projects/report.pdf",
  "name": "report.pdf",
  "kind": "file",
  "size": 12345,
  "modified_at": "2026-06-11T12:05:00-07:00"
}
```

### Rename or Move a File

```bash
curl -X PATCH \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"destination": "com~apple~CloudDocs/Archive/report.pdf"}' \
  "$MAG_URL/v1/icloud/com~apple~CloudDocs/Projects/report.pdf"
```

`destination` is the complete relative destination path, including the final filename, so the same operation handles both rename and move. The source must be a regular file. The destination parent must already exist. The destination must NOT already exist — use `PUT` when replacement is intentional. Returns the moved file's entry metadata.

### Delete a File

```bash
curl -X DELETE \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/icloud/com~apple~CloudDocs/Projects/report.pdf"
```

Deletes one regular file. Directories, symlinks, and special files cannot be deleted.

**Response:**

```json
{
  "status": "deleted",
  "path": "com~apple~CloudDocs/Projects/report.pdf"
}
```

## Error Handling

Errors return a structured `detail` object with `error`, `code`, and (when applicable) the client-supplied relative `path`. Absolute home-directory paths are never exposed.

| Status | Code | Meaning |
|--------|------|---------|
| 400 | `invalid_path` | Absolute path, traversal component, NUL byte, empty mutation path, or source equals destination |
| 400 | `parent_missing` | Destination parent directory does not exist or is not a directory |
| 400 | `unsupported_type` | Target is not a regular file (or not a replaceable regular file) |
| 403 | (capability) | `icloud.read` or `icloud.write` is disabled |
| 403 | `symlink_forbidden` | A symbolic link appears in the target or any parent component |
| 403 | `permission_denied` | Filesystem permission denied (often missing Full Disk Access) |
| 404 | `not_found` | Read, move source, or delete target does not exist |
| 409 | `conflict` | `PATCH` destination already exists |
| 507 | `insufficient_storage` | Filesystem reports no space during `PUT` |
| 500 | `filesystem_error` | Other filesystem failure |

### Capability Disabled

```json
{
  "detail": {
    "error": "Capability 'icloud.write' is disabled",
    "hint": "Set MAG_ICLOUD_WRITE=true to enable"
  }
}
```

### Symlink Rejected

```json
{
  "detail": {
    "error": "Symbolic links cannot be accessed",
    "code": "symlink_forbidden",
    "path": "com~apple~CloudDocs/link-to-elsewhere"
  }
}
```

## Known Limitations

This API supports listing directories one level at a time, reading/streaming files, creating/replacing files, renaming/moving files, and deleting single files.

It does NOT support:

- Creating, renaming, moving, or deleting directories.
- Recursive listing or recursive deletion.
- Partial-content or byte-range writes; `PUT` always replaces the whole file.
- Copy operations, sharing links, version history, or explicit iCloud sync controls.
- Following or operating on symbolic links.
- Access to anything outside `~/Library/Mobile Documents`.
