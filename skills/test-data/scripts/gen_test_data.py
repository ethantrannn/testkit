# /// script
# requires-python = ">=3.10"
# dependencies = ["Faker==40.44.0"]
# ///
"""Generate realistic test data (vi_VN / en_US) and edge-case strings for testkit cases.

    uv run gen_test_data.py person  --count 5 --locale vi_VN --prefix proj-123-s2 --seed 1
    uv run gen_test_data.py order   --count 3 --locale en_US --format csv --out data/orders.csv
    uv run gen_test_data.py edge    --max-length 50 [--kind text|number|date|email|phone|all]

Entities: person, company, address, product, order (and edge).
  --locale     vi_VN (default) or en_US
  --prefix     run/stream tag put into every email, username, SKU, order number and company name,
               e.g. proj-123-s2, so parallel streams never collide and cleanup can find the rows
  --seed       same seed → same data (default: random)
  --email-domain  default example.test (reserved; never delivers to real people)
  --format     json (default) or csv (nested fields flattened as a.b, lists as JSON)
  --out        write to a file instead of stdout

vi_VN data: Vietnamese names with diacritics in family-middle-given order, mobile numbers with real
carrier prefixes (03x/05x/07x/08x/09x, also as +84), post-2025 provinces and communes from Faker,
12-digit CCCD numbers (province code + gender/century digit + birth year + 6 digits) and bank
account numbers. en_US: Faker names/addresses, 555-01xx fictional phone numbers, SSNs in the
never-issued 9xx range. ID and bank numbers are format-valid but random: they are FAKE, marked
`"fake": true`, and must only be used in test environments.

edge: boundary and edge values from the test-case-standard checklist — empty/whitespace, length
max-1/max/max+1 (ASCII, Vietnamese multi-byte, emoji), emoji/ZWJ, RTL and bidi override,
HTML/script, template and SQL-ish strings, control and zero-width characters, NFC vs NFD
Vietnamese, leading zeros and other number forms, dates, emails, VN phone formats. Each item has
id, kind, label, value, chars (code points), utf16 (JS .length), bytes (UTF-8).
Exit codes: 0 ok · 2 usage error.
"""
import argparse
import csv
import io
import json
import random
import string
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from faker import Faker

VN_SURNAMES = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ",
               "Hồ", "Ngô", "Dương", "Lý", "Trương", "Đinh"]
VN_MIDDLE_M = ["Văn", "Hữu", "Minh", "Đức", "Quốc", "Gia", "Thành", "Công", "Hoàng", "Xuân"]
VN_MIDDLE_F = ["Thị", "Ngọc", "Thu", "Thanh", "Bảo", "Hoài", "Mỹ", "Khánh", "Phương", "Kim"]
VN_GIVEN_M = ["An", "Bình", "Cường", "Dũng", "Hùng", "Khánh", "Long", "Minh", "Nam", "Phúc", "Quân", "Sơn",
              "Thắng", "Tuấn", "Việt", "Đạt", "Huy", "Lộc", "Tài", "Khoa"]
VN_GIVEN_F = ["Anh", "Hà", "Hạnh", "Hương", "Lan", "Linh", "Mai", "Ngọc", "Nhung", "Phương", "Quỳnh", "Thảo",
              "Trang", "Uyên", "Yến", "Ánh", "Diệp", "Hằng", "Thư", "Vy"]
VN_MOBILE_PREFIXES = ["032", "033", "034", "035", "036", "037", "038", "039", "052", "056", "058", "059",
                      "070", "076", "077", "078", "079", "081", "082", "083", "084", "085", "086", "088",
                      "089", "090", "091", "092", "093", "094", "096", "097", "098", "099"]
# CCCD province codes (first 3 digits), a representative subset.
VN_CCCD_PROVINCES = ["001", "002", "004", "008", "010", "011", "012", "014", "015", "019", "020", "022",
                     "024", "025", "026", "027", "030", "031", "033", "034", "035", "036", "037", "038",
                     "040", "042", "044", "045", "046", "048", "049", "051", "052", "054", "056", "058",
                     "060", "062", "064", "066", "067", "068", "070", "072", "074", "075", "077", "079",
                     "080", "082", "083", "084", "086", "087", "089", "091", "092", "093", "094", "095", "096"]
VN_BANKS = [("Vietcombank", 13), ("VietinBank", 12), ("BIDV", 14), ("Agribank", 13), ("Techcombank", 14),
            ("MB Bank", 13), ("ACB", 9), ("VPBank", 10), ("TPBank", 11), ("Sacombank", 12)]
