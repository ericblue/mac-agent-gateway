# Security

Mac Agent Gateway (MAG) provides API access to sensitive Apple services (Reminders and Messages). This document outlines the security measures in place and important considerations for users.

## Security Measures

### Authentication

- **API Key Required** — All endpoints (except `/health` and `/v1/capabilities`) require a valid `X-API-Key` header
- **Key Validation** — Startup is blocked if the API key is:
  - A common placeholder value (e.g., "changeme", "secret", "password")
  - Too short (minimum 16 characters required, 32+ recommended)
- **Constant-Time Comparison** — API key validation uses `secrets.compare_digest()` to prevent timing attacks
- **Key Recommendations** — We recommend 32+ character randomly-generated keys (use `make generate-api-key`)

### Network Security

- **Localhost by Default** — MAG binds to `127.0.0.1` by default, rejecting external connections
- **CORS Protection** — Cross-Origin Resource Sharing is restricted to localhost origins only
- **No Cloud Dependencies** — All processing happens locally on your Mac; no data is sent to external servers by MAG itself
- **SSH Tunneling** — For remote access, we recommend SSH tunnels or private mesh VPNs (Tailscale) rather than exposing the port publicly

### Rate Limiting

- **Global Rate Limiting** — Default limit of 100 requests per minute per IP address
- **Message Send Limits** — Send and reply endpoints are limited to 10 requests per minute to prevent spam
- **Configurable** — Rate limits can be adjusted in code if needed for your use case

### Access Control

- **Capability Restrictions** — Fine-grained control over what operations are allowed:
  - Disable message sending while allowing read access
  - Disable search while allowing thread listing
  - Disable all message access while keeping reminders enabled

- **Send Allowlist** — Restrict message sending to specific phone numbers/emails only
  - Even if an agent is compromised, it can only message approved contacts
  - Allowlist is redacted in unauthenticated `/v1/capabilities` responses

- **Capability Discovery** — Agents can query `/v1/capabilities` to discover what's enabled before attempting operations

### Input Validation

- **Path Parameter Validation** — Reminder IDs and list names are validated to prevent command injection
- **File Attachment Restrictions** — When `MAG_ATTACHMENT_ALLOWED_DIRS` is set, only files from those directories can be attached
- **Pydantic Validation** — All request bodies are validated with strict schemas

### Attachment Download Security

- **Restricted Directory Access** — Only files within `~/Library/Messages/Attachments/` can be downloaded
- **Path Traversal Protection** — Paths are resolved and validated before serving
- **Capability Control** — Attachment downloads can be disabled via `MAG_MESSAGES_ATTACHMENTS=false`
- **Authentication Required** — Download endpoints require valid API key

### Data Handling

- **No Data Storage** — MAG does not store messages or reminders; it proxies requests to Apple's local databases
- **Contacts Cache** — The optional contacts cache is stored locally with restricted file permissions (600)
- **No Logging of Content** — Message content and reminder details are not logged by default
- **Error Sanitization** — Internal error details are logged server-side only; clients receive generic error messages

### Audit Logging

- **Access Logs** — Optional HTTP request logging for audit trail and security monitoring
- **Rotating Log Files** — Logs are automatically rotated to prevent disk exhaustion
- **Secure Permissions** — Log files are created with owner-only permissions (600)
- **Configurable** — Enable/disable access logging and configure retention as needed

```bash
# Enable file logging with access audit trail
MAG_LOG_DIR=./logs
MAG_LOG_ACCESS=true
MAG_LOG_MAX_BYTES=10485760  # 10 MB per file
MAG_LOG_BACKUP_COUNT=5      # Keep 5 rotated files
```

Access log format: `TIMESTAMP CLIENT_IP METHOD PATH STATUS DURATION_MS`

Example:
```
2026-01-31 14:30:45 127.0.0.1 GET /v1/reminders 200 45.2ms
2026-01-31 14:30:46 127.0.0.1 POST /v1/messages/send 201 523.1ms
```

**Note:** Query parameters are not logged to prevent sensitive data exposure.

### PII Filtering

MAG includes PII (Personally Identifiable Information) filtering to mask sensitive data before it's returned from the API. **This is enabled by default.**

```bash
# Default: regex-based PII filtering (enabled)
MAG_PII_FILTER=regex

# To disable PII filtering (not recommended):
MAG_PII_FILTER=
```

When enabled, the following patterns are automatically masked:
- Social Security Numbers → `[REDACTED-SSN]`
- Credit Card Numbers → `[REDACTED-CC]`
- Bank Account Numbers → `[REDACTED-ACCOUNT]`
- Routing Numbers → `[REDACTED-ROUTING]`
- Passwords in context → `[REDACTED-PASSWORD]`
- API Keys/Tokens → `[REDACTED-KEY]`

**Note:** Regex-based filtering catches common patterns but is not foolproof. For more comprehensive PII detection, future versions may support Microsoft Presidio integration.

## Configuration Options

### Security-Related Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAG_API_KEY` | (required) | API key for authentication (min 16 chars, 32+ recommended) |
| `MAG_HOST` | `127.0.0.1` | Host to bind to (localhost only by default) |
| `MAG_PII_FILTER` | `regex` | PII filtering mode: "regex" or "" (disabled) |
| `MAG_MESSAGES_SEND_ALLOWLIST` | (empty) | Comma-separated list of allowed message recipients |
| `MAG_ATTACHMENT_ALLOWED_DIRS` | (empty) | Comma-separated directories for allowed file attachments |
| `MAG_ALLOW_UNKNOWN_RECIPIENTS` | `true` | Allow sending to recipients not in contacts cache |
| `MAG_MESSAGES_SEND` | `true` | Enable/disable message sending capability |
| `MAG_MESSAGES_READ` | `true` | Enable/disable message reading capability |
| `MAG_MESSAGES_ATTACHMENTS` | `true` | Enable/disable attachment downloads |
| `MAG_REMINDERS_WRITE` | `true` | Enable/disable reminder modification capability |
| `MAG_LOG_DIR` | (empty) | Directory for log files (empty = stdout only) |
| `MAG_LOG_ACCESS` | `true` | Enable HTTP access logging for audit trail |
| `MAG_LOG_MAX_BYTES` | `10485760` | Max log file size before rotation (10 MB) |
| `MAG_LOG_BACKUP_COUNT` | `5` | Number of rotated log files to keep |

