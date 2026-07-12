#!/usr/bin/env python3
"""
AI周报 - 黑名单过滤脚本
读取 raw/ 下的JSON数据，按黑名单关键字过滤，输出 filtered/ 下过滤后的JSON
策略：先放行，黑名单剔除。只保留模型、Agent、Code相关。
"""

import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = Path(__file__).parent
RAW_DIR = SCRIPT_DIR / "raw"
FILTERED_DIR = SCRIPT_DIR / "filtered"

NOW = datetime.now(timezone(timedelta(hours=8)))
TODAY = NOW.strftime("%Y-%m-%d")
WEEK_AGO = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
WEEK_LABEL = TODAY  # filtered 目录名，用结束日期标识，如 2026-05-12

# ========== 黑名单规则 ==========

# 通用黑名单（标题匹配，不区分大小写）—— 命中即剔除
TITLE_BLACKLIST = [
    # 人事变动
    r"离职", r"人事变动", r"任命", r"高管.*[辞离]", r"裁员", r"解雇", r"辞职",
    # 无关行业
    r"成人", r"情趣", r"赌博", r"博彩", r"彩票",
    # 产品小更新
    r"修复.*bug", r"版本号.*更新", r"UI优化",
]

# GitHub 专属黑名单（repo名+描述匹配）
GITHUB_BLACKLIST = [
    r"\btrading\b", r"\bfinancial\b", r"\bfinance\b", r"\bstock\b", r"\bcrypto\b", r"\bblockchain\b",
    r"\bmeetly\b|\bmeeting\b",
    r"\bvalue\s+investing?\b",
    r"\bvideo\b", r"video.?generat", r"short.?video", r"\bcapcut\b", r"\becommerce\b", r"\bmarketing\b",
    r"\bnft\b", r"\bdefi\b", r"\bgame\b", r"\bgaming\b", r"\bmusic\b", r"\bsong\b",
    r"\brecipe\b", r"\bcook\b", r"\bfood\b", r"\btravel\b", r"\bhotel\b", r"\bbooking\b",
    r"\bdating\b", r"social.?media", r"\binfluencer\b",
    r"\bdocuseal\b", r"\bdocsign\b", r"\bsigning\b",
    r"vscode.?theme", r"\btheme\b", r"\btabular.?data\b",
    r"ai.?to.?earn", r"earn.?money",
    # 音频/语音/TTS类
    r"\btts\b", r"text-to-speech", r"\bspeech\b", r"\bvoice\b", r"\baudio\b",
    # IPTV类
    r"\biptv\b",
]

# HuggingFace 黑名单（模型名+pipeline_tag匹配）
HF_BLACKLIST = [
    r"\bmedical\b", r"\bclinic\b", r"\bdoctor\b", r"\bpatient\b", r"\bhealth\b",
    r"\bbiology\b", r"\bprotein\b", r"\bgene\b", r"\bdrug\b", r"\bpharma\b",
    r"\bmusic\b", r"audio.?generat", r"\btts\b", r"speech.?synthesis",
    r"\bbench\b",
]

# AIBase 专属黑名单
AIBASE_BLACKLIST = [
    # 无关行业/平台
    r"短视频", r"直播带货", r"电商", r"营销", r"广告投放",
    r"股价", r"市值", r"人事变动", r"组织架构.*调整",
    # 融资/商业化
    r"融资", r"增资", r"IPO", r"商业化",
    r"订阅付费", r"订阅服务", r"月费", r"付费方案",
    # 产品小更新/无关产品
    r"贴图", r"表情包", r"壁纸", r"铃声",
    r"答题免单", r"购物", r"试穿", r"种草",
    r"可灵", r"视频生成生态", r"AI短剧",
    r"手环", r"智能眼镜", r"AirPods", r"耳机",
    r"机器人", r"人形机器人",
    r"宇树",
    # 人物八卦
    r"贾跃亭",
    r"积分福利",
    r"SpaceX", r"航天",
    r"搜狐",
    r"短剧",
    r"模型委员会",
    r"语音",
    r"Music",
    r"music",
    r"音乐",
    r"汽车",
    r"美图秀秀",
    r"网约车",
    r"nba",
    r"食用",
    r"3D",
    r"高考",
    r"宠物",
    # 平台治理/消费硬件
    r"小红书", r"ai眼镜", r"带货",
    # 视频编辑/图像生成工具（非大模型本身）
    r"视频编辑",
    r"视频",
    r"电影",
    r"网文",
    r"ps5",
    r"ps6",
    r"游戏",
    # 用户指定黑名单
    r"ai写作", r"连锁", r"灌水", r"sk集团",
    # 社交/诈骗/餐饮/出行
    r"诈骗", r"社交", r"餐饮", r"出行",
]

