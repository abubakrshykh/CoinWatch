import json
import threading
import time
from pathlib import Path

import requests
from flask import Flask, render_template, request, redirect, url_for

CONFIG_PATH = Path(__file__).parent / "config.json"
POLL_INTERVAL = 60  # seconds between price checks
NTFY_BASE = "https://ntfy.sh/"
COINGECKO = "https://api.coingecko.com/api/v3"

def _coin(sym):
    return {
        "symbol": sym,
        "lower": None, "upper": None,
        "lower_triggered": False, "upper_triggered": False,
        "last_price": None, "last_update": None,
        "change_24h": None,
        "position": None,
    }


DEFAULT_CONFIG = {
    "ntfy_topic": "your-ntfy-topic-here",
    "coins": {
        "bitcoin":     _coin("BTC"),
        "ethereum":    _coin("ETH"),
        "solana":      _coin("SOL"),
        "binancecoin": _coin("BNB"),
        "ripple":      _coin("XRP"),
    },
}

_lock = threading.Lock()


def load_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def fetch_prices(coin_ids):
    if not coin_ids:
        return {}
    url = f"{COINGECKO}/simple/price"
    r = requests.get(
        url,
        params={
            "ids": ",".join(coin_ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        },
        timeout=15,
    )
    r.raise_for_status()
    out = {}
    for k, v in r.json().items():
        if "usd" in v:
            out[k] = {"price": v["usd"], "change_24h": v.get("usd_24h_change")}
    return out


def fetch_monthly_range(coin_id):
    url = f"{COINGECKO}/coins/{coin_id}/market_chart"
    r = requests.get(url, params={"vs_currency": "usd", "days": 30}, timeout=20)
    r.raise_for_status()
    prices = [p[1] for p in r.json().get("prices", [])]
    if not prices:
        raise ValueError("no price data returned")
    return min(prices), max(prices)


def send_ntfy(topic, title, message, priority="urgent", tags=""):
    try:
        requests.post(
            NTFY_BASE + topic,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": tags},
            timeout=10,
        )
    except Exception as e:
        print(f"[ntfy error] {e}")


def check_and_alert(cfg):
    ids = list(cfg["coins"].keys())
    data = fetch_prices(ids)
    now = time.time()
    for cid, d in data.items():
        coin = cfg["coins"][cid]
        price = d["price"]
        coin["last_price"] = price
        coin["change_24h"] = d.get("change_24h")
        coin["last_update"] = now
        sym = coin["symbol"]
        lower = coin.get("lower")
        upper = coin.get("upper")

        # LOWER bound breach
        if lower is not None:
            if price <= lower and not coin.get("lower_triggered"):
                send_ntfy(
                    cfg["ntfy_topic"],
                    f"{sym} broke LOWER ${lower:,.2f}",
                    f"{sym} is at ${price:,.2f} — below your lower bound of ${lower:,.2f}",
                    priority="urgent",
                    tags="rotating_light,chart_with_downwards_trend",
                )
                coin["lower_triggered"] = True
            elif price > lower * 1.01:  # 1% hysteresis to re-arm
                coin["lower_triggered"] = False

        # UPPER bound breach
        if upper is not None:
            if price >= upper and not coin.get("upper_triggered"):
                send_ntfy(
                    cfg["ntfy_topic"],
                    f"{sym} broke UPPER ${upper:,.2f}",
                    f"{sym} is at ${price:,.2f} — above your upper bound of ${upper:,.2f}",
                    priority="urgent",
                    tags="rocket,chart_with_upwards_trend",
                )
                coin["upper_triggered"] = True
            elif price < upper * 0.99:
                coin["upper_triggered"] = False


def poller():
    while True:
        try:
            with _lock:
                cfg = load_config()
                check_and_alert(cfg)
                save_config(cfg)
        except Exception as e:
            print(f"[poll error] {e}")
        time.sleep(POLL_INTERVAL)


def init_bounds_if_missing():
    with _lock:
        cfg = load_config()
        for cid, coin in cfg["coins"].items():
            if coin.get("lower") is None or coin.get("upper") is None:
                try:
                    lo, hi = fetch_monthly_range(cid)
                    coin["lower"] = round(lo, 4)
                    coin["upper"] = round(hi, 4)
                    print(f"  {coin['symbol']:<5} bounds: ${lo:,.2f} – ${hi:,.2f}")
                    time.sleep(1.5)  # be polite to free API
                except Exception as e:
                    print(f"  {coin['symbol']:<5} init failed: {e}")
        save_config(cfg)


# ---------------- Flask ----------------
app = Flask(__name__)


@app.route("/")
def index():
    cfg = load_config()
    return render_template("index.html", cfg=cfg, now=time.time())


@app.route("/api/state")
def api_state():
    cfg = load_config()
    return {"coins": cfg["coins"], "ntfy_topic": cfg["ntfy_topic"], "now": time.time()}


@app.route("/update", methods=["POST"])
def update():
    cid = request.form.get("coin_id", "")
    lower = request.form.get("lower", "").strip()
    upper = request.form.get("upper", "").strip()
    with _lock:
        cfg = load_config()
        if cid in cfg["coins"]:
            cfg["coins"][cid]["lower"] = float(lower) if lower else None
            cfg["coins"][cid]["upper"] = float(upper) if upper else None
            cfg["coins"][cid]["lower_triggered"] = False
            cfg["coins"][cid]["upper_triggered"] = False
            save_config(cfg)
    return redirect(url_for("index"))


@app.route("/add", methods=["POST"])
def add_coin():
    cid = request.form.get("coin_id", "").strip().lower()
    symbol = request.form.get("symbol", "").strip().upper()
    if not cid:
        return redirect(url_for("index"))
    try:
        lo, hi = fetch_monthly_range(cid)
    except Exception as e:
        return f"Could not add '{cid}'. CoinGecko error: {e}. Use the CoinGecko id (e.g. 'cardano', not 'ADA').", 400
    with _lock:
        cfg = load_config()
        if cid not in cfg["coins"]:
            new = _coin(symbol or cid.upper()[:5])
            new["lower"] = round(lo, 4)
            new["upper"] = round(hi, 4)
            cfg["coins"][cid] = new
            save_config(cfg)
    return redirect(url_for("index"))


@app.route("/remove/<cid>", methods=["POST"])
def remove(cid):
    with _lock:
        cfg = load_config()
        if cid in cfg["coins"]:
            del cfg["coins"][cid]
            save_config(cfg)
    return redirect(url_for("index"))


@app.route("/reset/<cid>", methods=["POST"])
def reset(cid):
    try:
        lo, hi = fetch_monthly_range(cid)
    except Exception as e:
        return f"Reset failed: {e}", 400
    with _lock:
        cfg = load_config()
        if cid in cfg["coins"]:
            cfg["coins"][cid]["lower"] = round(lo, 4)
            cfg["coins"][cid]["upper"] = round(hi, 4)
            cfg["coins"][cid]["lower_triggered"] = False
            cfg["coins"][cid]["upper_triggered"] = False
            save_config(cfg)
    return redirect(url_for("index"))


@app.route("/test")
def test_notify():
    cfg = load_config()
    send_ntfy(
        cfg["ntfy_topic"],
        "Crypto tracker test",
        "If you see this, ntfy + your topic are wired up correctly.",
        priority="default",
        tags="white_check_mark",
    )
    return redirect(url_for("index"))


@app.route("/position/<cid>", methods=["POST"])
def open_position(cid):
    side = request.form.get("side", "long")
    if side not in ("long", "short"):
        return "side must be long or short", 400
    try:
        entry = float(request.form["entry_price"])
        margin = float(request.form["margin"])
        leverage = float(request.form["leverage"])
    except (KeyError, ValueError):
        return "entry_price, margin, leverage must all be numbers", 400
    if entry <= 0 or margin <= 0 or leverage < 1:
        return "entry/margin must be > 0 and leverage >= 1", 400
    with _lock:
        cfg = load_config()
        if cid in cfg["coins"]:
            cfg["coins"][cid]["position"] = {
                "active": True,
                "side": side,
                "entry_price": entry,
                "margin": margin,
                "leverage": leverage,
            }
            save_config(cfg)
    return redirect(url_for("index"))


@app.route("/position/<cid>/close", methods=["POST"])
def close_position(cid):
    with _lock:
        cfg = load_config()
        if cid in cfg["coins"]:
            cfg["coins"][cid]["position"] = None
            save_config(cfg)
    return redirect(url_for("index"))


@app.route("/topic", methods=["POST"])
def update_topic():
    new_topic = request.form.get("ntfy_topic", "").strip()
    if new_topic:
        with _lock:
            cfg = load_config()
            cfg["ntfy_topic"] = new_topic
            save_config(cfg)
    return redirect(url_for("index"))


if __name__ == "__main__":
    print("Initializing bounds from 30-day min/max where missing...")
    init_bounds_if_missing()
    print("Starting price poller (every 60s)...")
    threading.Thread(target=poller, daemon=True).start()
    print("Dashboard: http://localhost:5000  (or http://<your-pc-ip>:5000 from your phone)")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
