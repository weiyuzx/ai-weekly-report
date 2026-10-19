#!/usr/bin/env python3
"""workflow 工具函数集（2026-10-14 由 slim.py 改名，项目通用工具库）：

背景：js 编排层（workflow-test.js）的文件通道对大文件有限制，
大文件 IO 统一由本工具在 python 侧完成。三个子命令：

- slim {date}      filtered/hf.json → filtered/hf-slim.json（title/likes/pipeline + readme 前2000字符，
                   供 review 判定读取，~15KB 安全区）
- prep {date}      按 reviewed keep 名单导出 reviewed/{date}/hf-prep/readme-{i}.txt
                   （title + readme 前30000字符，19个入刊模型实测89%等效全文）与 list.json，供 interpret 逐条读取
- assemble {date}  filtered 全字段 + reviewed keep 名单 + hf-prep/interpretation-{i}.txt
                   → interpreted/{date}/huggingface.json（含 readme_interpretation，不含 readme）
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def _load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_slim(date):
    src = SCRIPT_DIR / "filtered" / date / "huggingface.json"
    if not src.exists():
        print("0")
        return
    data = _load(src)
    slim_items = []
    for it in data.get("items", []):
        slim_items.append({
            "title": it.get("title", ""),
            "likes": it.get("likes", 0),
            "pipeline_tag": it.get("pipeline_tag", ""),
            "readme_head": (it.get("readme") or "")[:2000],
        })
    out = {"source": "huggingface", "fetch_date": date, "items": slim_items}
    (src.parent / "huggingface-slim.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(len(slim_items))


def cmd_prep(date):
    rdir = SCRIPT_DIR / "reviewed" / date
    fdir = SCRIPT_DIR / "filtered" / date
    keep_titles = None
    rv = rdir / "huggingface.json"
    if rv.exists():
        keep_titles = {it.get("title", "") for it in _load(rv).get("items", [])}
    fd = _load(fdir / "huggingface.json")
    prep = rdir / "hf-prep"
    prep.mkdir(parents=True, exist_ok=True)
    # 清掉上次残留的 readme/interpretation 临时文件
    for f in prep.glob("readme-*.txt"):
        f.unlink()
    for f in prep.glob("interpretation-*.txt"):
        f.unlink()
    lst = []
    i = 0
    for it in fd.get("items", []):
        t = it.get("title", "")
        if keep_titles is not None and t not in keep_titles:
            continue
        (prep / f"readme-{i}.txt").write_text(
            "TITLE: " + t + "\n\n" + (it.get("readme") or "")[:30000],
            encoding="utf-8")
        lst.append({"i": i, "title": t})
        i += 1
    (prep / "list.json").write_text(json.dumps(lst, ensure_ascii=False), encoding="utf-8")
    print(len(lst))


def cmd_assemble(date):
    rdir = SCRIPT_DIR / "reviewed" / date
    fdir = SCRIPT_DIR / "filtered" / date
    prep = rdir / "hf-prep"

    keep_titles = None
    rv = rdir / "huggingface.json"
    if rv.exists():
        keep_titles = {it.get("title", "") for it in _load(rv).get("items", [])}

    fd = _load(fdir / "huggingface.json")
    interps = {}
    if prep.exists():
        for f in prep.glob("interpretation-*.txt"):
            i = int(f.stem.split("-")[1])
            interps[i] = f.read_text(encoding="utf-8").strip()
    lst = _load(prep / "list.json") if (prep / "list.json").exists() else []
    title2i = {x["title"]: x["i"] for x in lst}

    items = []
    for it in fd.get("items", []):
        t = it.get("title", "")
        if keep_titles is not None and t not in keep_titles:
            continue
        item = {k: v for k, v in it.items() if k != "readme"}
        i = title2i.get(t)
        if i is not None and i in interps:
            item["readme_interpretation"] = interps[i]
        items.append(item)

    out_dir = SCRIPT_DIR / "interpreted" / date
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "huggingface.json").write_text(
        json.dumps({"source": "huggingface", "fetch_date": date, "items": items},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for it in items if it.get("readme_interpretation"))
    print(f"{ok}/{len(items)}")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("slim", "prep", "assemble"):
        print("usage: slim.py slim|prep|assemble {date}", file=sys.stderr)
        sys.exit(1)
    {"slim": cmd_slim, "prep": cmd_prep, "assemble": cmd_assemble}[sys.argv[1]](sys.argv[2])


if __name__ == "__main__":
    main()
