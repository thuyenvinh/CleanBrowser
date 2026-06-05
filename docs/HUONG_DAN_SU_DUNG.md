# HƯỚNG DẪN SỬ DỤNG HỆ THỐNG

**CleanBrowser — Trình duyệt ẩn danh dành cho team**

> Ghi chú trước khi đọc: tài liệu này được biên soạn dựa trên mã nguồn, thiết kế giao diện và mô tả AI tích hợp. **Không có ảnh chụp giao diện và video thao tác được cung cấp** tại thời điểm viết. Mô tả vị trí nút và bố cục dựa trên cấu trúc component thực tế trong code. Khi giao diện thật khác mô tả, vui lòng đối chiếu lại theo phiên bản đang chạy.

---

## 1. Giới thiệu chung

### Hệ thống dùng để làm gì
CleanBrowser cho phép **tạo và quản lý nhiều "trình duyệt ảo" độc lập** trên cùng một máy hoặc trên server. Mỗi trình duyệt có vân tay (fingerprint), cookie, IP riêng — các website coi mỗi profile là một thiết bị hoàn toàn khác.

Hệ thống cũng cho phép:
- **Tự động hoá thao tác** trên trình duyệt (click, gõ, điều hướng, trích xuất dữ liệu) qua flow kéo thả hoặc script.
- **Lập lịch** chạy tự động theo cron hoặc khi có webhook.
- **Chia sẻ team**: nhiều người cùng quản lý chung kho profile, phân vai trò rõ ràng.
- **Thanh toán theo gói** (Free → Team) với hạn mức từng tài nguyên.

### Ai nên sử dụng hệ thống
- Nhân viên marketing đa kênh quản lý nhiều tài khoản mạng xã hội
- Nhân viên thương mại điện tử dropship / affiliate
- Đội ngũ kiểm thử web cần test trên nhiều môi trường giả lập
- Người làm crawl dữ liệu cần tránh chặn IP / fingerprint
- Quản lý team cần phân quyền và theo dõi hoạt động

### Hệ thống giúp giải quyết công việc nào
| Vấn đề | Giải pháp của CleanBrowser |
|---|---|
| Bị nền tảng phát hiện và khóa nhiều tài khoản | Mỗi profile có fingerprint riêng — không bị link |
| Phải mở 20 cửa sổ Chrome cùng lúc | Mỗi profile chạy độc lập, quản lý từ 1 dashboard |
| Thay đổi IP thủ công mệt mỏi | Pool proxy tự xoay, tự kiểm tra IP |
| Lặp đi lặp lại thao tác (đăng bài, like, follow) | Vẽ flow tự động, đặt lịch chạy |
| Nhân viên nghỉ việc cuốn theo dữ liệu | Profile lưu trên hệ thống chung, phân quyền theo vai trò |

### Vai trò của AI trong hệ thống
AI (Anthropic Claude) được tích hợp vào **trình tạo Automation**. Người dùng mô tả công việc bằng tiếng Việt/tiếng Anh tự nhiên (ví dụ: *"Mở Twitter, đăng tweet 'xin chào'"*), AI sẽ sinh ra **luồng tự động hoá hoàn chỉnh** (flow gồm các bước goto/click/type/wait/extract) sẵn sàng chạy. Người dùng kiểm tra lại, chỉnh sửa, rồi lưu.

AI **không trực tiếp điều khiển trình duyệt** — chỉ tạo bản kế hoạch (DSL). Người dùng vẫn là người ra quyết định cuối cùng.

---

## 2. Nguyên tắc chung khi sử dụng

### Cách đăng nhập
1. Vào địa chỉ hệ thống (vd `https://cleanbrowser.com` nếu dùng bản cloud, hoặc `http://localhost:8080` nếu chạy local).
2. Có **3 cách đăng nhập**:
   - **Email + mật khẩu**: nhập email + mật khẩu, nhấn "Login".
   - **Google/GitHub**: nhấn nút *"Continue with Google"* hoặc *"Continue with GitHub"* phía trên form (chỉ hiện nếu admin đã cấu hình).
   - **Token cũ** (legacy): chế độ self-host single-token — chỉ admin server biết.
3. Nếu có bật **MFA (xác thực 2 lớp)**: sau khi nhập mật khẩu đúng, hệ thống yêu cầu mã 6 số từ ứng dụng Google Authenticator / Authy.
4. Nếu chưa có tài khoản: nhấn link *"Don't have an account? Sign up"*.

### Cách di chuyển giữa các màn hình
Giao diện chính có **thanh tab phía trên** với 6 mục:
- **Profiles** — quản lý trình duyệt ảo
- **Proxies** — quản lý kho proxy
- **Automations** — luồng tự động hoá
- **Marketplace** — chợ app tự động
- **Billing** — gói cước + hoá đơn
- **API Keys** — khoá truy cập lập trình

Bên cạnh các tab là **chọn workspace** (nếu thuộc nhiều team) và nút **đăng xuất** (icon ổ khoá).

### Cách nhập dữ liệu đúng
- Field có dấu `*` đỏ là **bắt buộc**.
- Email phải đúng định dạng (vd `name@domain.com`).
- Mật khẩu phải ≥ 8 ký tự.
- Tên profile / tên proxy không được để trống.
- Port phải là số từ 1 đến 65535.
- Cron expression phải có đúng 5 hoặc 6 phần (vd `0 9 * * *` = 9h sáng mỗi ngày).
- JSON trong DSL Automation phải hợp lệ — hệ thống tự bắt lỗi cú pháp.

### Cách lưu dữ liệu
Hệ thống có 2 kiểu:
- **Form CRUD** (profile, proxy, automation): nhấn nút **Save** ở cuối form. Trước khi save, hệ thống validate.
- **Auto-save**: trong dialog (vd schedule form), thay đổi được lưu khi nhấn Save trong dialog.

### Cách kiểm tra dữ liệu trước khi gửi, sửa, xoá
- **Trước khi gửi/lưu**: đọc lại form, đặc biệt các field tự động sinh (vd fingerprint_seed). Đảm bảo proxy đã được test "ok" trước khi gán cho profile.
- **Trước khi sửa profile đang chạy**: phải **Stop** trước. Một số thay đổi (vd đổi proxy) chỉ áp dụng cho lần launch tiếp theo.
- **Trước khi xoá**: hệ thống hiện dialog xác nhận. Nếu là profile đang chạy → bị chặn, phải stop trước. Nếu là proxy đang gán cho profile → profile sẽ mất proxy, nhưng vẫn launch được (không có IP riêng).

