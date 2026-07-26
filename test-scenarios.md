# Support Desk Gateway — Test Scenarios

All prompts are meant to be typed into claude.ai with the connector attached.
Assumes `AUTH_DISABLED=1` (single user `dev-user-001` with no role).

---

## 1. Session & Identity

### 1.1 Begin session (always first)
```
Start a support session.
```
Expected: Rules, persona, saved state, session token returned.

### 1.2 Cross-chat memory
```
Save in my state that I'm working on ticket tkt-004 and my name is Shahab.
```
Then start a **new chat** and:
```
What was I working on last time? And what's my name?
```
Expected: "ticket tkt-004" and "Shahab" remembered from previous chat.

---

## 2. Ticket Lookup

### 2.1 Get ticket by ID
```
Show me ticket tkt-001.
```
Expected: Subject, body, status, priority, category, created_by, timestamps, attachment_count.

### 2.2 View non-existent ticket
```
Show me ticket tkt-999.
```
Expected: `"not found"`

### 2.3 List my tickets
```
List all my tickets.
```
Expected: Array of tickets created by `dev-user-001`.

### 2.4 Customer profile
```
What does my support profile look like?
```
Expected: Open tickets, total tickets, avg resolution time, CSAT score, SLA breaches, account age, last contact, CSAT trend.

---

## 3. Order & Policy Lookup

### 3.1 Get order from catalog
```
Show me order ORD-8821.
```
Expected: Customer name, items, total, status, tracking.

### 3.2 Get non-existent order (falls through to Shopify)
```
Where is order ORD-9921?
```
Expected: Either live Shopify data with `source: "shopify"` or `"not found"` if Shopify not configured.

### 3.3 Get policy
```
What's the refund policy? Fetch policy pol-001.
```
Expected: Title, body, applies_to.

### 3.4 Semantic search
```
Search for "shipping time for orders"
```
Expected: Ranked results from orders/policies.

---

## 4. File Attachments

### 4.1 Attach a file
```
I want to attach a screenshot to ticket tkt-001. Here's the file data:
[base64 of a small text file]
```
Expected: attachment_id, file_name, size_bytes.

### 4.2 Retrieve attachment
```
Show me the attachments on ticket tkt-001. Then get the first one.
```
Expected: Presigned URL or file_data.

### 4.3 Invalid file type
```
Attach this executable to ticket tkt-001:
[base64 of some bytes]
mime_type: application/x-msdownload
```
Expected: `"unsupported file type"`

---

## 5. Ticket Creation & Management

### 5.1 Create ticket
```
Create a ticket: subject "Website login not working", body "I can't log in since yesterday", priority high, category technical.
```
Expected: ticket_id, status "open", created_at.

### 5.2 Create ticket with missing fields
```
Create a ticket with priority low.
```
Expected: Error — subject and body are required.

### 5.3 Submit CSAT (will fail — ticket not resolved)
```
Rate my last ticket 5 stars.
```
Expected: `"ticket must be resolved before rating"`

---

## 6. Agent Tools (requires `role: "staff"` or `"admin"`)

> These return `"not found"` under `AUTH_DISABLED=1` because `dev-user-001` has no role.
> Test them by setting `role: "admin"` in Descope (or temporarily in session.py).

### 6.1 Assign ticket
```
Assign ticket tkt-004 to agent Ravi.
```

### 6.2 Reassign ticket
```
Reassign ticket tkt-004 to agent Priya. Reason: "vacation coverage".
```

### 6.3 Update ticket status
```
Update ticket tkt-004: set status to resolved, add reply "Your refund has been processed."
```

### 6.4 Draft reply
```
Draft a reply for ticket tkt-004.
```
Expected: Structured context with policy match, customer history, agent name.

### 6.5 Audit log
```
Show me the audit log for the last hour.
```

### 6.6 Sync to Freshdesk
```
Sync ticket tkt-004 to Freshdesk.
```

---

