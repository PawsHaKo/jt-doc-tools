"""CSS theme presets for markdown-to-doc rendering.

Each theme defines a full <style> block applied to the rendered HTML before
soffice converts it to PDF / DOCX / ODT. All themes are designed to be
print-friendly (light backgrounds, dark text), since they target paper-output
formats.

Web font stacks list CJK fonts first (PingFang TC / Microsoft JhengHei /
Noto CJK) so Chinese content always picks a readable font on whatever the
host has installed.
"""
from __future__ import annotations

# Shared base used by every theme — resets, code styling, table baseline,
# print page setup. Theme-specific colours / fonts come on top.
_BASE = """
@page { size: A4; margin: 22mm 20mm 22mm 20mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  line-height: 1.7;
  font-size: 11pt;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
h1, h2, h3, h4, h5, h6 {
  line-height: 1.3; margin: 1.4em 0 0.6em;
  font-weight: 700;
}
h1 { font-size: 24pt; }
h2 { font-size: 18pt; }
h3 { font-size: 15pt; }
h4 { font-size: 13pt; }
h5 { font-size: 12pt; }
h6 { font-size: 11pt; opacity: 0.85; }
p { margin: 0.7em 0; }
ul, ol { margin: 0.6em 0; padding-left: 1.6em; }
li { margin: 0.25em 0; }
li > p { margin: 0.3em 0; }
code, kbd, samp {
  font-family: 'SF Mono', 'JetBrains Mono', Menlo, Consolas,
               'Liberation Mono', monospace;
  font-size: 0.88em;
}
pre {
  padding: 12pt 14pt; border-radius: 5pt;
  overflow-x: auto;
  font-size: 9.5pt; line-height: 1.55;
  margin: 0.8em 0;
  page-break-inside: avoid;
}
pre code { background: transparent !important; padding: 0; font-size: inherit; }
table { border-collapse: collapse; margin: 0.8em 0; width: auto; }
th, td { padding: 5pt 10pt; vertical-align: top; }
img { max-width: 100%; }
hr { border: 0; margin: 1.4em 0; }
blockquote {
  margin: 0.8em 0; padding: 4pt 14pt;
  page-break-inside: avoid;
}
blockquote > :first-child { margin-top: 0; }
blockquote > :last-child { margin-bottom: 0; }
a { text-decoration: none; }
a:hover { text-decoration: underline; }
"""

# Heading-anchor / footnote helpers
_EXTRAS = """
sup.fn-ref a { font-size: 0.75em; vertical-align: super; text-decoration: none; }
.task-list-item { list-style: none; }
.task-list-item input { margin-right: 6px; }
"""

