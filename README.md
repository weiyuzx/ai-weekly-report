# AI 周报生成器

在 OpenClaw 中通过定时任务自动采集 AI 行业资讯，过滤、翻译、渲染为精美 PDF 报告并推送给您。

周报内容聚焦大模型与智能体（Agent）领域，面向从事该领域研究的企业或个人。

## 数据源

- **[HuggingFace](https://huggingface.co/models?sort=trending)** — 热门大模型
  - 自动过滤：剔除医学、生物、音频、机器人等非 LLM/Agent 方向，仅保留 ≥32B 模型
- **[GitHub Trending](https://github.com/trending?since=weekly)** — 热门开源项目
  - 自动过滤：剔除音视频、金融、社交、游戏等非模型/Agent 方向的项目
- **[AIBase](https://news.aibase.com)** — AI 行业日报
  - 自动过滤：剔除人事变动、融资商业化、短视频、机器人等无关资讯

## 环境准备

```bash
git clone https://github.com/weiyuzx/ai-weekly-report.git
cd ai-weekly-report

python -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 Pillow

# wkhtmltopdf 为系统依赖（Debian/Ubuntu 示例）
sudo apt install wkhtmltopdf
```

## 项目结构

```
├── fetch.py         # 数据采集
├── filter.py        # 黑名单过滤
├── translate.py     # 英文摘要 → 中文（Google Translate 免费 gtx 接口）
├── render.py        # HTML 构建 + wkhtmltopdf 转 PDF
├── templates/
│   └── report.html  # 报告模板
├── openclaw-cron/
│   ├── workflow-prod.js   # 生产工作流（script 载荷源稿）
│   └── workflow-test.js   # 测试工作流（script 载荷源稿）
├── raw/             # 原始 JSON（按日期）
├── filtered/        # 过滤后 JSON（按日期）
├── cache/           # 翻译缓存（周维度）
└── output/
    ├── prod/        # 正式版 PDF
    └── test/        # 测试版 PDF
```

## 在 OpenClaw 中生成定时任务

`openclaw-cron/` 内置生产与测试两份工作流源稿（script 载荷），可直接应用到定时任务：

```bash
# 使用前先修改脚本头部常量：dir（项目路径）、chat（飞书群）、driveFolder（云盘归档文件夹 token）
openclaw cron edit <job-id> --script openclaw-cron/workflow-prod.js \
  --script-timeout-seconds 900 --script-tool-budget 80

# 手动跑一次验证
openclaw cron run <job-id>
```

## 依赖

- Python 3.12+
- `requests`, `beautifulsoup4`, `Pillow`（pip）
- `wkhtmltopdf`（系统依赖）

## License

MIT
