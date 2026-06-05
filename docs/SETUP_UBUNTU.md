# Hướng dẫn chạy CleanBrowser trên Ubuntu

Áp dụng cho Ubuntu 22.04 / 24.04 LTS. Có 2 lối chạy:

- **Lối A — Docker Compose** (khuyên dùng): 1 lệnh, không cần cài Python/Postgres trên host.
- **Lối B — Native** (dành cho dev): chạy backend/frontend trực tiếp trên host để debug, hot-reload.

---

## Yêu cầu chung

| Thành phần | Phiên bản | Ghi chú |
|---|---|---|
| Ubuntu | 22.04 / 24.04 | 20.04 chạy được nhưng phải build từ source nhiều dep |
| RAM | ≥ 4 GB free | Mỗi profile browser ~500 MB |
| Disk | ≥ 10 GB | Image + Postgres data + cloakbrowser binary |
| CPU | x86_64 hoặc arm64 | KasmVNC + Chromium đều hỗ trợ cả 2 |

---

## Lối A — Docker Compose

### A.1 Cài Docker + Docker Compose v2

```bash
# Gỡ phiên bản cũ nếu có
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Cài Docker CE chính thức
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Cho user hiện tại chạy docker không cần sudo (đăng xuất + đăng nhập lại để apply)
sudo usermod -aG docker $USER
newgrp docker
```

Kiểm tra: `docker --version && docker compose version`.

### A.2 Clone + tạo `.env`

```bash
git clone <repo-url> CleanBrowser
cd CleanBrowser

# Sinh secrets ngẫu nhiên
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d /=+)
JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
PROXY_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null \
            || python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

cat > .env <<EOF
# --- Bắt buộc (compose sẽ fail closed nếu thiếu) ---
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
JWT_SECRET=${JWT_SECRET}

# --- Khuyên dùng ---
PROXY_ENCRYPTION_KEY=${PROXY_KEY}
APP_ENV=development
COOKIE_SECURE=false

# --- Bật khi deploy production ---
# APP_ENV=production
# COOKIE_SECURE=true
# RATE_LIMIT_STORAGE_URI=redis://redis:6379
EOF
chmod 600 .env
```

> **Lưu ý**: Compose template (`docker-compose.yml`) refuse start nếu `POSTGRES_PASSWORD` hoặc `JWT_SECRET` không set — đây là rào chắn từ security review C-01/H-01/H-07.

### A.3 Khởi động

```bash
# Build + run nền
docker compose up -d --build

# Theo dõi log đến khi thấy "CloakBrowser Manager started"
docker compose logs -f manager
# Ctrl+C thoát log (container vẫn chạy)
```

Lần đầu mất 5–15 phút (kéo image base, build frontend, tải KasmVNC + CloakBrowser binary).

### A.4 Tạo tài khoản

Mở `http://localhost:8080` → trang signup. Tài khoản đầu tiên tự tạo:
- 1 tenant tên = phần trước `@` của email
- 1 workspace `Default`, role `owner`
- 1 subscription `Pro` trạng thái `trialing` 14 ngày (free trial)

### A.5 Bootstrap platform-admin (tùy chọn)

Nếu muốn 1 user quản lý tất cả tenant (moderate marketplace, disable user xấu, list cross-tenant):

```bash
docker compose exec manager bash -c '
  DATABASE_URL=postgresql://cleanbrowser:${POSTGRES_PASSWORD}@postgres:5432/cleanbrowser \
  SEED_EMAIL=admin@yourdomain.com \
  SEED_PASSWORD="ChangeMeStrong-123!" \
  python -m scripts.seed_admin
'
```

Sau đó admin có thể gọi `GET /api/admin/tenants`, `GET /api/admin/users`, `POST /api/admin/users/{id}/disable`, …

### A.6 Tắt / cập nhật / xoá

