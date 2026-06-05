"""逐句翻譯：admin 可設定句數上限 + 分頁大小，前端分頁。

對應功能（v1.11.69）：
- llm_settings 新增 translate_max_sentences / translate_page_size（預設 20000 / 200）
- /extract-text 截斷改吃 admin 設定（非寫死 800）
- admin /api/llm/settings 對兩欄位 clamp 防呆
- translate-doc 頁面注入 TRD_MAX_SENTENCES / TRD_PAGE_SIZE + 分頁 UI
"""
from __future__ import annotations

import io


def _restore_llm(orig: dict):
    from app.core.llm_settings import llm_settings
    llm_settings.update({
        "translate_max_sentences": orig.get("translate_max_sentences", 20000),
        "translate_page_size": orig.get("translate_page_size", 200),
    })


def test_split_merges_punct_only_fragments():
    """PDF 目錄點引導符被切成獨立「.」碎片 → 併入前一句，不各佔一列。"""
    import importlib
    r = importlib.import_module("app.tools.translate_doc.router")
    # 一堆獨立的點 → 併入前一句，只剩一列
    assert r._split_sentences("Section Title .\n.\n.\n.\n.") == ["Section Title ."]
    # 句尾多餘的孤立點 → 丟棄（前句已以句點結尾）
    assert r._split_sentences("Hello world. This is a test. .") == [
        "Hello world.", "This is a test."]
    # 開頭的純標點碎片 → 丟棄
    assert r._split_sentences(". . .\nReal sentence here.") == ["Real sentence here."]
    # 正常內容不受影響
    assert r._split_sentences("First. Second.") == ["First.", "Second."]


def test_llm_settings_translate_defaults():
    from app.core.llm_settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["translate_max_sentences"] >= 1000
    assert 20 <= DEFAULT_SETTINGS["translate_page_size"] <= 5000


def test_extract_text_respects_admin_max(client):
    from app.core.llm_settings import llm_settings
    orig = llm_settings.get()
    try:
        llm_settings.update({"translate_max_sentences": 3})
        text = "".join(f"Sentence number {i}.\n" for i in range(10))
        files = {"file": ("doc.txt", io.BytesIO(text.encode("utf-8")), "text/plain")}
        r = client.post("/tools/translate-doc/extract-text", files=files)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["sentence_count"] == 10           # 偵測到 10 句
        assert len(j["sentences"]) == 3            # 只回前 3 句
        assert j["truncated"] is True
        assert j["max_sentences"] == 3
    finally:
        _restore_llm(orig)


def test_extract_text_no_truncate_under_limit(client):
    from app.core.llm_settings import llm_settings
    orig = llm_settings.get()
    try:
        llm_settings.update({"translate_max_sentences": 5000})
        text = "One. Two. Three."
        files = {"file": ("doc.txt", io.BytesIO(text.encode("utf-8")), "text/plain")}
        r = client.post("/tools/translate-doc/extract-text", files=files)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["truncated"] is False
        assert len(j["sentences"]) == j["sentence_count"]
    finally:
        _restore_llm(orig)


def test_admin_llm_save_clamps_translate_fields(client):
    from app.core.llm_settings import llm_settings
    orig = llm_settings.get()
    try:
        # 超大 / 過小 → 應 clamp 到合法範圍，不會原樣寫入
        r = client.post("/admin/api/llm/settings", json={
            "translate_max_sentences": 9_999_999,   # > 200000
            "translate_page_size": 1,                # < 20
            "translate_concurrency": 999,            # > 64
        })
        assert r.status_code == 200, r.text
        s = llm_settings.get()
        assert s["translate_max_sentences"] == 200000
        assert s["translate_page_size"] == 20
        assert s["translate_concurrency"] == 64
        # 非數值 → 丟棄不覆寫（保留原值）
        before = llm_settings.get()["translate_page_size"]
        r2 = client.post("/admin/api/llm/settings",
                         json={"translate_page_size": "abc"})
        assert r2.status_code == 200
        assert llm_settings.get()["translate_page_size"] == before
    finally:
        _restore_llm(orig)


def test_translate_doc_page_injects_pagination(client):
    from app.core.llm_settings import llm_settings
    orig = llm_settings.get()
    try:
        # 必須先啟用 LLM，否則整個工具 UI 被 llm_gate 隱藏成 placeholder，
        # 注入的常數就不會出現在頁面上。
        llm_settings.update({"enabled": True,
                             "translate_max_sentences": 12345,
                             "translate_page_size": 150})
        r = client.get("/tools/translate-doc/")
        assert r.status_code == 200
        body = r.text
        assert "TRD_MAX_SENTENCES = 12345" in body
        assert "TRD_PAGE_SIZE = Math.max(1, 150)" in body
        assert 'id="trdPager"' in body
        assert "function renderPage" in body
        assert "function _trdPairAt" in body   # copy/export 讀資料陣列
    finally:
        llm_settings.update({"enabled": orig.get("enabled", False)})
        _restore_llm(orig)