VN_COMPANY_FORMS = ["Công ty TNHH", "Công ty Cổ phần", "Công ty TNHH MTV", "Doanh nghiệp tư nhân"]
VN_COMPANY_WORDS = ["Sao Mai", "Hưng Thịnh", "Phú Gia", "An Khang", "Đại Việt", "Thành Công", "Hoàng Long",
                    "Minh Phát", "Tân Tiến", "Bình Minh", "Ánh Dương", "Trường An"]
VN_COMPANY_FIELDS = ["Thương mại Dịch vụ", "Công nghệ", "Xây dựng", "Thực phẩm", "Vận tải", "Giáo dục",
                     "Du lịch", "Phần mềm"]
PRODUCTS = {
    "vi_VN": [("Áo thun cotton", "Thời trang", 99000, 399000), ("Cà phê rang xay 500g", "Thực phẩm", 85000, 250000),
              ("Nồi cơm điện 1.8L", "Gia dụng", 450000, 2500000), ("Tai nghe Bluetooth", "Điện tử", 290000, 3500000),
              ("Sách kỹ năng sống", "Sách", 59000, 249000), ("Bàn phím cơ", "Điện tử", 650000, 3200000),
              ("Nước mắm Phú Quốc 500ml", "Thực phẩm", 45000, 120000), ("Dép tổ ong", "Thời trang", 25000, 60000)],
    "en_US": [("Cotton T-shirt", "Apparel", 9.99, 39.99), ("Ground coffee 1lb", "Grocery", 7.5, 24.0),
              ("Rice cooker 10-cup", "Home", 39.0, 199.0), ("Bluetooth headphones", "Electronics", 19.0, 299.0),
              ("Paperback novel", "Books", 6.99, 24.99), ("Mechanical keyboard", "Electronics", 49.0, 229.0)],
}
ORDER_STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled", "refunded"]
PAYMENTS = {"vi_VN": ["cod", "bank_transfer", "momo", "zalopay", "vnpay", "card"],
            "en_US": ["card", "paypal", "apple_pay", "bank_transfer"]}