THEMES: dict[str, dict] = {
    "classic": {
        "name": "清爽（預設）",
        "desc": "白底、藍色標題、暗灰內文，閱讀舒適、列印俐落。",
        "css": _BASE + _EXTRAS + """
body {
  font-family: 'Noto Sans TC', -apple-system, 'PingFang TC',
               'Microsoft JhengHei', sans-serif;
  color: #1e293b; background: #ffffff;
}
h1 { color: #1e3a8a; border-bottom: 3px solid #3b82f6; padding-bottom: 6pt; }
h2 { color: #1e40af; border-bottom: 1px solid #cbd5e1; padding-bottom: 3pt; }
h3 { color: #1d4ed8; }
h4, h5, h6 { color: #334155; }
strong { color: #0f172a; }
a { color: #2563eb; }
code { background: #f1f5f9; color: #be185d; padding: 1pt 5pt; border-radius: 3pt; }
pre { background: #1e293b; color: #e2e8f0; }
table { font-size: 10.5pt; }
th { background: #eff6ff; color: #1e3a8a; border: 1px solid #93c5fd; }
td { border: 1px solid #cbd5e1; }
blockquote { background: #f8fafc; border-left: 4px solid #94a3b8; color: #475569; }
hr { border-top: 1px dashed #cbd5e1; }
""",
    },
    "github": {
        "name": "GitHub 風",
        "desc": "模擬 GitHub README 樣式，工程師熟悉的灰白配色。",
        "css": _BASE + _EXTRAS + """
body {
  font-family: -apple-system, 'Segoe UI', 'Noto Sans TC',
               'PingFang TC', 'Microsoft JhengHei', sans-serif;
  color: #24292f; background: #ffffff;
}
h1 { color: #1f2328; border-bottom: 1px solid #d0d7de; padding-bottom: 6pt; }
h2 { color: #1f2328; border-bottom: 1px solid #d0d7de; padding-bottom: 4pt; }
h3, h4, h5, h6 { color: #1f2328; }
a { color: #0969da; }
code { background: rgba(175, 184, 193, 0.2); color: #cf222e; padding: 1pt 6pt; border-radius: 3pt; }
pre { background: #f6f8fa; color: #24292f; border: 1px solid #d0d7de; }
pre code { color: inherit; }
table th { background: #f6f8fa; border: 1px solid #d0d7de; }
table td { border: 1px solid #d0d7de; }
blockquote { background: #f6f8fa; border-left: 4px solid #d0d7de; color: #59636e; }
hr { border-top: 1px solid #d0d7de; }
""",
    },
    "academic": {
        "name": "學術論文（襯線）",
        "desc": "Times-style 襯線字、保守配色，適合論文 / 公文 / 法規。",
        "css": _BASE + _EXTRAS + """
@page { margin: 25mm 22mm; }
body {
  font-family: 'Source Han Serif TC', 'Noto Serif TC',
               'Times New Roman', 'PingFang TC', serif;
  color: #1c1c1c; background: #ffffff;
  font-size: 11pt; line-height: 1.85;
  text-align: justify;
}
h1 { font-size: 22pt; text-align: center; margin: 1em 0 1em; color: #1c1c1c; }
h2 { color: #1c1c1c; border-bottom: 1.5px solid #1c1c1c; padding-bottom: 3pt; }
h3 { color: #2c2c2c; }
strong { font-weight: 700; }
a { color: #1c1c1c; text-decoration: underline; }
code { background: #f4f4f4; padding: 1pt 5pt; border: 1px solid #d4d4d4; border-radius: 2pt; font-size: 0.9em; }
pre { background: #f9f9f9; color: #1c1c1c; border: 1px solid #d4d4d4; }
table { font-size: 10.5pt; margin: 1em auto; }
th, td { border-top: 1px solid #1c1c1c; border-bottom: 1px solid #1c1c1c; }
th { border-bottom: 1.5px solid #1c1c1c; background: transparent; }
blockquote { border-left: 3px solid #444; color: #444; font-style: italic; background: transparent; }
hr { border-top: 1px solid #1c1c1c; }
""",
    },
    "book": {
        "name": "書籍 / 暖色",
        "desc": "米色紙底、棕色標題、襯線字。閱讀感舒適，適合報告 / 書本印刷。",
        "css": _BASE + _EXTRAS + """
@page { margin: 24mm 24mm; }
body {
  font-family: 'Noto Serif TC', 'Source Han Serif TC',
               Georgia, 'PingFang TC', serif;
  color: #3d2914; background: #fbf6ec;
  line-height: 1.85;
}
h1 { color: #8b4513; border-bottom: 3px double #8b4513; padding-bottom: 6pt; text-align: center; }
h2 { color: #a0522d; }
h3 { color: #b8743f; }
h4, h5, h6 { color: #6f3a1e; }
strong { color: #6f3a1e; }
a { color: #8b4513; }
code { background: #f0e6d4; color: #8b3a00; padding: 1pt 5pt; border-radius: 3pt; }
pre { background: #f3e9d5; color: #3d2914; border: 1px solid #c9a87e; }
pre code { color: inherit; }
table { font-size: 10.5pt; }
th { background: #efe1c5; color: #6f3a1e; border: 1px solid #c9a87e; }
td { border: 1px solid #c9a87e; }
blockquote { background: #f3e9d5; border-left: 4px solid #b8743f; color: #6f3a1e; font-style: italic; }
hr { border-top: 1px solid #c9a87e; }
""",
    },
    "report": {
        "name": "商務報告",
        "desc": "深藍標題、灰色強調、嚴謹清晰，適合對外提案 / 季報。",
        "css": _BASE + _EXTRAS + """
body {
  font-family: 'Noto Sans TC', -apple-system, 'PingFang TC',
               'Microsoft JhengHei', sans-serif;
  color: #2d3748; background: #ffffff;
}
h1 {
  color: #ffffff; background: #2c5282;
  padding: 12pt 18pt; margin: 0 0 18pt -20mm; margin-right: -20mm;
  font-size: 22pt; letter-spacing: 0.04em;
}
h2 { color: #2c5282; border-bottom: 2px solid #2c5282; padding-bottom: 4pt; }
h3 { color: #2b6cb0; }
h4 { color: #4a5568; }
strong { color: #1a365d; }
a { color: #2c5282; }
code { background: #edf2f7; color: #c53030; padding: 1pt 5pt; border-radius: 3pt; }
pre { background: #2d3748; color: #e2e8f0; }
table { font-size: 10.5pt; box-shadow: 0 1pt 3pt rgba(0,0,0,0.08); }
th { background: #2c5282; color: #ffffff; border: 1px solid #2c5282; font-weight: 600; }
td { border: 1px solid #cbd5e1; }
tbody tr:nth-child(even) td { background: #f7fafc; }
blockquote { background: #edf2f7; border-left: 4px solid #2c5282; color: #2d3748; }
hr { border-top: 2px solid #2c5282; }
""",
    },
    "mono": {
        "name": "極簡黑白",
        "desc": "純黑白配色，無修飾，適合需要絕對中性視覺的場合。",
        "css": _BASE + _EXTRAS + """
body {
  font-family: 'Noto Sans TC', -apple-system, 'PingFang TC',
               'Microsoft JhengHei', sans-serif;
  color: #000000; background: #ffffff;
}
h1 { border-bottom: 3px solid #000; padding-bottom: 4pt; }
h2 { border-bottom: 1.5px solid #000; padding-bottom: 3pt; }
h3, h4, h5, h6 { color: #000; }
strong { color: #000; }
a { color: #000; text-decoration: underline; }
code { background: #e8e8e8; color: #000; padding: 1pt 5pt; border-radius: 2pt; }
pre { background: #f5f5f5; color: #000; border: 1.5px solid #000; }
table { font-size: 10.5pt; }
th, td { border: 1px solid #000; }
th { background: #e8e8e8; }
blockquote { border-left: 4px solid #000; color: #333; background: transparent; }
hr { border-top: 1.5px solid #000; }
""",
    },
}


def get_theme(name: str) -> dict:
    """Return theme dict (name / desc / css). Falls back to classic if unknown."""
    return THEMES.get(name) or THEMES["classic"]


def theme_options() -> list[dict]:
    """For UI: list of {id, name, desc} suitable for a select/radio."""
    return [{"id": k, "name": v["name"], "desc": v["desc"]}
            for k, v in THEMES.items()]