## 7. Admin Tools (requires `role: "admin"`)

### 7.1 Report summary
```
How did support perform this week?
```

### 7.2 Agent performance
```
How is agent Ravi performing?
```

### 7.3 Update rules
```
Update the rules: add a new escalation criterion for "international shipping issues".
```

### 7.4 Update persona
```
Make the persona more casual for returning customers.
```

### 7.5 Restore config version
```
Restore version 1 of the rules.
```

### 7.6 Catalog — set policy
```
Update policy pol-001: change return window from 30 to 60 days.
```

### 7.7 Catalog — set order
```
Add order ORD-9999 to the catalog: customer "Test User", items ["Widget"], total 19.99, status shipped.
```

### 7.8 Catalog — list all
```
List all policies in the catalog.
```

### 7.9 Catalog — delete item
```
Delete policy pol-003 from the catalog.
```

### 7.10 Configure Freshdesk credentials
```
Set Freshdesk API key to "abc123" and domain to "mycompany.freshdesk.com".
```

### 7.11 Configure Shopify credentials
```
Set Shopify access token and store domain for live order lookups.
```

---

## 8. Notifications (requires SendGrid configured)

### 8.1 Configure email notification
```
Notify me by email at user@example.com when my ticket status changes.
```

### 8.2 Read notification config
```
Show me my current notification settings.
```

### 8.3 Configure webhook
```
Send webhooks to https://myapp.webhook.example/notifications for all events.
```

### 8.4 Invalid email
```
Configure notifications with email "not-an-email".
```
Expected: `"email is not a valid email address"`

---

## 9. Edge Cases & Failures

### 9.1 Call tool without session
```
Show me ticket tkt-001.
```
(without calling begin_session first)
Expected: `"no session — call begin_session first"`

### 9.2 Semantic search with empty query
```
Search for "".
```
Expected: `"query is required"`

### 9.3 Create ticket with invalid priority
```
Create a ticket: subject "Test", body "Testing", priority "urgent".
```
Expected: `"priority must be one of: low, medium, high, critical"`

### 9.4 Attach file exceeding size limit
```
Attach a very large file to ticket tkt-001.
```
(file_data > 10MB after decoding)
Expected: `"file exceeds 10MB limit"`

### 9.5 Attach more than 10 files
```
Upload 11 files to the same ticket.
```
Expected on 11th: `"ticket already has 10 attachments"`

### 9.6 Invalid base64
```
Attach this to ticket tkt-001: file_data "this-is-not-valid-base64!!!"
```
Expected: `"file data is not valid base64"`

### 9.7 Create ticket with body > 5000 chars
```
Create a ticket with a very long body (over 5000 characters).
```
Expected: `"body exceeds 5000 characters"`

### 9.8 CSAT on non-existent ticket
```
Rate ticket tkt-999 4 stars.
```
Expected: `"not found"`

### 9.9 CSAT with invalid score
```
Rate ticket tkt-001 6 stars.
```
Expected: `"score must be between 1 and 5"`

---

## 10. Integration Chain (Full Lifecycle)

### 10.1 Customer → Ticket → Agent → Resolution → CSAT

1. `Start a support session.`
2. `Create a ticket: subject "Double charged for order ORD-8821", body "I was charged $49 twice for my subscription", priority high, category billing.`
3. `Show me my new ticket.`
4. `Search for "refund double charge policy"`
5. `Save the ticket ID in my state.`
6. Start new chat.
7. `Continue from where I left off — what was my last ticket?`
8. `Are there any attachments on my ticket?`

### 10.2 Policy → Catalog → Search → Verify

1. `What policies do you have?`
2. `Show me policy pol-001.`
3. `Search for "can I return damaged items"`
4. `List all policies in the catalog.`

### 10.3 Notifications → Status → Verify

1. `Notify me at user@test.com when my ticket changes.`
2. `Create a ticket about a test issue.`
3. `Show me my notification settings.`