class Gen:
    def __init__(self, locale, prefix, seed, domain):
        self.locale, self.prefix, self.domain = locale, prefix.strip("-"), domain
        self.fk = Faker(locale)
        self.rnd = random.Random(seed)
        if seed is not None:
            self.fk.seed_instance(seed)
        self.vi = locale == "vi_VN"

    def tag(self, kind, n):
        return f"{self.prefix}-{kind}{n}" if self.prefix else f"{kind}{n}"

    def email(self, kind, n):
        return f"qa+{self.tag(kind, n)}@{self.domain}".lower()

    def digits(self, k):
        return "".join(self.rnd.choice(string.digits) for _ in range(k))

    def phone(self):
        if self.vi:
            p = self.rnd.choice(VN_MOBILE_PREFIXES)
            rest = self.digits(7)
            return {"phone": f"{p}{rest}", "phone_display": f"{p} {rest[:3]} {rest[3:]}",
                    "phone_e164": f"+84{p[1:]}{rest}"}
        last = f"01{self.digits(2)}"
        area = self.rnd.choice(["212", "312", "415", "512", "617", "702", "808"])
        return {"phone": f"({area}) 555-{last}", "phone_display": f"{area}-555-{last}",
                "phone_e164": f"+1{area}555{last}"}

    def address(self, n=1):
        fk = self.fk
        if self.vi:
            street, commune = fk.street_address(), fk.commune()
            province = self.rnd.choice([fk.province(), fk.city()])
            postcode = fk.postcode()
            return {"street": street, "ward": commune, "province": province, "postal_code": postcode,
                    "country": "Việt Nam", "full": f"{street}, {commune}, {province}"}
        street, city, state, zipc = fk.street_address(), fk.city(), fk.state_abbr(), fk.zipcode()
        return {"street": street, "city": city, "state": state, "postal_code": zipc, "country": "United States",
                "full": f"{street}, {city}, {state} {zipc}"}

    def person(self, n):
        gender = self.rnd.choice(["male", "female"])
        dob = date(1960, 1, 1) + timedelta(days=self.rnd.randint(0, 365 * 46))
        if self.vi:
            family = self.rnd.choice(VN_SURNAMES)
            middle = self.rnd.choice(VN_MIDDLE_M if gender == "male" else VN_MIDDLE_F)
            given = self.rnd.choice(VN_GIVEN_M if gender == "male" else VN_GIVEN_F)
            full = f"{family} {middle} {given}"
            century = 0 if dob.year < 2000 else 2
            nid = self.rnd.choice(VN_CCCD_PROVINCES) + str(century + (gender == "female")) + \
                f"{dob.year % 100:02d}" + self.digits(6)
            id_doc = {"type": "CCCD", "number": nid, "fake": True}
            bank, length = self.rnd.choice(VN_BANKS)
            bank_acc = {"bank": bank, "number": self.digits(length), "holder": strip_marks(full).upper(), "fake": True}
        else:
            family = self.fk.last_name()
            given = self.fk.first_name_male() if gender == "male" else self.fk.first_name_female()
            middle, full = "", f"{given} {family}"
            id_doc = {"type": "SSN", "number": f"9{self.digits(2)}-{self.digits(2)}-{self.digits(4)}", "fake": True}
            bank_acc = {"bank": "Example Bank", "routing": "000000000", "number": self.digits(10), "fake": True}
        return {"ref": self.tag("person", n), "full_name": full, "family_name": family, "middle_name": middle,
                "given_name": given, "gender": gender, "date_of_birth": dob.isoformat(),
                "email": self.email("person", n), "username": self.tag("user", n).replace("-", "_"),
                "password": strong_password(self.rnd), **self.phone(), "address": self.address(),
                "id_document": id_doc, "bank_account": bank_acc}

    def company(self, n):
        if self.vi:
            name = f"{self.rnd.choice(VN_COMPANY_FORMS)} {self.rnd.choice(VN_COMPANY_FIELDS)} " \
                   f"{self.rnd.choice(VN_COMPANY_WORDS)}"
            tax = {"type": "MST", "number": "0" + self.digits(9), "fake": True}
        else:
            name = self.fk.company()
            tax = {"type": "EIN", "number": f"00-{self.digits(7)}", "fake": True}
        return {"ref": self.tag("company", n), "name": f"{name} [{self.prefix}]" if self.prefix else name,
                "tax_id": tax, "email": self.email("company", n), **self.phone(),
                "website": f"https://{self.tag('company', n)}.example.test", "address": self.address()}

    def product(self, n):
        name, cat, lo, hi = self.rnd.choice(PRODUCTS[self.locale])
        if self.vi:
            price, cur = self.rnd.randrange(int(lo), int(hi) + 1, 1000), "VND"
        else:
            price, cur = round(self.rnd.uniform(lo, hi), 2), "USD"
        return {"ref": self.tag("product", n), "sku": self.tag("SKU", n).upper(), "name": name,
                "category": cat, "price": price, "currency": cur, "stock": self.rnd.randint(0, 500),
                "description": f"{name} — test product {self.tag('product', n)}"}

    def order(self, n):
        cust = self.person(n)
        items = []
        for i in range(self.rnd.randint(1, 3)):
            p = self.product(f"{n}-{i + 1}")
            items.append({"sku": p["sku"], "name": p["name"], "quantity": self.rnd.randint(1, 3),
                          "unit_price": p["price"]})
        subtotal = sum(i["quantity"] * i["unit_price"] for i in items)
        ship = (self.rnd.choice([0, 15000, 30000]) if self.vi else self.rnd.choice([0, 4.99, 9.99]))
        total = subtotal + ship if self.vi else round(subtotal + ship, 2)
        created = datetime.now(timezone.utc) - timedelta(minutes=self.rnd.randint(0, 60 * 24 * 30))
        return {"ref": self.tag("order", n), "order_no": self.tag("ORD", n).upper(),
                "customer": {**{k: cust[k] for k in ("full_name", "phone", "address")},
                             "email": self.email("customer", n)},
                "items": items, "subtotal": round(subtotal, 2), "shipping_fee": ship, "total": total,
                "currency": "VND" if self.vi else "USD", "status": self.rnd.choice(ORDER_STATUSES),
                "payment_method": self.rnd.choice(PAYMENTS[self.locale]),
                "created_at": created.replace(microsecond=0).isoformat()}


def strip_marks(s):
    s = s.replace("Đ", "D").replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def strong_password(rnd):
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*-_"]
    chars = [rnd.choice(p) for p in pools] + [rnd.choice("".join(pools)) for _ in range(12)]
    rnd.shuffle(chars)
    return "".join(chars)


