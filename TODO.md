# TODO

Planned enhancements and ideas for future development.

## Reminders

### List Allowlist for Reminders
- **Priority:** Low
- **Description:** Add `MAG_REMINDERS_WRITE_ALLOWLIST` to restrict which reminder lists an agent can create/modify reminders in
- **Use case:** Sandbox agent to designated lists (e.g., "AI Tasks") without touching personal lists
- **Implementation:**
  - Add `reminders_write_allowlist: str = ""` to `Settings`
  - Add `get_reminders_write_allowlist()` method
  - Check list name in create/update/delete/complete endpoints
  - Add `write_allowlist` field to `RemindersCapabilities` in `/v1/capabilities`
  - Update skills documentation

### Delete Protection (Optional)
- **Priority:** Low
- **Description:** Add `MAG_REMINDERS_DELETE=true/false` to allow create/update but block delete
- **Use case:** Let agent add reminders but prevent removal
- **Note:** Lower priority since list allowlist provides better protection

## Messages

### Group Message Support
- **Priority:** Medium
- **Description:** Better support for group conversations
- **Notes:** Depends on `imsg` CLI capabilities

## Privacy & PII

### Presidio Integration
- **Priority:** Medium
- **Description:** Add Microsoft Presidio as an optional PII detection backend
- **Use case:** More accurate detection of names, addresses, medical terms, etc.
- **Implementation:**
  - Add optional dependency: `presidio-analyzer`, `presidio-anonymizer`
  - New setting: `MAG_PII_FILTER=presidio`
  - Detect and mask: names, emails, phones, SSNs, credit cards, addresses
  - Fall back to regex if Presidio not installed

### Thread/Contact Exclusion
- **Priority:** Low
- **Description:** Allow excluding specific threads or contacts from API responses
- **Use case:** Never expose messages from sensitive contacts (bank, medical)
- **Implementation:**
  - `MAG_EXCLUDE_THREADS=2,15,42`
  - `MAG_EXCLUDE_CONTACTS=+15551234567`

## General

### Rate Limiting
- **Priority:** Medium
- **Description:** Add optional rate limiting per endpoint or globally
- **Use case:** Prevent runaway agents from spamming APIs

### Audit Logging
- **Priority:** Low
- **Description:** Log all write operations (sends, creates, deletes) to a file
- **Use case:** Track what agents have done for debugging/accountability
