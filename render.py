#!/usr/bin/env python3
"""
AI周报 - HTML 构建脚本
从 filtered/ 目录读取 JSON 数据，填充到模板中生成完整 HTML
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = Path(__file__).parent
FILTERED_DIR = SCRIPT_DIR / "filtered"
TEMPLATE_DIR = SCRIPT_DIR / "templates"
NOW = datetime.now(timezone(timedelta(hours=8)))
TODAY = NOW.strftime("%Y-%m-%d")
DATE_CN = f"{NOW.year}年{NOW.month}月{NOW.day}日"


def find_latest_filtered_dir():
    """数据目录：interpreted/reviewed/filtered 取日期最新，同级优先 interpreted
    （六步流水线：interpret 集成后 interpreted 是第五步数据源；
    interpret 缺席时回退 reviewed，再回退 filtered）"""
    names = set()
    for base in ("interpreted", "reviewed", "filtered"):
        d = SCRIPT_DIR / base
        if d.exists():
            names |= {s.name for s in d.iterdir() if s.is_dir()}
    if not names:
        return None
    latest = sorted(names)[-1]
    for base in ("interpreted", "reviewed", "filtered"):
        p = SCRIPT_DIR / base / latest
        if p.exists():
            return p
    return None


def format_params(num):
    if num is None or num == 0:
        return ""
    if num >= 1e9:
        return f"{num / 1e9:.1f}B"
    if num >= 1e6:
        return f"{num / 1e6:.1f}M"
    if num >= 1e3:
        return f"{num / 1e3:.1f}K"
    return str(num)


def format_downloads(num):
    if num is None:
        return ""
    if num == 0:
        return "↓ 0"
    if num >= 1e6:
        return f"↓ {num / 1e6:.1f}M"
    if num >= 1e3:
        return f"↓ {num / 1e3:.0f}K"
    return f"↓ {num}"


def format_likes(num):
    if num is None or num == 0:
        return ""
    if num >= 1000:
        return f"♥ {num / 1000:.1f}K"
    return f"♥ {num}"


def format_stars(num):
    if num is None or num == 0:
        return ""
    if num >= 1000:
        return f"★ {num / 1000:.1f}k"
    return f"★ {num}"


def format_stars_weekly(num):
    if num is None or num == 0:
        return ""
    return f"+{num:,}/周"


def read_json(data_dir, name):
    filepath = data_dir / f"{name}.json"
    if not filepath.exists():
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("items", [])



def _hf_card_html(item, idx):
    title = item.get("title", "")
    pipeline = item.get("pipeline_tag", "")
    pipeline_display = pipeline
    likes = format_likes(item.get("likes"))
    downloads = format_downloads(item.get("downloads"))
    params = format_params(item.get("num_parameters"))
    license_tag = item.get("license", "")

    tags_html = f'<span class="tag pipeline">{pipeline}</span>'
    if likes:
        tags_html += f'<span class="tag stat">{likes}</span>'
    if downloads:
        tags_html += f'<span class="tag stat">{downloads}</span>'
    if params:
        tags_html += f'<span class="tag stat">{params}</span>'
    if license_tag:
        tags_html += f'<span class="tag license">{license_tag}</span>'

    interp = item.get("readme_interpretation", "")
    # 2026-10-13：正文 = interpret 步 LLM 解读；字段没有就不显示（兜底只显更新内容）
    desc_html = f'\n    <p class="card-desc">{interp}</p>' if interp else ''

    last_commit = item.get("last_commit", "")
    last_commit = item.get("last_commit_cn", last_commit)

    update_html = ""
    if last_commit:
        update_html = f'<p class="card-update">更新: {last_commit}</p>'

    return f'''<div class="card">
    <p class="card-title">{idx}. {title}</p>
    <div class="card-tags">{tags_html}</div>{desc_html}
{update_html}  </div>'''


def _gh_card_html(item, idx):
    title = item.get("title", "")
    lang = item.get("language", "")
    stars = format_stars(item.get("stars"))
    stars_weekly = format_stars_weekly(item.get("stars_weekly"))

    tags_html = ""
    if lang:
        tags_html += f'<span class="tag lang">{lang}</span>'
    if stars:
        tags_html += f'<span class="tag stat">{stars}</span>'
    if stars_weekly:
        tags_html += f'<span class="tag stat">{stars_weekly}</span>'

    desc = item.get("summary", "")
    desc = item.get("summary_cn", desc)

    return f'''<div class="card">
    <p class="card-title">{idx}. {title}</p>
    <div class="card-tags">{tags_html}</div>
    <p class="card-desc">{desc}</p>
  </div>'''


def _section_header(text, css_class):
    """生成章节标题"""
    return f'<h2 class="section-header {css_class}">{text}</h2>'


def _card_grid(items, card_fn, start_idx):
    """将 items 生成 inline-block 卡片列表"""
    cards = []
    for i, item in enumerate(items):
        cards.append(card_fn(item, start_idx + i))
    return '<div class="card-grid">\n' + '\n'.join(cards) + '\n</div>'


def build_cards(hf_items, gh_items):
    """构建 HF + GitHub 卡片区域"""
    parts = []
    parts.append(_section_header("HuggingFace 热门模型", "hf"))
    parts.append(_card_grid(hf_items, _hf_card_html, 1))
    parts.append(_section_header("GitHub 热门项目", "gh"))
    parts.append(_card_grid(gh_items, _gh_card_html, 1))
    return '\n'.join(parts)


def build_news_items(items):
    if not items:
        return ""
    sections = []
    for i, item in enumerate(items, 1):
        title = item.get("title", "")
        summary = item.get("summary", "")
        sections.append(f'''<div class="item">
<p><strong>{i}. {title}</strong></p>
<p>{summary}</p>
</div>''')
    return '\n'.join(sections)


def build_html(data_dir, output_path):
    template_path = TEMPLATE_DIR / "report.html"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    css_start = template.index("<style>")
    css_end = template.index("</style>") + len("</style>")
    css = template[css_start:css_end]

    hf_items = read_json(data_dir, "huggingface")
    gh_items = read_json(data_dir, "github")
    news_items = read_json(data_dir, "aibase")

    total = len(hf_items) + len(gh_items) + len(news_items)

    cards_html = build_cards(hf_items, gh_items)
    news_html = build_news_items(news_items)

    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
{css}
</head>
<body>

<h1>AI行业近一周热点 · {DATE_CN}</h1>

{cards_html}

<h2 class="news">行业资讯</h2>
{news_html}

<div class="footer">AI行业近一周热点 · 聚焦大模型和智能体领域</div>

</body>
</html>'''

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ HTML 生成完成: {output_path} ({total} 条内容)")
    return total


def to_pdf(html_path, pdf_path):
    import subprocess
    result = subprocess.run(
        ["wkhtmltopdf", "--encoding", "utf-8", str(html_path), str(pdf_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"❌ PDF 转换失败: {result.stderr}")
        return False
    size = pdf_path.stat().st_size if pdf_path.exists() else 0
    print(f"📄 PDF: {pdf_path} ({size:,} bytes)")
    return True


def main():
    import sys
    data_dir = find_latest_filtered_dir()
    if not data_dir:
        print("❌ 未找到 filtered 数据目录")
        sys.exit(1)

    print(f"📂 使用数据: {data_dir}")

    is_test = "test" in sys.argv
    output_path = SCRIPT_DIR / "output" / ("test" if is_test else "prod") / f"report-{TODAY}.html"
    if len(sys.argv) > 1 and sys.argv[1] not in ("test",):
        output_path = Path(sys.argv[1])

    total = build_html(data_dir, output_path)
    print(f"📊 共 {total} 条内容")

    pdf_dir = SCRIPT_DIR / "output" / "prod"
    if is_test:
        pdf_dir = SCRIPT_DIR / "output" / "test"
        ts = datetime.now().strftime("%H%M%S")
        pdf_name = f"AI周报-测试-{TODAY}-{ts}.pdf"
    else:
        pdf_name = f"AI周报-{TODAY}.pdf"

    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / pdf_name
    if not to_pdf(output_path, pdf_path):
        print("❌ PDF 转换失败，render 以非零退出")
        sys.exit(1)


if __name__ == "__main__":
    main()