def edge_values(max_len, kind):
    vi = "Nguyễn Thị Ánh Tuyết"
    items = []

    def add(k, label, value):
        items.append({"kind": k, "label": label, "value": value})

    if kind in ("text", "all"):
        add("text", "empty", "")
        add("text", "single space", " ")
        add("text", "whitespace only (spaces, tab, newline)", "  \t\n ")
        add("text", "leading and trailing spaces", "  abc  ")
        add("text", "non-breaking space only", " ")
        add("text", "zero-width space inside", "ab​c")
        add("text", "single character", "a")
        if max_len:
            for n, lbl in ((max_len - 1, "max-1"), (max_len, "max"), (max_len + 1, "max+1")):
                if n >= 0:
                    add("text", f"ASCII length {lbl} ({n})", "a" * n)
            add("text", f"Vietnamese length max ({max_len} chars, more UTF-8 bytes)", ("ệ" * max_len))
            add("text", f"Vietnamese length max+1 ({max_len + 1})", "ệ" * (max_len + 1))
            add("text", f"emoji length max ({max_len} code points, {2 * max_len} UTF-16 units)", "😀" * max_len)
        add("text", "very long (10000)", "x" * 10000)
        add("text", "Vietnamese diacritics (NFC, precomposed)", unicodedata.normalize("NFC", vi))
        add("text", "Vietnamese diacritics (NFD, decomposed — looks identical)", unicodedata.normalize("NFD", vi))
        add("text", "Vietnamese uppercase", "ĐẶNG VĂN ỨNG")
        add("text", "emoji", "Xin chào 😀🎉")
        add("text", "emoji ZWJ sequence and flag", "👨‍👩‍👧‍👦🇻🇳")
        add("text", "CJK", "测试データ테스트")
        add("text", "RTL Arabic", "مرحبا بالعالم")
        add("text", "RTL Hebrew mixed with LTR", "שלום abc 123")
        add("text", "bidi override (RLO)", "abc‮dcba.exe")
        add("text", "full-width Latin", "ＡＢＣ１２３")
        add("text", "combining marks stack (zalgo)", "á̂̃̄̅")
        add("text", "HTML tag", "<b>bold</b>")
        add("text", "script injection", "<script>alert(1)</script>")
        add("text", "attribute injection", "\"><img src=x onerror=alert(1)>")
        add("text", "javascript URL", "javascript:alert(1)")
        add("text", "template injection", "{{7*7}} ${7*7} <%= 7*7 %>")
        add("text", "SQL-ish OR", "' OR 1=1 --")
        add("text", "SQL-ish drop", "Robert'); DROP TABLE students;--")
        add("text", "quotes and backslash", "O'Brien \"quoted\" back\\slash")
        add("text", "CSV formula injection", "=HYPERLINK(\"http://example.test\",\"x\")")
        add("text", "path-like", "../../etc/passwd")
        add("text", "null-ish words", "null")
        add("text", "undefined word", "undefined")
        add("text", "NUL control character", "a\u0000b")
        add("text", "line breaks (CRLF)", "line1\r\nline2")
    if kind in ("number", "all"):
        for v, lbl in [("0", "zero"), ("-1", "negative"), ("0.1", "decimal"), ("1,5", "decimal comma (vi)"),
                       ("1.000.000", "thousands dots (vi)"), ("1e3", "exponent"), ("00123", "leading zeros"),
                       ("2147483648", "int32 max+1"), ("9007199254740993", "above JS safe integer"),
                       ("99999999999999999999", "very large"), (" 12 ", "spaces around"), ("12abc", "trailing letters"),
                       ("abc", "non-numeric"), ("NaN", "NaN"), ("Infinity", "Infinity"), ("١٢٣", "Arabic-Indic digits"),
                       ("", "empty")]:
            add("number", lbl, v)
    if kind in ("date", "all"):
        today = date.today()
        for v, lbl in [(today.isoformat(), "today"), ((today - timedelta(days=1)).isoformat(), "yesterday"),
                       ((today + timedelta(days=1)).isoformat(), "tomorrow"), ("2024-02-29", "leap day"),
                       ("2023-02-29", "invalid leap day"), ("2025-13-01", "month 13"), ("1900-01-01", "very old"),
                       ("9999-12-31", "far future"), ("31/12/2025", "dd/mm/yyyy (vi format)"),
                       ("12/31/2025", "mm/dd/yyyy (US format)"), ("2025-12-31T23:59:59+07:00", "end of day ICT"),
                       ("2025-12-31T17:00:00Z", "same instant in UTC"), ("not-a-date", "invalid text")]:
            add("date", lbl, v)
    if kind in ("email", "all"):
        for v, lbl in [("qa@example.test", "simple"), ("QA.Upper@Example.TEST", "mixed case"),
                       ("qa+tag.sub@sub.example.test", "plus and subdomain"), ("a@b", "no TLD"),
                       ("qa@@example.test", "double @"), ("qa example@example.test", "space inside"),
                       (" qa@example.test ", "spaces around"), ("tiếng.việt@example.test", "unicode local part"),
                       ("qa@xn--vit-nam-y0a.example.test", "punycode domain"),
                       ("a" * 64 + "@example.test", "local part 64 (max)"), ("a" * 65 + "@example.test", "local part 65"),
                       ("", "empty")]:
            add("email", lbl, v)
    if kind in ("phone", "all"):
        for v, lbl in [("0912345678", "VN mobile 10 digits"), ("+84912345678", "VN mobile E.164"),
                       ("84912345678", "VN without +"), ("091 234 5678", "VN with spaces"),
                       ("091-234-5678", "VN with dashes"), ("091234567", "9 digits (too short)"),
                       ("09123456789", "11 digits (too long)"), ("0123456789", "retired prefix 012"),
                       ("02838123456", "VN landline (HCMC)"), ("+1 (212) 555-0123", "US fictional"),
                       ("abcdefghij", "letters"), ("", "empty")]:
            add("phone", lbl, v)
    for i, it in enumerate(items, 1):
        v = it["value"]
        it.update({"id": f"EDGE-{i:03d}", "chars": len(v), "utf16": len(v.encode("utf-16-le")) // 2,
                   "bytes": len(v.encode("utf-8"))})
    return [{k: it[k] for k in ("id", "kind", "label", "value", "chars", "utf16", "bytes")} for it in items]


