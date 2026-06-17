#!/usr/bin/env bash
#
# update-from-upstream.sh — 把原作者 (upstream) 的最新 commit rebase 進你的
# fork,並在動手前先檢查會不會衝突。
#
# 在你的客製分支 `main` 上執行(客製就活在 main;production 的 jtdt update 讀
# origin/main)。腳本會 rebase「目前所在分支」,所以請先 git switch main。
# 詳見 docs/UPSTREAM_SYNC.md。
#
# 設計前提:CF 登入是 sidecar,改動「只新增檔案、不改既有檔」,所以
# rebase 幾乎永遠乾淨。這支腳本做三件事:
#   1. 抓 upstream 最新狀態
#   2. (預設) 先「試跑」一次 rebase 看會不會衝突 —— 不動你的分支
#   3. 確認乾淨後才真的 rebase;不乾淨就清楚告訴你是哪幾個檔案撞到
#
# 用法:
#   ./update-from-upstream.sh --check     # 只檢查會不會衝突,什麼都不改
#   ./update-from-upstream.sh             # 真的更新 (前面會自動先檢查)
#   UPSTREAM_REF=v1.12.0 ./update-from-upstream.sh   # rebase 到某個 tag 而非 main
#
set -euo pipefail

# ---------- 設定 (請填上原作者 repo) ----------
UPSTREAM_REMOTE="upstream"
UPSTREAM_URL="https://github.com/jasoncheng7115/jt-doc-tools.git"   # ← 改成原作者的 repo URL
UPSTREAM_REF="${UPSTREAM_REF:-main}"                            # 要追的上游分支或 tag

# ---------- 顏色 ----------
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
grn()   { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()   { printf '\033[33m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n'  "$*"; }

# ---------- 前置檢查 ----------
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { red "✗ 不在 git repo 裡"; exit 1; }

WORK_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$WORK_BRANCH" != "HEAD" ] || { red "✗ 目前是 detached HEAD,請先 git checkout 你的分支"; exit 1; }

# 工作目錄必須乾淨 (避免 rebase 把未存檔的改動搞丟)
if ! git diff --quiet || ! git diff --cached --quiet; then
  red "✗ 工作目錄有未 commit 的改動,請先 commit 或 stash 後再跑"
  git status --short
  exit 1
fi

# upstream remote 不存在就自動加 (需先填好 UPSTREAM_URL)
if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  if [[ "$UPSTREAM_URL" == *REPLACE_ME* ]]; then
    red "✗ 還沒設定 upstream。請編輯本檔最上面的 UPSTREAM_URL,或手動執行:"
    echo "    git remote add $UPSTREAM_REMOTE <原作者 repo URL>"
    exit 1
  fi
  ylw "→ 第一次執行,加入 upstream remote: $UPSTREAM_URL"
  git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
fi

# ---------- 抓 upstream ----------
bold "→ 抓取 $UPSTREAM_REMOTE ..."
git fetch --tags "$UPSTREAM_REMOTE"

UPSTREAM="$UPSTREAM_REMOTE/$UPSTREAM_REF"
git rev-parse --verify "$UPSTREAM" >/dev/null 2>&1 || { red "✗ 找不到 $UPSTREAM (分支/tag 名打錯?)"; exit 1; }

# 已經是最新 → 直接結束
BEHIND="$(git rev-list --count "HEAD..$UPSTREAM")"
if [ "$BEHIND" -eq 0 ]; then
  grn "✓ 已經是最新,沒有新的上游 commit 要合。"
  exit 0
fi

bold "→ upstream 有 $BEHIND 個新 commit:"
git log --oneline --no-decorate "HEAD..$UPSTREAM" | sed 's/^/    /' | head -20
echo

# ---------- 試跑 rebase (在拋棄式分支上,不動你的工作分支) ----------
trial_branch="_upstream_trial_$$"
cleanup_trial() {
  git rebase --abort >/dev/null 2>&1 || true
  git checkout --quiet "$WORK_BRANCH" >/dev/null 2>&1 || true
  git branch -D "$trial_branch" >/dev/null 2>&1 || true
}

bold "→ 試跑 rebase 檢查衝突 (不會改到 $WORK_BRANCH) ..."
git branch --quiet "$trial_branch" "$WORK_BRANCH"

if git rebase --quiet "$UPSTREAM" "$trial_branch" >/dev/null 2>&1; then
  CONFLICT=0
  grn "✓ 乾淨,沒有衝突。"
else
  CONFLICT=1
  red "⚠ 偵測到衝突,以下檔案需要手動處理:"
  git diff --name-only --diff-filter=U | sed 's/^/    - /'
fi
cleanup_trial

# ---------- --check 模式:只報告,不動手 ----------
if [ "${1:-}" = "--check" ]; then
  echo
  if [ "$CONFLICT" -eq 0 ]; then
    grn "可以安全更新 → 直接執行 ./update-from-upstream.sh"
  else
    ylw "更新會有衝突。執行 ./update-from-upstream.sh 後依指示解決。"
  fi
  exit "$CONFLICT"
fi

# ---------- 真的 rebase ----------
# 先存一個 backup 分支,出事隨時 git reset --hard 回來
BACKUP="backup/${WORK_BRANCH}-$(date +%Y%m%d-%H%M%S)"
git branch "$BACKUP"
bold "→ 已建立備份分支: $BACKUP"

bold "→ 開始 rebase $WORK_BRANCH 到 $UPSTREAM ..."
if git rebase "$UPSTREAM"; then
  NEW_VER="$(git show "$UPSTREAM:app/main.py" 2>/dev/null | grep -m1 'VERSION = ' || true)"
  echo
  grn "✓ 更新完成!你的改動已重放到上游最新版之上。"
  [ -n "$NEW_VER" ] && echo "    上游版本: ${NEW_VER#*VERSION = }"
  echo "    備份在 $BACKUP (確認沒問題後可 git branch -D 刪掉)"
  echo "    若有推到遠端,因為 rebase 改寫了歷史,需要 git push --force-with-lease"
else
  echo
  red "⚠ rebase 過程中出現衝突 (理論上不該發生 — 你動到既有檔了?)"
  echo "    衝突檔案:"
  git diff --name-only --diff-filter=U | sed 's/^/      - /'
  echo
  ylw "  接下來你可以二選一:"
  echo "    A) 解決衝突:編輯上面的檔 → git add <檔> → git rebase --continue"
  echo "    B) 放棄這次更新:git rebase --abort   (會回到 rebase 前的狀態)"
  echo
  echo "    不論如何,更新前的完整備份都在分支 $BACKUP"
  exit 1
fi
