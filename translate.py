#!/usr/bin/env python3
"""
AI周报 - 翻译脚本
读取 filtered/ 下日期最新目录的 huggingface.json 和 github.json，
将英文 summary / last_commit 翻译为中文，写入 *_cn 字段。

2026-09-08 改造：
- 周维度缓存 cache/{日期}.json，key=sha256(原文)，原文不变不重复调用
- 未命中文本编号打包（@@@i@@@ 分隔），单次 POST 提交，超长自动分包
- 打包失败重试 -> 切分校验失败 -> 降级逐条；翻译失败不入缓存，重跑自动补翻
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
FILTERED_DIR = SCRIPT_DIR / "filtered"
CACHE_DIR = SCRIPT_DIR / "cache"
NOW = datetime.now(timezone(timedelta(hours=8)))

# Google Translate (gtx)
GT_URL = "https://translate.googleapis.com/translate_a/single"
# 2026-09-18 修复：sl 由写死 "en" 改 "auto"（AliceAI-T5 事件：俄语源+en 声明，
# 逐条翻译失败回退原文直接上刊；auto 让 gtx 自动检测源语言）
GT_PARAMS = {"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t"}

MAX_PACK_CHARS = 6000   # 单包字符上限（含分隔符开销），超出自动分包
PACK_RETRIES = 2        # 打包请求失败重试次数
SINGLE_INTERVAL = 1.0   # 降级逐条模式的请求间隔（秒）

STATS = {"hit": 0, "translated": 0, "failed": 0, "api_calls": 0}


def find_latest_filtered_dir():
    """找到 filtered/ 下日期最新的文件夹"""
    if not FILTERED_DIR.exists():
        return None
    dirs = sorted(d for d in FILTERED_DIR.iterdir() if d.is_dir())
    return dirs[-1] if dirs else None


def text_key(text):
    """原文指纹：sha256。原文不变则 key 不变，变一个字符则完全不同"""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def cyrillic_ratio(t):
    """西里尔字符占比（俄语检测）"""
    if not t:
        return 0.0
    cyr = sum(1 for c in t if '\u0400' <= c <= '\u04FF')
    return cyr / len(t)


def load_cache(path):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print(f"  ⚠️ 缓存文件损坏，按空缓存处理: {path.name}")
    return {}


def save_cache(path, cache):
    """原子写：先写 .tmp 再 rename，防止中断产生半文件"""
    CACHE_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def call_gt(text, timeout=60):
    """单次 gtx 调用（POST），返回整段译文"""
    r = requests.post(GT_URL, data={**GT_PARAMS, "q": text}, timeout=timeout)
    r.raise_for_status()
    return "".join(seg[0] for seg in r.json()[0] if seg and seg[0])


def clean(t):
    """译文清理：去掉翻译器添加的行首列表符号"""
    return re.sub(r"^(?:[-*•]\s+)+", "", t.strip()).strip()


def split_packed(full, n):
    """按 @@@i@@@ 切分打包译文；编号 0..n-1 齐全且块数相符才认可"""
    parts = re.split(r"@@@\s*(\d+)\s*@@@", full)
    nums = [int(x) for x in parts[1::2]]
    blocks = [b.strip() for b in parts[2::2]]
    if nums == list(range(n)) and len(blocks) == n:
        return blocks
    return None


def build_packs(texts):
    """按 MAX_PACK_CHARS 把待翻文本切成若干包，返回每包的索引列表"""
    packs, current, size = [], [], 0
    for i, t in enumerate(texts):
        w = len(t) + 12  # 文本长度 + 分隔符与换行开销
        if current and size + w > MAX_PACK_CHARS:
            packs.append(current)
            current, size = [], 0
        current.append(i)
        size += w
    if current:
        packs.append(current)
    return packs


def translate_packed(texts):
    """打包翻译：每包一次 POST；失败重试后降级逐条。返回 {索引: 译文}"""
    results = {}
    packs = build_packs(texts)
    for no, idxs in enumerate(packs, 1):
        packed = "".join(f"\n@@@{i}@@@\n{texts[i]}" for i in idxs)
        print(f"    包 {no}/{len(packs)}: {len(idxs)} 条 / {len(packed)} 字符", flush=True)
        done = False
        for attempt in range(1, PACK_RETRIES + 2):
            try:
                STATS["api_calls"] += 1
                blocks = split_packed(call_gt(packed), len(idxs))
                if blocks is None:
                    print(f"    ✗ 切分校验失败（尝试 {attempt}）")
                    time.sleep(2)
                    continue
                results.update(dict(zip(idxs, blocks)))
                done = True
                break
            except Exception as e:
                print(f"    ✗ 请求失败（尝试 {attempt}）: {e}")
                time.sleep(2)
        if not done:
            print(f"    ⤵ 包 {no} 降级为逐条翻译")
            for i in idxs:
                try:
                    STATS["api_calls"] += 1
                    results[i] = call_gt(texts[i])
                except Exception as e:
                    print(f"    ✗ 条目 {i} 逐条仍失败: {e}")
                time.sleep(SINGLE_INTERVAL)
    return results


def collect_tasks(data_dir):
    """扫描两个 json，收集全部待翻字段任务"""
    tasks = []
    for name in ("huggingface", "github"):
        fp = data_dir / f"{name}.json"
        if not fp.exists():
            print(f"  {name}.json: 文件不存在，跳过")
            continue
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        fields = ("summary", "last_commit") if name == "huggingface" else ("summary",)
        cnt = 0
        for idx, item in enumerate(items):
            for fld in fields:
                text = (item.get(fld) or "").strip()
                if text:
                    tasks.append({"file": name, "data": data, "idx": idx,
                                  "field": fld, "text": text})
                    cnt += 1
        print(f"  {name}.json: {cnt} 条待翻字段")
    return tasks


def main():
    data_dir = find_latest_filtered_dir()
    if not data_dir:
        print("❌ 未找到 filtered 数据目录")
        sys.exit(1)
    print(f"📂 使用数据: {data_dir}")

    cache_path = CACHE_DIR / f"{data_dir.name}.json"
    cache = load_cache(cache_path)
    print(f"🗃 周缓存: {cache_path.name}（现有 {len(cache)} 条）")

    tasks = collect_tasks(data_dir)
    if not tasks:
        print("无待翻内容")
        return

    # ① 逐条查缓存
    miss = []
    for t in tasks:
        t["key"] = text_key(t["text"])
        if t["key"] in cache:
            t["cn"] = cache[t["key"]]["cn"]
            STATS["hit"] += 1
        else:
            miss.append(t)
    print(f"🎯 缓存命中 {STATS['hit']} / 未命中 {len(miss)}")

    # ② 未命中的打包翻译
    if miss:
        results = translate_packed([t["text"] for t in miss])
        for i, t in enumerate(miss):
            if i in results:
                t["cn"] = clean(results[i])
                # 2026-09-18 修复：gtx打包模式对西里尔源会半翻译（AliceAI事件：
                # 英俄混包按句检测，俄语条只翻一段），质检残留→单条重翻
                src_cyr = cyrillic_ratio(t["text"])
                if src_cyr > 0.15 and cyrillic_ratio(t["cn"]) > 0.10:
                    try:
                        STATS["api_calls"] += 1
                        t["cn"] = clean(call_gt(t["text"]))
                        print(f"    ↻ 西里尔质检触发单条重翻: {t['field']}#{t['idx']}", flush=True)
                    except Exception as e:
                        print(f"    ✗ 单条重翻失败: {e}", flush=True)
                if src_cyr <= 0.15 or cyrillic_ratio(t["cn"]) < 0.10:
                    STATS["translated"] += 1
                    cache[t["key"]] = {"cn": t["cn"],
                                       "ts": NOW.isoformat(timespec="seconds")}
                else:
                    t["cn"] = t["text"]  # 仍残留：兜底原文，不入缓存
                    STATS["failed"] += 1
            else:
                t["cn"] = t["text"]  # 兜底：保留英文，不入缓存，重跑补翻
                STATS["failed"] += 1
        save_cache(cache_path, cache)

    # ③ 写回 filtered json
    by_file = {}
    for t in tasks:
        by_file.setdefault(t["file"], []).append(t)
    for name, group in by_file.items():
        for t in group:
            group[0]["data"]["items"][t["idx"]][t["field"] + "_cn"] = t["cn"]
        with open(data_dir / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(group[0]["data"], f, ensure_ascii=False, indent=2)

    print(f"\n📊 完成: 命中 {STATS['hit']} | 新翻 {STATS['translated']} | "
          f"失败 {STATS['failed']} | API调用 {STATS['api_calls']} 次 | "
          f"缓存累计 {len(cache)} 条")


if __name__ == "__main__":
    main()
