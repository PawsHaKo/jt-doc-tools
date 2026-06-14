# Cloudflare Zero Trust 登入 — Sidecar 實作計畫

> 目標:用 Cloudflare Access(Zero Trust)在邊緣驗證身分,把驗過的 email 當帳號帶進
> 本 app,**完全不修改既有檔案**(只新增檔案 + 改部署進入點),讓上游 commit 永遠
> 能乾淨 rebase。

---

## 0. 設計原則(為什麼這樣做)

1. **只新增檔案** → 上游 rebase 永不衝突(見 `update-from-upstream.sh`)。
2. **用 `app.add_middleware()` 掛 middleware**,不用外層 ASGI 包裝 → `request.state.user`
   跟現有 `_auth_gate` 共用 scope 的機制是同一套,穩定可靠。
3. **CF 使用者存成 `source='local'` + `password_hash=NULL`** → 通過現有
   `CHECK (source IN ('local','ldap','ad'))`,**不需要 DB migration**。
4. **唯一的「穩定假設」**:`_auth_gate` 第 ~656 行的短路
   ```python
   bearer_user = getattr(request.state, "user", None)
   if bearer_user: user = bearer_user      # 跳過 cookie 檢查
   ```
   只要這行在,sidecar 就成立。哪天上游改掉它,`update-from-upstream.sh` 不會報錯
   (因為我們沒改那檔),但功能會壞 → 在測試階段就會發現。把這行記成「監看點」。

---

## 1. 檔案清單(全部新增)

| 檔案 | 性質 | 內容 |
|---|---|---|
| `app/core/auth_cf.py` | 新檔 | JWT 驗證(JWKS 快取)、provisioning(建/查 CF 使用者)、admin email 對應 |
| `app/cf_wrap.py` | 新檔 | `from app.main import app` → `app.add_middleware(CF middleware)` → re-export `app` |
| `requirements-cf.txt` | 新檔 | 額外依賴(`PyJWT[crypto]`),不動 `requirements.txt` / `pyproject.toml` |
| `run_cf.py` | 新檔(可選) | 本機跑用:`uvicorn.run("app.cf_wrap:app", ...)` |
| `docs/CF_SIDECAR_PLAN.md` | 本檔 | 計畫文件 |

**唯一非新增的改動:部署進入點** 從 `app.main:app` 改指到 `app.cf_wrap:app`
(systemd unit / install 設定 / `run_cf.py`),這是**部署設定**,不是會被 merge 的原始碼。

---

## 2. 元件細節

### 2.1 `app/core/auth_cf.py`

職責三塊:

**(a) JWT 驗證**
- CF Access 在每個 request 帶 `Cf-Access-Jwt-Assertion` header(或 `CF_Authorization` cookie)。
- 用團隊 JWKS 驗章:`https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`
- 用 `PyJWKClient` 自動抓 + 快取 signing key:
  ```python
  import jwt
  from jwt import PyJWKClient

  _jwks = PyJWKClient(f"https://{TEAM}.cloudflareaccess.com/cdn-cgi/access/certs")

  def verify(token: str) -> dict:
      key = _jwks.get_signing_key_from_jwt(token).key
      return jwt.decode(
          token, key, algorithms=["RS256"],
          audience=AUD,                                    # CF Access App 的 AUD tag
          issuer=f"https://{TEAM}.cloudflareaccess.com",
      )  # 失敗會丟 jwt.InvalidTokenError → middleware 視為未驗證
  ```
- email 取自 `claims["email"]`;顯示名可用 `claims.get("name") or email`。

**(b) Provisioning**(模式抄 `auth_ldap._sync_user`,但寫在新檔)
```python
def provision(email: str, display: str) -> dict:
    conn = auth_db.conn()
    row = conn.execute(
        "SELECT id, enabled FROM users WHERE username=? AND source='local'",
        (email,)).fetchone()
    now = time.time()
    if row:
        if not row["enabled"]:
            raise CFAuthError("帳號已停用")
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, row["id"]))
        uid = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO users(username, display_name, password_hash, source, "
            " enabled, is_admin_seed, created_at, last_login_at) "
            "VALUES (?,?,NULL,'local',1,0,?,?)", (email, display or email, now, now))
        uid = cur.lastrowid
        role = "admin" if email.lower() in ADMIN_EMAILS else "default-user"
        permissions.set_subject_roles("user", str(uid), [role])
    return {"user_id": uid, "username": email,
            "display_name": display or email, "source": "local"}
```
- `password_hash=NULL` → 沒人能用密碼表單登入這帳號(`verify_password(pw, None)` 回 False)。
- **首位 admin 用環境變數** `CF_ADMIN_EMAILS`(逗號分隔)bootstrap;之後在
  `/admin/permissions` 正常指派角色。

**(c) 設定來源**:直接讀 `os.environ`(不動 `config.py`)
- `CF_TEAM_DOMAIN`(例 `mycompany`,組成 `mycompany.cloudflareaccess.com`)
- `CF_ACCESS_AUD`(Access Application Audience tag)
- `CF_ADMIN_EMAILS`(可選)

### 2.2 `app/cf_wrap.py`(掛 middleware)

