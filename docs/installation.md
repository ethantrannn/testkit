# Cài đặt testkit

Có hai bước: cài lệnh `testkit` một lần cho mỗi máy, rồi chạy `testkit init` trong từng dự án cần test.

## 1. Cài lệnh `testkit` (một lần)

Dán vào terminal:

**macOS / Linux**
```bash
curl -fsSL https://testkit.example.com/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://testkit.example.com/install.ps1 | iex
```

Installer làm các việc sau, và hỏi trước mỗi bước cài:

| Bước | macOS | Linux | Windows |
|---|---|---|---|
| Coding agent | Nhận ra Claude Code, Codex, Cursor, Gemini CLI, Copilot; nếu không có cái nào thì đề nghị cài Claude Code (`claude.ai/install.sh`) | như macOS | như macOS (`claude.ai/install.ps1`) |
| uv | `astral.sh/uv/install.sh` | `astral.sh/uv/install.sh` | `astral.sh/uv/install.ps1` |
| browser-use CLI 1.x (công cụ trình duyệt mặc định) | `uv tool install browser-use` | như macOS | như macOS |
| Chrome | chỉ kiểm tra, báo nếu thiếu | chỉ kiểm tra, gợi ý cài (không dùng Chromium bản snap vì snap chặn CDP) | kiểm tra, đề nghị cài bằng winget |
| pandoc (đọc spec Word) | Homebrew | apt / dnf (sudo) | winget |
| LibreOffice + poppler (không bắt buộc, để xem trước file Word xuất ra) | chỉ khi có `--with-office` | như macOS | chỉ khi `$env:TESTKIT_OFFICE='1'` (poppler cài tay) |
| Node.js ≥ 22 + `agent-browser` (không bắt buộc) | chỉ khi có `--with-agent-browser` | như macOS | chỉ khi `$env:TESTKIT_AGENT_BROWSER='1'` |
| Kit | tải về `~/.testkit/kit` | tải về `~/.testkit/kit` | tải về `%USERPROFILE%\.testkit\kit` |
| Lệnh `testkit` | `~/.local/bin/testkit`, tự thêm vào PATH trong `~/.zshrc` / `~/.bashrc` | như macOS | `%USERPROFILE%\.testkit\bin\testkit.cmd`, thêm vào PATH của user |

Tùy chọn:

| macOS / Linux | Windows (đặt biến trước khi chạy) | Ý nghĩa |
|---|---|---|
| `... \| bash -s -- --yes` | `$env:TESTKIT_YES='1'` | Đồng ý mọi bước cài, không hỏi |
| `--skip-prereqs` | `$env:TESTKIT_SKIP_PREREQS='1'` | Chỉ cài lệnh `testkit` |
| `--with LIST` | `$env:TESTKIT_WITH='LIST'` | Cài thêm nhóm công cụ, cách nhau bằng dấu phẩy, hoặc `all`: `api` (Hurl), `mail` (Mailpit), `db` (psql, mysql client), `automation` (Node.js cho Playwright), `video` (ffmpeg), `load` (k6), `mobile` (Maestro, cần Java 17+), `security` (kiểm tra Docker cho OWASP ZAP), `office`, `agent-browser` |
| `--with-office` | `$env:TESTKIT_OFFICE='1'` | Cài thêm LibreOffice và poppler (khoảng 700 MB) để render file Word xuất ra thành ảnh và kiểm tra |
| `--with-agent-browser` | `$env:TESTKIT_AGENT_BROWSER='1'` | Cài thêm Node.js và `agent-browser`, nếu muốn dùng `browser.tool: agent-browser` |
| `--source <nguồn>` | `$env:TESTKIT_SOURCE='<nguồn>'` | Lấy kit từ nguồn khác: URL trang host (`https://...`), GitHub `owner/repo`, git URL kết thúc bằng `.git`, hoặc thư mục local |
| `--ref v1.2.0` | `$env:TESTKIT_REF='v1.2.0'` | Ghim branch hoặc tag khi nguồn là GitHub hoặc git. Mặc định `main`; không dùng khi nguồn là trang host |

