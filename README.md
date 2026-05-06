# CoinWatch

> Lightweight crypto price-alert system. Set a lower and upper bound per coin, get an urgent push notification on your phone the moment a threshold breaks.

![Python](https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/flask-3.0-000?style=flat-square&logo=flask)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-cron-2088FF?style=flat-square&logo=githubactions&logoColor=white)
![ntfy](https://img.shields.io/badge/ntfy.sh-push-317F43?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)

---
---

## What it does

Polls live prices from CoinGecko, compares them against per-coin lower and upper bounds, and fires a push notification to your phone via [ntfy.sh](https://ntfy.sh) the instant a bound is crossed. Bounds auto-initialize from the rolling 30-day min/max so the first run is zero-config.

Two ways to run it:

- **Local mode** — Flask dashboard on `localhost:5000`, polls every 60 s. Best when your laptop is usually on.
- **Cloud mode** — GitHub Actions cron, runs every 5 min on free-tier minutes. Best when you want 24/7 alerts without a host.

Both modes share the same `config.json`, so you can swap freely.

## Features

- **Per-coin lower / upper bounds** with 1 % hysteresis to prevent alert spam at the threshold
- **Auto-initialized bounds** from a coin's 30-day price range (re-anchorable on demand)
- **Push notifications** through ntfy.sh — no app store, no account, free, works on iOS and Android
- **Live web dashboard** with 24 h change, range visualization, and distance-to-trigger chips. Auto-refreshes every 30 s
- **GitHub Actions cron** for serverless 24/7 polling — edit bounds from the GitHub mobile app, no laptop required
- **Single source of truth** — `config.json` holds coins, bounds, trigger state, and last seen prices

## How it works

```
┌──────────────┐     poll prices       ┌─────────────┐
│ tracker.py   │  ───────────────────► │ CoinGecko   │
│ (cron, 5min) │  ◄───── prices ────── │   API       │
└──────┬───────┘                       └─────────────┘
       │ check bounds
       │ update state
       ▼
┌──────────────┐     push (urgent)     ┌─────────────┐
│ config.json  │  ───────────────────► │  ntfy.sh    │ ───► iPhone / Android
└──────────────┘                       └─────────────┘
       ▲
       │ read / write
       │
┌──────┴───────┐
│  app.py      │  Flask dashboard at localhost:5000
│  (local)     │  edit bounds, add coins, trigger test alerts
└──────────────┘
```

A short hysteresis band (~1 %) gates re-arming after a trigger fires so a price hovering at the boundary does not spam notifications.

## Quick start (local)

```bash
git clone https://github.com/abubakrshykh/coinwatch.git
cd coinwatch
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`. On Windows you can just double-click `run.bat`.

In the **ntfy iOS / Android app**, subscribe to your topic (the value of `ntfy_topic` in `config.json`). Tap *send test alert* on the dashboard to verify the push works.

## Quick start (GitHub Actions cron)

1. Push the repo to GitHub (private recommended).
2. **Settings → Actions → General → Workflow permissions → Read and write**.
3. The `poll-prices` workflow runs every 5 min automatically. Trigger manually from the **Actions** tab to test.
4. Edit `config.json` from the GitHub mobile app to change bounds, add or remove coins.
5. Use **`reset-bounds`** (Actions → *Run workflow*) to re-anchor every coin's bounds to the current 30-day range.

If your repo is **public**, remove `ntfy_topic` from `config.json` and put it in **Settings → Secrets and variables → Actions** as `NTFY_TOPIC`. The script reads `os.environ["NTFY_TOPIC"]` first.

## Config schema

```json
{
  "ntfy_topic": "your-unguessable-topic-string",
  "coins": {
    "bitcoin": {
      "symbol": "BTC",
      "lower": 66486.5,
      "upper": 79321.1,
      "lower_triggered": false,
      "upper_triggered": false,
      "last_price": 78462.0,
      "last_update": 1777756999.5,
      "change_24h": 0.65
    }
  }
}
```

Add a coin by inserting a new entry under `"coins"` with the [CoinGecko id](https://api.coingecko.com/api/v3/coins/list) (e.g. `cardano`, `dogecoin`, `chainlink`) and `null` bounds — they auto-fill on the next run.

## Tech stack

| Layer            | Choice                  |
| ---------------- | ----------------------- |
| Price data       | CoinGecko free API      |
| Push delivery    | ntfy.sh                 |
| Local runtime    | Python + Flask          |
| Cloud runtime    | GitHub Actions cron     |
| State            | Single JSON file in git |

## Project layout

```
coinwatch/
├── tracker.py            # single-run cron entrypoint
├── app.py                # Flask dashboard + 60s poll loop
├── config.json           # coins, bounds, trigger state
├── templates/
│   └── index.html        # dashboard UI
├── .github/workflows/
│   ├── poll.yml          # cron: every 5 min
│   └── reset-bounds.yml  # manual: re-anchor monthly bounds
├── requirements.txt
├── run.bat               # Windows one-click launcher
└── LICENSE
```

## Notes

- CoinGecko free tier is rate-limited to ~30 calls/min. The default 60 s poll uses one batched call, well under the limit.
- GitHub Actions cron is best-effort — runs may be delayed 5 – 15 min during peak load.
- ntfy.sh topics are public broadcast channels; anyone who knows the topic name can read your alerts. Use a long, unguessable string.

## License

MIT — see [LICENSE](LICENSE).
