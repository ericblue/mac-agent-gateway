# Real-World Examples: `mag-reminders` + `mag-messages`

These examples are designed to be copy/paste prompts a user can send to an agent (OpenClaw, Claude Code, Cursor) that has the **mag-reminders** and/or **mag-messages** skills configured.

**Assumptions:**

- The agent can call the Mac Agent Gateway (MAG) via `MAG_URL` and `MAG_API_KEY`.
- `mag-messages` may be configured with a **send allowlist**; examples assume your own number/email are allowed.

> **Tip:** These prompts are designed to be short and realistic. Copy, paste, and adapt to your needs.

---

## Reminders Examples

### 1) "What's due today?" (quick daily scan)

**Prompt:**
> What are my Apple Reminders due today? Group them by list.

**Example output:**
- **Work**
  - Send revised deck to John (due 10:00)
  - Review PR #842 (due 16:00)
- **Personal**
  - Pick up package that was delivered (due 17:30)

---

### 2) "Overdue triage" (reduce backlog)

**Prompt:**
> Show my overdue reminders. Suggest: reschedule, split, or drop.

**Example output:**
- **Overdue (5)**
  1. Call accountant (overdue 6d) → *reschedule*: tomorrow 09:00
  2. Update website copy (overdue 14d) → *split*: 30m outline today + 60m draft Thu
  3. Cancel old subscriptions (overdue 30d) → *drop?* confirm

---

### 3) Reschedule an item by fuzzy name

**Prompt:**
> Push "Review quarterly goals" out by 2 weeks and add a note: "discussed in 1:1 meeting".

**Example output:**
- Updated ✅
  - Title: Review quarterly goals
  - Due: 2026-02-14 07:00
  - Notes: discussed in 1:1 meeting

---

### 4) Create a reminder in plain English

**Prompt:**
> Add a reminder tomorrow at 9am: "Write documentation examples for the API".

**Example output:**
- Created ✅
  - Title: Write documentation examples for the API
  - Due: 2026-02-01 09:00 (local)
  - List: Reminders

---

### 5) Create recurring reminders (habits / routines)

**Prompt:**
> Create a recurring reminder: weekdays at 8:30am "Morning exercise routine".

**Example output:**
- Created ✅ Recurring reminder
  - Weekdays 08:30
  - Title: Morning exercise routine

---

### 6) Batch complete by query

**Prompt:**
> Mark anything containing "groceries" as completed.

**Example output:**
- Completed ✅ (2)
  - Buy groceries for weekend
  - Order groceries online

---

## Messages Examples

### 7) "Send me my reminders as a text" (push delivery)

**Prompt:**
> Text me my top 5 reminders for today.

**Example output:**

Sent via iMessage to **+1 (555) 123-4567**:
- Today (Top 5)
  1) Send revised deck (10:00)
  2) Review PR #842 (16:00)
  3) Pick up prescription (17:30)
  4) Pay invoice #219 (EOD)
  5) Plan weekend hike (EOD)

---

### 8) "Create a reminder from a message" (quote-to-reminder)

**Prompt:**
> In my chat with Jane, take her last message and make it a reminder for tomorrow morning. Put the message text in the reminder notes.

**Example output:**
- Created ✅
  - Title: Follow up on Jane's message
  - Due: tomorrow 09:00
  - Notes:
    - From: Jane (+15559876543)
    - Message: "Can you pick up the package on your way home?"

---

### 9) "Who messaged me recently?" (inbound triage)

**Prompt:**
> Who sent me messages in the last 3 days? Show counts.

**Example output:**
- Last 3 days — unique senders: 8
  - Jane (+15559876543): 9
  - +15551112222: 6
  - +15553334444: 4
  - user@example.com: 3
  - 12345: 2
  - …

---

### 10) "Weekly message review" (inbox zero triage)

**Prompt:**
> Review my messages from the past week and identify:
> - items that may be urgent
> - messages I haven't replied to
> - messages that may be especially relevant or interesting

**Example output:**
- **Urgent (3)**
  - Jane (Jan 29, 14:22): "Can you call me ASAP about the lease?"
  - +15551112222 (Jan 28, 09:15): "Meeting moved to tomorrow 8am"
  - Mom (Jan 27, 18:30): "Dad's flight arrives at 6pm, can you pick up?"

- **Awaiting Reply (5)**
  - John (Jan 30): Asked about weekend plans — no response
  - Sarah (Jan 29): Shared restaurant link, asked if interested
  - +15553334444 (Jan 28): "Did you get my email?" — no response
  - Mike (Jan 27): Project question about API design
  - Jane (Jan 26): Asked for recipe recommendation

- **Interesting/Relevant (4)**
  - Sarah: Shared article about productivity systems
  - John: Sent photos from last weekend's hike
  - Jane: Link to concert tickets on sale
  - +15551112222: Forwarded job posting that matches your skills

---

### 11) "Find the last Instagram links I sent myself" (self-chat as inbox)