### Recommended Production Configuration

```bash
# Strong API key (32+ characters)
MAG_API_KEY=$(openssl rand -base64 32)

# Localhost only (default)
MAG_HOST=127.0.0.1

# Enable PII filtering (default)
MAG_PII_FILTER=regex

# Restrict message recipients
MAG_MESSAGES_SEND_ALLOWLIST=+15551234567,user@example.com

# Restrict file attachments to safe directories
MAG_ATTACHMENT_ALLOWED_DIRS=~/Downloads,~/Pictures

# Enable file logging with audit trail
MAG_LOG_DIR=./logs
MAG_LOG_ACCESS=true

# Read-only mode for messages (optional)
MAG_MESSAGES_SEND=false
```

## Important Considerations

### LLM and AI Agent Privacy

When using MAG with AI agents (Claude, OpenAI, etc.), be aware that:

- **Message content may be sent to LLM providers** — When you ask an agent to search messages or extract information, that content is sent to the AI service for processing
- **Reminder titles and notes may be sent to LLM providers** — Similarly, reminder content is processed by the AI to understand and respond to your requests
- **This is inherent to how AI agents work** — The agent needs to see the data to help you with it

**Recommendations:**

1. Review your AI provider's privacy policy and data handling practices
2. Be mindful of highly sensitive information in messages/reminders when using AI agents
3. Use the capability restrictions to limit access (e.g., read-only mode)
4. Consider which conversations and reminders you ask the AI to access

### Remote Access Risks

If you expose MAG beyond localhost:

- Use strong, randomly-generated API keys (32+ characters)
- Prefer SSH tunnels or Tailscale over binding to `0.0.0.0`
- If binding to a network interface, use firewall rules to restrict access
- Enable the send allowlist to limit potential damage if compromised
- Configure attachment allowed directories to prevent sensitive file access

### File Attachment Security

When the `MAG_ATTACHMENT_ALLOWED_DIRS` setting is empty (default):
- Any readable file on the system can potentially be attached to messages
- This is convenient but less secure

When `MAG_ATTACHMENT_ALLOWED_DIRS` is configured:
- Only files within the specified directories can be attached
- Path traversal attacks (e.g., `../../../etc/passwd`) are blocked
- Recommended for production use

## Skill Signing

MAG skills are cryptographically signed to protect against tampering. Before installing a skill, you can verify its authenticity.

### Verifying Skills

```bash
# Clone the repository
git clone https://github.com/ericblue/mac-agent-gateway.git
cd mac-agent-gateway

# Install dependencies
pip install cryptography

# Verify all skills
make verify-skills

# Or verify a specific skill
python scripts/verify_skill.py skills/mag-reminders/SKILL.md
```

Expected output for valid skills:
```
✓ skills/mag-reminders/SKILL.md: Valid (signed 2026-01-31T14:00:00Z)
✓ skills/mag-messages/SKILL.md: Valid (signed 2026-01-31T14:00:00Z)

All 2 skill(s) verified successfully
```

### What Verification Checks

| Check | What It Detects |
|-------|-----------------|
| **Content hash** | Any modification to the skill file content |
| **Ed25519 signature** | Unauthorized changes (only the maintainer can sign) |
| **Signer key** | Skills signed by unknown parties |

### Signing Key

The official MAG skill signing public key is:

```
Algorithm: Ed25519
Key ID: mag-skills-v1
Public Key (base64): Nb7iFHZDGjKM85eug84ura3BS7zihu7/975jeNQx8gI=
```

**Only install skills that verify successfully against this key.**

### For Maintainers: Signing Skills

```bash
# First time: generate a keypair (stored in ~/.mag/)
make generate-signing-key

# Sign all skills before release
make sign-skills

# Commit the signed skills
git add skills/
git commit -m "Sign skills for vX.Y.Z release"
```

**Important:** Keep the private key (`~/.mag/signing_key.pem`) secure. Never commit it to the repository.

## Security Testing

MAG includes comprehensive security tests. Run them with:

```bash
pytest tests/test_security.py -v
```

## Reporting Security Issues

If you discover a security vulnerability, please report it by:

1. Opening a GitHub issue (for non-sensitive issues)
2. Contacting the maintainer directly for sensitive vulnerabilities

## Disclaimer

Mac Agent Gateway is provided "as is" without warranty of any kind. While we have taken reasonable steps to implement security best practices, the authors and contributors:

- Are not responsible for any data exposure, loss, or misuse that may occur through use of this software
- Cannot guarantee the security of data transmitted to third-party AI services
- Recommend users evaluate their own security requirements before deployment

By using MAG, you acknowledge that you are responsible for:

- Securing your API keys and access credentials
- Understanding the privacy implications of connecting AI agents to your personal data
- Configuring appropriate access restrictions for your use case
- Complying with applicable laws and regulations regarding data privacy

This software is intended for personal use and local development. Users deploying MAG in production or shared environments should conduct their own security review.

---

*Last updated: January 2026*