Nguồn và ref được lưu trong `~/.testkit/config`. Các lần `testkit init` sau đều tải từ đây.

`testkit.example.com` là domain ví dụ. Thay bằng domain thật sau khi publish (xem mục "Publish trang cài đặt" bên dưới).

## 2. Cài testkit vào dự án

```bash
cd my-project
testkit init
```

`testkit init` tải bản kit mới nhất từ nguồn đã cấu hình. Nếu mất mạng thì dùng bản cache. Sau đó nó cài skill và subagent cho các coding agent được chọn, và tạo `qa/`. Ví dụ với Claude Code:

```
my-project/
├── .claude/
│   ├── agents/                 test-lead, script-writer, test-reviewer, test-executor
│   ├── skills/                 testkit-config, testkit-run, testkit-verify, test-case-standard, browser-testing, bug-reporting
│   │   ├── browser-use/        skill của browser-use, sinh bằng `browser-use skill install` cho đúng phiên bản đang cài (git-ignored)
│   │   └── browser-testing/    quy ước testkit + scripts/bu-session.sh (phiên trình duyệt riêng cho mỗi stream)
├── qa/
│   ├── config.yml              tạo từ template, không bị ghi đè khi update
│   ├── accounts.local.json     git-ignored
│   ├── .testkit-manifest       danh sách file testkit quản lý, phiên bản, các agent đã chọn
│   ├── bugs/index.md
│   └── runs/
└── .gitignore                  thêm các dòng cho file local và file sinh ra
```

Sau đó mở Claude Code trong dự án và chạy `/testkit-config` để điền URL môi trường, tài khoản test, tracker.

## Các lệnh

| Lệnh | Ý nghĩa |
|---|---|
| `testkit init [dir]` | Cài hoặc làm mới testkit trong thư mục, mặc định là thư mục hiện tại |
| `testkit init --agents LIST` | Chọn coding agent: `auto` (mặc định: nhận ra CLI có trên máy và thư mục `.claude/`, `.codex/`, `.cursor/`, `.gemini/`, `.github/agents/` trong dự án), `all`, hoặc danh sách `claude,codex,cursor,gemini,copilot`. Lựa chọn được lưu lại cho các lần `update` sau. Bỏ một agent khỏi danh sách thì file của nó bị dọn |
| `testkit init --force` | Ghi đè cả file trùng tên mà testkit không quản lý |
| `testkit init --offline` | Không tải, dùng bản cache |
| `testkit update [dir]` | Như `init`, nhưng chỉ chạy khi dự án đã có testkit |
| `testkit doctor` | Kiểm tra Claude Code, uv, browser-use, mở thử một phiên Chrome isolated, pandoc/LibreOffice/pdftoppm, bản kit đang cache và bản trong dự án |
| `testkit version` | In phiên bản kit |

## Nhiều coding agent trong một dự án

| Chọn | Skill được đặt ở | Subagent được sinh ở |
|---|---|---|
| `claude` | `.claude/skills/` | `.claude/agents/*.md` |
| `codex` | `.agents/skills/` | `.codex/agents/*.toml` |
| `gemini` | `.agents/skills/` | `.gemini/agents/*.md` |
| `cursor` | `.claude/skills/` hoặc `.agents/skills/` (cái nào đã có) | Cursor tự đọc `.claude/agents/` và `.codex/agents/`; `.cursor/agents/` chỉ được tạo khi không chọn Claude Code hay Codex |
| `copilot` | như Cursor | `.github/agents/*.agent.md` |

Lưu ý:
- Claude Code chỉ đọc `.claude/skills/`, còn Codex chỉ đọc `.agents/skills/` (đã kiểm tra với Claude Code 2.1 và Codex CLI 0.168). Dùng cả hai thì mỗi skill có hai bản giống nhau. Cursor và Copilot đọc cả hai thư mục nên sẽ thấy mỗi skill hai lần.
- Gemini CLI và Codex chỉ nạp skill và agent của dự án khi thư mục dự án đã được đánh dấu tin cậy (trusted).
- Một số phiên bản Codex chỉ cho tạo sub-agent chung chung, không chọn được custom agent theo tên. Khi đó skill `testkit-run` tạo sub-agent chung và yêu cầu nó làm theo file vai trò, ví dụ `.codex/agents/test-lead.toml`.
- File subagent của các công cụ khác Claude Code được sinh từ `agents/*.md` trong kit. Muốn sửa vai trò thì sửa trong kit, không sửa file đã sinh.

