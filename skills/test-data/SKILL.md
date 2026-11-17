---
name: test-data
description: Generate realistic and edge-case test data for testkit cases — Vietnamese (vi_VN, with diacritics, VN mobile numbers, CCCD, fake bank accounts) and US (en_US) people, companies, addresses, products and orders as JSON, CSV or a ready-to-run Hurl seed file, plus boundary and edge strings from the test-case-standard checklist (empty, whitespace, max/max+1, emoji, RTL, HTML/script, SQL-ish, leading zeros, NFC vs NFD Vietnamese). Covers loading data through the app's API or seed command with run/stream prefixes so parallel streams never collide, and cleanup. Use when a case needs input values or bulk records, when writing validation/boundary cases, or when the user says "test data", "dữ liệu test", "tạo dữ liệu mẫu", "sinh dữ liệu", "edge cases", "fake data", "seed data".
argument-hint: "<person|company|address|product|order|edge> [--count N] [--locale vi_VN|en_US] [--prefix <run>-<stream>]"
---

# Test data

Good test data is realistic enough to look like production (Vietnamese names with diacritics, real phone formats, plausible addresses) and hostile enough to find bugs (edge strings at and beyond every limit). It is always clearly fake and always tagged with the stream that made it.

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
GEN=$SK/test-data/scripts/gen_test_data.py                         # uv run $GEN --help
```

## 1. Generating records

```bash
uv run $GEN person  --count 5 --locale vi_VN --prefix proj-123-s2 --seed 1
uv run $GEN company --count 2 --prefix proj-123-s2
uv run $GEN product --count 20 --locale en_US --prefix proj-123-s2 --format csv \
  --out qa/runs/PROJ-123/data/S2/products.csv
