# Hướng dẫn chạy CleanBrowser trên Windows

Có 2 lối:

- **Lối A — WSL2 + Docker Desktop** (khuyên dùng): mượt nhất, KasmVNC + Chromium chạy ổn định trong Linux container.
- **Lối B — Native Windows** (dành cho dev backend Python thuần): chạy backend/Postgres trực tiếp trên Windows; **không** chạy được tính năng launch browser profile (KasmVNC chỉ chạy Linux).

> Lối B chỉ dùng cho phát triển API/UI; nếu cần test launch profile, dùng Lối A.

---

## Yêu cầu chung

| Thành phần | Phiên bản | Ghi chú |
|---|---|---|
| Windows | 10 21H2 / 11 | Cần WSL2 |
| RAM | ≥ 8 GB | WSL2 + Docker mặc định 50% RAM |
| Disk | ≥ 15 GB free | WSL distro + Docker image |
| CPU | x86_64 + virtualization | Bật Intel VT-x / AMD-V trong BIOS |

---

## Lối A — WSL2 + Docker Desktop

### A.1 Cài WSL2 + Ubuntu

Mở **PowerShell** as Administrator:

```powershell
# Bật WSL + Virtual Machine Platform
wsl --install -d Ubuntu-22.04

# Restart máy nếu lần đầu cài
# Sau khi restart, terminal Ubuntu mở ra → tạo username + password Linux
```

Kiểm tra:
```powershell
wsl --status         # phải hiển thị Default Version: 2
wsl -l -v            # phải hiển thị Ubuntu-22.04   Running   2
```

### A.2 Cài Docker Desktop

1. Tải [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) — phiên bản 4.30+.
2. Cài đặt, chọn **Use WSL 2 instead of Hyper-V** khi được hỏi.
3. Mở Docker Desktop → **Settings → Resources → WSL Integration** → bật cho `Ubuntu-22.04`.
4. Apply & Restart.

Kiểm tra trong PowerShell hoặc terminal Ubuntu:
```bash
docker --version
docker compose version
```

### A.3 Clone repo (trong Ubuntu WSL)

> **Quan trọng**: clone vào filesystem WSL (`~`), KHÔNG clone vào `/mnt/c/...` — performance kém + permission xung đột.

```bash
# Trong terminal Ubuntu WSL
cd ~
git clone <repo-url> CleanBrowser
cd CleanBrowser
```

### A.4 Tạo `.env`

```bash
# Trong terminal Ubuntu WSL
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d /=+)
JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
PROXY_KEY=$(python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

cat > .env <<EOF
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
JWT_SECRET=${JWT_SECRET}
PROXY_ENCRYPTION_KEY=${PROXY_KEY}
APP_ENV=development
COOKIE_SECURE=false
EOF
chmod 600 .env
```

> Compose template **fail closed** nếu thiếu `POSTGRES_PASSWORD` / `JWT_SECRET` (rào chắn từ security review).

### A.5 Khởi động

```bash
docker compose up -d --build
docker compose logs -f manager
# Đợi đến khi thấy "CloakBrowser Manager started" → Ctrl+C
```

Lần đầu mất 10–20 phút (tải image base, build frontend, KasmVNC + CloakBrowser binary).

### A.6 Truy cập

Mở **Edge / Chrome trên Windows** → `http://localhost:8080`.

Docker Desktop tự forward port WSL ↔ Windows; bạn không cần làm gì thêm.

### A.7 Seed admin (tùy chọn)

```bash
docker compose exec manager bash -c '
  DATABASE_URL=postgresql://cleanbrowser:${POSTGRES_PASSWORD}@postgres:5432/cleanbrowser \
  SEED_EMAIL=admin@yourdomain.com \
  SEED_PASSWORD="ChangeMeStrong-123!" \
  python -m scripts.seed_admin
'
```

### A.8 Stop / restart / xoá

```bash
docker compose stop                # giữ container + volume
docker compose down                # xoá container, giữ volume DB
docker compose down -v             # xoá tất cả (mất dữ liệu)
git pull && docker compose up -d --build   # update code
```

---

## Lối B — Native Windows (chỉ backend dev)

