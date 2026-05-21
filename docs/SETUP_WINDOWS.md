# CleanBrowser — Cài đặt trên Windows

Hướng dẫn dành riêng cho máy Windows 10/11. Vì backend chạy Chromium + KasmVNC (Linux-only), trên Windows bắt buộc dùng **Docker Desktop với backend WSL2**.

Có 2 kịch bản:
- **[Cách 1: Docker Desktop](#cách-1--docker-desktop-recommended)** — nhanh nhất, dùng được luôn (~15 phút).
- **[Cách 2: Dev mode trong WSL2](#cách-2--dev-mode-trong-wsl2-cho-người-sửa-code)** — sửa code, hot reload.

> Để xem hướng dẫn Linux/Mac/VPS chi tiết, xem [SETUP.md](./SETUP.md).

---

## Yêu cầu chung

- Windows 10 version 2004+ hoặc Windows 11
- ~8 GB RAM (khuyến nghị 16 GB nếu chạy nhiều profile)
- ~10 GB ổ cứng trống
- Quyền Administrator để cài Docker + WSL2

---

## Cách 1 — Docker Desktop (recommended)

### Bước 1: Cài WSL2 + Docker Desktop

1. **Bật WSL2** (PowerShell mở dưới quyền Admin):
   ```powershell
   wsl --install
   ```
   → Restart máy khi prompt.

2. **Tải Docker Desktop** từ <https://www.docker.com/products/docker-desktop/> → cài → tick "Use WSL 2 instead of Hyper-V" lúc install.

3. **Khởi động Docker Desktop** từ Start menu. Đợi icon trên taskbar (cá voi xanh) chuyển sang trạng thái Running.

4. Kiểm tra trong PowerShell:
   ```powershell
   docker --version
   docker compose version
   ```
   Cả 2 phải trả về version 20.10+ và v2.x+.

### Bước 2: Cài Git + Clone repo

1. Tải Git for Windows từ <https://git-scm.com/download/win> → cài với mặc định.

2. Mở **Git Bash** (Start menu → "Git Bash") và clone:
   ```bash
   cd /c/Users/$USER/Documents
   git clone https://github.com/CloakHQ/CloakBrowser-Manager.git
   cd CloakBrowser-Manager
   ```

   > Hoặc dùng **PowerShell** nếu thoải mái hơn — các lệnh `git`/`docker compose` hoạt động giống.

### Bước 3: Tạo file .env

Trong Git Bash (vì lệnh `openssl` có sẵn):

```bash
cat > .env <<EOF
POSTGRES_PASSWORD=devpassword
JWT_SECRET=$(openssl rand -hex 32)
PROXY_ENCRYPTION_KEY=$(openssl rand -base64 32 | head -c 44)
COOKIE_SECURE=false
EOF
```

Nếu dùng PowerShell:

```powershell
@"
POSTGRES_PASSWORD=devpassword
JWT_SECRET=$(-join ((48..57) + (97..122) | Get-Random -Count 64 | % {[char]$_}))
PROXY_ENCRYPTION_KEY=$(-join ((48..57) + (97..122) | Get-Random -Count 44 | % {[char]$_}))
COOKIE_SECURE=false
"@ | Out-File -Encoding ASCII .env
```

### Bước 4: Build + start

```bash
docker compose up -d --build
```

> Lần đầu mất **~15-20 phút** vì tải base image (Node, Python, KasmVNC, ttf-mscorefonts) + CloakBrowser binary. Bạn có thể đi pha cốc cà phê. ☕

Xem log để verify migration chạy xong:

```bash
docker compose logs -f manager
```

Đợi đến khi thấy:
```
INFO: CloakBrowser Manager started
```

Ctrl+C để thoát log (container vẫn chạy nền).

### Bước 5: Mở trình duyệt

Mở Chrome/Edge/Firefox và truy cập:

```
http://localhost:8080
```

Lần đầu → trang **Signup**. Tạo tài khoản → tự tạo tenant + workspace + free plan. Sau đó:

1. **Tạo profile mới** → chọn fingerprint, region, proxy (optional)
2. Nhấn **Launch** → đợi 5-10s → VNC iframe hiển thị browser bên trong
3. Thử mở `https://creepjs.com` để kiểm tra fingerprint isolation

### Bước 6: Dừng / khởi động lại

```bash
# Tạm dừng (giữ data)
docker compose stop

# Chạy lại
docker compose start

# Xoá container (giữ data trong volume)
docker compose down

# XOÁ TẤT CẢ (kể cả data — cẩn thận!)
docker compose down -v
```

### Bước 7: Update lên version mới

```bash
cd /c/Users/$USER/Documents/CloakBrowser-Manager
git pull
docker compose up -d --build
```

Alembic migration tự chạy trong entrypoint.

---

## Cách 2 — Dev mode trong WSL2 (cho người sửa code)

Hot reload backend Python + frontend Vite. Yêu cầu WSL2 Ubuntu vì CloakBrowser binary là Linux ELF.

### Bước 1: Cài Ubuntu trong WSL2

```powershell
wsl --install -d Ubuntu-22.04
```

Mở Ubuntu từ Start menu, tạo username + password đầu tiên.

### Bước 2: Cài Python + Node + Docker (trong Ubuntu)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip git curl

# Node 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verify
python3 --version    # → 3.12.x
node --version        # → v20.x
```

Docker Desktop từ Windows đã expose `docker` command vào WSL2 — không cần cài lại.

### Bước 3: Clone repo trong WSL2

```bash
cd ~
git clone https://github.com/CloakHQ/CloakBrowser-Manager.git
cd CloakBrowser-Manager
```

> File trong WSL2 nằm ở đường dẫn Windows `\\wsl$\Ubuntu-22.04\home\<user>\CloakBrowser-Manager`. VS Code có extension "WSL" cho phép edit từ Windows trực tiếp.

### Bước 4: Start Postgres trong Docker

```bash
docker compose up -d postgres
```

### Bước 5: Backend dev (Terminal 1 trong Ubuntu)

```bash
cd ~/CloakBrowser-Manager/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Migrate
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  alembic upgrade head

# Run với hot reload
JWT_SECRET=devkey \
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  uvicorn main:app --reload --port 8080
```

### Bước 6: Frontend dev (Terminal 2 trong Ubuntu)

```bash
cd ~/CloakBrowser-Manager/frontend
npm install
npm run dev
```

Vite sẽ chạy trên `http://localhost:5173` và tự proxy `/api/*` về backend `:8080`.

Mở Chrome/Edge ở Windows → `http://localhost:5173`.

### Bước 7: Run tests

```bash
# Backend (terminal 3)
cd ~/CloakBrowser-Manager
DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser \
  pytest backend/tests

# Frontend
cd frontend
npx vitest run
```

---

## Troubleshooting Windows

| Triệu chứng | Fix |
|---|---|
| `WSL 2 installation is incomplete` khi mở Docker Desktop | Update WSL: `wsl --update` (PowerShell admin), restart. |
| Docker Desktop ngốn nhiều RAM | Settings → Resources → giảm RAM limit (4-6 GB đủ). |
| `localhost:8080` không truy cập được | Kiểm tra container chạy: `docker compose ps`. Nếu manager Exit, xem `docker compose logs manager`. |
| `connect ECONNREFUSED 127.0.0.1:5432` khi dev mode | Postgres chưa lên. `docker compose up -d postgres` rồi thử lại. |
| Build Docker lần đầu **rất chậm** | Bình thường vì tải KasmVNC + CloakBrowser binary. Subsequent build chạy qua cache, < 1 phút. |
| `python3.12: command not found` trong Ubuntu cũ | `sudo apt install software-properties-common; sudo add-apt-repository ppa:deadsnakes/ppa; sudo apt install python3.12 python3.12-venv` |
| VNC trắng đen khi Launch profile | Đợi 5-10s sau khi nhấn Launch. Browser cần boot trước. |
| Tài liệu Vietnamese hiển thị lỗi font trong PowerShell | Dùng Windows Terminal thay vì PowerShell cổ điển. |
| File `.env` báo lỗi khi `docker compose` đọc | Đảm bảo encoding là ASCII / UTF-8 không BOM. Trong PowerShell: `Out-File -Encoding ASCII`. |
| Mất kết nối WSL2 sau khi update Windows | `wsl --shutdown` rồi mở lại. |
| Cần expose ra internet để chia sẻ | Trong PowerShell admin: `netsh interface portproxy add v4tov4 listenport=8080 connectport=8080 connectaddress=127.0.0.1` + mở firewall port 8080. Production khuyến nghị deploy lên VPS thay vì máy cá nhân (xem [SETUP.md](./SETUP.md)). |

---

## Lệnh tiện ích Windows

```bash
# Xem container đang chạy
docker compose ps

# Tail log
docker compose logs -f manager

# Exec vào container manager
docker compose exec manager bash

# Postgres CLI
docker compose exec postgres psql -U cleanbrowser -d cleanbrowser

# Reset toàn bộ
docker compose down -v && docker compose up -d --build
```

---

## Khi nào cần dùng Cách 2 (WSL dev)?

- Đang sửa code Python (backend) hoặc TypeScript (frontend) — cần hot reload.
- Chạy unit tests trước khi commit.
- Debug step-by-step với debugger Python.

**Bình thường (chỉ dùng để chạy + tạo profile), Cách 1 Docker Desktop là đủ.**

---

## Tài liệu khác

- [SETUP.md](./SETUP.md) — Linux/Mac/VPS quickstart + deployment chi tiết.
- [DEPLOYMENT.md](./DEPLOYMENT.md) — Env var reference + security checklist (Stripe, OAuth, SMTP, S3, ClickHouse).
- [ARCHITECTURE.md](./ARCHITECTURE.md) — Kiến trúc + roadmap.
- [HANDOFF.md](./HANDOFF.md) — Bàn giao tổng quan.
