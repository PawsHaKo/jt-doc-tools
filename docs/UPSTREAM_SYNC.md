# 上游同步 + 部署更新手冊（fork 維護）

本專案是原作者開源專案的 fork。客製功能（如 Cloudflare Access 登入）以
**「只新增檔案」的 sidecar** 方式實作,目的就是讓上游 commit 永遠能乾淨 rebase。

> ⚠️ 有「兩個更新」,別混淆:
> - **開發端更新**:把**原作者**的新 commit 合進你的碼 → `update-from-upstream.sh`
> - **production 端更新**:把你的碼部署到伺服器 → `sudo jtdt update`
>
> 兩者是不同機器、不同工作,中間交會點是 **`origin/main`**。

---

## 分支 / remote 模型

| 角色 | 內容 | 規則 |
|---|---|---|
| 本機 `main` | **上游碼 + 你的 CF sidecar 客製** | 你開發 & rebase 都在這;客製就活在 main |
| `upstream` remote | **原作者** repo（jasoncheng7115） | 只讀,拿上游新 commit |
| `origin` remote | **你的 fork**（PawsHaKo） | 你 push 客製、production 從這拉 |

> **為什麼客製放 `main` 而不是獨立分支?**
> production 的 `sudo jtdt update` 寫死做 `git reset --hard origin/main`（見 `app/cli.py`）,
> 只認 `origin/main`。所以你要部署的東西最後一定要落在 `origin/main`。最省事就是
> 客製直接活在 `main`。對「用 jtdt update 部署的 fork」而言,main = 上游 + 客製 是常態。
>
> 客製「只新增檔案、不改既有檔」是整個流程能無痛的前提 —— 新增檔上游永遠不會碰,
> rebase 不可能衝突。詳見 `docs/CF_SIDECAR_PLAN.md`。

```
【你的電腦 = 開發】
  upstream (jasoncheng7115/main) ─┐
                                  ├─ update-from-upstream.sh（rebase）
  你的 CF 新檔                  ─┘
        │ git push --force-with-lease origin main
        ▼
【origin = 你的 fork (PawsHaKo) main】 = 上游碼 + CF 客製
        │ sudo jtdt update → git reset --hard origin/main
        ▼
【production 伺服器】
```

---

## 一次性設定（只做一次）

```bash
# 1. 加上游 remote（指向原作者,不是你的 fork）
git remote add upstream https://github.com/jasoncheng7115/jt-doc-tools.git

# 2. 把更新腳本最上面的 UPSTREAM_URL 改成同一個 URL（與步驟 1 二擇一即可）
#    編輯 update-from-upstream.sh：
#        UPSTREAM_URL="https://github.com/jasoncheng7115/jt-doc-tools.git"

# 3. 確認 remote
git remote -v
#    應看到 origin（你的 fork）+ upstream（原作者）兩組
```

---

## 開發端:合上游新版（在本機 `main` 上）

```bash
git switch main
git status                        # 應為 clean;有改動先 commit 或 stash

# 1. 預檢:這次合上游會不會衝突?（完全不動你的分支,只報告）
./update-from-upstream.sh --check

# 2. 確認綠燈後,真的 rebase 到 upstream 最新
./update-from-upstream.sh

# 3. 推到你的 fork（production 之後就從這裡拉）
git push --force-with-lease origin main
#    第一次推用：git push -u origin main
```

腳本會自動:抓 upstream、列新 commit、**先建 backup 分支**（`backup/main-<時間>`）、
用 rebase 把客製重放到上游最新版之上。

> 因為只新增檔案,`--check` 正常情況**永遠綠燈**。若紅燈 → 代表不小心改到既有檔,
> 腳本會指出是哪個檔,把那段搬回 sidecar 新檔即可。

---

## production 端:部署更新

```bash
sudo jtdt update
```

它會自動:停服務 → 備份 `data/`（留最近 3 份）→ `git fetch` →
**`git reset --hard origin/main`** → `uv sync` → 重啟 → 健康檢查。

因為 production 的 `origin` 指向你的 fork,這條就會把伺服器對齊到你 fork 的 `main`
（含 CF 客製）。`reset --hard` 本來就是為「remote 被 force-push 改寫歷史」設計的,
所以開發端 force-push 後 production 照拉無虞。

### production 機器上的一次性 override（用 systemd drop-in,不碰 repo）

`jtdt update` 預設用 `app.main` 啟動、`uv sync` 會清掉 `PyJWT`。要跑 CF 版需在伺服器上
做一次性覆寫（這些是機器設定,不是 repo 程式碼,不影響 rebase）:

```bash
sudo systemctl edit jt-doc-tools     # 建立 drop-in override
```
填入:
```ini
[Service]
# 1. 改用 CF sidecar 進入點
ExecStart=
ExecStart=/opt/jt-doc-tools/.venv/bin/python -m run_cf
# 2. 每次啟動前補裝 PyJWT（uv sync 會把它清掉）
ExecStartPre=/opt/jt-doc-tools/.venv/bin/python -m pip install -r /opt/jt-doc-tools/requirements-cf.txt
# 3. CF 環境變數
Environment=CF_TEAM_DOMAIN=你的team
Environment=CF_ACCESS_AUD=你的AUD
Environment=CF_ADMIN_EMAILS=alex.chang@concentrus.com
```
（路徑 `/opt/jt-doc-tools` 請換成實際 INSTALL_DIR;改完 `sudo systemctl daemon-reload && sudo jtdt restart`。）

---

## 為什麼推送要 `--force-with-lease`

rebase 會**改寫 commit 歷史**,遠端舊歷史對不上,一般 `git push` 會被擋。
`--force-with-lease` 是「安全版 force」:只有遠端沒有別人新推東西時才覆蓋,
避免蓋掉協作者的 commit（單人維護尤其安全)。

---

## 出現衝突時（理論上不該發生）

正常情況只新增檔案,`--check` 永遠綠燈。若紅燈 = 你不小心改到既有檔,腳本會列出哪個檔。
最佳解:把那段邏輯搬回 sidecar 新檔,讓既有檔回到上游原狀。

當場解:
```bash
git add <衝突檔>
git rebase --continue     # 解完繼續
# 或
git rebase --abort        # 放棄這次,回到 rebase 前
```

---

## 回復（更新後發現怪怪的）

```bash
git reflog
git reset --hard <commit 或 backup 分支>
# 例：git reset --hard backup/main-20260614-1530
```