# AITNT 不用黑名单，纯白名单逻辑


def matches_blacklist(text, patterns):
    """检查文本是否命中任一黑名单规则"""
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def filter_aibase(items):
    """过滤AIBase条目"""
    result = []
    for item in items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        full_text = f"{title} {summary}"

        if matches_blacklist(full_text, TITLE_BLACKLIST):
            continue
        if matches_blacklist(full_text, AIBASE_BLACKLIST):
            continue

        result.append(item)
    return result


def filter_aitnt(items):
    """过滤AITNT条目 —— 纯白名单逻辑，只保留大模型/Agent/Code相关"""
    WHITELIST_KW = [
        "模型", "LLM", "Agent",
    ]

    result = []
    for item in items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        full_text = f"{title} {summary}"

        if any(kw.lower() in full_text.lower() for kw in WHITELIST_KW):
            result.append(item)

    return result


def filter_github(items):
    """过滤GitHub Trending条目"""
    result = []
    for item in items:
        repo = item.get("title", "")
        desc = item.get("summary", "")
        lang = item.get("language", "")
        full_text = f"{repo} {desc} {lang}"

        if matches_blacklist(full_text, TITLE_BLACKLIST):
            continue
        if matches_blacklist(full_text, GITHUB_BLACKLIST):
            continue

        result.append(item)
    return result


def filter_huggingface(items):
    """过滤HuggingFace模型条目"""
    result = []
    for item in items:
        title = item.get("title", "")
        pipeline = item.get("pipeline_tag", "")
        summary = item.get("summary", "")
        full_text = f"{title} {pipeline} {summary}"

        if matches_blacklist(full_text, TITLE_BLACKLIST):
            continue
        if matches_blacklist(full_text, HF_BLACKLIST):
            continue

        result.append(item)
    return result


def sort_github(items):
    """GitHub 条目按 stars_weekly（周增星）从高到低排序"""
    return sorted(items, key=lambda x: int(x.get("stars", 0) or 0), reverse=True)


def sort_huggingface(items):
    """HuggingFace 条目按 likes 从高到低排序，likes 相同按下载数从高到低"""
    def sort_key(x):
        likes = int(x.get("likes", 0) or 0)
        downloads = int(str(x.get("downloads", "0")).replace(",", ""))
        return (-likes, -downloads)
    return sorted(items, key=sort_key)