uv run $GEN order   --count 3 --prefix proj-123-s2 --out qa/runs/PROJ-123/data/S2/orders.json
uv run $GEN address --count 3 --locale vi_VN
```

| Entity | Fields |
|---|---|
| `person` | ref, full/family/middle/given name, gender, date_of_birth, email, username, password, phone (`0912345678`), phone_display, phone_e164 (`+84912345678`), address, id_document (CCCD / SSN), bank_account |
| `company` | ref, name, tax_id (MST / EIN), email, phone, website, address |
| `address` | street, ward, province (vi) or city/state (en), postal_code, country, full |
| `product` | ref, sku, name, category, price (VND integers / USD decimals), currency, stock, description |
| `order` | ref, order_no, customer, items (sku, name, quantity, unit_price), subtotal, shipping_fee, total, currency, status, payment_method, created_at |

- **vi_VN**: names in family-middle-given order (`Nguyễn Thị Ánh`), gender-consistent middle names; mobile numbers with current carrier prefixes 03x/05x/07x/08x/09x; post-2025 provinces and wards; CCCD = province code + gender/century digit + birth year + 6 digits, consistent with gender and date of birth; bank account numbers with typical lengths per bank.
- **en_US**: Faker names and addresses, phone numbers in the fictional `555-01xx` range, SSNs in the never-issued `9xx` range.
- **Fake by construction**: emails use `example.test` (a reserved domain that never delivers), every ID and bank number is random and marked `"fake": true`. Format-valid numbers can still coincide with a real person's: use them only in test environments, and never in a form that submits to a real bank, KYC or government service.
- **`--prefix`** goes into every email (`qa+proj-123-s2-person1@example.test`), username, SKU, order number and company name. Always pass `<RUN_ID>-<STREAM_ID>` in lower case.
- **`--seed`** makes the output repeatable; put the seed in the case's `Test data` line when the exact values matter.
- `--format csv` flattens nested fields (`address.province`) and writes lists as JSON, ready for import screens. Save generated files under `qa/runs/<RUN_ID>/data/<STREAM_ID>/`.

Accounts for logging in still come from the executor's account strategy (`test-executor` → Test accounts); `person` records are for forms and imports, not for replacing that flow.

## 2. Edge values

```bash
uv run $GEN edge --max-length 50                       # everything, with length cases for a 50-char limit
uv run $GEN edge --kind text --max-length 255 --format csv
uv run $GEN edge --kind number | --kind date | --kind email | --kind phone
```

Each item has `id` (`EDGE-001`), `kind`, `label`, `value`, `chars` (code points), `utf16` (what JavaScript `.length` and many `maxlength` attributes count) and `bytes` (UTF-8, what `VARCHAR` limits in MySQL bytes-mode or byte-based APIs count). The gaps between those three counts are where length bugs live: `ệ` × 50 is 50 chars but 150 bytes; 😀 × 50 is 100 UTF-16 units.

The groups cover the `test-case-standard` edge-case checklist:

- **text**: empty, whitespace-only, leading/trailing spaces, NBSP, zero-width space, max-1/max/max+1 in ASCII, Vietnamese and emoji, 10 000 chars, Vietnamese NFC vs NFD (look identical, compare and search differently), emoji ZWJ sequences and flags, CJK, Arabic and Hebrew RTL, bidi override, full-width Latin, stacked combining marks, HTML, `<script>`, attribute injection, `javascript:` URL, template injection, SQL-ish strings, quotes and backslash, CSV formula injection, path-like, `null`/`undefined` words, NUL and CRLF.
- **number**: 0, negative, decimal point and Vietnamese decimal comma, thousands dots, exponent, leading zeros, int32 max+1, beyond JS safe integer, very large, spaces, trailing letters, non-numeric, NaN, Infinity, Arabic-Indic digits, empty.
- **date**: today, yesterday, tomorrow, leap day, invalid leap day, month 13, very old, far future, dd/mm/yyyy vs mm/dd/yyyy, end of day in ICT vs the same instant in UTC, invalid text.
- **email**, **phone**: valid and invalid forms, Vietnamese formats with and without +84, spaces, dashes, too short/long.

In a case, name the item: `Test data: EDGE-016 (Vietnamese NFD) from test-data edge`, and state the expected behaviour per item (accepted and stored unchanged, trimmed, rejected with message "…"). For NFC/NFD, expect search and duplicate checks to treat both forms as the same name unless the docs say otherwise.

## 3. Loading data into the app

Pick the first that the project supports, in this order:

1. **The app's API (preferred)** — the same path real data takes, so validation runs. Generate a Hurl seed file and run it with the `api-testing` runner as the first file of the stream:

   ```bash
   # lib/login-member.hurl: a login entry that captures {{token}} (see api-testing)
   uv run $GEN product --count 10 --prefix proj-123-s2 \
     --format hurl --endpoint "POST /api/products" --expect 201 \
     --hurl-login qa/runs/PROJ-123/api/S2/lib/login-member.hurl \
     --out qa/runs/PROJ-123/api/S2/00-seed.hurl
   uv run $SK/api-testing/scripts/api_run.py run --run PROJ-123 --stream S2 --case 00-seed
   ```

   The request body is the generated record; if the API expects other field names, generate JSON and write the seed `.hurl` by hand from it. `00-seed` sorts first, so a full-stream run seeds before the cases; its row in `summary.md` shows whether seeding worked.
2. **The project's seed command** from config (`test_data.seed_command`), e.g. `pnpm db:seed --file {file} --prefix {prefix}`: generate a JSON/CSV file, substitute `{file}` and `{prefix}`, run it, and record the command in the results.
3. **The UI** — for a handful of records, or when the case is about the creation flow itself.

Never insert directly into the database: `data-checks` is read-only, and direct inserts skip the app's validation and side effects.

Safety: loading data is a write. Only on environments with `allow_write: true`; otherwise mark the dependent cases `BLOCKED`. Keep volumes small (tens of records, not thousands) unless the case is explicitly about volume and config allows it.

## 4. Parallel streams and cleanup

- Everything a stream creates carries its prefix, and every check filters by it (`WHERE sku LIKE 'PROJ-123-S2-%'`, `?search=proj-123-s2`). Two streams never share a record unless the plan says so.
- At the end of the stream, delete what it created: a `zz-cleanup.hurl` (runs last) that deletes by the ids captured or by prefix search, or `test_data.cleanup_command` with `{prefix}`. Verify with a search by prefix that nothing is left. Anything that could not be deleted goes in the results under "Other observations" with its prefix.
- Generated files in `qa/runs/<RUN_ID>/data/` contain only fake data and may be kept as evidence; delete large or binary files (oversize uploads) after the run.

## Config

```yaml
test_data:
  locale: vi_VN                     # default --locale for gen_test_data.py (vi_VN | en_US)
  email_domain: example.test        # --email-domain; must not deliver mail to real people
  seed_command: ""                  # optional, e.g. "pnpm db:seed --file {file} --prefix {prefix}"
  cleanup_command: ""               # optional, e.g. "pnpm db:cleanup --prefix {prefix}"
```