def flatten(d, parent=""):
    out = {}
    for k, v in d.items():
        key = f"{parent}.{k}" if parent else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        elif isinstance(v, list):
            out[key] = json.dumps(v, ensure_ascii=False)
        else:
            out[key] = v
    return out


def to_csv(rows):
    flat = [flatten(r) for r in rows]
    cols = list(dict.fromkeys(k for r in flat for k in r))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(flat)
    return buf.getvalue()


def to_hurl(rows, args):
    if not args.endpoint or len(args.endpoint.split()) != 2:
        sys.exit('gen_test_data: --format hurl needs --endpoint "METHOD /path"')
    method, path = args.endpoint.split()
    out = [f"# Seed data generated by gen_test_data.py ({args.entity} x{len(rows)}, prefix {args.prefix or '-'})"]
    if args.hurl_login:
        out.append(Path(args.hurl_login).read_text(encoding="utf-8").strip() + "\n")
    auth = "Authorization: Bearer {{token}}\n" if args.hurl_login else ""
    for r in rows:
        # "{{" would start a Hurl template; inside a JSON string \u007b is the same character.
        body = json.dumps(r, ensure_ascii=False).replace("{{", "\\u007b\\u007b")
        out.append(f"{method.upper()} {{{{base_url}}}}{path}\n{auth}```json\n{body}\n```\nHTTP {args.expect}\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entity", choices=["person", "company", "address", "product", "order", "edge"])
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--locale", choices=["vi_VN", "en_US"], default="vi_VN")
    ap.add_argument("--prefix", default="", help="run/stream tag, e.g. proj-123-s2")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--email-domain", default="example.test")
    ap.add_argument("--max-length", type=int, help="edge: field max length → max-1/max/max+1 cases")
    ap.add_argument("--kind", choices=["text", "number", "date", "email", "phone", "all"], default="all",
                    help="edge: which group of values (default all)")
    ap.add_argument("--format", choices=["json", "csv", "hurl"], default="json",
                    help="hurl: one request per record, body = the record (needs --endpoint)")
    ap.add_argument("--endpoint", help='hurl: "METHOD /path", e.g. "POST /api/products"')
    ap.add_argument("--expect", default="201", help="hurl: expected status per request (default 201)")
    ap.add_argument("--hurl-login", help="hurl: file whose entries (a login capturing {{token}}) go first")
    ap.add_argument("--out", help="output file (default stdout)")
    args = ap.parse_args()
    if args.count < 1 or args.count > 10000:
        ap.error("--count must be 1..10000")
    if args.max_length is not None and args.max_length < 1:
        ap.error("--max-length must be >= 1")

    if args.entity == "edge":
        rows = edge_values(args.max_length, args.kind)
    else:
        g = Gen(args.locale, args.prefix, args.seed, args.email_domain)
        make = getattr(g, args.entity)
        rows = [make(n) for n in range(1, args.count + 1)]
    if args.format == "hurl":
        text = to_hurl(rows, args)
    else:
        text = to_csv(rows) if args.format == "csv" else json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {len(rows)} {args.entity} record(s) to {args.out}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