def deduplicate_hf_series(items):
    """HF 同系列去重：按模型名去掉参数量后的系列名分组，每组只保留 likes 最高的"""
    if len(items) <= 1:
        return items

    def series_key(title):
        # 去掉 org/ 前缀
        parts = title.split('/')
        name = parts[-1] if len(parts) > 1 else title
        # 1. 去掉量化格式标记块：qat-q4_0, qat-w4a16 等
        name = re.sub(r'-qat(?:-[A-Za-z0-9_.]+)+', '', name, flags=re.IGNORECASE)
        # 2. 去掉量化精度后缀：-FP4-DFlash, -NVFP4, -FP8, -bf16 等
        name = re.sub(r'-(?:FP\d|bf\d|NVFP\d|FP\d-D\w+|GGUF|gptq)(?:-[A-Za-z0-9_.]+)*$', '', name, flags=re.IGNORECASE)
        # 3. 去掉末尾参数量段：-31B-it, -26B-A4B-it, -30B-A3B, -749B 等
        name = re.sub(r'-(?:\d+(\.\d+)?[BMK][A-Za-z0-9]*(?:-[A-Za-z0-9.]+)*)$', '', name, flags=re.IGNORECASE)
        # 4. 去掉残余的 unquantized 后缀
        name = re.sub(r'-unquant(?:ified|ized)?$', '', name, flags=re.IGNORECASE)
        return name

    # 按 likes 降序排列（最高优先）
    items_sorted = sorted(items, key=lambda x: int(x.get('likes', 0) or 0), reverse=True)

    kept = []
    kept_keys = set()
    for item in items_sorted:
        sk = series_key(item['title'])
        if sk not in kept_keys:
            kept.append(item)
            kept_keys.add(sk)

    removed = len(items) - len(kept)
    if removed > 0:
        removed_names = [item['title'] for item in items_sorted if series_key(item['title']) in {series_key(k['title']) for k in kept} and item not in kept]
        print(f"  🔄 同系列去重: {len(items)} → {len(kept)} 条（合并 {removed} 条）")
    return kept


def deduplicate(items, key="title"):
    """按标题前20字符去重"""
    seen = set()
    result = []
    for item in items:
        k = item.get(key, "")[:20].lower().strip()
        if k and k not in seen:
            seen.add(k)
            result.append(item)
    return result


def load_raw(source_filename):
    """读取当天raw目录下同名信源的数据"""
    all_items = []
    raw_file = RAW_DIR / TODAY / f"{source_filename}.json"
    if not raw_file.exists():
        print(f"  ⏭️ {TODAY}/{source_filename}.json 不存在，跳过")
        return all_items

    try:
        with open(raw_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
    except Exception as e:
        print(f"  ⚠️ 读取 {raw_file} 失败: {e}")
        return all_items

    print(f"  📂 {TODAY}/{source_filename}.json: {len(items)} 条")
    return items


def main():
    print(f"🔍 AI周报 - 黑名单过滤 {TODAY}")
    print(f"   数据范围: {WEEK_AGO} ~ {TODAY}")

    out_dir = FILTERED_DIR / WEEK_LABEL
    out_dir.mkdir(parents=True, exist_ok=True)

    total_in = 0
    total_out = 0

    filters = {
        "aibase": ("aibase", filter_aibase),
        # "aitnt": ("aitnt", filter_aitnt),  # 暂不启用，信息太多过滤不干净
        "github": ("github", filter_github),
        "huggingface": ("huggingface", filter_huggingface),
    }

    for source_name, (filename, filter_fn) in filters.items():
        print(f"\n  📡 {source_name}:")
        items = load_raw(filename)

        if not items:
            print(f"  ⏭️ {source_name}: 无原始数据，跳过")
            continue

        total_in += len(items)

        filtered = filter_fn(items)
        # HuggingFace 有自己的同系列去重逻辑（deduplicate_hf_series），不走通用 deduplicate
        if source_name != "huggingface":
            filtered = deduplicate(filtered)

        # 排序 + HF同系列去重
        if source_name == "huggingface":
            filtered = deduplicate_hf_series(filtered)
            filtered = sort_huggingface(filtered)

        total_out += len(filtered)
        removed = len(items) - len(filtered)
        print(f"  ✅ {source_name}: {len(items)} → {len(filtered)} 条（剔除 {removed}）")

        out_data = {
            "source": source_name,
            "fetch_date": TODAY,
            "date_range": f"{WEEK_AGO} ~ {TODAY}",
            "items": filtered,
        }
        out_file = out_dir / f"{filename}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"\n📊 总计: {total_in} → {total_out} 条（剔除 {total_in - total_out}）")
    print(f"   过滤后数据: {out_dir}")


if __name__ == "__main__":
    main()