### Cách sử dụng AI an toàn và hiệu quả
- **Luôn xem flow AI tạo ra** trước khi nhấn Run. AI có thể chọn selector sai hoặc bỏ sót bước.
- **Test trước trên profile thử nghiệm**, không phải tài khoản chính.
- **Không nhập thông tin nhạy cảm** (mật khẩu, số thẻ) vào prompt AI. Thay vào đó dùng `set_variable` thủ công.
- **Đọc kỹ phần [Hướng dẫn sử dụng AI](#5-hướng-dẫn-sử-dụng-ai-trong-hệ-thống)** trước khi giao công việc quan trọng cho AI.

### Những thao tác người dùng cần tránh
| Thao tác | Hậu quả |
|---|---|
| Xoá profile khi đang chạy | Bị chặn (HTTP 409); nhưng force-delete sẽ làm crash session |
| Gán proxy "fail" cho profile | Browser không kết nối được mạng, treo lúc launch |
| Đặt cron 30 giây | Hệ thống tick 60s/lần, schedule < 1 phút sẽ bị bỏ qua |
| Sửa profile đang launch | Thay đổi không áp dụng — phải stop + launch lại |
| Đăng nhập sai mật khẩu liên tục > 10 lần/phút | Bị rate-limit, IP đó bị chặn 1-15 phút |
| Tạo > 500 proxy trong 1 lần bulk import | Bị từ chối (giới hạn an toàn) |
| Chia sẻ API key qua email/chat công khai | Ai có key cũng coi như là bạn — phải revoke ngay nếu lộ |
| Xoá workspace có member khác | Mất hết profile + automation của cả team |

---

## 3. Tổng quan giao diện

| STT | Màn hình/Khu vực | Mục đích | Thao tác chính | Lưu ý |
|---|---|---|---|---|
| 1 | **Trang Login** | Đăng nhập | Nhập email + mật khẩu, hoặc OAuth Google/GitHub | Có toggle "Use legacy token" cho self-host single-token |
| 2 | **Trang Signup** | Đăng ký tài khoản mới | Nhập email + mật khẩu + tên workspace | Tự cấp trial Pro 14 ngày |
| 3 | **Trang Pricing** (`/pricing` hoặc `?pricing=1`) | Xem bảng giá public | Chọn plan → bấm "Start trial" → đến signup | Không cần đăng nhập |
| 4 | **Banner xác minh email** (đầu app) | Nhắc verify email | Nhấn "Resend verification email" | Banner biến mất khi đã verify |
| 5 | **Tab Profiles** | Quản lý trình duyệt ảo | Sidebar list + form bên phải | Tab mặc định khi mở app |
| 6 | **Tab Proxies** | Quản lý kho proxy | List + form + dialog bulk import | Health check tự chạy mỗi 5 phút |
| 7 | **Tab Automations** | Luồng tự động | List + form + flow editor + schedule | Có nút "AI Build" |
| 8 | **Tab Marketplace** | Chợ ứng dụng | Grid card + install | Có Creator Dashboard cho người submit app |
| 9 | **Tab Billing** | Gói cước + hoá đơn | Plan card + usage bar + invoice list | Hiển thị nút "Manage" mở Stripe portal |
| 10 | **Tab API Keys** | Khoá API | Bảng list + dialog create | Token plaintext chỉ hiện 1 lần duy nhất |
| 11 | **Trang Status** (`/status`) | Trạng thái hệ thống | Hiển thị uptime + incident | Public, không cần login |
| 12 | **Header Workspace selector** | Chuyển workspace | Dropdown bên phải header | Chỉ hiện khi user thuộc ≥ 1 workspace |

---

## 4. Hướng dẫn chi tiết từng chức năng

### 4.1. Quản lý Profile trình duyệt

#### Mục đích
Tạo trình duyệt ảo độc lập — mỗi cái có fingerprint, IP, cookie riêng. Sử dụng để vận hành nhiều tài khoản mà không bị link.

#### Khi nào cần sử dụng
- Quản lý nhiều tài khoản Facebook/TikTok/Shopee
- Crawl dữ liệu cần vai trò khác nhau (anonymous, logged-in)
- Test sản phẩm web với các môi trường giả lập khác nhau

#### Dữ liệu cần chuẩn bị
- Tên profile (ví dụ: `tiktok-account-1`)
- Region (US/EU/SG/VN/local — tuỳ admin server config)
- Proxy (optional — chọn từ kho proxy đã có)
- Loại trình duyệt: Chromium (mặc định) hoặc Firefox
- Platform giả lập: Windows / macOS / Linux

#### Cách thêm dữ liệu mới
1. Vào tab **Profiles**.
2. Nhấn nút **"+ New"** ở góc trên sidebar trái.
3. Điền form bên phải:
   - **Name** (bắt buộc): tên gợi nhớ, ví dụ `tiktok-vn-01`.
   - **Browser engine**: chọn Chromium (stealth tốt) hoặc Firefox.
   - **Platform**: thường để Windows.
   - **Region**: chọn vùng gần với tài khoản đích (vd VN cho TikTok VN).
   - **Proxy**: chọn từ dropdown (đã thêm trước ở tab Proxies).
   - **Fingerprint seed**: để trống → tự random; hoặc cố định nếu muốn fingerprint giữ nguyên qua các lần launch.
   - **Screen size**: mặc định 1920x1080 — đổi khi cần giả lập màn hình khác.
   - **Timezone, Locale**: để trống nếu đã bật **GeoIP** (tự fill theo IP proxy).
   - **Tags**: gắn nhãn để lọc về sau.
4. Nhấn **Save**.
5. Kết quả: profile xuất hiện trong sidebar trái, có thể nhấn **Launch** để khởi động.

#### Cách sửa dữ liệu
1. Trong sidebar, click vào profile cần sửa → form hiển thị bên phải.
2. Sửa các field cần đổi.
3. Nhấn **Save**.
4. **Lưu ý trước khi sửa**:
   - Nếu profile đang chạy (badge xanh "running"), **stop trước**, sửa xong rồi launch lại.
   - Thay đổi fingerprint_seed = browser sẽ xuất hiện như "máy khác" — có thể bị nền tảng nghi ngờ.

#### Cách xóa dữ liệu
1. Click profile → form mở ra.
2. Cuộn xuống cuối, nhấn nút **Delete** (đỏ).
3. Confirm trong dialog.
4. **Cảnh báo**: 
   - Toàn bộ cookie, session, history của profile sẽ mất.
   - Nếu có snapshot trên S3 → snapshot vẫn còn (vào tab "Version history" của profile khác để khôi phục bản trước đó). Nhưng metadata profile bị xoá hoàn toàn.
5. **Trường hợp không nên xoá**:
   - Khi profile đang chạy automation theo lịch
   - Khi là profile chứa tài khoản chính của khách
   - Khi chưa export cookie ra ngoài (nếu cần backup)

#### Cách tìm kiếm, lọc hoặc sắp xếp
1. Sidebar Profiles có **ô search** ở trên cùng.
2. Gõ tên hoặc tag → list lọc real-time.
3. *Chưa đủ thông tin để xác định chính xác* có hỗ trợ sắp xếp theo cột nào trong UI — code chỉ filter theo workspace + region.

#### Các thông báo hoặc lỗi thường gặp

| Thông báo/Lỗi | Nguyên nhân dễ hiểu | Cách xử lý |
|---|---|---|
| `Profile not found (404)` | UUID profile sai, hoặc khác workspace | Kiểm tra đang ở đúng workspace; load lại list |
| `Profile is running; stop it before restoring a version` | Cố restore version khi đang chạy | Nhấn Stop, đợi 5s, rồi restore |
| `Proxy unavailable: ...` (khi launch) | Proxy đã gán bị fail hoặc password sai | Vào tab Proxies, test lại proxy đó; đổi proxy khác cho profile |
| `quota_exceeded: Plan limit reached for profiles` (HTTP 402) | Đã chạm hạn mức số profile của plan | Upgrade plan ở tab Billing, hoặc xoá profile cũ không dùng |
| `Firefox engine not installed` | Profile chọn Firefox nhưng server chưa cài binary | Liên hệ admin server cài: `playwright install firefox` |
| `Insufficient role` (HTTP 403) | Vai trò trong workspace không đủ để launch | Người launch cần role **launcher** trở lên |

#### Lưu ý nghiệp vụ
- **1 profile = 1 danh tính**. Đừng chia sẻ cùng 1 profile cho 2 tài khoản khác nền tảng — vẫn link được qua cookie.
- **Nên ghép profile với 1 proxy cố định cùng quốc gia**. Đổi IP đột ngột giữa các lần launch → cảnh báo bảo mật từ Google/Facebook.
- **Stop profile khi không dùng** để giải phóng RAM. Hệ thống tự stop sau 30 phút idle.

---

### 4.2. Quản lý Proxy

#### Mục đích
Lưu trữ và quản lý kho IP proxy dùng cho các profile. Tự động kiểm tra IP còn hoạt động, đo độ trễ, phát hiện quốc gia.

#### Khi nào cần sử dụng
- Trước khi tạo profile nào — vì profile cần có IP riêng để giả thiết bị khác
- Khi muốn xoay nhiều IP cho cùng 1 nền tảng (tránh chặn)
- Khi mua proxy mới từ nhà cung cấp (911, BrightData, Smartproxy, IPRoyal)

#### Dữ liệu cần chuẩn bị
- Loại proxy: HTTP, HTTPS hay SOCKS5
- Host, Port, Username, Password (do nhà cung cấp cấp)
- Tên dễ gợi nhớ (vd `911-us-east-01`)
- Provider: chọn `manual` cho proxy thường, hoặc `911`/`brightdata`/`smartproxy`/`iproyal` cho proxy xoay (rotating)

#### Cách thêm dữ liệu mới
**Thêm thủ công (1 proxy):**
1. Vào tab **Proxies**.
2. Nhấn **"+ New Proxy"**.
3. Điền form:
   - **Name** (bắt buộc)
   - **Type**: HTTP / HTTPS / SOCKS5
   - **Host**: IP hoặc tên miền (vd `proxy.example.com`)
   - **Port**: số port
   - **Username/Password**: nếu proxy có auth
   - **Provider**: chọn đúng để cấu hình rotation tự động (nếu rotating proxy)
4. Nhấn **Save**.
5. Kết quả: proxy xuất hiện trong list với status "unchecked" (chưa kiểm tra) ban đầu.

**Bulk import nhiều proxy:**
1. Nhấn **"Import"** cạnh nút "New Proxy".
2. Dialog mở ra với 1 textarea.
3. Dán danh sách proxy theo 1 trong 2 format:
   - **Mỗi dòng `host:port:user:pass`** — hệ thống tự nhận diện.
   - **CSV với header**: `name,type,host,port,username,password,provider`
4. Hệ thống parse + preview các dòng hợp lệ.
5. Nhấn **"Import N proxies"**.
6. Kết quả: thông báo "Imported X, failed Y" — kiểm tra danh sách failed nếu có.

#### Cách sửa dữ liệu
1. Click vào proxy trong list → form mở bên phải.
2. Sửa field cần đổi (host, port, password, v.v.).
3. Nhấn **Save**.
4. **Lưu ý**:
   - Đổi password sẽ tự encrypt lại (Fernet).
   - Đổi host/port giữa chừng có thể làm profile đang chạy bị mất kết nối lần launch sau.

#### Cách xóa dữ liệu
1. Click proxy → cuộn xuống nút **Delete**.
2. Confirm.
3. **Cảnh báo**: profile đang gán proxy này sẽ bị mất proxy (proxy_id = NULL). Profile vẫn launch được, nhưng dùng IP trực tiếp của server — KHÔNG có ẩn danh.
4. **Trường hợp không nên xoá**:
   - Khi proxy đang được dùng bởi profile chạy production
   - Trước khi backup credentials sang nơi khác

#### Cách tìm kiếm, lọc hoặc sắp xếp
- Filter theo status: `ok` / `fail` / `unchecked` qua query `?status=...` (UI có dropdown hoặc cần kiểm tra trên ProxyList).
- *Chưa đủ thông tin để xác định chính xác* các tuỳ chọn sort khác.

#### Kiểm tra (Test) thủ công
1. Trên 1 dòng proxy, nhấn nút **Test** (icon Play màu xanh).
2. Hệ thống chạy GET `https://api.ipify.org` qua proxy trong 10 giây.
3. Kết quả:
   - **OK + latency_ms**: proxy hoạt động.
   - **Fail + error message**: cần kiểm tra credentials hoặc đổi proxy.

#### Các thông báo hoặc lỗi thường gặp

| Thông báo/Lỗi | Nguyên nhân dễ hiểu | Cách xử lý |
|---|---|---|
| `Health check not available yet` (503) | httpx chưa cài hoặc tính năng tắt | Liên hệ admin server |
| Status `fail`, error `Timeout` | Proxy quá chậm (>10s) hoặc offline | Liên hệ nhà cung cấp / thay proxy |
| Status `fail`, error `401 Unauthorized` | Username/password sai | Sửa lại credentials |
| Status `fail`, error `407` | Proxy yêu cầu auth nhưng bạn không gửi | Điền username/password |
| `quota_exceeded` khi import 600 proxy | Plan free chỉ cho 500/lần | Chia nhỏ, hoặc upgrade plan |

#### Lưu ý nghiệp vụ
- **Health check tự chạy 5 phút/lần**, không cần test thủ công thường xuyên.
- **Sticky session** dùng cho rotating proxy: gán 1 session id cố định → IP không đổi trong khoảng 10 phút (Smartproxy) hoặc 1 giờ (IPRoyal).
- **Mỗi profile nên gán 1 proxy cố định** — đừng share 1 proxy cho 50 profile.

---

### 4.3. Automation (Tự động hoá)

#### Mục đích
Vẽ luồng thao tác trình duyệt một lần, hệ thống tự chạy lặp đi lặp lại — không cần ngồi click thủ công.

#### Khi nào cần sử dụng
- Lặp đi lặp lại 1 chuỗi hành động (đăng bài, like, comment)
- Cào dữ liệu theo lịch (mỗi sáng 9h tự crawl giá)
- Trigger bởi sự kiện ngoài (webhook từ Zapier, Make.com)
- Test E2E web mỗi đêm

#### Dữ liệu cần chuẩn bị
- Mô tả công việc bằng lời (để chat với AI), hoặc
- Bản DSL JSON (nếu tự viết)
- Profile đích để chạy (phải đang **running**)

#### Cách thêm dữ liệu mới
**Tạo bằng kéo thả (Visual editor):**
1. Vào tab **Automations**.
2. Nhấn **"+ New Automation"**.
3. Điền:
   - **Name**: vd `Đăng tweet hàng ngày`
   - **Kind**: chọn `flow` (kéo thả) hoặc `script` (TypeScript code)
   - **Description** (optional)
4. Nhấn **Save** → tạo automation rỗng.
5. Trong form edit, chọn tab **"Visual"** (mặc định bên cạnh nút "JSON").
6. Từ thanh node bên trái, kéo node vào canvas:
   - `goto_url` — mở URL
   - `click` — click selector
   - `type` — gõ text vào ô input
   - `wait` — đợi element xuất hiện
   - `extract` — trích xuất text/attribute vào biến
   - `condition` — rẽ nhánh true/false
   - `loop` — lặp
   - và 3 node khác (`wait_seconds`, `set_variable`, `log`)
7. Nối các node bằng cách kéo từ "handle" (chấm tròn dưới mỗi node) sang node tiếp theo.
8. Click 1 node → panel bên phải hiện form param (vd `goto_url` → field URL).
9. Sau khi vẽ xong, nhấn **Save new version**.

**Tạo bằng AI (nhanh nhất):**
1. Trong form Automation, nhấn nút **"AI Build"** (icon Sparkles ✨ cạnh toggle Visual/JSON).
2. Modal mở ra với textarea.
3. Nhập mô tả tự nhiên, ví dụ: *"Mở example.com, đợi heading h1, trích xuất nội dung h1 vào biến title, log ra"*.
4. Nhấn **Generate**.
5. AI trả về DSL JSON. Hệ thống tự gán vào field.
6. Nhấn **Save new version**.

*Xem chi tiết AI ở mục [5. Hướng dẫn sử dụng AI](#5-hướng-dẫn-sử-dụng-ai-trong-hệ-thống).*

**Tạo bằng JSON thủ công:**
1. Chọn tab "JSON" trong form.
2. Dán DSL JSON theo schema:
   ```json
   {
     "version": 1,
     "start": "n1",
     "nodes": [
       {"id": "n1", "type": "goto_url", "params": {"url": "..."}, "next": ["n2"]},
       ...
     ]
   }
   ```
3. Nhấn **Save**.

#### Cách chạy thủ công
1. Trong form Automation, tìm section **"Run"** (phía dưới editor).
2. Chọn **profile** từ dropdown (phải có ít nhất 1 profile đang running trong workspace).
3. Nhấn **Run**.
4. Hệ thống trả về `run_id` + status `queued` (đã đưa vào hàng đợi).
5. Background task tự kết nối tới profile qua CDP, chạy flow.

#### Cách xem kết quả chạy
1. Nhấn **"View runs"** trong form Automation.
2. Modal **Run Viewer** mở:
   - Status (badge màu): `queued` / `running` / `success` / `failure`
   - Start time, end time, duration
   - **Log text**: toàn bộ output từ các node `log` + thông báo từ engine
   - **Result JSON**: tất cả biến đã `set_variable` hoặc `extract`
   - **Error message**: nếu fail
3. Nhấn **Refresh** để cập nhật khi run đang chạy.

#### Cách lập lịch chạy tự động (Schedule)
1. Trong form Automation, cuộn xuống section **Schedules**.
2. Nhấn **"+ Add schedule"**.
3. Điền:
   - **Cron**: ví dụ `0 9 * * *` (9h sáng mỗi ngày). [Tham khảo cron syntax tại crontab.guru]
   - **Timezone**: chọn (mặc định UTC; thường chọn `Asia/Ho_Chi_Minh` cho VN)
   - **Profile**: profile chạy schedule (tuỳ chọn — nếu để trống, schedule chỉ fire run nhưng không attach profile)
   - **Enabled**: bật/tắt
4. Nhấn **Save**.
5. Scheduler tick 60 giây/lần — sẽ fire run khi đến hạn.

#### Cách kích hoạt qua Webhook (từ Zapier/Make/external service)
1. Trong form Automation, cuộn xuống section **Webhooks**.
2. Nhấn **"+ Create webhook"**.
3. Điền tên (vd `Zapier-Daily-Tweet`).
4. Hệ thống sinh URL dạng: `https://yourdomain.com/api/webhooks/automation/<random-token>`
5. Nhấn **Copy** để copy URL.
6. Paste URL này vào Zapier/Make ở action "POST request".
7. Mỗi lần dịch vụ ngoài POST đến URL → 1 run được tạo ngay lập tức.
8. Rate limit: 60 request/phút mỗi IP.

#### Cách sửa dữ liệu
1. Trong list bên trái, click automation.
2. Sửa name, description, hoặc tạo **version mới** của DSL (mỗi lần Save version cũ vẫn được giữ — có thể xem ở list versions).
3. Sửa schedules trong section Schedules.

#### Cách xóa dữ liệu
1. Click automation → form mở.
2. Nhấn **Delete** ở cuối form.
3. **Cảnh báo**: 
   - Tất cả runs lịch sử + schedules + webhooks **mất sạch**.
   - Schedule đang chạy sẽ bị huỷ.
4. **Trường hợp không nên xoá**:
   - Khi schedule đang quan trọng cho khách hàng/team
   - Khi chưa export run history cho audit

#### Các thông báo hoặc lỗi thường gặp

| Thông báo/Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `script mode not implemented yet` (run failure) | Run automation kind=`script` nhưng version chưa có code | Switch sang kind=`flow` hoặc thêm code script |
| `profile not running` (run failure) | Cố run trên profile chưa launch | Vào tab Profiles → launch profile → run lại |
| `no profile available` (run failure) | Run không truyền profile_id | Truyền profile_id khi run hoặc thêm profile vào schedule |
| `Invalid cron expression` (HTTP 400) | Cron syntax sai | Test trên crontab.guru, vd `0 9 * * *` |
| `quota_exceeded: automation_minutes` (HTTP 402) | Hết quota tháng | Upgrade plan; nếu plan có overage thì charge thêm |
| Run đứng "queued" mãi không "running" | Background task crash hoặc scheduler stop | Liên hệ admin xem log |
| AI trả về JSON không hợp lệ | Mô tả quá mơ hồ | Viết lại prompt rõ hơn (xem mục 5) |

#### Lưu ý nghiệp vụ
- **Test trên profile thử nghiệm trước**. Đừng chạy automation lạ trên profile chứa tài khoản chính.
- **Mỗi run = 1 phút quota** (tính tròn). Plan Free: 60 phút/tháng. Plan Pro: 3000 phút/tháng.
- **Profile phải đang chạy** trước khi automation kết nối — không thể "run on stopped profile".
- **Schedule fire = tạo run, không lock profile**. Nếu profile đang chạy automation khác, 2 task chia sẻ cùng browser context → có thể xung đột.

---

### 4.4. Marketplace (Chợ ứng dụng)

#### Mục đích
Tải về các automation đã có sẵn (do team CleanBrowser hoặc cộng đồng tạo) thay vì tự vẽ từ đầu.

#### Khi nào cần sử dụng
- Muốn dùng workflow chuẩn (vd "Auto Twitter Posting", "Mass Like Instagram")
- Không có thời gian build từ đầu
- Học hỏi cấu trúc flow từ creator giàu kinh nghiệm

#### Cách cài app từ Marketplace
1. Vào tab **Marketplace**.
2. Browse grid card (mỗi card = 1 app với icon, tên, mô tả, install_count, badge "Official" nếu là app chính thức).
3. Filter theo category bằng chip ở đầu trang (data, social, ecommerce, misc...).
4. Click vào card → xem chi tiết.
5. Nhấn **Install**.
6. App được clone thành **automation mới** trong workspace hiện tại. Vào tab Automations để chạy/sửa.

#### Cách submit app riêng (Creator)
1. Trong Marketplace, nhấn nút **"Submit your app"** (góc trên phải).
2. Dialog mở. Điền:
   - **Slug**: định danh URL-friendly, vd `auto-tiktok-warmup` (chỉ chữ-số-gạch)
   - **Name**: tên hiển thị
   - **Description / Long description**: markdown được
   - **Category**: chọn
   - **Kind**: flow hoặc script
   - **DSL JSON** (cho flow): toàn bộ JSON của automation
   - **Creator name, Creator URL** (optional): branding của bạn
3. Nhấn **Submit**.
4. App đi vào trạng thái **`moderation_status='pending'`** — chờ admin duyệt.
5. Sau khi admin approve, app xuất hiện public cho mọi người install.

#### Cách xem thu nhập (Creator Dashboard)
1. Trong Marketplace, nhấn **"Creator Dashboard"** (button góc trên).
2. Dashboard hiển thị:
   - **Summary cards**: số app, số install, tiền pending, available, paid out
   - **Earnings table**: từng giao dịch với status (pending → available sau 14 ngày → paid_out khi admin payout)
   - **My Submissions**: danh sách app đã submit + moderation_status
3. **Nút "Request payout"**: hiện tại disabled — Phase 1 chỉ tracking, payout cần xử lý thủ công với admin.

#### Lưu ý nghiệp vụ
- **App nội bộ không cần submit**. Tự tạo trong tab Automations là đủ.
- **Cẩn thận khi install app từ creator không rõ**: flow có thể chứa selector độc hại hoặc step không cần thiết. Xem JSON trước khi install.
- **Revenue share mặc định 70% creator / 30% platform** với app có giá > 0. Phase này chưa thu tiền thật.

---

### 4.5. Billing (Gói cước + Hoá đơn)

#### Mục đích
Quản lý gói cước, theo dõi sử dụng so với hạn mức, thanh toán, xem hoá đơn.

#### Khi nào cần sử dụng
- Mới đăng ký → check trial Pro 14 ngày
- Khi nhận warning "quota_exceeded"
- Khi cần xuất hoá đơn cho kế toán
- Khi muốn upgrade/downgrade plan

#### Tổng quan tab Billing
1. Vào tab **Billing**.
2. **Section "Current plan"** — hiển thị:
   - Tên plan đang dùng (Free / Starter / Pro / Team)
   - Giá ($X/mo hoặc Free)
   - Status (active / trialing / past_due / cancelled)
   - Nút **"Manage"** (mở Stripe Customer Portal — chỉ với subscription qua Stripe)
   - **5 thanh usage**: Profiles, Concurrent runs, Workspace members, Automation minutes, Storage (GB). Mỗi thanh có max và current; vàng khi > 80%, đỏ khi đã đầy.
3. **Section "Plans"** — grid 4 plan với feature bullet và button:
   - **"Current plan"** (xanh) — không click được
   - **"Upgrade"** / **"Switch"** — mở Stripe checkout
4. **Section "Invoices"** — bảng hoá đơn:
   - Date, Number, Amount, Status badge (paid/open/failed/void)
   - Actions: link PDF và link Hosted invoice (Stripe URL)

#### Cách upgrade plan qua Stripe
1. Trong section Plans, click **"Upgrade"** trên plan muốn (vd Pro).
2. Browser redirect đến Stripe Checkout.
3. Nhập card / Apple Pay / Google Pay.
4. Sau khi pay thành công, Stripe redirect về `https://yourdomain.com/?billing=success`.
5. Webhook tự cập nhật subscription trong hệ thống → reload Billing thấy plan mới.

#### Cách thanh toán qua VNPay (Việt Nam)
*Chưa đủ thông tin để xác định chính xác* — API endpoint `POST /api/billing/vnpay/checkout` tồn tại, nhưng UI có thể chưa thêm nút "Pay with VNPay". Có thể gọi qua API thủ công, hoặc đợi admin server bật.

#### Cách quản lý subscription (Stripe portal)
1. Click **"Manage"** trong section Current plan.
2. Browser redirect đến Stripe Customer Portal.
3. Tại đây có thể: đổi card, cancel subscription, đổi plan, xem invoice cũ, download tax receipt.

#### Hiểu các plan

| Plan | Giá/tháng | Profiles | Concurrent runs | Members | Automation min/mo | Storage GB | Regions |
|---|---|---|---|---|---|---|---|
| Free | $0 | 10 | 2 | 1 | 60 | 1 | local |
| Starter | $19 | 100 | 10 | 3 | 600 | 10 | local, us, eu |
| Pro | $49 | 500 | 50 | 10 | 3000 | 50 | local, us, eu, sg, jp |
| Team | $99 | 2000 | 200 | 50 | 12000 | 200 | tất cả |

#### Trial flow tự động
- Tài khoản mới tự được cấp **subscription trial=Pro trong 14 ngày**.
- Sau 14 ngày, status = `past_due` → các thao tác bị block nếu user không upgrade.
- Trong 14 ngày, dùng hạn mức Pro thoải mái.

#### Overage billing (vượt hạn mức)
- Chỉ áp dụng cho **automation_minutes** trên plan Starter+.
- Mỗi phút vượt = 5 cents (do plan config). Hệ thống ghi event vào DB.
- **Worker tự gửi lên Stripe** mỗi 60s qua `subscription_items.create_usage_record` (cộng vào hoá đơn cuối tháng).
- Hạn mức `max_profiles`, `max_concurrent_runs` **vẫn là hard cap** — không cho vượt, trả 402.

#### Các thông báo hoặc lỗi thường gặp

| Thông báo/Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Stripe not configured` (503) khi nhấn Upgrade | Admin chưa set STRIPE_SECRET_KEY | Liên hệ admin |
| `Plan free does not require payment` (400) | Chọn Free khi đã Free | Không cần action |
| `No active subscription` (404) khi nhấn Manage | Chưa từng pay qua Stripe (vd đang trial) | Subscribe qua Stripe trước, rồi mới mở portal |
| Hoá đơn không cập nhật sau khi pay | Webhook chưa đến | Đợi 1-2 phút, hoặc admin check log Stripe webhook |

#### Lưu ý nghiệp vụ
- **Đọc kỹ usage bars trước khi tạo profile mới**. Tránh chạm hard cap khi đang chạy production.
- **Hoá đơn paid sau 14 ngày refund window** mới available cho creator marketplace.

---

### 4.6. API Keys (Khoá truy cập lập trình)

#### Mục đích
Cấp khoá để dùng API ngoài UI — phục vụ script tự động, integration Playwright/Puppeteer, CI/CD.

#### Khi nào cần sử dụng
- Viết script Python/Node tự động tạo profile hàng loạt
- Tích hợp CleanBrowser với hệ thống nội bộ
- Cho phép CI/CD tạo run automation khi deploy

#### Cách tạo API key
1. Vào tab **API Keys**.
2. Nhấn **"Create new key"**.
3. Trong dialog:
   - **Name** (bắt buộc): vd `ci-cd-deploy-bot`
   - **Scopes**: tick `*` (toàn quyền) hoặc chọn từng scope cụ thể
4. Nhấn **Create**.
5. **🔑 QUAN TRỌNG**: hệ thống hiển thị token plaintext **CHỈ 1 LẦN DUY NHẤT** trong banner màu vàng. **Copy ngay** và lưu vào nơi an toàn (password manager). Sau khi dismiss banner, không thể xem lại — phải tạo key mới.

#### Cách sử dụng key trong code
```bash
curl -H "Authorization: Bearer YOUR_KEY_HERE" https://yourdomain.com/api/profiles
```

#### Cách quản lý
- **List**: bảng hiển thị name, scopes, created date, last_used, status (active/revoked).
- **Revoke**: click nút "Revoke" trên dòng → confirm. Sau đó request dùng key này trả 401.

#### Các thông báo hoặc lỗi thường gặp

| Thông báo/Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `name required` (400) | Tạo key không nhập tên | Nhập tên |
| `404 Not found` khi revoke | Key không thuộc user hiện tại | Chỉ chủ key mới revoke được |
| `Too many requests` (429) khi spam tạo | Rate limit 20 keys/giờ | Đợi 1 giờ |

#### Lưu ý nghiệp vụ
- **Key có quyền y như user**. Mất key = mất tài khoản. **Revoke ngay** nếu lộ.
- **Đặt tên rõ ràng** mục đích từng key (vd `playwright-test-runner`, `crawl-daily-script`). Dễ revoke đúng cái khi cần.
- **Không commit key vào Git**. Dùng env var.

---

### 4.7. Quản lý Workspace + Team

#### Mục đích
Cho nhiều người cùng quản lý chung kho profile/proxy/automation, phân vai trò để kiểm soát quyền.

#### 5 vai trò trong workspace

| Vai trò | Quyền |
|---|---|
| **viewer** | Chỉ xem profile, không launch, không sửa |
| **launcher** | viewer + Launch/Stop browser + xem VNC + chạy automation |
| **editor** | launcher + tạo/sửa/xoá profile, proxy, automation |
| **admin** | editor + mời/đuổi member, đổi role member khác |
| **owner** | admin + đổi billing plan, xoá workspace |

#### Cách tạo workspace mới
1. Vào header → workspace selector → **"+ New workspace"** (*Chưa đủ thông tin để xác định chính xác* — UI dropdown có thể có hoặc không nút này).
2. Hoặc gọi API `POST /api/workspaces` với `{name: "Team B"}`.
3. User tạo tự động là **owner**.

#### Cách mời member
1. Vào trang chi tiết workspace (*Chưa đủ thông tin để xác định chính xác* — endpoint backend tồn tại nhưng vị trí UI chưa rõ).
2. Nhập email + role.
3. **Lưu ý**: email phải thuộc cùng tenant. Phase 1 chưa hỗ trợ cross-tenant invite.

#### Đổi role member
- Endpoint: `PATCH /api/workspaces/{ws}/members/{user}` với `{role}`.
- **Protection**: không thể demote / remove **owner cuối cùng** của workspace (HTTP 403).

#### Xoá member
- Endpoint: `DELETE /api/workspaces/{ws}/members/{user}`.
- Yêu cầu role admin trở lên.

#### Lưu ý nghiệp vụ
- **Mỗi tenant nên có ít nhất 2 owner** để phòng trường hợp 1 người quên mật khẩu.
- **Mời member với role nhỏ nhất đủ dùng**. Viewer cho người chỉ xem report; editor cho người quản lý profile; admin chỉ cho team lead.

---

### 4.8. Snapshot + Version history

#### Mục đích
Tự động backup profile mỗi lần stop, cho phép quay về phiên bản trước (vd khi profile bị broken).

#### Cách hoạt động (tự động)
1. Mỗi lần **Stop profile**, hệ thống:
   - Đóng tar + nén zstd thư mục dữ liệu (`user_data_dir`)
   - Upload lên S3 / MinIO (hoặc local disk nếu không config)
   - Ghi record vào bảng `profile_versions`
2. Diff sync: chỉ những file thay đổi mới được upload (tiết kiệm ~80% bandwidth). Mỗi 10 version có 1 snapshot full để giữ chain ngắn.

#### Cách xem lịch sử version
1. Vào profile → cuộn xuống section **"Version history"**.
2. Bảng hiển thị: vN, ngày tạo, kích thước, ghi chú.
3. Nếu chưa enable storage → banner "Cloud snapshots not yet enabled — Configure STORAGE_BUCKET".

#### Cách restore về version cũ
1. Trên 1 dòng version, nhấn **"Restore"**.
2. Confirm dialog: *"Restore version N? This will overwrite current profile data."*
3. **Yêu cầu profile phải đang stopped**. Nếu đang running → lỗi 409.
4. Hệ thống tải snapshot xuống, ghi đè user_data_dir.
5. Lần launch tiếp theo → browser load lại với data của version cũ.

#### Cách xoá version (nếu hết quota storage)
- Có endpoint `DELETE /api/profiles/{id}/versions/{version_id}`.
- Cần role editor.

#### Lưu ý nghiệp vụ
- **Mỗi version có sha256** để verify integrity.
- **Storage tính vào quota plan**. Plan Free chỉ 1 GB → khoảng 10-20 version tuỳ kích thước.
- **Idle reaper auto-stop sau 30 phút** → tự động trigger snapshot. Bạn không cần stop thủ công để snapshot.

---

### 4.9. Xác minh email + MFA

#### Verify email
1. Sau khi signup, hệ thống gửi email với link `/api/auth/verify-email?token=...`.
2. Banner vàng hiển thị đầu app: *"Your email X is not verified. [Resend verification email]"*.
3. Click link trong email → verify thành công → redirect `/?verified=1`.
4. Nếu không nhận email: click **"Resend verification email"** (rate limit 3/giờ).

#### Bật MFA TOTP
1. Trong cài đặt user (*Chưa đủ thông tin để xác định chính xác* — endpoint `POST /api/auth/mfa/setup` tồn tại nhưng vị trí UI chưa rõ — có thể trong tab API Keys hoặc settings ngầm).
2. Gọi API: `POST /api/auth/mfa/setup` → trả secret + QR provisioning URI.
3. Quét QR bằng Google Authenticator / Authy.
4. Gọi `POST /api/auth/mfa/enable` với secret + code 6 số xác nhận.
5. Lần login sau, sau khi nhập password sẽ hỏi thêm code MFA.

#### Tắt MFA
- `POST /api/auth/mfa/disable` với password + code hiện tại. Double check để tránh hijack.

---

## 5. Hướng dẫn sử dụng AI trong hệ thống

### AI dùng để làm gì
AI (Anthropic Claude) tích hợp tại nút **"AI Build"** trong trình tạo Automation. Cụ thể, AI giúp:

- **Sinh flow tự động hoá** từ mô tả tiếng Việt/tiếng Anh tự nhiên
- **Đề xuất CSS selector** cho các website phổ biến
- **Cấu trúc node logic** (goto → wait → click → extract)
- **Bổ sung node log/wait** để flow ổn định hơn

AI **KHÔNG**:
- Tự chạy browser
- Tự fix flow khi run fail
- Học từ data của workspace bạn
- Truy cập internet trong lúc generate

### Cách nhập yêu cầu cho AI
Viết prompt theo công thức **MỤC TIÊU + DỮ LIỆU + KẾT QUẢ + LƯU Ý**.

**Mục tiêu** (Hành động chính):
- Mở website nào? Làm gì trên đó?
- VD: "Mở Twitter và post tweet 'Xin chào'"

**Dữ liệu** (Input cụ thể):
- URL chính xác
- Selector nếu biết
- Text cần gõ
- VD: "URL: https://twitter.com, ô input có selector `textarea[data-testid=tweetTextarea_0]`"

**Kết quả mong muốn**:
- Trích xuất biến gì
- Log gì
- VD: "Sau khi post xong, trích xuất link tweet vào biến `tweet_url`"

**Lưu ý đặc biệt**:
- Đợi bao lâu giữa các bước
- Có rẽ nhánh không
- VD: "Đợi 3 giây sau mỗi click; nếu thấy 'Login' thì log lỗi"

### Ví dụ yêu cầu nên nhập cho AI

1. **"Mở example.com, đợi h1 hiện, trích xuất nội dung h1 vào biến title, log ra"**
   → Flow đơn giản 3 node.

2. **"Đăng nhập Twitter: vào twitter.com/login, gõ username 'myuser' vào input[name=text], click Next, gõ password vào input[name=password], click Login"**
   → Flow login chuỗi.

3. **"Crawl giá sản phẩm Shopee: mở URL sản phẩm, đợi `.product-price`, extract giá vào biến `price`, log ra"**
   → Flow scraping.

4. **"Đăng tweet 'Tin tức mới': click `[data-testid=SideNav_NewTweet_Button]`, gõ tweet vào textarea, click `[data-testid=tweetButton]`"**
   → Flow đăng bài.

5. **"Kiểm tra inventory: vào trang sản phẩm; nếu thấy 'In stock' thì log SUCCESS, ngược lại log OUT_OF_STOCK"**
   → Flow có condition.

6. **"Like 10 video TikTok: lặp 10 lần, mỗi lần click nút like (selector `button[data-e2e=like-icon]`), đợi 5 giây giữa các lần"**
   → Flow loop.

7. **"Auto-fill form đăng ký: gõ name, email, phone (đã cho qua biến), tick checkbox đồng ý, click Submit"**
   → Flow form fill.

8. **"Mở Gmail, đợi inbox load, đếm số mail chưa đọc trong biến `unread_count`, log"**
   → Flow extract count.

9. **"Search Google 'best laptop 2026', lấy 5 link đầu tiên vào biến `results`"**
   → Flow loop extract.

10. **"Mở URL từ biến `target_url`, đợi 5 giây, screenshot vào log với note 'verified'"**
    → Flow đơn giản dùng biến input.

### Cách kiểm tra kết quả AI

Sau khi AI trả về JSON, **luôn làm 4 việc**:

1. **Đọc lại flow trong tab Visual** — kiểm tra các node có nối đúng thứ tự, condition có rẽ đúng nhánh.
2. **Kiểm tra selector** — AI hay đoán selector. Mở DevTools trong browser thật, copy selector chính xác nếu cần.
3. **Test trên profile dummy trước** — đừng chạy lên profile chính ngay.
4. **Xem run log lần đầu** — AI có thể quên `wait`, làm click trước khi element xuất hiện → click fail.

Trước khi lưu version:
- Tất cả node có `params` hợp lệ?
- Có node `condition` mà không có cả `next_true` lẫn `next_false`? → flow đứng giữa chừng.
- Có loop không có điểm thoát? → step limit kích hoạt (1000 step)

### Những việc không nên giao hoàn toàn cho AI

| Tình huống | Lý do | Phải làm |
|---|---|---|
| Flow liên quan đến tiền (chuyển khoản, mua hàng) | AI có thể click sai nút "Confirm payment" | Người ra quyết định cuối cùng phải kiểm tra từng node |
| Flow đăng nhập tài khoản chính | AI không biết MFA, captcha của tài khoản đó | Vẽ thủ công, đặc biệt phần MFA |
| Flow trên website có anti-bot Cloudflare/reCAPTCHA | AI không tính delay humanize đủ | Bật `humanize: true` trong profile, vẽ thủ công các step có random delay |
| Flow chạy 24/7 mass action (mass like, mass follow) | Risk bị nền tảng ban | Có quy tắc rate tự chọn (mỗi action cách 10-30s random), AI không tự đặt |
| Selector động (thay đổi mỗi load page) | AI chỉ thấy selector static | Phải tự inspect và dùng data-testid hoặc XPath chính xác |
| Khi log AI báo `_notice: ANTHROPIC_API_KEY not set` | Hệ thống đang dev-mode, trả flow giả | Liên hệ admin set API key thật, KHÔNG dùng flow giả |

---

## 6. Công thức và quy tắc nghiệp vụ

### Tính phí overage automation_minutes

- **Mục đích**: Charge thêm khi user vượt hạn mức automation minutes của plan.
- **Dữ liệu đầu vào**:
  - `automation_minutes_used` (current usage tháng)
  - `max_automation_minutes` (hạn mức plan)
  - `overage_price_per_minute_cents` (cấu hình plan, mặc định 5)
- **Cách tính bằng lời**: Mỗi phút vượt hạn mức, charge thêm 5 cents.
- **Công thức**:
  ```
  IF automation_minutes_used > max_automation_minutes:
      overage_minutes = automation_minutes_used - max_automation_minutes
      overage_charge_cents = overage_minutes × overage_price_per_minute_cents
  ELSE:
      overage_charge_cents = 0
  ```
- **Ví dụ minh họa**:
  - Plan Starter (600 phút/mo, 5¢/min overage)
  - Đã dùng 700 phút
  - Overage = (700 − 600) × 5 = 500 cents = **$5**
- **Lưu ý**: Chỉ áp dụng cho action `run_automation`. `create_profile`, `launch_profile` vẫn là hard cap.
- **Trường hợp đặc biệt**: Plan Free không có overage — vượt là bị từ chối 402.

---

### Tính revenue share marketplace

- **Mục đích**: Chia tiền giữa creator submit app và platform.
- **Dữ liệu đầu vào**:
  - `gross_cents` (giá user trả khi install)
  - `revenue_share_pct` (% creator nhận, mặc định 70)
- **Cách tính bằng lời**: Creator nhận 70% giá, platform giữ 30%.
- **Công thức**:
  ```
  creator_cents = (gross_cents × revenue_share_pct) ÷ 100   # integer division
  platform_cents = gross_cents − creator_cents
  ```
- **Ví dụ minh họa**:
  - App có price = 1000 cents ($10)
  - revenue_share_pct = 70
  - creator nhận = 1000 × 70 / 100 = **700 cents ($7)**
  - platform giữ = 300 cents ($3)
- **Lưu ý**: 
  - Earnings status `pending` trong 14 ngày (refund window) → sau đó `available` để payout.
  - Phase 1 chưa charge tiền thật khi install — chỉ track earnings.

---

### Quy tắc xác định plan effective của tenant

- **Mục đích**: Quyết định plan/hạn mức nào áp dụng cho tenant tại 1 thời điểm.
- **Cách tính bằng lời**:
  1. Tìm subscription có status thuộc `{active, trialing, past_due}` của tenant.
  2. Nếu có → plan_id của subscription đó.
  3. Nếu không có → fallback **free**.
- **Ví dụ**:
  - Tenant A vừa signup → có sub trialing=Pro → plan effective = **Pro** trong 14 ngày.
  - Sau 14 ngày, sub thành `past_due` → vẫn coi là Pro nhưng API trả `is_overage=true` cho run.
  - Tenant B chưa từng pay → fallback **free**.

---

### Quy tắc Idle Reaper

- **Mục đích**: Tự stop profile không hoạt động để tiết kiệm RAM.
- **Dữ liệu đầu vào**: 
  - `started_at` của session đang chạy
  - Config `IDLE_REAPER_TIMEOUT_SECONDS` (mặc định 1800 = 30 phút)
- **Cách tính bằng lời**: Bất kỳ session nào chạy đã quá 30 phút → tự stop.
- **Lưu ý**: Phase 1 không track VNC activity thực → chỉ dùng tuổi session. User vẫn nên stop thủ công khi xong.

---

### Quy tắc enforce role hierarchy

- **Mục đích**: Quyết định user có quyền thực hiện action nào trong workspace.
- **Hierarchy**:
  ```
  viewer (level 1)  < launcher (2) < editor (3) < admin (4) < owner (5)
  ```
- **Áp dụng**:
  - `GET /api/profiles/{id}` → cần ≥ viewer
  - `POST /launch` → cần ≥ launcher
  - `POST/PUT/DELETE` profile → cần ≥ editor
  - `POST/PATCH/DELETE` member → cần ≥ admin
  - Đổi billing plan → cần owner
- **Lưu ý**: Vai trò trả từ `db_auth.get_member_role()`. Nếu user không phải member → 404 (không 403, để tránh leak tồn tại).

---

## 7. Quy trình vận hành chuẩn

### Quy trình A: Setup tài khoản đầu tiên + tạo profile + chạy thử

- **Người thực hiện**: Người dùng mới
- **Thời điểm**: Lần đầu sử dụng
- **Dữ liệu cần chuẩn bị**: Email, mật khẩu, ít nhất 1 proxy (mua từ provider hoặc tự host)

**Các bước:**
1. Vào trang chính → nhấn link "Sign up" trên trang login.
2. Nhập email, mật khẩu (min 8 ký tự), tên workspace (vd "My Company").
3. Submit → hệ thống tạo tenant + user + workspace + tự apply trial Pro 14 ngày.
4. Banner vàng đầu app: nhắc verify email → vào inbox, click link verify.
5. Vào tab **Proxies** → "+ New Proxy" → nhập proxy đầu tiên → Save.
6. Nhấn nút **Test** → đợi vài giây → status "ok" + latency hiển thị.
7. Vào tab **Profiles** → "+ New" → tên `test-profile-1` → chọn proxy vừa tạo → Save.
8. Click profile vừa tạo → nhấn **Launch** → đợi 5-10 giây → VNC iframe hiển thị browser.
9. Trong browser ảo: mở `https://creepjs.com` → đợi → check fingerprint score (mong đợi > 0.6).
10. Stop profile → vào "Version history" → thấy v1 snapshot.

**Kết quả cần kiểm tra**:
- Tài khoản đã verify email
- Có 1 proxy status `ok`
- Có 1 profile launch + view VNC + stop thành công
- Có 1 version snapshot

**Lỗi thường gặp + cách xử lý**:
- Banner email verify không biến mất → click resend, check spam folder
- Launch profile báo "proxy unavailable" → test lại proxy, nếu fail thì dùng proxy khác
- VNC trắng đen → đợi thêm 5 giây, refresh iframe

---

### Quy trình B: Vẽ automation với AI và chạy lần đầu

- **Người thực hiện**: Editor/Launcher
- **Thời điểm**: Khi cần tạo workflow mới
- **Dữ liệu cần chuẩn bị**: Mô tả công việc bằng lời, profile đang chạy

**Các bước:**
1. Đảm bảo có 1 profile đang **running** (vd `test-profile-1`).
2. Vào tab **Automations** → "+ New Automation" → tên `test-auto-1` → kind=`flow` → Save.
3. Trong form, nhấn **"AI Build"** (icon Sparkles).
4. Nhập prompt: *"Mở example.com, đợi h1, trích xuất nội dung h1 vào biến title, log title ra"*.
5. Nhấn **Generate** → AI trả về flow JSON 4 node.
6. **Kiểm tra**: switch sang tab Visual → đảm bảo 4 node (goto → wait → extract → log) nối đúng thứ tự.
7. Nhấn **Save new version**.
8. Trong section Run, chọn profile `test-profile-1` từ dropdown.
9. Nhấn **Run** → toast "Run queued: <run_id>".
10. Nhấn **"View runs"** → modal Run Viewer mở.
11. Đợi 5-10s, refresh → status chuyển `running` → `success`.
12. Xem log + result JSON → confirm biến `title` chứa text "Example Domain".

**Kết quả cần kiểm tra**:
- Run status = `success`
- Log có dòng "Example Domain"
- Result JSON: `{"title": "Example Domain"}`

**Lỗi thường gặp**:
- Run = `failure` + error "profile not running" → đảm bảo profile đã launch
- AI trả flow giả với `_notice: ANTHROPIC_API_KEY not set` → liên hệ admin
- Selector h1 sai cho website khác → mở DevTools tìm selector chính xác

---

### Quy trình C: Mời member vào team

- **Người thực hiện**: Owner hoặc Admin
- **Thời điểm**: Khi cần thêm người vào workspace
- **Dữ liệu cần chuẩn bị**: Email của người mời (phải đã signup trong cùng tenant)

**Các bước:**
1. Người được mời tự signup trước (vào trang signup), dùng workspace của bạn (đổi qua workspace selector sau khi signup).
2. *Chưa đủ thông tin để xác định chính xác* — UI mời member: API tồn tại `POST /api/workspaces/{id}/members` nhưng vị trí button trong UI chưa rõ. Có thể qua endpoint API tạm.
3. Body: `{"email": "newuser@example.com", "role": "editor"}`.
4. Hệ thống tự add user vào workspace_members.
5. User refresh → workspace switcher hiện workspace mới.

**Kết quả cần kiểm tra**:
- User mới có thể switch sang workspace
- Có quyền tương ứng role

---

### Quy trình D: Backup + restore profile khi bị broken

- **Người thực hiện**: Editor
- **Thời điểm**: Khi profile bị crash, login bị mất, cookie corrupt

**Các bước:**
1. Vào profile bị lỗi → **Stop** (nếu đang running).
2. Cuộn xuống "Version history" → list các version trước (vN, vN-1, ...).
3. Chọn version trước thời điểm bị lỗi → nhấn **"Restore"**.
4. Confirm dialog.
5. Hệ thống wipe user_data_dir hiện tại + tải snapshot xuống + extract.
6. Launch lại profile → kiểm tra cookie/login đã trở về.

**Kết quả cần kiểm tra**:
- Profile launch thành công
- Cookie/login giống trạng thái ngày restore

**Lỗi thường gặp**:
- "Profile is running; stop it before restoring" → stop trước
- "Cloud snapshots not yet enabled" → admin chưa config storage; không restore được, profile mới sẽ phải bắt đầu lại từ đầu

---

## 8. Các lỗi người dùng mới thường gặp

| Tình huống | Nguyên nhân | Cách phòng tránh | Cách khắc phục |
|---|---|---|---|
| Sau signup không nhận email verify | SMTP chưa cấu hình hoặc vào spam | Check spam folder; admin set SMTP | Click "Resend verification email", check spam |
| Login bị 401 dù password đúng | Caps Lock bật / khoảng trắng cuối | Type cẩn thận, không copy-paste có space | Reset password (cần admin support) |
| Tạo profile xong mà list trống | Đang ở wrong workspace | Đảm bảo workspace selector đúng | Switch workspace ở header |
| Launch profile lâu (>30s) | CloakBrowser binary chưa cache local | Lần đầu chậm, lần 2 nhanh | Đợi; nếu >2 phút admin check log |
| VNC iframe không hiển thị | Browser chặn iframe / popup blocker | Cho phép popup từ domain | Refresh trang, hoặc disable extension chặn iframe |
| Automation run mãi "queued" | Background worker chết | — | Liên hệ admin restart server |
| AI trả flow với selector `[data-testid=...]` không tồn tại | AI đoán theo schema phổ biến | Mở DevTools website thật để verify selector | Sửa node `params` thủ công |
| Quota_exceeded khi tạo profile thứ 11 (plan Free) | Free chỉ 10 profile | Upgrade plan trước | Xoá profile cũ hoặc upgrade |
| Stripe checkout redirect về dashboard mà plan không đổi | Webhook chưa cập nhật | — | Đợi 1-2 phút, hoặc admin check Stripe webhook log |
| Mất proxy gắn vào profile sau khi xoá proxy | FK ON DELETE SET NULL | Hỏi confirm trước khi xoá proxy đang dùng | Gán lại proxy khác cho profile |
| Member không thấy profile của mình | Profile thuộc workspace khác (workspace_id NULL) | Tạo profile khi đã chọn workspace | Migrate profile qua admin SQL |
| API key bị lộ qua git commit | Commit nhầm `.env` | `.gitignore` chứa `.env` | Revoke key ngay, tạo key mới, đổi sạch |

---

## 9. Câu hỏi thường gặp (FAQ)

**Q: Có cần cài Chrome trên máy mình không?**  
A: Không. Trình duyệt chạy trên server, bạn chỉ xem qua VNC trong trang web. Có thể dùng từ bất kỳ thiết bị nào có browser.

**Q: Tôi có thể dùng được trên iPhone/iPad không?**  
A: Mở `https://yourdomain.com` trong Safari được, nhưng VNC kéo chuột trên màn hình cảm ứng không tiện. Khuyến nghị dùng máy tính/laptop.

**Q: Profile của tôi có an toàn nếu admin hệ thống xem được không?**  
A: Admin server (người có quyền truy cập DB) có thể đọc fingerprint settings. Nhưng **proxy password được mã hoá Fernet**, cookie nằm trong user_data_dir trên S3 (mã hoá ở rest nếu config). Mật khẩu account của bạn được Argon2id hash — admin không đọc được plaintext.

**Q: Quên mật khẩu thì làm sao?**  
A: *Chưa đủ thông tin để xác định chính xác* — endpoint forgot-password chưa thấy trong code. Tạm thời cần liên hệ admin server reset thủ công.

**Q: Trial 14 ngày hết, có bị xoá data không?**  
A: Không. Subscription chuyển sang `past_due`, hạn mức xuống Free (10 profile). Nếu bạn đã có > 10 profile, bạn vẫn xem được nhưng không tạo thêm. Upgrade plan bất cứ lúc nào để khôi phục.

**Q: Tôi muốn dùng AI mà không có API key Anthropic, có cách nào không?**  
A: Hệ thống có **dev-mode** trả flow mẫu. Nhưng flow chỉ là 3 node placeholder (log + goto + extract), không thực sự sinh từ prompt. Cần API key thật để có giá trị thực.

**Q: Có thể chạy bao nhiêu automation cùng lúc?**  
A: Tuỳ plan: Free 2 concurrent, Pro 50, Team 200. Vượt sẽ trả 402.

**Q: Webhook trigger có chậm không?**  
A: Khi external service POST → run tạo NGAY LẬP TỨC (status=queued). Background task pick up trong ~1 giây. Tổng latency ~1-3 giây nếu profile đang running.

**Q: Tôi có thể export profile data ra ngoài (cookie, history)?**  
A: Có thể download presigned URL của snapshot từ tab "Version history" → "Download" button. File `.tar.zst` chứa user_data_dir.

**Q: Workspace switch có làm mất context không?**  
A: Switch workspace → toàn bộ list (profiles, proxies, automations) reload theo workspace mới. Profile đang running không bị stop.

**Q: AI có lưu prompt của tôi không?**  
A: Prompt đi qua Anthropic API. Theo policy của Anthropic, không train trên data API (trừ khi opt-in). Hệ thống không lưu prompt vào DB của bạn.

**Q: Tôi muốn tự host trên VPS, có hướng dẫn không?**  
A: Có. Đọc [SETUP.md](./SETUP.md) cho Linux/Mac, hoặc [SETUP_WINDOWS.md](./SETUP_WINDOWS.md) cho Windows.

**Q: Profile Firefox có khác Chrome thế nào?**  
A: Phase 1: Firefox launch được nhưng KHÔNG có fingerprint stealth patches như CloakBrowser Chromium. Dùng Firefox cho diverse fingerprint, không khuyến nghị cho stealth critical.

---

## 10. Phụ lục: Danh sách trường dữ liệu

### Profile

| Tên trường | Ý nghĩa | Bắt buộc? | Định dạng hợp lệ | Ví dụ | Lưu ý |
|---|---|---|---|---|---|
| Name | Tên gợi nhớ | ✅ | String 1-200 ký tự | `tiktok-vn-01` | Nên có pattern để dễ tìm |
| Browser engine | Loại trình duyệt | ✅ | `chromium` / `firefox` | `chromium` | Firefox không có stealth patches |
| Platform | OS giả lập | ✅ | `windows` / `macos` / `linux` | `windows` | Khớp với User-Agent |
| Region | Khu vực worker | ❌ | Code trong `WORKER_REGIONS` env | `vn` | Mặc định kế thừa workspace |
| Proxy | Proxy gán | ❌ | UUID từ Proxy list | dropdown | Phải cùng workspace |
| Fingerprint seed | Cố định fingerprint | ❌ | Số nguyên 0-2^31 | `12345` | Để trống = random mỗi lần |
| Screen width | Chiều rộng màn hình | ❌ | Số 800-3840 | `1920` | Mặc định 1920 |
| Screen height | Chiều cao | ❌ | Số 600-2160 | `1080` | Mặc định 1080 |
| GPU vendor | Hãng GPU giả | ❌ | String | `Intel Inc.` | Phải khớp renderer |
| GPU renderer | Tên GPU giả | ❌ | String | `Intel Iris Plus Graphics 640` | |
| Hardware concurrency | Số CPU core giả | ❌ | Số 1-32 | `8` | |
| Timezone | Múi giờ | ❌ | IANA name | `Asia/Ho_Chi_Minh` | Auto fill nếu GeoIP=true |
| Locale | Ngôn ngữ | ❌ | BCP-47 | `vi-VN`, `en-US` | |
| User agent | UA string tuỳ chỉnh | ❌ | String | Mozilla/5.0... | Override mặc định |
| Humanize | Click/type tự nhiên | ❌ | Boolean | true | Bật cho website có anti-bot |
| Human preset | Mức humanize | ❌ | `default` / `careful` | `default` | Careful = chậm hơn, ít bị detect |
| GeoIP | Tự fill timezone theo IP proxy | ❌ | Boolean | true | Cần proxy có country ok |
| Clipboard sync | Sync clipboard với VNC | ❌ | Boolean | true | |
| Auto launch | Tự launch khi server restart | ❌ | Boolean | false | Cẩn thận với quota |
| Color scheme | Light/Dark | ❌ | `light`/`dark`/`no-preference` | `dark` | |
| Headless | Chạy không UI | ❌ | Boolean | false | Cho automation thuần |
| Launch args | Tham số CLI Chromium thêm | ❌ | List string | `["--disable-features=X"]` | Power user |
| Notes | Ghi chú nội bộ | ❌ | Text | `Tài khoản nhân viên A` | |
| Tags | Nhãn phân loại | ❌ | List string | `["client-x", "vn"]` | Để filter |

### Proxy

| Tên trường | Ý nghĩa | Bắt buộc? | Định dạng hợp lệ | Ví dụ | Lưu ý |
|---|---|---|---|---|---|
| Name | Tên gợi nhớ | ✅ | String 1-200 | `911-us-01` | |
| Type | Giao thức | ✅ | `http` / `https` / `socks5` | `http` | |
| Host | Server proxy | ✅ | IP hoặc tên miền | `192.168.1.1` | |
| Port | Port | ✅ | Số 1-65535 | `8080` | |
| Username | User auth | ❌ | String | `user_session-abc` | Một số provider có format đặc biệt |
| Password | Pass auth | ❌ | String | `pass123` | Auto encrypt Fernet |
| Provider | Loại provider | ❌ | `manual` / `911` / `brightdata` / `smartproxy` / `iproyal` | `manual` | Ảnh hưởng format username tự sinh khi rotating |
| Rotation URL | Endpoint xoay IP | ❌ | URL | `https://...` | Cho provider có rotation API |
| Sticky session | Session ID cố định | ❌ | String | `abc123` | Để IP không đổi trong cùng session |
| Country code | Quốc gia (auto detect) | ❌ | ISO-2 | `US`, `VN` | Health check tự fill |

### Automation

| Tên trường | Ý nghĩa | Bắt buộc? | Định dạng hợp lệ | Ví dụ |
|---|---|---|---|---|
| Name | Tên | ✅ | String 1-200 | `Đăng tweet hàng ngày` |
| Kind | Loại | ✅ | `flow` / `script` | `flow` |
| Description | Mô tả ngắn | ❌ | Text | `Crawl giá Shopee mỗi sáng` |

### Schedule

| Tên trường | Ý nghĩa | Bắt buộc? | Định dạng hợp lệ | Ví dụ | Lưu ý |
|---|---|---|---|---|---|
| Cron | Biểu thức cron | ✅ | 5 hoặc 6 phần | `0 9 * * *` | Test trên crontab.guru |
| Timezone | Múi giờ tính cron | ❌ | IANA | `Asia/Ho_Chi_Minh` | Mặc định UTC |
| Profile | Profile để chạy | ❌ | UUID | (dropdown) | Optional |
| Enabled | Bật/tắt | ❌ | Boolean | true | |

### Webhook

| Tên trường | Ý nghĩa | Bắt buộc? | Định dạng hợp lệ | Ví dụ |
|---|---|---|---|---|
| Name | Tên gợi nhớ | ❌ | String | `Zapier-Daily` |
| Profile | Profile khi trigger | ❌ | UUID | (dropdown) |

### API Key

| Tên trường | Ý nghĩa | Bắt buộc? | Định dạng hợp lệ | Ví dụ | Lưu ý |
|---|---|---|---|---|---|
| Name | Tên | ✅ | String 1-100 | `playwright-ci` | |
| Scopes | Phạm vi quyền | ❌ | List string | `["*"]` hoặc `["profile:read","profile:launch"]` | `*` = full |

---

## Phụ chú cuối

### Mâu thuẫn / chưa đủ thông tin được phát hiện
- **UI mời member workspace**: backend endpoint tồn tại nhưng vị trí UI chưa rõ trong tài liệu.
- **UI quản lý MFA**: API có nhưng không thấy component dedicated trong code đã đọc.
- **UI forgot password**: endpoint chưa thấy.
- **UI sort profile theo cột**: code chỉ filter, không thấy sort.
- **Banner VNPay trên Billing**: endpoint sẵn sàng nhưng UI có thể chưa add button.

### Khi giao diện thay đổi
Nếu phiên bản hệ thống của bạn khác mô tả trong tài liệu, vui lòng:
1. Đối chiếu version Frontend qua `Settings → About` (nếu có).
2. Liên hệ team support nội bộ để cập nhật tài liệu.
3. Tham khảo [ARCHITECTURE.md](./ARCHITECTURE.md) để xem roadmap thay đổi.

---

**Tài liệu này được biên soạn ngày 17/05/2026 dựa trên branch `claude/research-login-app-architecture-LNyv4` (88 commits).**
