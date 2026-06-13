# Automotive Materials Intelligence Hub

汽车新材料与前沿技术情报平台是一个面向汽车新材料研究人员的每日情报简报网站。系统目标是每天采集当月汽车新材料、先进制造、前沿技术、专利、论文、企业技术动态等信息，经过规则筛选和 DeepSeek API 结构化分析后，生成 GitHub Pages 静态网站，并通过钉钉/咚咚群机器人推送摘要。

## Core Rules

- 不编造新闻、来源、日期或链接。
- 每条新闻必须保留真实原文 URL。
- 只收录当前月份内容。
- 每日最终发布 5-8 条高价值信息。
- DeepSeek 仅用于摘要、分类、技术要点和影响评估，不能作为新闻来源。
- 先做规则筛选，再少量调用 AI，以控制免费额度消耗。

## Directory Structure

```text
auto-materials-intelligence-hub/
├── scripts/              # Pipeline scripts, each with a main() entry point
├── data/                 # Source registry and JSON pipeline artifacts
├── docs/                 # GitHub Pages output
│   ├── daily/            # Daily archive pages
│   ├── monthly/          # Monthly archive pages
│   └── assets/           # Static CSS and future assets
├── templates/            # Jinja2 templates
├── .github/workflows/    # Daily automation workflow
├── config.yaml           # Limits, timezone, site, and category config
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
└── README.md
```

## Local Setup

```bash
cd auto-materials-intelligence-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the full local pipeline:

```bash
python -m pip install -r requirements.txt
python scripts/fetch_news.py
python scripts/filter_candidates.py
python scripts/analyze_deepseek.py
python scripts/rank_select.py
python scripts/build_site.py
python scripts/push_bot.py
```

Preview the site:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000/docs/`.

## Configuration

The default limits live in `config.yaml`:

```yaml
limits:
  max_news_candidates: 150
  max_filtered_news: 20
  max_ai_analysis: 8
  daily_publish_min: 5
  daily_publish_max: 8
timezone: Asia/Shanghai
```

Secrets should be copied from `.env.example` into a local `.env` file or configured as GitHub Actions secrets.

## DingTalk Bot Push

The project currently supports DingTalk custom robots for daily Markdown brief delivery. Dongdong or other robots can be added later after their webhook format is confirmed.

To create a DingTalk custom robot:

1. Open the target DingTalk group settings.
2. Add a custom robot from the group robot settings.
3. Choose the security mode required by your organization. If you enable signing, copy the generated secret.
4. Copy the webhook URL.

Create a local `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Configure the bot:

```bash
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=your_token
DINGTALK_SECRET=your_signing_secret
SITE_URL=https://your-github-pages-url/
```

Local dry-run, without sending a real message:

```bash
unset DINGTALK_WEBHOOK
python3 scripts/push_bot.py
```

Local real push:

```bash
python3 scripts/push_bot.py
```

For GitHub Actions, configure `DINGTALK_WEBHOOK`, `DINGTALK_SECRET`, `SITE_URL`, and `DEEPSEEK_API_KEY` as GitHub Secrets. Do not commit real webhook URLs or secrets to the repository.

## GitHub Deployment

### 1. Local Run

From the repository root:

```bash
python -m pip install -r requirements.txt
python scripts/fetch_news.py
python scripts/filter_candidates.py
python scripts/analyze_deepseek.py
python scripts/rank_select.py
python scripts/build_site.py
python scripts/push_bot.py
```

### 2. GitHub Secrets

Go to the GitHub repository:

`Settings → Secrets and variables → Actions → New repository secret`

Add these repository secrets:

- `DEEPSEEK_API_KEY`: DeepSeek API Key.
- `DINGTALK_WEBHOOK`: DingTalk custom robot webhook.
- `DINGTALK_SECRET`: DingTalk robot signing secret. Optional but recommended.
- `SITE_URL`: GitHub Pages site URL.

If `SITE_URL` is not known during the first deployment, leave it empty first. After GitHub Pages generates the final URL, add it back as a repository secret.

### 3. GitHub Pages

Go to:

`Settings → Pages`

Use these settings:

- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/docs`

### 4. Manual Run

Go to:

`Actions → Daily Auto Materials Brief → Run workflow`

This manually starts the same pipeline used by the daily schedule.

### 5. Schedule

The workflow runs every day at Beijing time 09:00.

GitHub Actions cron uses UTC, so the workflow is configured as:

```yaml
cron: "0 1 * * *"
```

### 6. Deployment Notes

- The workflow reads secrets from GitHub Actions and does not print them.
- `.env` is ignored by Git and must not be committed.
- If no `DINGTALK_WEBHOOK` is configured, `push_bot.py` runs in dry-run mode and the workflow does not fail.
- If there are no changes under `data/` or `docs/`, the workflow skips commit and push.
- GitHub Pages serves the generated static site from `/docs`.

## Development Stages

1. Project skeleton: directories, configuration, placeholder scripts, README, and placeholder site.
2. Source configuration and collection: RSS/Bing News RSS/web source ingestion with real URLs.
3. Current-month and keyword filtering: rule-based screening before AI calls.
4. DeepSeek analysis: structured summaries, categories, technical points, and impact fields.
5. Ranking and daily selection: select 5-8 high-value items.
6. Static site generation: index, daily archive, monthly archive, filters, and source links.
7. Bot push: DingTalk/Dongdong summary with site link.
8. GitHub Actions and Pages hardening: scheduled Beijing 09:00 run, commits, and publishing.

## Stage 1 Status

This stage does not fetch news, call DeepSeek, or push robots. The included `docs/index.html` is a static placeholder and contains no news items.
