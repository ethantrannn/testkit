# Hurl patterns for testkit API cases

Every snippet below was run against a local test API with Hurl 8.1.0. Variables in `{{...}}` come from the runner (`base_url`, `prefix`, `<role>_email`, `<role>_password`, `api.vars`, `api.secrets_env`). Full syntax: https://hurl.dev/docs/hurl-file.html.

File anatomy: a file is a list of entries; each entry is a request (method + URL, headers, optional sections and body) followed by an optional response spec (`HTTP <status>`, expected headers, `[Captures]`, `[Asserts]`). An entry with `HTTP 200` and no asserts still fails if the status differs. `HTTP *` accepts any status.

## Contents

- Auth: bearer token, cookie session, CSRF, form login
- Permission matrix
- IDOR
- Validation and boundaries
- Error format
- Lists and pagination
- Duplicates and idempotency
- Rate limits
- File upload
- GraphQL
- Schema checks
- Waiting for async results
- Assert cheat sheet

## Auth

Bearer token from a JSON login. `redact` keeps the token out of logs and reports:

```hurl
POST {{base_url}}/api/auth/login
{"email": "{{member_email}}", "password": "{{member_password}}"}
HTTP 200
[Captures]
token: jsonpath "$.token" redact
[Asserts]
jsonpath "$.token" isString

GET {{base_url}}/api/me
Authorization: Bearer {{token}}
HTTP 200
[Asserts]
jsonpath "$.email" == "{{member_email}}"
```

Cookie session: Hurl keeps cookies between the entries of one file, so log in once and call on. Form login with a CSRF token:

```hurl
GET {{base_url}}/login
HTTP 200
[Captures]
csrf: xpath "string(//input[@name='_csrf']/@value)"

POST {{base_url}}/login
[FormParams]
_csrf: {{csrf}}
email: {{member_email}}
password: {{member_password}}
HTTP 302
[Asserts]
header "Location" == "/dashboard"
cookie "session" exists
```

A static token from config (`api.secrets_env: {admin_api_key: TESTKIT_API_ADMIN_KEY}`) is used as `X-Api-Key: {{admin_api_key}}`.

Negative auth cases: no `Authorization` header → 401; `Authorization: Bearer invalid-{{prefix}}` → 401; an expired token only if the docs give a way to get one (short TTL in a test environment).

## Permission matrix

One file per protected action, one entry per role, including anonymous. Write the matrix in the case as a table, then:

```hurl
# TC-S1-002 — GET /api/admin/users: anonymous 401, member 403, admin 200
GET {{base_url}}/api/admin/users
HTTP 401

POST {{base_url}}/api/auth/login
{"email": "{{member_email}}", "password": "{{member_password}}"}
HTTP 200
[Captures]
member_session: jsonpath "$.token" redact

GET {{base_url}}/api/admin/users
Authorization: Bearer {{member_session}}
HTTP 403
[Asserts]
jsonpath "$.error.code" == "FORBIDDEN"

POST {{base_url}}/api/auth/login
{"email": "{{admin_email}}", "password": "{{admin_password}}"}
HTTP 200
[Captures]
admin_session: jsonpath "$.token" redact

GET {{base_url}}/api/admin/users
Authorization: Bearer {{admin_session}}
HTTP 200
```

If one role × action pair fails, the whole file fails; the summary's `Detail` names the line, so the bug can say exactly which pair. When a matrix is large, split per role so results stay readable.

## IDOR

Use two accounts of the same role (`member`, `member2`). Owner creates or lists a resource, captures its id; the other user tries to read, update and delete it. Expect 404 or 403 exactly as documented, and assert that no data leaks:

```hurl
GET {{base_url}}/api/orders/{{foreign_id}}
Authorization: Bearer {{token}}
HTTP 404
[Asserts]
jsonpath "$.owner" not exists
```

Also try the id in the body (`{"order_id": {{foreign_id}}}`), in query strings, and in nested routes (`/api/orders/{{foreign_id}}/invoice`). For multi-tenant apps, repeat with a user of another tenant. Writes (PUT/DELETE on a foreign id) only on `allow_write: true` environments, and verify afterwards that the owner's resource is unchanged.

## Validation and boundaries

One entry per value; take edge strings from `uv run $SK/test-data/scripts/gen_test_data.py --edge --max-length 200`:

```hurl
POST {{base_url}}/api/orders
Authorization: Bearer {{token}}
{"quantity": 0}
HTTP 422
[Asserts]
jsonpath "$.error.fields.quantity" exists

POST {{base_url}}/api/orders
Authorization: Bearer {{token}}
{"quantity": 1, "note": "{{prefix}} min"}
HTTP 201
[Asserts]
header "Location" matches "^/api/orders/\\d+$"

POST {{base_url}}/api/orders
Authorization: Bearer {{token}}
{"quantity": "1"}
HTTP 422
```

Cover: missing field, `null`, wrong type (`"1"` vs `1`), min-1/min/max/max+1, extra unknown field (accepted or rejected per docs), invalid JSON (`Content-Type: application/json` with body `{"quantity":`), wrong content type. Strings longer than a line: put the body in a ```` ```json ```` block or reference a file: `file,payloads/note-201.json;`.

## Error format

Assert the documented shape on every negative case at least once per stream, and that internals do not leak:

```hurl
POST {{base_url}}/api/auth/login
{"email": "{{member_email}}", "password": "wrong-{{prefix}}"}
HTTP 401
[Asserts]
header "Content-Type" contains "application/json"
jsonpath "$.error.code" == "INVALID_CREDENTIALS"
jsonpath "$.error.message" isString
jsonpath "$.token" not exists
body not contains "Traceback"
body not contains "SQLSTATE"
duration < 2000
```

## Lists and pagination

```hurl
GET {{base_url}}/api/orders
Authorization: Bearer {{token}}
[Query]
page: 1
per_page: 5
HTTP 200
[Captures]
total: jsonpath "$.meta.total"
[Asserts]
jsonpath "$.data" count == 5
jsonpath "$.meta.page" == 1