```python
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from app.main import app                      # 跑完整個 main.py(含所有 @app.middleware)
from app.core import auth_cf

_PUBLIC = ("/static/", "/healthz", "/favicon", "/branding/", "/api/")
# /api/ 放行 → 交給內層 _api_token_gate 用 Bearer token 把關(API 呼叫者沒有 CF JWT)

@app.middleware("http")          # 此刻加 → 疊在最外層 → 最先執行(早於 _auth_gate)
async def _cf_access(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in _PUBLIC):
        return await call_next(request)
    # 登出 → 導去 CF 邊緣登出,否則 CF 會立刻重新登入
    if path == "/logout":
        return RedirectResponse("/cdn-cgi/access/logout", status_code=302)

    token = (request.headers.get("Cf-Access-Jwt-Assertion")
             or request.cookies.get("CF_Authorization", ""))
    try:
        claims = auth_cf.verify(token)
        user = auth_cf.provision(claims["email"], claims.get("name", ""))
    except Exception:
        # 沒 JWT / 驗不過 = 沒經過 CF(可能有人直接打 origin)→ fail closed
        return JSONResponse({"detail": "Cloudflare Access 驗證失敗"}, status_code=403)

    request.state.user = user        # 內層 _auth_gate 的 bearer 短路會直接採用
    return await call_next(request)

# uvicorn 指這個檔:`uvicorn app.cf_wrap:app`
```

執行順序(驗證過):後加的 middleware 最外層 → `_cf_access` 先跑,設好 `request.state.user`,
接著 `_api_token_gate` → `_auth_gate`(看到 user 已設,跳過 cookie)→ per-tool 權限照常 → handler。

### 2.3 後端開關

backend 設 **`local`**(讓 `_auth_gate` 生效、per-tool 權限生效,但**不會**跑 LDAP):
```bash
sudo jtdt auth set-local        # 或在 /admin/auth-settings 啟用本機認證
```
- backend 必須非 `off`,否則 `_auth_gate` 整個放行、沒有 per-user 身分。
- 選 `local` 而非 `ldap/ad`:CF 已負責身分,app 不該再連 AD。
- 既有的 `jtdt-admin`(source=local)與 CF 使用者(source=local、不同 username)並存,互不干擾。

---

## 3. 必須拍板的 4 個決策點

| # | 議題 | 建議 |
|---|---|---|
| 1 | **Origin 防護** | CF Tunnel(`cloudflared`)讓 origin 只收 CF 流量;或防火牆只放 CF IP。**沒做的話 header 可被偽造,整個方案失守**——最高優先。 |
| 2 | **救援路徑** | 另起一個**不經 CF**、只綁 `127.0.0.1` 的實例,用**原始**進入點 `app.main:app`(無 CF wrapper),以 `jtdt-admin` + 密碼登入救援;或 server 端 `sudo jtdt auth disable`。 |
| 3 | **登出** | wrapper 攔 `/logout` → 導 `/cdn-cgi/access/logout`(已含在 2.2)。 |
| 4 | **2FA / 稽核員強制 MFA** | 信任 proxy 模式會**繞過** app 內 TOTP 流程(CF 使用者不走 `/login` POST)。若合規要求稽核員 MFA,改在 **CF Access 政策**對該應用強制 MFA / 硬體金鑰,app 端 TOTP 在此模式下不可靠。 |

---

## 4. 部署

1. 安裝額外依賴:`pip install -r requirements-cf.txt`
2. 設環境變數:
   ```
   CF_TEAM_DOMAIN=mycompany
   CF_ACCESS_AUD=<Access Application 的 AUD tag>
   CF_ADMIN_EMAILS=alex.chang@concentrus.com
   ```
3. 進入點改指 `app.cf_wrap:app`(systemd `ExecStart` / `run_cf.py`)。
4. Cloudflare 端:
   - 建 Access Application 指向本服務網域,記下 **AUD tag**。
   - 設身分提供者(可接 **Microsoft Entra ID** → 你們的微軟登入就在這層發生)。
   - 用 `cloudflared` tunnel 連 origin(順帶完成決策點 1 的 origin 防護)。

---

## 5. 測試計畫

1. **單元**:`auth_cf.verify` 對偽造 / 過期 / aud 不符的 token 一律丟例外。
2. **provisioning**:新 email → 建 row + default-user;`CF_ADMIN_EMAILS` 內 → admin;
   既有 email → 不重複建、更新 last_login;停用帳號 → 擋。
3. **短路假設**:帶合法 JWT 打 `/tools/<某工具>/` → 200;default-user 打沒權限工具 → 403;
   打 `/admin/` → 403(非 admin)。**這步驗證 `request.state.user` 短路仍有效**。
4. **fail closed**:不帶 JWT 直打 origin → 403。
5. **登出**:`/logout` → 302 到 `/cdn-cgi/access/logout`。
6. **救援**:停掉 CF,用 127.0.0.1 + `app.main:app` 以 jtdt-admin 登入成功。

---

## 6. 維護

- 例行更新:`./update-from-upstream.sh --check` 看會不會衝突 → `./update-from-upstream.sh`。
- 因為只新增檔案,正常情況**永遠綠燈**。若哪天紅燈 → 代表不小心改到既有檔,把那段邏輯搬回新檔。
- **唯一監看點**:`app/main.py` 的 `_auth_gate` `bearer_user` 短路。上游若重構認證 middleware,
  跑一次第 5 節第 3 步即可確認 sidecar 還活著。

---

## 7. 工作量estimate

| 項目 | 估時 |
|---|---|
| `auth_cf.py`(JWT + JWKS 快取 + provisioning) | 0.5–1 天 |
| `cf_wrap.py` + `run_cf.py` + `requirements-cf.txt` | 0.5 天 |
| Cloudflare Access + tunnel + origin 防護設定 | 0.5 天 |
| 測試(含救援演練) | 0.5 天 |
| **合計** | **約 2–2.5 天** |
