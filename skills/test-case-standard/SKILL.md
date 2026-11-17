---
name: test-case-standard
description: The testkit test case format, test design techniques and coverage checklist. Load before writing, reviewing or executing testkit test cases (cases/*.md), or whenever you need the TC template, priority rules, or the edge-case checklist.
---

# Test case standard

Every testkit agent reads and writes test cases in this one format, so the writer, reviewer and executor never disagree about what a case means.

## File layout

One file per stream: `qa/runs/<RUN_ID>/cases/<STREAM_ID>.md`.

```markdown
# <STREAM_ID> — <stream title>

- Ticket: <ticket id + title>
- Sources: <docs sections, code paths, UI routes actually read>
- Assumptions: <anything not stated in the docs that you had to assume; each one is a question for the reviewer>

## Traceability

| Requirement | Source | Test cases |
|---|---|---|
| AC-1: User can log in with email | docs/auth.md#login | TC-S1-001, TC-S1-002 |
| (implicit) Session expires after 30m | src/auth/session.ts:42 | TC-S1-009 |

## Test cases

### TC-S1-001 — Log in with a valid email and password
- Priority: P0
- Type: functional
- Requirement: AC-1
- Preconditions: An active account with role `member` exists. User is logged out.
- Test data: account `{{member}}`; password `{{member.password}}`
- Steps:
  1. Open `/login`.
  2. Fill "Email" with `{{member.email}}`.
  3. Fill "Password" with `{{member.password}}`.
  4. Click "Sign in".
- Expected:
  - Redirects to `/dashboard` within 3 s.
  - Header shows the account's display name.
  - No console errors.
- Reference: `evidence/S1/explore-login.png` (optional, captured while exploring)
```

## Rules

- **IDs**: `TC-<STREAM_ID>-<NNN>`, never reused within a run. When a case is deleted after review, retire its ID.
- **One behaviour per case.** If a case has two unrelated expected outcomes, split it.
- **Steps are executable by someone who has never seen the app**: name the exact route, the visible label of each control, and the exact input value. Never write "fill the form with valid data".
- **Expected results are observable and checkable**: visible text, URL, element state, a value in a list, an HTTP status in the network log. Never write "works correctly" or "shows an error"; write the error text the docs specify, or mark it `(text not specified in docs)`.
- **Test data uses placeholders** (`{{role}}`, `{{role.email}}`) for accounts the executor creates. Never hard-code real user data or production credentials.
- **Expected results come from the docs/ticket first**, then from the code. If the code and the docs disagree, write the case to the docs and add the conflict to `Assumptions` so the reviewer and lead see it.
- **Independence**: each case states its own preconditions and can run alone. If a case truly needs a previous case's output, write `Depends on: TC-...` and keep it in the same stream.

## Priority

| Priority | Use for |
|---|---|
| P0 | Core happy path of the ticket, data loss, security, payments, anything that blocks release |
| P1 | Main negative paths, validation, permissions, important edge cases |
| P2 | Cosmetic, rare edge cases, nice-to-have UX |

## Type

`functional` · `negative` · `edge` · `validation` · `permission` · `ui` · `state` · `integration` · `regression` · `accessibility` · `api` · `mobile`

`Type` says what the case checks; how it runs follows from it. Browser is the default. `api` cases run with Hurl (`api-testing` skill) and add these fields:

```markdown
- Endpoint: `PATCH /api/profile`
- Auth: `{{member}}` (bearer token from login) | none
- Request: JSON body, headers, query (use `{{...}}` placeholders for data)
- Expected: status `422`; body `$.errors[0].field == "displayName"`; header `Content-Type` contains `json`
```

`mobile` cases run with Maestro (`mobile-testing` skill) and add `Platform: android | ios | both` and the device state they need (permissions, network, app version).

## Design techniques (apply what fits, name it in the case when it drives the data)

- **Equivalence partitioning**: one case per class of valid and invalid input.
- **Boundary values**: min-1, min, min+1, max-1, max, max+1 for every numeric or length limit.
- **Decision table**: when 2+ conditions combine (role × status × plan), list the combinations and cover each distinct outcome.
- **State transition**: for entities with a lifecycle (draft → published → archived), cover each valid transition and at least one invalid one.
- **Permission matrix**: every role × every protected action, including "not logged in" and "another user's resource" (IDOR).
- **Error guessing**: the edge-case checklist below.

## Edge-case checklist

The writer goes through this list for every stream and the reviewer checks it was done. Skip an item only with a one-line reason in `Assumptions`.

- Empty, whitespace-only, very long (max+1), unicode/emoji, Vietnamese diacritics, RTL text, HTML/script injection (`<script>alert(1)</script>`), SQL-ish strings (`' OR 1=1 --`).
- Numbers: 0, negative, decimal, very large, non-numeric, leading zeros.
- Dates and times: past, future, today, leap day, timezone boundary, invalid format.
- Duplicates: submitting the same item twice, double-click on submit, back button after submit, refresh mid-flow.
- Concurrency: the same record edited in two tabs or by two users.
- Session: expired session mid-flow, logout in another tab, direct URL access without login.
- Permissions: lower role, other tenant/user's record by changing the ID in the URL.
- Network: slow network, offline, server error (simulate with the browser tool when the stream needs it; see `browser-testing`).
- Lists: zero items, one item, pagination boundary, sorting and filtering combined.
- Files: wrong type, oversize, zero-byte, filename with spaces/unicode.
- Responsive: mobile viewport (375×812) for any UI the ticket changes.
- Accessibility basics: keyboard-only path through the main flow, visible focus, labels on inputs.