> Chỉ dùng cho phát triển API/UI. **KHÔNG** launch được browser profile vì KasmVNC chỉ chạy Linux.

### B.1 Cài Python 3.12

1. Tải [Python 3.12 từ python.org](https://www.python.org/downloads/windows/).
2. Khi cài, tick **Add python.exe to PATH**.
3. Verify: PowerShell → `python --version` → `Python 3.12.x`.

### B.2 Cài Node 20 + npm

Tải [Node.js LTS 20 từ nodejs.org](https://nodejs.org/) và cài. Verify:
```powershell
node --version    # v20.x
npm --version
```

### B.3 Cài Postgres 16

1. Tải [PostgreSQL 16 Windows installer](https://www.postgresql.org/download/windows/).
2. Cài với password superuser dễ nhớ (lưu lại — sẽ dùng tạm).
3. Cho phép port 5432.
4. Verify trong PowerShell:
   ```powershell
   & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "SELECT version()"
   ```

Tạo user + DB:
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE USER cleanbrowser WITH PASSWORD 'devpassword'"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE cleanbrowser OWNER cleanbrowser"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE cleanbrowser TO cleanbrowser"
```

### B.4 Cài Git + clone repo

Cài [Git for Windows](https://git-scm.com/download/win), sau đó trong PowerShell:
```powershell
cd $HOME
git clone <repo-url> CleanBrowser
cd CleanBrowser
```

### B.5 Tạo virtualenv + cài Python deps

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Nếu PowerShell báo "execution policy", chạy 1 lần:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

> Nếu pip báo lỗi build `psycopg2-binary` hoặc `cryptography`, cài [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (chọn workload "C++ build tools").

### B.6 Run Alembic migration

```powershell
$env:DATABASE_URL = "postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser"
cd backend
alembic upgrade head
cd ..
```

Verify:
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U cleanbrowser -d cleanbrowser `
  -h localhost -c "SELECT version_num FROM alembic_version"
# Kỳ vọng: 0031_platform_admin (hoặc mới hơn)
```

### B.7 Build frontend

```powershell
cd frontend
npm ci
npm run build
cd ..
```

### B.8 Tạo `.env.local` cho backend

Tạo file `.env.local` ở thư mục gốc repo với nội dung:
```ini
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser
JWT_SECRET=dev-secret-change-me-for-production
APP_ENV=development
COOKIE_SECURE=false
RATE_LIMIT_ENABLED=true
```

### B.9 Chạy backend

PowerShell 1 (backend):
```powershell
.\.venv\Scripts\Activate.ps1
Get-Content .env.local | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
  }
}
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
```

Verify trong PowerShell 2:
```powershell
curl http://localhost:8080/api/status/public
```

### B.10 (Tùy chọn) Frontend dev với hot-reload

PowerShell 2:
```powershell
cd frontend
npm run dev    # http://localhost:5173 (vite proxy /api -> :8080)
```

### B.11 Seed admin

```powershell
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser"
$env:SEED_EMAIL = "admin@yourdomain.com"
$env:SEED_PASSWORD = "ChangeMeStrong-123!"
python -m scripts.seed_admin
```

### B.12 (Tùy chọn) E2E test trên Windows

```powershell
cd tests/e2e
npm install
npx playwright install --with-deps chromium

# Khởi động backend với AUTH_TOKEN + JWT_SECRET ở PowerShell khác:
#   $env:AUTH_TOKEN="force-auth"; $env:JWT_SECRET="dev-secret";
#   $env:RATE_LIMIT_ENABLED="false";
#   python -m uvicorn backend.main:app --port 8080

$env:E2E_BASE_URL = "http://localhost:8080"
npx playwright test
```

---

## Truy cập từ máy khác trong LAN

Mặc định compose chỉ bind localhost. Để mở ra LAN:

```yaml
# docker-compose.yml (Lối A)
ports:
  - "0.0.0.0:8080:8080"
```

Native (Lối B):
```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080
# Mở Windows Firewall cho port 8080:
New-NetFirewallRule -DisplayName "CleanBrowser 8080" -Direction Inbound `
  -LocalPort 8080 -Protocol TCP -Action Allow
```

> Khi mở public, **bắt buộc** `APP_ENV=production`, HTTPS phía trước, `COOKIE_SECURE=true`.

---

## Troubleshooting

### "wsl --install" báo "The Windows Subsystem for Linux has no installed distributions"
Restart máy sau lệnh `wsl --install`. Nếu vẫn lỗi, mở **Turn Windows features on/off** → tick "Virtual Machine Platform" + "Windows Subsystem for Linux".

### Docker Desktop không start — "WSL 2 installation is incomplete"
Tải [WSL2 Linux kernel update](https://learn.microsoft.com/windows/wsl/install-manual) và cài thủ công.

### Performance WSL2 chậm khi clone vào `/mnt/c/...`
Đây là filesystem mount cross-OS — luôn chậm. Chuyển repo vào `~` trong WSL.

### Port 8080 đã chiếm
```powershell
netstat -ano | findstr :8080
# Tìm PID, kill bằng:
Stop-Process -Id <PID> -Force
```

### Backend báo "Refusing to start: insecure production configuration"
Bạn đặt `APP_ENV=production` mà thiếu `JWT_SECRET` hoặc `COOKIE_SECURE=true`. Xem thông báo lỗi liệt kê cái nào thiếu. Dev mode dùng `APP_ENV=development`.

### Native backend (Lối B) không launch được browser profile
Tính năng KasmVNC chỉ chạy Linux container. Bạn cần Lối A (Docker) cho phần này — hoặc setup WSL2 + chạy backend trong WSL Ubuntu (thay vì PowerShell).

### Lỗi `psycopg2-binary` build wheel khi pip install
Cài [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/), workload "C++ build tools". Sau đó `pip install psycopg2-binary` lại.

### PowerShell không activate được venv — "execution policy"
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Đăng nhập trên trình duyệt báo "Sign in" nhưng login đúng password
- Đảm bảo truy cập `http://localhost:8080`, không phải `127.0.0.1`
- Xoá cookie cũ của domain (DevTools → Application → Cookies)
- Kiểm tra log backend xem có error trong middleware `CsrfOriginMiddleware` không

### Trình duyệt báo "Cross-origin request rejected"
Bạn truy cập từ một domain khác nhưng `Host` header ≠ `Origin`. Đặt reverse proxy đúng để forward `Host` header gốc, hoặc trong dev dùng cùng origin (`localhost:8080`).

### Quên password admin (Lối A)
```bash
# Trong WSL Ubuntu
docker compose exec manager bash -c '
  DATABASE_URL=postgresql://cleanbrowser:${POSTGRES_PASSWORD}@postgres:5432/cleanbrowser \
  python -c "
from backend import db_auth
from backend.middleware_rls import system_context
with system_context():
    db_auth.update_user_password_by_id(\"<user_id>\", \"NewStrong-123!\")
"
'
```

### Quên password admin (Lối B)
```powershell
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser"
python -c @"
from backend import db_auth
from backend.middleware_rls import system_context
with system_context():
    db_auth.update_user_password_by_id('<user_id>', 'NewStrong-123!')
"@
```

---

## Đường dẫn quan trọng

| Mục đích | Path Lối A (WSL/Docker) | Path Lối B (native) |
|---|---|---|
| Repo | `~/CleanBrowser` trong WSL | `%USERPROFILE%\CleanBrowser` |
| `.env` | `~/CleanBrowser/.env` | `%USERPROFILE%\CleanBrowser\.env.local` |
| Backend log | `docker compose logs -f manager` | stdout uvicorn |
| Postgres data | Docker volume `postgres_data` | `C:\Program Files\PostgreSQL\16\data` |
| Profile data | `~/.cloakbrowser-manager` trong WSL | n/a (không launch được) |
| Migration | `backend/alembic/versions/` | `backend\alembic\versions\` |
| Seed script | `scripts/seed_admin.py` | `scripts\seed_admin.py` |

Đọc thêm: [`SECURITY.md`](../SECURITY.md), [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md), [`docs/DEPLOYMENT.md`](./DEPLOYMENT.md), [`docs/SETUP_UBUNTU.md`](./SETUP_UBUNTU.md) (nếu bạn chuyển sang VPS Linux).
