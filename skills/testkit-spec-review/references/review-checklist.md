# Spec review checklist

Go through every section for every requirement. Each finding gets an ID (`A-`, `C-`, `M-`, `T-`, `R-`) and, when someone must decide, a question `Q-n`.

## 1. Extracting acceptance criteria

- Use the ticket's own numbering if it has one; otherwise number in document order: `AC-1`, `AC-2` … One observable behaviour per AC. Split "user can create and edit" into two.
- Keep the source wording close; cite `<file> § <heading>`, `<file>.pdf p.<N>`, `Confluence: <page title> § <heading>`, `Figma: <frame name>` or the Jira field.
- Implicit requirements found only in code or design are not ACs: list them under *Missing cases* or *Contradictions* and ask.
- Unaccepted tracked changes and comments in Word specs are open questions, not requirements.

## 2. Ambiguity patterns

Flag wording a tester cannot turn into a pass/fail check:

- Vague quality words: fast, quickly, user-friendly, appropriate, valid, correct, properly, etc., as needed, similar to — Vietnamese: nhanh, hợp lệ, phù hợp, thân thiện, chính xác, tương tự, v.v., khi cần, nếu có thể.
- Missing numbers: limits, lengths, sizes, counts, timeouts, retries, rounding (VND has no decimals; percentages round how?).
- Undefined terms, roles or statuses; the same thing called two names.
- Pronouns or "it/this" with more than one possible referent.
- "Should/may/có thể" where it is unclear if the behaviour is required.
- Unclear trigger or timing: on save or on blur? immediately or after approval? which time zone for "today", "end of day", "within 24 hours"?
- Error behaviour described only as "show an error / báo lỗi" with no text or placement.

For each: quote the text, give the two (or more) readings, and the question that settles it.

## 3. Contradictions

Compare pairwise and cite both sides:

- Ticket vs spec document; spec vs another spec or an older version.
- Docs vs design (Figma): field list, labels and button text, required markers, validation messages, states shown (empty, loading, error, disabled), number/date/currency formats, flows and screens that exist in one but not the other.
- Docs vs code (`code.paths`): limits in validators, enum values, permission checks, feature flags, default values, error messages in i18n files. Note `file:line`. Code may be ahead of or behind the spec; do not decide which is right — ask.
- Within one document: a rule stated twice with different values.

## 4. Missing cases

Ask "what happens when …" for each area the requirement touches. Mark each gap with a suggested expected behaviour only as an assumption.

- **Errors**: server error, timeout, third-party down, partial failure, retry and idempotency (double submit), what the user sees and what is saved.
- **Permissions**: each role × action; not logged in; another user's/tenant's record; owner vs admin; what is hidden vs disabled vs rejected by the API.
- **Limits**: min/max length and value, file size/type, page size, quotas, rate limits, max items in a list, concurrent edits.
- **Empty states**: no data yet, search with no results, all items deleted, first-time user.
- **States and lifecycle**: every status and transition; what can be edited or cancelled in each status; undo.
- **Data**: required vs optional fields, defaults, duplicates, uniqueness (case, spaces, diacritics), trimming, sorting and filtering rules, audit/history.
- **i18n / Vietnamese text**: diacritics in input, search and sort (does "a" find "á"? is "Đ" sorted after "D"?), Unicode normalisation (NFC vs NFD from macOS/iOS keyboards), text length in characters vs bytes, UI text and messages provided in Vietnamese (and English if bilingual), truncation of long Vietnamese labels, number and currency format (`1.000.000 ₫` vs `1,000,000 VND`), date format `dd/MM/yyyy`, names with one word or many words.
- **Time zones and dates**: server vs user time zone (Asia/Ho_Chi_Minh, UTC+7, no DST), "today"/"end of day" boundaries, scheduled jobs, date pickers, leap day, display vs storage format, expiry calculations.
- **Notifications**: email/SMS/push content, language, when sent, to whom, on failure.
- **Integrations and migration**: existing data that does not meet new rules, API consumers (mobile apps on old versions), reports and exports.
- **Non-functional**: response time targets, volume, accessibility, supported browsers/devices, security (PII, logs), audit.

## 5. Testability

An AC is testable when a tester can set it up, act, and observe a pass/fail result without asking anyone. Flag:

- No observable outcome ("data is processed").
- Outcome observable only in logs/DB nobody can access in the test environment.
- Needs data, accounts, time travel or a third-party sandbox that does not exist — say what is needed.
- Two behaviours in one AC; conditions without an "otherwise".
- Rate it `yes` / `partly` / `no` in the AC table and give the rewrite or the missing piece.

## 6. Risks

For each risk: what can go wrong, impact (`high` money/data/security/legal/core flow, `medium` a feature, `low` cosmetic), likelihood (`high` new or complex code, unclear spec, many components, history of bugs; `low` small change to stable code), and the test focus that reduces it.

## 7. Ranking questions

Rank by impact on testing and release, highest first:

1. `high`: blocks test design or could change the implementation (contradictions, missing business rules, money/data/security/permissions).
2. `medium`: changes expected results of some cases (messages, limits, formats, edge behaviour).
3. `low`: wording, cosmetic, nice-to-know.

Within a level, questions that affect more ACs come first. Each question names who should answer (PO, dev, design), is answerable in one sentence, and offers the options when there are clear ones ("A or B?").