**Prompt:**
> Search messages I sent to myself and list my last 5 Instagram links.

**Example output:**
1. https://www.instagram.com/share/ABC123

2. https://www.instagram.com/share/DEF456

3. https://www.instagram.com/share/GHI789

4. https://www.instagram.com/share/JKL012

5. https://www.instagram.com/share/MNO345

   

---

### 12) "Extract links someone sent me" (context retrieval)

**Prompt:**
> Pull the last 5 links Jane sent me and include the message context.

**Example output:**
- 1) https://example.com/article
  - Context: "This is the one I was talking about"
  - Sent: 2026-01-30 18:14

- 2) https://example.com/product
  - Context: "Check this out!"
  - Sent: 2026-01-29 14:22

---

### 13) "Find a message by keyword in a specific thread"

**Prompt:**
> Search my thread with Jane for messages containing "flight" in the last 30 days.

**Example output:**
- Matches (3)
  - 2026-01-22 09:11 — "Flight changed to 11:45…"
  - 2026-01-22 09:13 — "Can you confirm seats?"
  - 2026-01-25 19:04 — "Flight tracker says on time."

---

### 14) "Send a message safely using allowlist"

**Prompt:**
> Send a test message to me at both my phone and iMessage email.

**Example output:**
- Sent ✅ to +15551234567
- Sent ✅ to user@example.com

---

### 15) "Prove restrictions work" (permissions testing)

**Prompt:**
> Try sending "hello" to 555-0000.

**Example output:**
- Blocked ✅
  - Recipient '555-0000' is not in the send allowlist
  - Allowed: +15551234567, user@example.com

---

### 16) "Watch for replies" (SSE message watch)

**Prompt:**
> Start watching my thread with Jane and alert me here when a new message arrives.

**Example output:**
- Watching thread ✅ (poll interval 2s)
- New message from Jane: "On my way."

---

## Combined Workflows

### 17) "Daily check-in via text" (scheduled digest)

**Prompt:**
> Every weekday at 8:05am, text me:
> - today's top 5 reminders
> - any overdue reminders count

**Example output (iMessage):**

Weekday Morning Digest:
- Overdue: 3
- Today (Top 5):
  1) Team standup (09:00)
  2) Client call (11:00)
  3) Review docs (14:00)
  4) Submit report (16:00)
  5) Gym (18:00)

---

### 18) "Turn a link into an action" (capture → execution)

**Prompt:**
> Take the last article link I sent myself, summarize what it's about, and create a reminder tomorrow afternoon to read it.

**Example output:**
- Latest link: https://example.com/article
- Quick summary: "Blog post about productivity systems…"
- Reminder created: "Read article on productivity" (tomorrow 15:00)

---

### 19) "Contacts cache: make texting by name work"

**Prompt:**
> Remember that my number is 555-123-4567 and my partner Jane is 555-987-6543. Update the contacts cache.

**Example output:**
- Contacts updated ✅
  - Me: +15551234567
  - Jane: +15559876543

---

### 20) "Resolve who a number is" (using contacts cache)

**Prompt:**
> Who is +15559876543?

**Example output:**
- Jane (partner)

---

### 21) "Reply to a thread using a contact"

**Prompt:**
> Text Jane: "Running 10 minutes late."

**Example output:**
- Resolved contact: Jane → +15559876543
- Sent ✅

---

## Why These Skills Are Powerful

### `mag-messages`

- Works with real Messages.app data on macOS
- Adds **recipient filtering**, **search**, **link extraction**, **watch/stream**, and a **contacts cache**
- Enables "Messages as a command surface" for your assistant

### `mag-reminders`

- Create/update/complete Apple Reminders programmatically
- Great for turning chat/capture into **concrete next actions**

### Combined = High Leverage

The best user experience is:

1. Capture a thought in Messages (to self or from others)
2. Extract the actionable bit
3. Create a reminder (with the message quoted in notes)
4. Optionally deliver digests back via iMessage

---

## API Reference (for developers)

### Check Capabilities

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/capabilities"
```

### List Threads

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/messages/threads?limit=20"
```

### Search Messages

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/search?q=meeting&recipient=%2B15559876543&limit=50"
```

### Extract Links

```bash
curl -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/messages/links?recipient=%2B15559876543&limit=20"
```

### Create Reminder

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Call mom", "due": "tomorrow", "list": "Personal"}' \
  "$MAG_URL/v1/reminders"
```

### Send Message

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to": "+15551234567", "text": "Hello!"}' \
  "$MAG_URL/v1/messages/send"
```

### List Today's Reminders

```bash
curl -H "X-API-Key: $MAG_API_KEY" "$MAG_URL/v1/reminders?filter=today"
```

### Complete a Reminder

```bash
curl -X POST \
  -H "X-API-Key: $MAG_API_KEY" \
  "$MAG_URL/v1/reminders/ABC123/complete"
```
