"""Single-run price checker for GitHub Actions cron.

Usage:
  python tracker.py           # poll prices, send alerts, update state
  python tracker.py --reset   # recompute bounds from 30-day min/max
"""
import argparse
import json
import os
import time
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).parent / "config.json"
NTFY_BASE = "https://ntfy.sh/"
COINGECKO = "https://api.coingecko.com/api/v3"


def _coin(sym):
    return {
        "symbol": sym,
        "lower": None, "upper": None,
        "lower_triggered": False, "upper_triggered": False,
        "last_price": None, "last_update": None,
        "change_24h": None,
    }


DEFAULT_CONFIG = {
    "ntfy_topic": "your-ntfy-topic-here",
    "coins": {
        "bitcoin": _coin("BTC"),
        "ethereum": _coin("ETH"),
        "solana": _coin("SOL"),
        "binancecoin": _coin("BNB"),
        "ripple": _coin("XRP"),
    },
}


def load_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def fetch_prices(coin_ids):
    if not coin_ids:
        return {}
    r = requests.get(
        f"{COINGECKO}/simple/price",
        params={"ids": ",".join(coin_ids), "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=15,
    )
    r.raise_for_status()
    return {k: {"price": v["usd"], "change_24h": v.get("usd_24h_change")} for k, v in r.json().items() if "usd" in v}


def fetch_monthly_range(coin_id):
    r = requests.get(
        f"{COINGECKO}/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": 30},
        timeout=20,
    )
    r.raise_for_status()
    prices = [p[1] for p in r.json().get("prices", [])]
    if not prices:
        raise ValueError("no price data")
    return min(prices), max(prices)


def get_topic(cfg):
    # Env var takes precedence so you can keep the topic out of a public repo via secrets
    return os.environ.get("NTFY_TOPIC") or cfg.get("ntfy_topic")


def send_ntfy(topic, title, message, priority="urgent", tags=""):
    if not topic:
        print("[skip ntfy] no topic configured")
        return
    try:
        requests.post(
            NTFY_BASE + topic,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": tags},
            timeout=10,
        )
        print(f"[ntfy] {title}")
    except Exception as e:
        print(f"[ntfy error] {e}")


def init_missing(cfg):
    for cid, coin in cfg["coins"].items():
        if coin.get("lower") is None or coin.get("upper") is None:
            try:
                lo, hi = fetch_monthly_range(cid)
                coin["lower"] = round(lo, 4)
                coin["upper"] = round(hi, 4)
                print(f"  init {coin['symbol']}: ${lo:,.2f} - ${hi:,.2f}")
                time.sleep(2)
            except Exception as e:
                print(f"  init failed {cid}: {e}")


def reset_all(cfg):
    for cid, coin in cfg["coins"].items():
        try:
            lo, hi = fetch_monthly_range(cid)
            coin["lower"] = round(lo, 4)
            coin["upper"] = round(hi, 4)
            coin["lower_triggered"] = False
            coin["upper_triggered"] = False
            print(f"  reset {coin['symbol']}: ${lo:,.2f} - ${hi:,.2f}")
            time.sleep(2)
        except Exception as e:
            print(f"  reset failed {cid}: {e}")


def check_and_alert(cfg):
    ids = list(cfg["coins"].keys())
    data = fetch_prices(ids)
    topic = get_topic(cfg)
    now = time.time()
    for cid, d in data.items():
        coin = cfg["coins"][cid]
        price = d["price"]
        coin["last_price"] = price
        coin["change_24h"] = d.get("change_24h")
        coin["last_update"] = now
        sym = coin["symbol"]
        lo = coin.get("lower")
        hi = coin.get("upper")

        if lo is not None:
            if price <= lo and not coin.get("lower_triggered"):
                send_ntfy(
                    topic,
                    f"{sym} broke LOWER ${lo:,.2f}",
                    f"{sym} is at ${price:,.2f} - below your lower bound of ${lo:,.2f}",
                    priority="urgent",
                    tags="rotating_light,chart_with_downwards_trend",
                )
                coin["lower_triggered"] = True
            elif price > lo * 1.01:
                coin["lower_triggered"] = False

        if hi is not None:
            if price >= hi and not coin.get("upper_triggered"):
                send_ntfy(
                    topic,
                    f"{sym} broke UPPER ${hi:,.2f}",
                    f"{sym} is at ${price:,.2f} - above your upper bound of ${hi:,.2f}",
                    priority="urgent",
                    tags="rocket,chart_with_upwards_trend",
                )
                coin["upper_triggered"] = True
            elif price < hi * 0.99:
                coin["upper_triggered"] = False

        print(f"  {sym}: ${price:,.2f}  (lower=${lo}, upper=${hi})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="recompute bounds from 30-day min/max for all coins")
    args = ap.parse_args()
    cfg = load_config()
    if args.reset:
        reset_all(cfg)
    else:
        init_missing(cfg)
        check_and_alert(cfg)
    save_config(cfg)


if __name__ == "__main__":
    main()
