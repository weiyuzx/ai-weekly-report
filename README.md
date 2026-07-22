# AI 周报生成器

在 OpenClaw 中通过定时任务自动采集 AI 行业资讯，过滤、翻译、渲染为精美 PDF 报告并推送给您。

周报内容聚焦大模型与智能体（Agent）领域，面向从事该领域研究的企业或个人。

## 数据源

- **[HuggingFace](https://huggingface.co/models?sort=trending)** — 热门大模型
  - 自动过滤：剔除医学、生物、音频等非 LLM/Agent 方向，仅保留 ≥32B 模型
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
pip install requests beautifulsoup4 Pillow wkhtmltopdf
```

## 项目结构

```
├── fetch.py         # 数据采集
├── filter.py        # 黑名单过滤
├── translate.py     # 英文摘要 → 中文（Google Translate API）
├── render.py        # HTML 构建 + wkhtmltopdf 转 PDF
├── templates/
│   └── report.html  # 报告模板
├── raw/             # 原始 JSON（按日期）
├── filtered/        # 过滤后 JSON（按日期）
└── output/
    ├── prod/        # 正式版 PDF
    └── test/        # 测试版 PDF
```

## 在 OpenClaw 中生成定时任务

OpenClaw 隔离 session 中自动跑流水线的提示词：

```
执行 AI 周报流水线。项目路径 <project_dir>，venv Python 路径 <project_dir>/.venv/bin/python。

依次执行：
1. fetch.py    — 采集数据
2. filter.py   — 过滤
3. translate.py — 翻译
4. render.py   — 渲染（正式版不加参数，测试版加 test）

将生成的 PDF 用 message 工具发送到群聊。
```

## 依赖

- Python 3.12+
- `requests`, `beautifulsoup4`, `Pillow`, `wkhtmltopdf`

## License

MIT
