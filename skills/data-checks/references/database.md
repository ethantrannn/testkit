# Database checks — details

## Ask the team for a read-only user

The script makes every session read-only, but a database user that *cannot* write is the real guarantee. Give the team this SQL (adapt names) and put the URL in an env var named in `data_checks.databases.<name>.url_env`, e.g. in the user's shell profile or CI secret store, never in the repo.

PostgreSQL (verified on 17):

```sql
CREATE ROLE qa_ro LOGIN PASSWORD '<generated>' CONNECTION LIMIT 3;
GRANT CONNECT ON DATABASE app TO qa_ro;
GRANT USAGE ON SCHEMA public TO qa_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO qa_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO qa_ro;
ALTER ROLE qa_ro SET default_transaction_read_only = on;
ALTER ROLE qa_ro SET statement_timeout = '5s';
```

URL: `postgresql://qa_ro:<password>@db-staging.internal:5432/app?sslmode=require`

MySQL / MariaDB:

```sql
CREATE USER 'qa_ro'@'%' IDENTIFIED BY '<generated>' WITH MAX_USER_CONNECTIONS 3;
GRANT SELECT ON app.* TO 'qa_ro'@'%';
```

URL: `mysql://qa_ro:<password>@db-staging.internal:3306/app` (the script passes the password through `MYSQL_PWD`, not the command line).

SQLite: `sqlite:///path/to/app.db` (absolute) or `sqlite:path/relative/to/project.db`. Prefer a copy of the file when the app is running and writing to it.

Tables with secrets the testers never need (password hashes, payment tokens) can be left out of the grant entirely.

## What `db_query.py` blocks

| Layer | Postgres | MySQL / MariaDB | SQLite |
|---|---|---|---|
| Statement filter (before sending) | one statement; first word SELECT/WITH/EXPLAIN/SHOW/DESCRIBE/PRAGMA/VALUES/TABLE; no INSERT, UPDATE, DELETE, MERGE, CREATE, ALTER, DROP, TRUNCATE, GRANT, COPY, CALL, DO, LOCK, VACUUM, SET, INTO, FOR UPDATE/SHARE, `EXPLAIN ANALYZE`, sleep/file/dblink functions | same | same; PRAGMA only without `=` |
| Session | `PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=<ms>`, then `BEGIN READ ONLY` … `ROLLBACK` | `SET SESSION TRANSACTION READ ONLY`, `max_execution_time` (MySQL) / `max_statement_time` (MariaDB), `START TRANSACTION READ ONLY` … `ROLLBACK` | URI `mode=ro`, `PRAGMA query_only = ON` |
| Result | `LIMIT max_rows+1` wrapper, truncation reported | same | same |

Comments and string literals are ignored by the filter, so `WHERE note = 'please delete'` is fine. The filter is a guard against mistakes, not a sandbox; the read-only session and user are what make it safe.

## Raw client patterns

Use these only when the script cannot express what you need (e.g. `psql` meta-commands); keep the same rules.

PostgreSQL (`psql`):

```bash
PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=5000" \
  psql "$TESTKIT_DB_URL" -X -q --csv -v ON_ERROR_STOP=1 \
  -c "BEGIN READ ONLY" -c "SELECT id, status FROM orders WHERE id = 42 LIMIT 50" -c "ROLLBACK"
psql "$TESTKIT_DB_URL" -X -c '\d orders'          # describe a table
```

A write in that session fails with `ERROR: cannot execute DELETE in a read-only transaction`.

MySQL (`mysql`):

```bash
MYSQL_PWD="$DB_PASSWORD" mysql --batch -h db-staging.internal -u qa_ro app -e \
  "SET SESSION max_execution_time=5000; START TRANSACTION READ ONLY; SELECT id, status FROM orders WHERE id = 42 LIMIT 50; ROLLBACK;"
```

A write fails with `ERROR 1792: Cannot execute statement in a READ ONLY transaction`. MySQL DDL auto-commits, so never "test" read-only mode with `CREATE TABLE`; `db_query.py --prove-readonly` checks `@@session.transaction_read_only` instead.

SQLite (`sqlite3`, preinstalled on macOS):

```bash
sqlite3 -readonly app.db "SELECT id, status FROM orders LIMIT 50"
sqlite3 "file:app.db?mode=ro" "SELECT count(*) FROM users"
```

A write fails with `Error: stepping, attempt to write a readonly database (8)`.

Never pass a password with `-p<password>` or put it in a URL on the command line of a shared machine; use the env var.

## Masking rules

- Column name contains (as a `_`-separated word): `email`, `mail`, `phone`, `mobile`, `tel`, `fax`, `name` (any `*_name`), `address`, `street`, `dob`, `birth*`, `ssn`, `cccd`, `cmnd`, `national_id`, `id_number`, `passport`, `tax*`, `iban`, `account_no/number`, `card*`, `token`, `secret`, `password`, `pwd`, `hash`, `salt`, `ip`, `otp`; plus `data_checks.mask_columns` patterns (Python regexes).
- Masked as: emails `a***@domain`; mostly-digit values (phones, ID numbers, accounts) all but the last 3 digits; other text first character + `***`.
- Any email address inside other columns is masked the same way.
- Not masked: values equal to an email of a test account in `qa/accounts.local.json`; output of `PRAGMA`, `SHOW`, `DESCRIBE`, `EXPLAIN` (schema, not personal data).

If a case truly needs to compare a masked value (e.g. the phone number the test account entered), compare it in the terminal with `--no-mask` and write only the verdict ("phone stored as entered") into the result.