```bash
docker compose down                    # stop + xoá container, giữ volume DB
docker compose down -v                 # stop + XOÁ volume DB (mất sạch dữ liệu)
git pull && docker compose up -d --build   # cập nhật code mới
```

---

## Lối B — Native (dev mode)

Dùng khi bạn cần hot-reload backend/frontend, đặt breakpoint, hoặc chạy test suite.

### B.1 Cài dependencies hệ thống

```bash
sudo apt-get update
sudo apt-get install -y \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    nodejs npm \
    postgresql-16 postgresql-contrib \
    build-essential libpq-dev \
    git curl xclip \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdbus-1-3 libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2

# Nếu Ubuntu < 24.04 chưa có Node 20:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### B.2 Postgres setup

```bash
# Postgres 16 đã auto-start sau khi cài. Kiểm tra:
sudo systemctl status postgresql
sudo -u postgres psql -c "SELECT version()"

# Tạo user + DB
sudo -u postgres psql <<'SQL'
CREATE USER cleanbrowser WITH PASSWORD 'devpassword';
CREATE DATABASE cleanbrowser OWNER cleanbrowser;
GRANT ALL PRIVILEGES ON DATABASE cleanbrowser TO cleanbrowser;
SQL
```

### B.3 Clone + cài Python deps

```bash
git clone <repo-url> CleanBrowser
cd CleanBrowser

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

# Chrome dependencies cho CloakBrowser (chạy script tự động của Playwright)
pip install playwright
playwright install-deps chromium
pip uninstall -y playwright   # gỡ Playwright Python, nhưng giữ deps đã apt-install
```

### B.4 Run Alembic migration

```bash
cd backend
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  alembic upgrade head
cd ..
```

Verify: `alembic_version` đã đến revision mới nhất:
```bash
PGPASSWORD=devpassword psql -h localhost -U cleanbrowser -d cleanbrowser \
  -c "SELECT version_num FROM alembic_version"
# Kỳ vọng: 0031_platform_admin (hoặc mới hơn)
```

### B.5 Build frontend

```bash
cd frontend
npm ci
npm run build
cd ..
```

Backend sẽ serve trực tiếp từ `frontend/dist` qua route catch-all.

### B.6 Tạo `.env.local` cho backend

```bash
cat > .env.local <<'EOF'
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser
JWT_SECRET=dev-secret-change-me-for-production
PROXY_ENCRYPTION_KEY=
APP_ENV=development
COOKIE_SECURE=false
RATE_LIMIT_ENABLED=true
# Để rỗng AUTH_TOKEN: middleware sẽ bypass legacy guard
# AUTH_TOKEN=
EOF
```

> Lưu ý dev mode: `JWT_SECRET` không bắt buộc cũng được — backend sẽ sinh secret tạm và log cảnh báo (session mất khi restart). Nhưng `APP_ENV=production` thì bắt buộc — `_assert_production_safety` sẽ raise nếu thiếu.

### B.7 Chạy backend (terminal 1)

```bash
source .venv/bin/activate
set -a; source .env.local; set +a
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
```

Verify: `curl http://localhost:8080/api/status/public` → 200.

### B.8 Chạy frontend dev (terminal 2, tùy chọn)

Backend đã serve frontend đã build. Chỉ chạy vite dev khi bạn muốn hot-reload UI:

```bash
cd frontend
npm run dev    # http://localhost:5173
```

Vite proxy `/api/*` → `http://localhost:8080` (đã cấu hình sẵn trong `vite.config.ts`).

### B.9 Seed admin

```bash
source .venv/bin/activate
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  SEED_EMAIL=admin@yourdomain.com \
  SEED_PASSWORD='ChangeMeStrong-123!' \
  python -m scripts.seed_admin
```

### B.10 Chạy test suite