GET {{base_url}}/api/orders?page=999&per_page=5
Authorization: Bearer {{token}}
HTTP 200
[Asserts]
jsonpath "$.data" isEmpty

GET {{base_url}}/api/orders?per_page=51
Authorization: Bearer {{token}}
HTTP 422
```

Also: last page has `total % per_page` items, page 0 and negative page, sort order (`jsonpath "$.data[0].created_at"` vs `$.data[1]`), filter + sort combined, cursor pagination (capture `$.next_cursor`, follow it, stop when null), and that list endpoints only return the caller's own records.

## Duplicates and idempotency

```hurl
POST {{base_url}}/api/orders
Authorization: Bearer {{token}}
Idempotency-Key: {{key}}
[Options]
variable: key={{prefix}}-{{newUuid}}
```json
{"quantity": 2}
```
HTTP 201
[Captures]
first_id: jsonpath "$.id"

POST {{base_url}}/api/orders
Authorization: Bearer {{token}}
Idempotency-Key: {{key}}
{"quantity": 2}
HTTP 200
[Asserts]
jsonpath "$.id" == {{first_id}}
```

`[Options] variable:` defines a variable for this and later entries; `{{newUuid}}` and `{{newDate}}` are built in. Without idempotency keys: the same create twice → 409 or a second record per docs; a unique field (email, SKU) reused → 409 with the documented code.

## Rate limits

Check headers, not limits: `header "X-RateLimit-Remaining" exists`, `header "Retry-After" exists` on a 429. Only when a case explicitly tests the limit and the environment is not production, send exactly `limit + 1` requests (`[Options] repeat: 11` on one entry with `HTTP *`, then assert the next is `HTTP 429`). Never run such a case in parallel with other streams.

## File upload

```hurl
POST {{base_url}}/api/upload
Authorization: Bearer {{token}}
[Multipart]
title: {{prefix}} avatar
file: file,files/sample.txt; text/plain
HTTP 201
[Asserts]
jsonpath "$.filename" == "sample.txt"
```

Paths are relative to the `.hurl` file's folder; keep fixtures in `api/<STREAM_ID>/files/`. Make oversize and zero-byte files on the fly (`python3 -c "open('files/big.bin','wb').write(b'0'*(5*1024*1024+1))"`) and delete them after the run instead of committing them. Raw body upload: `PUT ...` then `file,files/report.pdf;` as the body.

## GraphQL

```hurl
POST {{base_url}}/graphql
Authorization: Bearer {{token}}
```graphql
query Order($id: ID!) {
  order(id: $id) { id status }
}

variables {
  "id": "{{order_id}}"
}
```
HTTP 200
[Asserts]
jsonpath "$.errors" not exists
jsonpath "$.data.order.status" == "paid"
```

GraphQL usually answers 200 even for errors: always assert `$.errors` (not exists, or its `extensions.code`). Field-level permission: query a protected field as a lower role and expect `errors[0].extensions.code` = the documented code and `data.<field>` null. Mutations are blocked on `allow_write: false` environments. Check introspection (`{ __schema { types { name } } }`) only if the docs state whether it must be disabled.

## Schema checks

Hurl has no JSON Schema predicate. Two levels:

1. In the file, type-check the fields the case relies on: `isInteger`, `isString`, `isList`, `isObject`, `isIsoDate`, `isUuid`, `exists`, `not exists`, `count`.
2. Full schema: the runner keeps every response body in `evidence/<S>/api/<TC_ID>/store/`. Extract the schema from the OpenAPI file (`components.schemas.Order`, converted to a standalone JSON Schema file in `api/<STREAM_ID>/schemas/`) and validate the stored body:

   ```bash
   uvx --from check-jsonschema==0.39.0 check-jsonschema \
     --schemafile qa/runs/PROJ-123/api/S2/schemas/order.json \
     qa/runs/PROJ-123/evidence/S2/api/TC-S2-007/store/<file>_response.json
   ```

   A validation error is a FAIL of the case; quote the error lines in the result.

## Waiting for async results

For jobs that finish later, poll with retries instead of sleeping:

```hurl
GET {{base_url}}/api/exports/{{export_id}}
Authorization: Bearer {{token}}
[Options]
retry: 10
retry-interval: 1000ms
HTTP 200
[Asserts]
jsonpath "$.status" == "done"
```

## Assert cheat sheet

Queries: `status`, `header "X"`, `cookie "name"`, `body`, `jsonpath "$.a[0].b"`, `xpath "..."`, `regex "..."`, `duration`, `url`, `sha256`, `bytes`.
Predicates (prefix with `not` to negate): `==`, `!=`, `>`, `>=`, `<`, `<=`, `contains`, `startsWith`, `endsWith`, `matches /re/`, `exists`, `isEmpty`, `isString`, `isInteger`, `isFloat`, `isNumber`, `isBoolean`, `isList`, `isObject`, `isIsoDate`, `isUuid`.
Filters: `count`, `nth 0`, `split ","`, `toDate "%Y-%m-%d"`, `decode "utf-8"`.