## Cập nhật an toàn

- Chỉ những file có tên trong `.claude/.testkit-manifest` mới được cập nhật hoặc xóa. Nếu dự án đã có `.claude/agents/test-lead.md` của riêng bạn, `testkit init` giữ nguyên file đó và báo ra, trừ khi bạn dùng `--force`.
- File nào bản kit mới không còn ship thì được xóa khỏi dự án.
- `qa/` không bao giờ bị ghi đè. Dữ liệu test, bug và config của bạn được giữ nguyên.
- Nếu bạn sửa trực tiếp một file testkit quản lý, lần `update` sau sẽ ghi đè thay đổi đó. Muốn tùy biến lâu dài thì sửa trong repo kit của team.

## Lỗi thường gặp

- **`testkit: command not found` ngay sau khi cài**: mở terminal mới. Installer đã thêm thư mục vào PATH nhưng terminal cũ chưa nhận.
- **`npm install -g` báo EACCES trên Linux**: Node cài bằng apt ghi vào `/usr`. Dùng Node từ nvm (installer tự đề xuất), hoặc `npm config set prefix ~/.npm-global`.
- **`testkit doctor` báo phiên isolated thất bại**: kiểm tra Chrome đã cài chưa. Nếu Chrome nằm ở chỗ lạ, đặt `browser.chrome_path` trong `qa/config.yml` hoặc biến `TESTKIT_CHROME`. Trên Linux, Chromium bản snap chặn CDP; hãy cài Chrome bản `.deb` (xem `browser-use doctor --fix-snap`). Chạy `browser-use --doctor` để xem chi tiết.
- **Windows**: agent chạy `bu-session.sh` qua Git Bash, vốn có sẵn khi cài Claude Code trên Windows.
- **Windows ARM64**: `agent-browser` (không bắt buộc) chạy bản x64 qua giả lập.

## Publish trang cài đặt (cho người maintain kit)

Lệnh cài một dòng cần một trang tĩnh phục vụ các file sau:

| Đường dẫn | Nội dung |
|---|---|
| `/install.sh` | Installer cho macOS/Linux, đã gắn sẵn URL của trang |
| `/install.ps1` | Installer cho Windows |
| `/kit.tar.gz`, `/kit.zip` | Gói kit mà `testkit init` và `testkit update` tải về |
| `/version.txt` | Phiên bản kit |
| `/` | Trang giới thiệu có sẵn hai lệnh cài |

`scripts/build-site.sh` tạo các file này vào `public/`:

```bash
TESTKIT_BASE_URL=https://testkit.example.com ./scripts/build-site.sh
```

**Vercel** (đã có `vercel.json`): import repo hoặc chạy `vercel --prod`. Khi build trên Vercel, script tự lấy URL production từ `VERCEL_PROJECT_PRODUCTION_URL`. Nếu dùng domain riêng, đặt biến môi trường `TESTKIT_BASE_URL` trong project Vercel. Mỗi lần push lên nhánh production là trang và kit được cập nhật, và người dùng nhận bản mới ở lần `testkit init` hoặc `testkit update` kế tiếp.

**Host khác** (GitHub Pages, Cloudflare Pages, S3, nginx): chạy build script với `TESTKIT_BASE_URL` đúng domain rồi upload thư mục `public/`. Nên trả `install.sh` và `install.ps1` với `Content-Type: text/plain` và không cache lâu.

Vì kit được tải từ trang host chứ không phải từ GitHub, repo của kit có thể để private.

Muốn ra bản mới thì tăng `version` trong `.claude-plugin/plugin.json`, rồi build và deploy lại.