```bash
# Backend unit/integration (pytest)
source .venv/bin/activate
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  pytest backend/tests

# Frontend unit (vitest)
cd frontend && npm test && cd ..

# E2E Playwright (cần backend đang chạy + AUTH_TOKEN để force auth flow)
cd tests/e2e
npm install
npx playwright install --with-deps chromium
# Backend phải khởi động với AUTH_TOKEN + JWT_SECRET:
#   AUTH_TOKEN=force-auth JWT_SECRET=dev-secret RATE_LIMIT_ENABLED=false \
#     python -m uvicorn backend.main:app --port 8080
E2E_BASE_URL=http://localhost:8080 npx playwright test
```

---

## Truy cập từ máy khác trong LAN

Mặc định compose chỉ bind `127.0.0.1:8080` (an toàn). Để mở ra LAN:

```yaml
# docker-compose.yml
ports:
  - "0.0.0.0:8080:8080"   # hoặc xoá "127.0.0.1:" thành "8080:8080"
```

Native mode:
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

> Nếu mở public, **bắt buộc** đặt `APP_ENV=production`, dựng HTTPS phía trước (caddy/nginx) và `COOKIE_SECURE=true`.

---

## Troubleshooting

### Backend không khởi động — "DATABASE_URL environment variable is required"
Bạn quên `set -a; source .env.local; set +a` (Lối B) hoặc compose chưa đọc `.env` (Lối A — file phải nằm cùng thư mục `docker-compose.yml`).

### "Refusing to start: insecure production configuration"
Đặt `APP_ENV=production` mà thiếu `JWT_SECRET`, `COOKIE_SECURE=true`, hoặc dùng `RATE_LIMIT_STORAGE_URI=memory://`. Xem message lỗi — `_assert_production_safety` liệt kê chính xác cái nào thiếu.

### `psycopg2.OperationalError: Connection refused`
Postgres chưa start. `sudo systemctl start postgresql` (native) hoặc `docker compose up -d postgres` (compose).

### "POSTGRES_PASSWORD must be set"
Compose template fail-closed; tạo `.env` cùng thư mục với `docker-compose.yml`.

### Trình duyệt báo "Sign in" nhưng login đúng password
Cookie session `samesite=lax` không gửi với HTTP cross-port. Đảm bảo truy cập đúng `http://localhost:8080` (không phải `127.0.0.1`) và để cookie samesite mặc định.

### E2E test bị 403 "Cross-origin request rejected"
Playwright APIRequestContext gửi `Origin: null`. CSRF middleware coi `null` như missing — phải dùng phiên bản `backend/main.py` ≥ commit `2b917e9`. Update code.

### Container chạy quá chậm — first start mất 15 phút+
Phần lâu nhất là `playwright install-deps chromium` + tải KasmVNC binary. Lần build sau sẽ cache lại.

### Browser profile không launch — "DISPLAY not set"
KasmVNC chạy trong container — nếu chạy Lối B native, bạn cần cài `kasmvncserver` và `xvfb` thủ công. Khuyến nghị dùng compose cho path này.

### Quên password admin
```bash
# Native
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  python -c "
from backend import db_auth
from backend.middleware_rls import system_context
with system_context():
    db_auth.update_user_password_by_id('<user_id>', 'NewStrongPassword-123')
"
# Sau đó re-seed sẽ flip lại is_platform_admin nếu cần.
```

---

## Đường dẫn quan trọng

| Mục đích | Path |
|---|---|
| Backend log (compose) | `docker compose logs -f manager` |
| Backend log (native) | stdout của uvicorn |
| Postgres data (compose) | volume `postgres_data` |
| Postgres data (native) | `/var/lib/postgresql/16/main` |
| Profile data | `~/.cloakbrowser-manager` (compose) hoặc `/data` (container internal) |
| Frontend build | `frontend/dist/` |
| Migration | `backend/alembic/versions/` |
| Seed admin script | `scripts/seed_admin.py` |
| Env mẫu | mục A.2 ở trên |

Đọc thêm: [`SECURITY.md`](../SECURITY.md), [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md), [`docs/DEPLOYMENT.md`](./DEPLOYMENT.md).
