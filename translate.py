#!/usr/bin/env python3
"""
AI周报 - 翻译脚本
读取 filtered/ 下的 huggingface.json 和 github.json，
将英文 summary 翻译为中文，写入 summary_cn 字段。
使用 Google Translate API (translate.googleapis.com)。
"""

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests

SCRIPT_DIR = Path(__file__).parent
FILTERED_DIR = SCRIPT_DIR / "filtered"
NOW = datetime.now(timezone(timedelta(hours=8)))
TODAY = NOW.strftime("%Y-%m-%d")

# Google Translate API
GT_URL = "https://translate.googleapis.com/translate_a/single"
GT_PARAMS = {
    "client": "gtx",
    "sl": "en",
    "tl": "zh-CN",
    "dt": "t",
}
REQUEST_INTERVAL = 0.5  # 秒，请求间隔


def find_latest_filtered_dir():
    """找到 filtered/ 下日期最新的文件夹"""
    if not FILTERED_DIR.exists():
        return None
    dirs = sorted([d for d in FILTERED_DIR.iterdir() if d.is_dir()])
    return dirs[-1] if dirs else None


def translate_single(text):
    """翻译单条文本，返回中文翻译"""
    if not text or not text.strip():
        return text
    r = requests.get(GT_URL, params={**GT_PARAMS, "q": text}, timeout=15)
    r.raise_for_status()
    data = r.json()
    translated = "".join([item[0] for item in data[0] if item[0]])
    return translated.strip()


def translate_batch(texts):
    """批量翻译，每条单独请求（保证顺序和一一对应）"""
    results = []
    total = len(texts)
    for i, text in enumerate(texts, 1):
        try:
            translated = translate_single(text)
            # 清理 Markdown 列表符号（"- " "* " "• " 开头）
            translated = re.sub(r'^(?:[-*•]\s+)+', '', translated)
            results.append(translated)
            print(f"  [{i}/{total}] ✓ {text[:50]}{'…' if len(text) > 50 else ''}")
        except Exception as e:
            print(f"  [{i}/{total}] ✗ {text[:50]}{'…' if len(text) > 50 else ''} — {e}")
            results.append(text)  # 翻译失败保留原文
        if i < total:
            time.sleep(REQUEST_INTERVAL)
    return results


def process_json(filepath):
    """读取 JSON，翻译 summary 和 last_commit，写回 summary_cn 和 last_commit_cn"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print(f"  {filepath.name}: 无数据，跳过")
        return 0

    # 翻译 summary
    summaries = [item.get("summary", "") for item in items]
    print(f"  {filepath.name}: 翻译 {len(summaries)} 条摘要...")
    summary_translations = translate_batch(summaries)

    # 翻译 last_commit（仅 huggingface 有此字段）
    has_last_commit = any(item.get("last_commit", "") for item in items)
    last_commit_translations = []
    if has_last_commit:
        commits = [item.get("last_commit", "") for item in items]
        print(f"  {filepath.name}: 翻译 {len(commits)} 条更新日志...")
        last_commit_translations = translate_batch(commits)

    # 写回
    for i, item in enumerate(items):
        item["summary_cn"] = summary_translations[i]
        if has_last_commit and i < len(last_commit_translations):
            item["last_commit_cn"] = last_commit_translations[i]

    # 保存
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  {filepath.name}: ✅ 完成，已写入 summary_cn" + (" + last_commit_cn" if has_last_commit else ""))
    return len(items)


def main():
    data_dir = find_latest_filtered_dir()
    if not data_dir:
        print("❌ 未找到 filtered 数据目录")
        sys.exit(1)

    print(f"📂 使用数据: {data_dir}")
    total = 0

    for name in ["huggingface", "github"]:
        filepath = data_dir / f"{name}.json"
        if filepath.exists():
            total += process_json(filepath)
        else:
            print(f"  {name}.json: 文件不存在，跳过")

    print(f"\n📊 翻译完成: 共 {total} 条摘要")


if __name__ == "__main__":
    main()
