#!/usr/bin/env python3
"""
AI周报 - 数据采集脚本
采集4个信源的原始JSON数据，按日期存储到 raw/目录
"""

import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
import html as html_mod

SCRIPT_DIR = Path(__file__).parent
RAW_DIR = SCRIPT_DIR / "raw"

NOW = datetime.now(timezone(timedelta(hours=8)))
TODAY = NOW.strftime("%Y-%m-%d")
WEEK_AGO = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
}


def save_raw(source_name, data):
    """保存原始数据"""
    out_dir = RAW_DIR / TODAY
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{source_name}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {source_name}: {len(data['items'])} 条 → {out_file}")
    return out_file


# ========== 信源1: AIBase 日报 ==========

def fetch_aibase():
    """AIBase日报：列表页提取日报ID+相对时间 → 过滤7天内的 → 详情页拿内容"""
    print("\n📡 AIBase 日报...")

    r = requests.get("https://news.aibase.com/zh/daily", timeout=15, headers=HEADERS)
    decoded = html_mod.unescape(r.text)

    # 提取日报ID + 时间（icon-rili后面跟的是时间文本）
    daily_with_time = []
    for m in re.finditer(r'icon-rili[^>]*>\s*</i>\s*([^<]+)', decoded):
        time_text = m.group(1).strip()
        pos = m.start()
        before = decoded[max(0, pos - 2000):pos]
        ids = re.findall(r'/zh/daily/(\d+)', before)
        if ids:
            daily_with_time.append((ids[-1], time_text))

    # 解析相对时间，过滤7天内
    valid_ids = []
    for did, time_str in daily_with_time:
        days_ago = None
        if time_str == '刚刚' or '小时前' in time_str or '分钟前' in time_str:
            days_ago = 0
        elif time_str.strip() == '昨天':
            days_ago = 1
        elif time_str.strip() == '前天':
            days_ago = 2
        elif '天前' in time_str:
            m2 = re.search(r'(\d+)', time_str)
            days_ago = int(m2.group(1)) if m2 else None
        elif re.match(r'\d{2}-\d{2}', time_str):
            # 格式如 04-30，需要判断年份
            try:
                md = time_str.strip()
                date_obj = datetime.strptime(f"{NOW.year}-{md}", "%Y-%m-%d").replace(
                    tzinfo=timezone(timedelta(hours=8)))
                delta = (NOW - date_obj).days
                days_ago = delta
            except:
                pass

        if days_ago is not None and days_ago <= 7:
            valid_ids.append(did)
            print(f"  {did}: {time_str} ({days_ago}天前) ✅")
        else:
            print(f"  {did}: {time_str} ({days_ago}天前) ❌ 超出7天")

    print(f"  7天内 {len(valid_ids)} 篇日报")

    items = []
    for did in valid_ids:
        try:
            r2 = requests.get(f"https://news.aibase.com/zh/daily/{did}", timeout=15, headers=HEADERS)
            r2.encoding = "utf-8"
            soup = BeautifulSoup(r2.text, "html.parser")

            # 获取发布日期（从title或页面提取）
            page_title = soup.find("title")
            date_str = ""
            if page_title:
                # title格式: "AI日报：..." 有时没有日期
                pass

            # 获取内容区域
            content = soup.find("div", class_=lambda c: c and "post-content" in str(c))
            if not content:
                content = soup.find("div", class_=lambda c: c and "content" in str(c).lower())
            if not content:
                continue

            # 遍历子元素，识别条目模式：
            # <p><strong>序号+标题</strong></p> → 下一兄弟是摘要<p> → 再下一是<blockquote>提要
            children = list(content.children)
            i = 0
            while i < len(children):
                child = children[i]
                if not hasattr(child, 'name') or child.name != 'p':
                    i += 1
                    continue

                strong = child.find("strong")
                if not strong:
                    i += 1
                    continue

                raw_title = strong.get_text(strip=True)
                # 必须有序号前缀才算是新闻条目
                num_match = re.match(r'^(\d+)[、.．)\s]+', raw_title)
                if not num_match:
                    i += 1
                    continue

                title = re.sub(r'^\d+[、.．)\s]+', '', raw_title).strip()
                if len(title) < 5:
                    i += 1
                    continue

                # 下一兄弟是摘要
                summary = ""
                highlights = []
                j = i + 1
                while j < len(children):
                    next_el = children[j]
                    if not hasattr(next_el, 'name') or next_el.name is None:
                        j += 1
                        continue
                    if next_el.name == 'p':
                        ptext = next_el.get_text(strip=True)
                        if ptext:  # 非空=摘要
                            summary = ptext[:400]
                            break
                        else:  # 空<p>=分隔符
                            j += 1
                            continue
                    elif next_el.name == 'blockquote':
                        # 提要
                        bq_text = next_el.get_text(strip=True)
                        bq_text = bq_text.replace("【AiBase提要:】", "").strip()
                        # 按emoji分隔提取亮点
                        parts = re.split(r'[\U0001F300-\U0001F9FF]\s*', bq_text)
                        highlights = [p.strip() for p in parts if len(p.strip()) > 5][:3]
                        break
                    else:
                        break

                items.append({
                    "title": title[:120],
                    "summary": summary,
                    "highlights": highlights,
                    "date": date_str,
                })

                i = j + 1 if j > i else i + 1
                continue

            i += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠️ 日报 {did} 获取失败: {e}")
            continue

    data = {"source": "aibase", "fetch_date": TODAY, "items": items}
    return save_raw("aibase", data)


