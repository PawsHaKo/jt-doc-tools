#!/usr/bin/env bash
#
# setup-cf.sh — 在 production 伺服器上「一鍵」設好 Cloudflare Access 登入。
#
# 它會做掉手冊裡的第 3~5 步:產生 systemd drop-in override（改用 CF sidecar
# 進入點 + 補裝 PyJWT + 塞 CF 環境變數）、開啟認證、重啟服務。你不用手動進
# nano 貼設定。
#
# 用法（在伺服器上）:
#   1. 改下面三個 ★ 的值(用 nano 打字改即可,不用貼整段)
#   2. 執行:  bash setup-cf.sh      (會自動用 sudo 提權)
#
# 也可以不改檔、直接用環境變數帶值:
#   CF_TEAM_DOMAIN=mycompany CF_ACCESS_AUD=abc123 \
#   CF_ADMIN_EMAILS=alex.chang@concentrus.com bash setup-cf.sh
#
set -euo pipefail

# ============ ★ 改這三個值（從 Cloudflare 後台拿到） ============
CF_TEAM_DOMAIN="${CF_TEAM_DOMAIN:-請填團隊名}"          # 例: mycompany (→ mycompany.cloudflareaccess.com)
CF_ACCESS_AUD="${CF_ACCESS_AUD:-請填AUD}"               # Access Application 的 Audience tag
CF_ADMIN_EMAILS="${CF_ADMIN_EMAILS:-alex.chang@concentrus.com}"  # 逗號分隔;這些 email 首次登入給 admin
# ===============================================================

# 安裝路徑（預設 Linux 安裝位置;若你裝在別處請改）
INSTALL_DIR="${JTDT_INSTALL_DIR:-/opt/jt-doc-tools}"
SERVICE="jt-doc-tools"

# ---- 需要 root（寫 /etc/systemd + 重啟服務）→ 自動提權 ----
if [ "$(id -u)" -ne 0 ]; then
  echo "→ 需要 root,改用 sudo 重跑 ..."
  exec sudo -E CF_TEAM_DOMAIN="$CF_TEAM_DOMAIN" CF_ACCESS_AUD="$CF_ACCESS_AUD" \
       CF_ADMIN_EMAILS="$CF_ADMIN_EMAILS" JTDT_INSTALL_DIR="$INSTALL_DIR" \
       bash "$0" "$@"
fi

# ---- 檢查值有填 ----
fail=0
[ "$CF_TEAM_DOMAIN" = "請填團隊名" ] && { echo "✗ CF_TEAM_DOMAIN 還沒填"; fail=1; }
[ "$CF_ACCESS_AUD"  = "請填AUD" ]    && { echo "✗ CF_ACCESS_AUD 還沒填"; fail=1; }
[ "$fail" -eq 1 ] && { echo "請先改檔開頭的 ★ 三個值,或用環境變數帶入。"; exit 1; }

VENV_PY="$INSTALL_DIR/.venv/bin/python"
[ -x "$VENV_PY" ] || { echo "✗ 找不到 $VENV_PY (INSTALL_DIR 對嗎?)"; exit 1; }
[ -f "$INSTALL_DIR/run_cf.py" ] || { echo "✗ $INSTALL_DIR/run_cf.py 不存在 (CF 程式碼還沒部署?先 sudo jtdt update)"; exit 1; }

# ---- 1. 產生 systemd drop-in override ----
DROPIN_DIR="/etc/systemd/system/${SERVICE}.service.d"
DROPIN="$DROPIN_DIR/override.conf"
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN" <<EOF
[Service]
# 改用 CF sidecar 進入點(先清空原 ExecStart 再設新的)
ExecStart=
ExecStart=$VENV_PY -m run_cf

# uv sync 會清掉 PyJWT;每次啟動前,缺了才補裝(idempotent)
ExecStartPre=/bin/sh -c '$VENV_PY -c "import jwt" 2>/dev/null || ($VENV_PY -m ensurepip -U && $VENV_PY -m pip install -r $INSTALL_DIR/requirements-cf.txt)'

# Cloudflare Access 設定
Environment=CF_TEAM_DOMAIN=$CF_TEAM_DOMAIN
Environment=CF_ACCESS_AUD=$CF_ACCESS_AUD
Environment=CF_ADMIN_EMAILS=$CF_ADMIN_EMAILS
EOF
echo "✓ 已寫入 $DROPIN"

# ---- 2. 開啟認證後端(讓權限系統生效) ----
echo "→ 開啟本機認證後端 (jtdt auth set-local) ..."
jtdt auth set-local || echo "  (set-local 回非 0,可能已是 local;繼續)"

# ---- 3. 套用 + 重啟 ----
systemctl daemon-reload
echo "→ 重啟服務 ..."
systemctl restart "$SERVICE"
sleep 2

echo
echo "================ 完成 ================"
echo "驗證:"
echo "  1) jtdt logs -f   → 應看到 'cf_wrap active: Cloudflare Access enforced'"
echo "  2) 用瀏覽器開你的 CF 網域 → 走 Cloudflare 登入 → 回到 app"
echo "  3) 你的 email ($CF_ADMIN_EMAILS) 首次登入應為 admin"
echo
echo "救援(萬一被鎖在外):  sudo jtdt auth disable && sudo jtdt restart"
echo "目前服務狀態:"
systemctl --no-pager --lines=5 status "$SERVICE" || true
