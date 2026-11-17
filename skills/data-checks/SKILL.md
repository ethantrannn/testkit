---
name: data-checks
description: How testkit verifies backend state that the UI or API does not show — read-only SQL queries against PostgreSQL, MySQL/MariaDB or SQLite (read-only session, statement timeout, row limit, personal data masked in evidence) and email/OTP/notification checks through a Mailpit or MailHog inbox (wait for a message to a test address, extract the OTP or verification link, assert subject and body). Use when a case expects a database row, status or count, when sign-up or login needs an email code, when a ticket sends emails or notifications, or when the user says "check DB", "kiểm tra database", "query dữ liệu", "lấy OTP", "kiểm tra email", "verify email sent", "check mailbox".
argument-hint: "db <name> <query> | mail <otp|link|wait> --to <address>"
---

# Data checks: database and mailbox

Some expected results live behind the UI: a row written with the right status, an audit log entry, an email with the right link. These checks are **read-only observations**. They never set up or repair state; that goes through the app's UI, API or seed command (`test-data` skill).

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
DQ=$SK/data-checks/scripts/db_query.py      # uv run $DQ ...
MB=$SK/data-checks/scripts/mailbox.py       # python3 $MB ...  (standard library only)
```

## 1. Database checks

### Config

```yaml
data_checks:
  max_rows: 50
  statement_timeout_s: 5
  databases:
    main:
      engine: postgres          # postgres | mysql | sqlite
      url_env: TESTKIT_DB_URL   # connection URL comes from this env var, never from the file
      environment: staging      # the environment this database belongs to
```

The URL should belong to a **read-only database user** (SQL to give the team: `references/database.md`). If `data_checks` is missing or the env var is not set, mark the DB-dependent expected results `BLOCKED` ("no read-only DB access configured") and check what you can through the UI/API.

### Running a query

```bash
uv run $DQ --list                                            # configured databases, env var set or not
uv run $DQ --db main --prove-readonly                        # once per run: shows that a write is rejected
uv run $DQ --db main "SELECT id, status, updated_at FROM orders WHERE note LIKE 'proj-123-s2%' ORDER BY id" \
  --save qa/runs/PROJ-123/evidence/S2/TC-S2-007-db.md
uv run $DQ --db main --file qa/runs/PROJ-123/sql/S2-audit.sql --format json
```

What the script enforces (details in `references/database.md`):

- **One read-only statement**: `SELECT`, `WITH`, `EXPLAIN` (not `ANALYZE`), `SHOW`, `DESCRIBE`, read-only `PRAGMA`. Anything with a write or DDL keyword, `SELECT ... INTO`, `FOR UPDATE`, or a second statement is rejected before it reaches the database.
- **Read-only session** on top: Postgres `default_transaction_read_only=on` + `BEGIN READ ONLY`; MySQL `START TRANSACTION READ ONLY`; SQLite opened `mode=ro` with `query_only`. If `--prove-readonly` does not print `OK`, stop using that connection and tell the user.
- **Statement timeout** (`statement_timeout_s`) and **row limit** (`max_rows`, `--limit`, max 1000). A truncated result says so; narrow the query instead of raising the limit.
- **Masking**: columns that look personal (email, phone, names, address, CCCD/ID numbers, tokens, hashes, IP) and any email address in the output are masked (`r***@gmail.com`, `*******678`). Emails of the stream's own test accounts stay readable. `--no-mask` prints raw values to your terminal for a comparison you must make, never into evidence.

### Writing good data checks

- **Query by your own data only**: filter by the stream's account ids/emails or the `{{prefix}}` your data carries. Never browse other users' rows.
- **Select only the columns the expected result needs.** `SELECT *` on a users table drags personal data into evidence.
- **Read the schema from the code first** (migrations, ORM models) rather than probing the database. `PRAGMA table_info(x)` / `\d x` equivalents (`SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'orders'`) are fine when needed.
- **Timing**: async writes (queues, webhooks) may land later. Re-run the query a few times with a pause (max ~30 s total) before calling it a FAIL, and say how long you waited.
- **Evidence**: always `--save qa/runs/<RUN_ID>/evidence/<STREAM_ID>/<TC_ID>-db.md` for a check that decides a case. In the result row link that file.
- Production databases: never, even if a URL exists, unless the user explicitly asks and the environment is in config. Replicas are preferred over primaries.

## 2. Mailbox checks (email, OTP, links)

### Config

Extends the existing `accounts.inbox` block:

```yaml
accounts:
  inbox:
    url: http://localhost:8025        # Mailpit web/API URL (MailHog works too)
    kind: mailpit                     # mailpit | mailhog (optional: auto-detected)
    auth_env: TESTKIT_INBOX_AUTH      # optional, env var holding "user:password" for basic auth
```

The app under test must send its mail to that catcher (its SMTP points at Mailpit, default port 1025), and test addresses must be ones only this stream uses (`accounts.email_pattern`).

### Commands

```bash
python3 $MB otp  --to "$EMAIL" --subject "verification|xác thực" --timeout 60          # prints e.g. 482913
python3 $MB otp  --to "$EMAIL" --pattern 'code: ([A-Z0-9]{4}-[A-Z0-9]{2})'           # custom code format
python3 $MB link --to "$EMAIL" --pattern '/verify\?token=' --save qa/runs/PROJ-123/evidence/S1/TC-S1-003-email.json
python3 $MB wait --to "$EMAIL" --subject '^Order #\d+ confirmed$' --body 'Total: 1\.250\.000 ₫' --timeout 60
python3 $MB list --to "$EMAIL"                       # what arrived (id, time, to, subject)
python3 $MB show --id <ID> --part html               # full body of one message
python3 $MB purge --to "$EMAIL"                      # only this address; never the whole inbox
```

`wait`, `otp` and `link` poll until a matching message to exactly that address arrives (received within the last `--since` seconds, default 900), newest first; exit 1 on timeout. `otp` prints the first capture group of `--pattern` (default `\b(\d{6})\b`), `link` the first matching URL from the HTML `href`s or text.

### In a test case

1. Before the step that sends mail, note the address (and `purge --to` it if an earlier case of the same stream left mail there).
2. Trigger the email in the UI/API.
3. `otp`/`link`/`wait` with a subject regex from the docs. Type the OTP into the page, or open the link with `goto_url(...)` in the same browser session.
4. For cases about the email itself, assert with `wait --subject ... --body ...` and save the message with `--save .../<TC_ID>-email.json`; look at the HTML with `show --part html` when layout or links matter (or open `<inbox url>/view/<ID>.html` in the browser session and take a screenshot).
5. No email within the timeout: FAIL if the docs promise an email, with the inbox listing in the notes. If the inbox is not configured or unreachable, BLOCKED.

Messages are test data, but OTPs and links are credentials for the test account: do not paste them into bug reports; write `(OTP from mailbox)`.

## 3. Results

Data checks appear in the results table like any other expected result: Evidence = `evidence/S2/TC-S2-007-db.md` or `evidence/S1/TC-S1-003-email.json`. A mismatch between what the UI says and what the database holds is a bug even if the UI case passed.

## References

- `references/database.md` — read-only users to request, raw `psql`/`mysql`/`sqlite3` patterns, what the statement filter blocks, masking rules.