# ========== 信源2: AITNT AI资讯 ==========

def fetch_aitnt():
    """AITNT：列表页直接解析"""
    print("\n📡 AITNT AI资讯...")

    items = []
    for page in range(1, 6):
        try:
            r = requests.get(
                f"https://aitntnews.com/newList.html?typeId=1&page={page}",
                timeout=15, headers=HEADERS
            )
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")

            articles = soup.find_all("article", class_="news-item")
            if not articles:
                # 备选：找其他结构
                articles = soup.find_all("div", class_=re.compile(r"news|item|card"))

            for art in articles:
                # 标题
                title_el = art.find(["h2", "h3", "h4", "a"])
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                # 摘要
                summary_el = art.find("p", class_=re.compile(r"desc|summary|content"))
                if not summary_el:
                    summary_el = art.find("p")
                summary = summary_el.get_text(strip=True) if summary_el else ""

                # 日期
                date_el = art.find("span", class_=re.compile(r"date|time"))
                if not date_el:
                    date_el = art.find("time")
                date_str = date_el.get_text(strip=True) if date_el else ""

                if len(title) < 5:
                    continue

                items.append({
                    "title": title[:120],
                    "summary": summary[:400] if summary else "",
                    "date": date_str,
                })

            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️ 第{page}页失败: {e}")
            continue

    data = {"source": "aitnt", "fetch_date": TODAY, "items": items}
    return save_raw("aitnt", data)


# ========== 信源3: GitHub Trending ==========

def fetch_github():
    """GitHub Trending：weekly，直接解析HTML"""
    print("\n📡 GitHub Trending (weekly)...")

    r = requests.get(
        "https://github.com/trending?since=weekly",
        timeout=15, headers=HEADERS
    )
    soup = BeautifulSoup(r.text, "html.parser")

    items = []
    rows = soup.find_all("article", class_="Box-row")
    if not rows:
        # 备选class名
        rows = soup.select("div.Box-row, article.Box-row, div[data-hydro-click]")

    for row in rows:
        # repo名
        h2 = row.find("h2")
        if not h2:
            continue
        repo_link = h2.find("a")
        if not repo_link:
            continue
        repo = repo_link.get("href", "").strip("/")
        if not repo:
            continue

        # 描述
        desc_el = row.find("p", class_=re.compile(r"col-9|color-fg-muted|description"))
        desc = desc_el.get_text(strip=True) if desc_el else ""

        # 语言
        lang_el = row.find("span", itemprop="programmingLanguage")
        lang = lang_el.get_text(strip=True) if lang_el else ""

        # stars
        stars_el = row.find("a", href=re.compile(r"/stargazers"))
        stars_str = stars_el.get_text(strip=True).replace(",", "") if stars_el else "0"
        try:
            stars = int(stars_str)
        except:
            stars = 0

        # 周增量
        growth_el = row.find("span", class_=re.compile(r"d-inline-block.float-sm-right|float-right"))
        if not growth_el:
            growth_el = row.find(string=re.compile(r"stars this week"))
        growth_str = growth_el.get_text(strip=True) if growth_el else "0"
        growth_match = re.search(r"([\d,]+)", growth_str)
        try:
            growth = int(growth_match.group(1).replace(",", "")) if growth_match else 0
        except:
            growth = 0

        items.append({
            "title": repo,
            "summary": desc[:400] if desc else "",
            "date": TODAY,
            "language": lang,
            "stars": stars,
            "stars_weekly": growth,
        })

    data = {"source": "github", "fetch_date": TODAY, "items": items}
    return save_raw("github", data)


