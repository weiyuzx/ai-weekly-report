# AI 周报生成器

在 OpenClaw 中通过定时任务自动采集 AI 行业资讯，经过滤、复核、解读、翻译，渲染为 PDF 报告并推送。

周报内容聚焦大模型与智能体（Agent）领域，面向从事该领域研究的企业或个人。

## 信源

- **[HuggingFace](https://huggingface.co/models?sort=trending)** — 热门大模型
  - 过滤规则：剔除医学、生物、音频、机器人等非 LLM/Agent 方向，仅保留 ≥32B 且 likes ≥ 100 的模型
- **[GitHub Trending](https://github.com/trending?since=weekly)** — 热门开源项目
  - 过滤规则：剔除音视频、金融、社交、游戏等非模型/Agent 方向的项目
- **[AIBase](https://news.aibase.com)** — AI 行业日报
  - 过滤规则：剔除人事变动、融资商业化、短视频、机器人等无关资讯

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
├── fetch.py         # 数据采集（HF 卡片抓 README 全文落盘）
├── filter.py        # 黑名单过滤
├── tool.py          # workflow 工具集（大文件 IO 适配：slim/prep/assemble）
├── translate.py     # 英文摘要 → 中文（Google Translate 免费 gtx 接口）
├── render.py        # HTML 构建 + wkhtmltopdf 转 PDF
├── templates/
│   └── report.html  # 报告模板
├── openclaw-cron/
│   ├── workflow-prod.js   # 生产工作流（周五 07:10）
│   └── workflow-test.js   # 测试工作流（每日 07:00，迭代验证用）
├── raw/ filtered/ reviewed/ interpreted/   # 数据目录（逐级产物，按日期）
├── cache/           # 翻译缓存（周维度）
└── output/
    ├── prod/        # 正式版 PDF
    └── test/        # 测试版 PDF
```

## 工作流

① fetch.py → ② filter.py → ③ review → ④ interpret → ⑤ translate.py → ⑥ render.py

review 与 interpret 为 LLM 节点，经 OpenClaw 的 llm-task 插件执行：

- review 复核：三源条目逐批提交判定是否属于大模型与智能体方向；头部 AI 企业与算力芯片巨头的重大动态（IPO、融资、核心人事、战略调整）保留；不确定时倾向保留
- interpret 解读：逐条阅读 HF 卡片 README，生成百字内中文通俗介绍，作为卡片正文

LLM 节点失败自动降级（复核失败=过滤结果直出，解读失败=卡片只显更新信息），出刊不依赖 LLM 可用性。

## 在 OpenClaw 中生成定时任务

`openclaw-cron/` 内置生产与测试两份工作流源稿（script 载荷），可直接应用到定时任务：

```bash
# 使用前先修改脚本头部常量：dir（项目路径）、chat（推送目标）、driveFolder（云盘文件夹 token）
openclaw cron edit <job-id> --script openclaw-cron/workflow-prod.js \
  --script-timeout-seconds 900 --script-tool-budget 80

# 手动跑一次验证
openclaw cron run <job-id>
```

## 依赖

- Python 3.12+
- `requests`, `beautifulsoup4`, `Pillow`（pip）
- `wkhtmltopdf`（系统依赖）
- OpenClaw 定时任务（script 载荷）+ llm-task 插件
