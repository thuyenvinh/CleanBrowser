# CleanBrowser — Hướng dẫn cài đặt

Tài liệu này hướng dẫn 2 kịch bản phổ biến nhất:

- **[Phần 1: Chạy local](#phần-1--chạy-local)** — phát triển hoặc dùng cá nhân trên máy bạn.
- **[Phần 2: Deploy lên VPS](#phần-2--deploy-lên-vps-ubuntu-22042404)** — production cho team.

Xem [DEPLOYMENT.md](./DEPLOYMENT.md) cho danh sách env var đầy đủ và security checklist.

---

## Phần 1 — Chạy local

### Yêu cầu

- Docker Desktop hoặc Docker Engine 20.10+
- Docker Compose v2
- ~3 GB dung lượng (image + Postgres + CloakBrowser binary)
- ~512 MB RAM mỗi profile đang chạy

### Cách 1: Docker Compose (nhanh nhất, recommended)

```bash
# 1. Clone repo
git clone https://github.com/CloakHQ/CloakBrowser-Manager.git
cd CloakBrowser-Manager

# 2. Tạo file .env tối thiểu
cat > .env <<'EOF'
POSTGRES_PASSWORD=devpassword
JWT_SECRET=change-me-to-a-long-random-string-please
COOKIE_SECURE=false
EOF

# 3. Build + start (lần đầu mất ~10 phút tải base image + CloakBrowser binary)
docker compose up -d --build

# 4. Xem log để verify alembic migration chạy xong
docker compose logs -f manager
# Đợi đến khi thấy: "CloakBrowser Manager started"
# Ctrl+C để thoát log (container vẫn chạy)

# 5. Mở trình duyệt
xdg-open http://localhost:8080    # Linux
open http://localhost:8080         # macOS
start http://localhost:8080        # Windows
```

Lần đầu truy cập → trang Signup. Tạo tài khoản đầu tiên (sẽ tự tạo tenant + workspace + plan free).

**Dừng / khởi động lại:**

```bash
docker compose stop          # tạm dừng (giữ data)
docker compose start         # khởi động lại
docker compose down          # xoá container nhưng giữ volume data
docker compose down -v       # xoá cả data (cẩn thận!)
```

### Cách 2: Dev mode (backend + frontend tách riêng, hot reload)

Khi bạn đang sửa code:

```bash
# Terminal 1: Postgres trong docker
docker compose up -d postgres
export DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser

# Terminal 2: Backend với hot reload
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
JWT_SECRET=devkey uvicorn main:app --reload --port 8080

# Terminal 3: Frontend dev server
cd frontend
npm install
npm run dev
# Mở http://localhost:5173 (Vite dev server, tự proxy /api → :8080)
```

Frontend Vite dev server tự reload khi sửa `.tsx`. Backend uvicorn `--reload` tự restart khi sửa `.py`.

### Cách 3: Chạy production-like local

Giống VPS deploy nhưng trên máy bạn — hữu ích để test trước khi deploy thật:

```bash
# Tạo .env có đủ secret
cat > .env <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET=$(openssl rand -hex 32)
PROXY_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
COOKIE_SECURE=false
EOF

docker compose up -d --build
```

Sau đó test các flow: signup → tạo proxy → tạo profile → launch.

### Kiểm tra cài đặt thành công

```bash
# Health check
curl http://localhost:8080/api/status
# → {"running_count":0,"binary_version":"...","profiles_total":0}

# Database migration version
docker compose exec manager bash -c "cd /app/backend && alembic current"
# → 0018_add_marketplace (head)

# Postgres reachable
docker compose exec postgres psql -U cleanbrowser -d cleanbrowser -c "\dt"
# → liệt kê 20+ bảng
```

### Troubleshooting local

| Triệu chứng | Fix |
|---|---|
| `Connection refused` cổng 5432 khi chạy test | `docker compose up -d postgres` |
| Container `manager` crash sau khi build | `docker compose logs manager` — thường do `JWT_SECRET` empty hoặc `DATABASE_URL` sai |
| `Permission denied` trên `/data` | Kiểm tra volume mount; thử `docker compose down -v && docker compose up -d` |
| Profile launch lỗi `Firefox engine not installed` | Profile có `browser_type='firefox'` nhưng container chỉ có Chromium. `docker compose exec manager playwright install firefox` |
| Trình duyệt VNC trắng đen | Đợi 3-5s sau khi nhấn Launch, hoặc bấm Refresh |
| Login email/password không nhận | Kiểm tra `JWT_SECRET` đã set chưa; nếu vừa restart, session cũ invalid |

---

## Phần 2 — Deploy lên VPS (Ubuntu 22.04/24.04)

### Yêu cầu VPS

| Tier | RAM | vCPU | Disk | Phù hợp |
|---|---|---|---|---|
| Tối thiểu | 2 GB | 2 | 30 GB | 5–10 profile concurrent, demo / nhỏ |
| Khuyến nghị | 4 GB | 4 | 60 GB | 30–50 profile concurrent, team nhỏ |
| Production | 8 GB+ | 8+ | 100 GB+ SSD | 100+ profile, S3 cloud sync, automation chạy nhiều |

Provider gợi ý: Hetzner CX31 (€8/tháng), Vultr Cloud Compute 4GB ($24/tháng), DigitalOcean Droplet 4GB ($24/tháng), Linode 4GB ($24/tháng). Tại VN: Bizfly Cloud, VNG Cloud.

### Bước 1: Setup hệ điều hành

SSH vào VPS với user `root` hoặc sudo user:

```bash
# Update + install docker + git + caddy (reverse proxy)
apt-get update && apt-get upgrade -y
apt-get install -y curl git ufw

# Docker (script chính thức)
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# Tạo user riêng cho app
useradd -m -s /bin/bash cleanbrowser
usermod -aG docker cleanbrowser

# Firewall: chỉ mở 22 (ssh), 80, 443
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

### Bước 2: Clone repo + tạo .env production

```bash
su - cleanbrowser
git clone https://github.com/CloakHQ/CloakBrowser-Manager.git
cd CloakBrowser-Manager

# Tạo .env an toàn
cat > .env <<EOF
# --- Bắt buộc ---
POSTGRES_PASSWORD=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)
PROXY_ENCRYPTION_KEY=$(docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || openssl rand -base64 32 | head -c 44)
COOKIE_SECURE=true

# --- Optional: bật khi cần ---
# SMTP cho email verify
# SMTP_HOST=smtp.sendgrid.net
# SMTP_PORT=587
# SMTP_USER=apikey
# SMTP_PASSWORD=...
# SMTP_FROM=no-reply@yourdomain.com

# Stripe billing
# STRIPE_SECRET_KEY=sk_live_...
# STRIPE_WEBHOOK_SECRET=whsec_...

# VNPay (Việt Nam)
# VNPAY_TMN_CODE=...
# VNPAY_HASH_SECRET=...
# VNPAY_URL=https://sandbox.vnpayment.vn/paymentv2/vpcpay.html

# OAuth
# GOOGLE_OAUTH_CLIENT_ID=...
# GOOGLE_OAUTH_CLIENT_SECRET=...
# GITHUB_OAUTH_CLIENT_ID=...
# GITHUB_OAUTH_CLIENT_SECRET=...

# AI assistant
# ANTHROPIC_API_KEY=sk-ant-...

# S3 cloud sync cho profile snapshot
# STORAGE_BUCKET=cleanbrowser-prod
# STORAGE_REGION=us-east-1
# STORAGE_ACCESS_KEY=...
# STORAGE_SECRET_KEY=...

# Region (default 'local'; thêm khi có worker pod)
# WORKER_REGIONS=local,us,eu,sg,vn
EOF

chmod 600 .env
```

**Quan trọng:** lưu file `.env` này ở nơi an toàn (1Password, Bitwarden) — mất là mất hết.

### Bước 3: Bind container chỉ vào localhost

Sửa `docker-compose.yml` để container không expose ra ngoài (Caddy sẽ proxy):

```bash
# Mặc định đã là 127.0.0.1:8080 — verify
grep "127.0.0.1:8080" docker-compose.yml
# Nếu không có, sửa:
#   ports:
#     - "127.0.0.1:8080:8080"
```

### Bước 4: Build + start

```bash
docker compose up -d --build
docker compose logs -f manager
# Đợi đến khi thấy "CloakBrowser Manager started" (Ctrl+C thoát log)

# Sanity check
curl http://127.0.0.1:8080/api/status
# → JSON với running_count, version, total
```

### Bước 5: Setup HTTPS với Caddy (đơn giản nhất)

Caddy tự xin Let's Encrypt cert, auto-renew.

```bash
# Cài Caddy ngoài container (chạy ở host)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# Caddyfile
sudo tee /etc/caddy/Caddyfile <<'EOF'
yourdomain.com {
    reverse_proxy 127.0.0.1:8080 {
        # WebSocket support cho VNC + CDP
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-For {remote}
        header_up X-Forwarded-Proto {scheme}
    }
    encode gzip
    
    # Limit body size cho bulk CSV import (proxies)
    request_body {
        max_size 10MB
    }
    
    # Rate limit auth endpoints (cần plugin caddy-ratelimit; tùy chọn)
    # rate_limit {
    #     zone auth_limit {
    #         match path /api/auth/*
    #         events 10
    #         window 1m
    #     }
    # }
}
EOF

# Replace yourdomain.com bằng domain thật
sudo sed -i 's/yourdomain.com/cleanbrowser.example.com/g' /etc/caddy/Caddyfile

# DNS: trỏ A record của domain về IP VPS TRƯỚC bước này
# Caddy sẽ tự xin Let's Encrypt khi thấy traffic đầu tiên

sudo systemctl reload caddy
sudo systemctl enable caddy
```

Mở `https://yourdomain.com` → trang Signup → tạo tài khoản admin đầu tiên.

### Bước 6: Setup email (recommended)

Email verify + password reset cần SMTP. Provider phổ biến:

| Provider | Free tier | Setup |
|---|---|---|
| SendGrid | 100 mail/ngày | API key → `SMTP_USER=apikey, SMTP_PASSWORD=<key>` |
| Mailgun | 100 mail/ngày 30 ngày | SMTP credentials trong dashboard |
| AWS SES | 62k mail/tháng (free tier) | Verify domain → SMTP credentials |
| Resend | 100 mail/ngày | API key → SMTP relay |
| Postmark | 100 mail/tháng | SMTP credentials |

Sau khi có credentials, cập nhật `.env` rồi `docker compose restart manager`.

### Bước 7: Setup Stripe (nếu muốn thu tiền)

1. Tạo Stripe account → Dashboard → Products → tạo 4 plan tương ứng `starter`, `pro`, `team` (giá theo `plans` table seed).
2. Copy `price_id` của mỗi plan, update DB:
   ```bash
   docker compose exec postgres psql -U cleanbrowser -d cleanbrowser <<EOF
   UPDATE plans SET stripe_price_id = 'price_xxx_starter' WHERE id = 'starter';
   UPDATE plans SET stripe_price_id = 'price_xxx_pro'     WHERE id = 'pro';
   UPDATE plans SET stripe_price_id = 'price_xxx_team'    WHERE id = 'team';
   EOF
   ```
3. Dashboard → Developers → Webhooks → Add endpoint:
   - URL: `https://yourdomain.com/api/billing/webhook`
   - Events: `customer.subscription.*`, `invoice.*`
   - Copy webhook signing secret → `STRIPE_WEBHOOK_SECRET`
4. Copy Secret key → `STRIPE_SECRET_KEY`
5. `docker compose restart manager`

### Bước 8: Setup S3 cho cloud sync (recommended từ ~10 profile)

Snapshot user_data_dir mỗi lần stop để versioning + restore.

```bash
# AWS S3
aws s3 mb s3://cleanbrowser-prod --region us-east-1
aws s3api put-bucket-versioning --bucket cleanbrowser-prod \
  --versioning-configuration Status=Enabled

# Tạo IAM user với policy:
# {
#   "Version": "2012-10-17",
#   "Statement": [{
#     "Effect": "Allow",
#     "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
#     "Resource": ["arn:aws:s3:::cleanbrowser-prod","arn:aws:s3:::cleanbrowser-prod/*"]
#   }]
# }

# Update .env
echo "STORAGE_BUCKET=cleanbrowser-prod" >> .env
echo "STORAGE_REGION=us-east-1" >> .env
echo "STORAGE_ACCESS_KEY=AKIA..." >> .env
echo "STORAGE_SECRET_KEY=..." >> .env

docker compose restart manager
```

Hoặc tự host MinIO trên VPS riêng:

```bash
docker run -d --name minio -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=admin -e MINIO_ROOT_PASSWORD=$(openssl rand -hex 24) \
  -v minio-data:/data minio/minio server /data --console-address ":9001"

# .env:
# STORAGE_ENDPOINT=https://minio.yourdomain.com
# STORAGE_BUCKET=cleanbrowser
# STORAGE_ACCESS_KEY=admin
# STORAGE_SECRET_KEY=<rand>
```

### Bước 9: Backup tự động

Postgres dump hàng ngày, giữ 7 ngày, upload S3:

```bash
sudo tee /etc/cron.daily/cleanbrowser-backup <<'EOF'
#!/bin/bash
set -e
TS=$(date +%Y%m%d-%H%M%S)
DEST=/backup
mkdir -p $DEST

# Postgres dump
docker compose -f /home/cleanbrowser/CloakBrowser-Manager/docker-compose.yml \
  exec -T postgres pg_dump -U cleanbrowser cleanbrowser | gzip > $DEST/db-$TS.sql.gz

# Upload S3 (nếu có aws cli)
# aws s3 cp $DEST/db-$TS.sql.gz s3://cleanbrowser-backups/

# Xoá > 7 ngày
find $DEST -name "db-*.sql.gz" -mtime +7 -delete
EOF
sudo chmod +x /etc/cron.daily/cleanbrowser-backup
```

### Bước 10: Monitoring đơn giản

Healthcheck đã có sẵn trong Dockerfile + docker-compose. Để alert khi down:

**Uptime Kuma** (self-hosted):
```bash
docker run -d --name uptime-kuma -p 3001:3001 \
  -v uptime-kuma:/app/data louislam/uptime-kuma:1
```

Setup monitor type=HTTPS, URL=`https://yourdomain.com/api/status`, interval 60s. Notification qua Telegram/Discord/Email.

Hoặc dùng dịch vụ ngoài: UptimeRobot (free 50 monitor), BetterStack, Pingdom.

### Update CleanBrowser lên version mới

```bash
cd /home/cleanbrowser/CloakBrowser-Manager
git pull
docker compose up -d --build
# Alembic migration tự chạy trong entrypoint
docker compose logs -f manager | head -50
```

Đã có rollback path: `git checkout <prev-commit>` + `docker compose up -d --build` + chạy `alembic downgrade <prev-revision>` nếu cần.

### Restore từ backup

```bash
# Khôi phục DB
gunzip < /backup/db-20260516-030000.sql.gz | \
  docker compose exec -T postgres psql -U cleanbrowser -d cleanbrowser

# Khôi phục profile data: snapshot trên S3 vẫn còn — UI restore qua nút "Restore" trong version history
```

### Security checklist trước go-live

- [ ] `.env` permission `600` (chỉ owner đọc)
- [ ] `JWT_SECRET` random 32+ bytes
- [ ] `PROXY_ENCRYPTION_KEY` đã set (mất key = mất hết proxy encrypted)
- [ ] `COOKIE_SECURE=true`
- [ ] HTTPS hoạt động (curl `https://yourdomain.com` không cảnh báo cert)
- [ ] UFW chỉ mở 22/80/443
- [ ] SSH disable password login, chỉ key:
  ```bash
  sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
  sudo systemctl restart sshd
  ```
- [ ] Stripe webhook signing secret đúng (test bằng `stripe events resend`)
- [ ] Postgres backup chạy được (`sudo /etc/cron.daily/cleanbrowser-backup` test thủ công)
- [ ] DNS có A record + AAAA record (IPv6) trỏ về VPS
- [ ] Email gửi được (test signup → check inbox)
- [ ] Tài khoản admin đã có MFA TOTP

### Troubleshooting VPS

| Triệu chứng | Fix |
|---|---|
| Caddy không xin được cert | DNS chưa propagate, hoặc 80/443 bị firewall block. Kiểm tra `dig yourdomain.com` + `sudo journalctl -u caddy -n 50` |
| `502 Bad Gateway` từ Caddy | Container `manager` chưa boot xong. `docker compose logs manager`, đợi "started" |
| Out of memory khi nhiều profile chạy | Chỉnh `IDLE_REAPER_TIMEOUT_SECONDS=600` (10 phút) trong `.env`; upgrade RAM |
| Profile launch lỗi `proxy unavailable` | Proxy bị block / hết hạn. Test riêng trong tab Proxies → bấm Test |
| Stripe webhook không nhận | Dashboard → Developers → Webhooks → xem failed events. Thường do `STRIPE_WEBHOOK_SECRET` sai hoặc body không khớp (do reverse proxy strip header) |
| Cloud snapshot không upload | `docker compose logs manager | grep snapshot` — kiểm tra `STORAGE_BUCKET` + IAM permission |
| Disk full | `docker system prune -af` + xoá `/data/snapshots/*` cũ (đã có trên S3) |

---

## Tham khảo thêm

- [README](../README.md) — overview tính năng
- [ARCHITECTURE.md](./ARCHITECTURE.md) — kiến trúc + roadmap
- [DEPLOYMENT.md](./DEPLOYMENT.md) — reference env var đầy đủ + security checklist