# ========== 信源4: HuggingFace Model Trending ==========

def extract_readme_summary(readme_text):
    """从 HF README 提取模型简介（v4，6层优先级 fallback）

    提取优先级：
    1. ## Introduction 段落
    2. H1 标题前的纯文本（处理 Gemma 等罕见结构）
    3. H1 标题后到第一个 ## 之间的纯文本
    4. ## xxx Highlights 段落
    5. **Description** 表格行
    6. 全文第一段兜底
    """
    body = re.sub(r'^---[\s\S]*?---\s*', '', readme_text, count=1)
    body = html_mod.unescape(body)
    # 2026-09-18 修复：围栏代码块整体剔除（此前逐行白名单杀不干净，
    # AliceAI-T5 的 adapter_path/tokenizer 赋值行漏过成为“最长段落”）
    body = re.sub(r'```.*?```', ' ', body, flags=re.S)
    # 未闭合围栏兑底（README 截断场景）
    body = re.sub(r'```.*$', ' ', body, flags=re.S)
    # 2026-09-18 修复：HTML 表格整体剔除（此前只认 markdown 管道符，
    # occamy 的 <td> 基准表剥标签后数字拼成一串成为“最长段落”）
    body = re.sub(r'<table.*?</table>', ' ', body, flags=re.S | re.I)

    def is_decoration(s):
        s = s.strip()
        if not s:
            return True
        if re.match(r'^<(div|p|font|img|br|hr|center|/)', s, re.IGNORECASE):
            return True
        if re.match(r'^</(div|p|font|center)', s, re.IGNORECASE):
            return True
        if s.startswith('!['):
            return True
        if s in ('<br>', '<br/>', '<br />', '<hr>', '<hr/>', '<hr />'):
            return True
        if re.search(r'<(a |img |font |/a)', s, re.IGNORECASE):
            return True
        # Markdown标题行不算描述内容
        if re.match(r'^#{1,3}\s+[^#]', s):
            return True
        return False

    def is_code_line(s):
        s = s.strip()
        if s.startswith('```'):
            return True
        if re.match(r'^(from |import |def |class |self\\.|return |print\(|model\\.|processor\\.)', s):
            return True
        if re.match(r'^(MODEL_ID|messages|text|outputs|response|image|audio|video|dtype|device_map|torch)\s*=', s):
            return True
        if re.match(r'^(pip |pip3 )', s):
            return True
        return False

    def is_link_bar_line(s):
        s = s.strip()
        if re.match(r'^\[[^\]]+\]\(https?://', s):
            return True
        return False

    def is_link_bar_paragraph(lines):
        if len(lines) <= 1:
            return False
        link_count = sum(1 for l in lines if is_link_bar_line(l.strip()) or is_decoration(l.strip()))
        return link_count >= len(lines) * 0.6

    def is_navigation_text(text):
        if re.match(r'^(Try|Get|Visit|Go|Check|See|Read|Download|Learn)', text):
            if '·' in text or ' | ' in text or ' • ' in text:
                return True
        parts = text.split(' | ')
        if len(parts) >= 3:
            return True
        # "🌐 Language versions: Español | Português" 等纯链接/导航行
        if re.match(r'^[\U0001F300-\U0001F9FF]+\s', text):
            return True
        if re.match(r'^(Language|Languages?|Version|Versions?|\w+ versions?)\s*[:：]', text, re.IGNORECASE):
            return True
        # "For more details... see below/guide/section" 引导语
        if re.match(r'^(For more details?|For details|For more information|See the|See below|Refer to)', text, re.IGNORECASE):
            return True
        return False

    def clean_and_extract(section_text):
        paras = re.split(r'\n\s*\n', section_text.strip())
        candidate = ""  # 短文本候选
        best_long = ""  # 最长段落（>= 30 字符），优先返回
        for para in paras:
            lines = []
            for line in para.strip().split('\n'):
                s = line.strip()
                if is_decoration(s):
                    continue
                if s.count('|') >= 2:
                    continue
                # "**Key:** Value" 元数据行（如 Model Developer, Model Dates 等）
                if re.match(r'^\*\*[\w\s]+:\*\*\s*', s):
                    continue
                if is_code_line(s):
                    continue
                if is_link_bar_line(s):
                    continue
                if s.startswith('>'):
                    continue
                # 无序列表项（通常为元数据，不是描述段落）
                if re.match(r'^\*\s', s):
                    continue
                if s.startswith('- ['):
                    continue
                lines.append(s)
            if not lines:
                continue
            if is_link_bar_paragraph(lines):
                continue
            # 全是 "-" 无序列表的段落，先清理格式再判断是否为元数据
            if all(re.match(r'^-\s', l.strip()) for l in lines) and len(lines) >= 3:
                # 先做格式清理再检测
                joined = ' '.join(lines)
                joined = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', joined)
                joined = re.sub(r'<[^>]+>', '', joined)
                joined = re.sub(r'\*\*([^*]+)\*\*', r'\1', joined)
                # 提取每个列表项文本
                items = [x.strip().lstrip('-').strip() for x in joined.split(' - ')]
                # 元数据特征：大部分项很短（<=60字符）且含有冒号或数字
                short_items = sum(1 for x in items if len(x) <= 60)
                meta_items = sum(1 for x in items if re.search(r':\s', x) or re.search(r'\d+', x))
                if short_items / len(items) >= 0.7 and meta_items / len(items) >= 0.5:
                    continue
            text = ' '.join(lines)
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', text)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if is_navigation_text(text):
                continue
            # 2026-09-18 兑底：数字密度判定——剥掉数字/空白/标点后剩余不足一半，
            # 视为表格残渣/基准数据糊，判废
            stripped = re.sub(r'[\d\s.,%+\-\u2013\u2014:;()/]', '', text)
            if len(text) > 0 and len(stripped) < len(text) * 0.5:
                continue
            if len(text) >= 15:
                # 长文本：记录最长段落，不立即返回
                if len(text) >= 30:
                    if len(text) > len(best_long):
                        best_long = text
                else:
                    # 短文本（15~29字符）：作为候选
                    if not candidate:
                        candidate = text
                    continue

        # 优先返回最长段落（> 300 需截断）
        if best_long:
            if len(best_long) <= 300:
                return best_long
            truncated = best_long[:300]
            # 在截断点附近（200~300）找句末标点
            for sep in '.!?;':
                last_sep = truncated.rfind(sep)
                if last_sep > 200:
                    return truncated[:last_sep + 1]
            # 在截断点附近找中文句末标点
            for sep in '。！？；':
                last_sep = truncated.rfind(sep)
                if last_sep > 200:
                    return truncated[:last_sep + 1]
            # 在逗号处截断（至少保留150字符）
            for sep in ',，':
                last_sep = truncated.rfind(sep)
                if last_sep > 150:
                    return truncated[:last_sep + 1]
            # 兜底：硬截300
            return truncated
        return candidate if candidate else ""

    h2_positions = [(m.start(), m.group()) for m in re.finditer(r'^##\s+.+$', body, re.MULTILINE)]
    h1_match = re.search(r'^#\s+.+$', body, re.MULTILINE)

    # 策略0：H1后到第一个##之间，检测Note/variant说明段落（如DSpark等推理加速变体）
    # 匹配类似 "**Note: xxx** is not a new model. It is the same checkpoint with ..." 的说明
    if h1_match:
        after_h1 = body[h1_match.end():]
        first_h2_pos = len(after_h1)
        for pos, _ in h2_positions:
            if pos > h1_match.end():
                first_h2_pos = pos - h1_match.end()
                break
        preamble = after_h1[:first_h2_pos]
        paras = re.split(r'\n\s*\n', preamble.strip())
        for para in paras:
            stripped = re.sub(r'\*+', '', para).strip()
            if re.search(r'\bNote\b', stripped) and re.search(
                r'(?:not\s+a\s+new\s+model|same\s+checkpoint|speculative\s+decoding|quantized\s+variant|distilled\s+version)',
                stripped, re.IGNORECASE
            ):
                text = clean_and_extract(para)
                if text:
                    return text

    # 策略1：## Introduction / ## Model Description（忽略 ** 加粗标记）
    for pos, title in h2_positions:
        # 去掉 markdown 加粗后匹配
        clean_title = re.sub(r'\*+', '', title).strip()
        if re.match(r'^##\s+(?:\d+\.\s+)?(?:Introduction|Model Description)\s*$', clean_title):
            idx = h2_positions.index((pos, title))
            end = h2_positions[idx + 1][0] if idx + 1 < len(h2_positions) else len(body)
            result = clean_and_extract(body[pos + len(title):end])
            if result:
                return result

    # 策略1.5：## Overview / ## Model Overview / ## About
    for pos, title in h2_positions:
        clean_title = re.sub(r'\*+', '', title).strip()
        if re.match(r'^##\s+(?:Model )?(?:Overview|About|About This Model)\s*$', clean_title):
            idx = h2_positions.index((pos, title))
            end = h2_positions[idx + 1][0] if idx + 1 < len(h2_positions) else len(body)
            result = clean_and_extract(body[pos + len(title):end])
            if result:
                return result

    # 策略2：H1 前的纯文本
    if h1_match:
        before_h1 = body[:h1_match.start()]
        result = clean_and_extract(before_h1)
        if result:
            return result

    # 策略3：H1 后到第一个 ## 之间
    if h1_match:
        after_h1 = body[h1_match.end():]
        first_h2_pos = len(after_h1)
        for pos, title in h2_positions:
            if pos > h1_match.end():
                first_h2_pos = pos - h1_match.end()
                break
        section = after_h1[:first_h2_pos]
        result = clean_and_extract(section)
        if result and len(result) >= 30:
            return result

    # 策略3.5：## Description（独立的 Description section，如 Nemotron）
    for pos, title in h2_positions:
        clean_title = re.sub(r'\*+', '', title).strip()
        if re.match(r'^##\s+Description\s*$', clean_title):
            idx = h2_positions.index((pos, title))
            end = h2_positions[idx + 1][0] if idx + 1 < len(h2_positions) else len(body)
            result = clean_and_extract(body[pos + len(title):end])
            if result:
                return result

    # 策略4：## xxx Highlights（忽略 ** 加粗标记）
    for pos, title in h2_positions:
        clean_title = re.sub(r'\*+', '', title).strip()
        if re.search(r'[Hh]ighlights?', clean_title):
            idx = h2_positions.index((pos, title))
            end = h2_positions[idx + 1][0] if idx + 1 < len(h2_positions) else len(body)
            result = clean_and_extract(body[pos + len(title):end])
            if result:
                return result

    # 策略5：Description 表格行
    desc_match = re.search(r'\*\*Description\*\*\s*\|?\s*(.+?)(?:<br|<br/|\n)', body)
    if desc_match:
        text = desc_match.group(1).strip()
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) >= 20:
            return text[:200]

    # 策略6：全文第一段兜底
    result = clean_and_extract(body)
    if result:
        return result

    return ""


def fetch_huggingface():
    """HuggingFace：列表页取基本信息 + README取简介 + commits页取更新日志 + 详情页取license"""
    print("\n📡 HuggingFace Model Trending...")

    # 1. 列表页
    r = requests.get(
        "https://huggingface.co/models?num_parameters=min:32B&library=transformers,safetensors&sort=trending",
        timeout=15, headers=HEADERS
    )
    decoded = html_mod.unescape(r.text)

    # 提取列表页数据
    model_ids = re.findall(r'"id"\s*:\s*"([^"]+/[^"]+)"', decoded[:100000])
    downloads_list = [int(x) for x in re.findall(r'"downloads"\s*:\s*(\d+)', decoded)]
    likes_list = [int(x) for x in re.findall(r'"likes"\s*:\s*(\d+)', decoded)]
    pipeline_list = re.findall(r'"pipeline_tag"\s*:\s*"([^"]*)"', decoded)
    num_params_list = [int(x) for x in re.findall(r'"numParameters"\s*:\s*(\d+)', decoded)]
    last_modified_list = re.findall(r'"lastModified"\s*:\s*"([^"]+)"', decoded)

    # 过滤7天内的
    models = []
    for i in range(len(model_ids)):
        date = last_modified_list[i][:10] if i < len(last_modified_list) else ""
        if date < WEEK_AGO:
            continue
        models.append({
            "idx": i,
            "title": model_ids[i],
            "date": date,
            "downloads": downloads_list[i] if i < len(downloads_list) else 0,
            "likes": likes_list[i] if i < len(likes_list) else 0,
            "pipeline_tag": pipeline_list[i] if i < len(pipeline_list) else "",
            "num_parameters": num_params_list[i] if i < len(num_params_list) else 0,
        })

    print(f"  列表页: {len(models)} 个7天内模型")

    # 2. 逐个取 README简介 + commit message + license
    for m in models:
        mid = m["title"]
        target_date = m["date"]

        # README 取全文落盘（2026-10-13 interpret 步改造：LLM 直读全文总结，
        # 规则提取逻辑作废——summary 字段不再产出，review/interpret/render 改用
        # readme 与 readme_interpretation）
        try:
            r_readme = requests.get(
                f"https://huggingface.co/{mid}/raw/main/README.md",
                timeout=10, headers=HEADERS
            )
            m["readme"] = r_readme.text
        except:
            m["readme"] = ""
        # 旧提取逻辑（作废保留备查）：
        # m["summary"] = extract_readme_summary(readme_text)

        # commits页取本周更新日志
        try:
            r2 = requests.get(
                f"https://huggingface.co/{mid}/commits/main",
                timeout=10, headers=HEADERS
            )
            decoded2 = html_mod.unescape(r2.text)
            last_commit = ""
            for match in re.finditer(r'"date":"(\d{4}-\d{2}-\d{2})[^}]*?"subject":"([^"]+)"', decoded2):
                cdate = match.group(1)
                subject = match.group(2)
                if cdate == target_date and not last_commit:
                    last_commit = subject
            m["last_commit"] = last_commit
        except:
            m["last_commit"] = ""

        # 详情页取license
        try:
            r3 = requests.get(f"https://huggingface.co/{mid}", timeout=10, headers=HEADERS)
            decoded3 = html_mod.unescape(r3.text)
            lm = re.search(r'"license"\s*:\s*"([^"]+)"', decoded3)
            m["license"] = lm.group(1) if lm else ""
        except:
            m["license"] = ""

        time.sleep(0.3)

    # 清理内部字段（2026-10-13：summary→readme 全文，interpret 步直读）
    items = []
    for m in models:
        items.append({
            "title": m["title"],
            "readme": m["readme"],
            "last_commit": m["last_commit"],
            "date": m["date"],
            "downloads": m["downloads"],
            "likes": m["likes"],
            "pipeline_tag": m["pipeline_tag"],
            "num_parameters": m["num_parameters"],
            "license": m["license"],
        })

    data = {"source": "huggingface", "fetch_date": TODAY, "items": items}
    return save_raw("huggingface", data)


# ========== 主流程 ==========

def should_fetch(source_name):
    """检查今天该信源是否已有数据，有则跳过"""
    out_file = RAW_DIR / TODAY / f"{source_name}.json"
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items", [])
            if len(items) > 0:
                print(f"  ⏭️ {source_name}: 今天已有 {len(items)} 条数据，跳过采集")
                return False
        except:
            pass
    return True


def main():
    print(f"🚀 AI周报数据采集 {TODAY}")
    print(f"   采集范围: {WEEK_AGO} ~ {TODAY}")

    out_dir = RAW_DIR / TODAY
    out_dir.mkdir(parents=True, exist_ok=True)

    if should_fetch("aibase"):
        fetch_aibase()
    if should_fetch("aitnt"):
        fetch_aitnt()
    if should_fetch("github"):
        fetch_github()
    if should_fetch("huggingface"):
        fetch_huggingface()

    print(f"\n✅ 全部采集完成，数据保存在: {out_dir}")


if __name__ == "__main__":
    main()
