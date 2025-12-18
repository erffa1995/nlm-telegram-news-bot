import os
import json
import feedparser
import requests
import html
import re
from urllib.parse import quote

# ✅ NEWS BOT secrets (new)
BOT_TOKEN = os.getenv("NEWS_BOT_TOKEN")
CHANNEL = os.getenv("NEWS_CHANNEL")

STATE_FILE = "state.json"
MAX_MESSAGE_LEN = 3800

FEEDS = {
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "DailyFX": "https://www.dailyfx.com/feeds/market-news",
    "Forexlive": "https://www.forexlive.com/feed/news/"
}

# STRICT HIGH IMPACT FILTER
HIGH_IMPACT_TERMS = [
    "cpi", "core cpi", "pce", "core pce", "inflation",
    "non-farm payroll", "nonfarm payroll", "nfp", "payrolls",
    "unemployment rate", "jobs report",
    "fomc", "fed minutes", "fed statement", "powell",
    "federal reserve", "fed rate", "rate decision",
    "ecb rate", "boe rate", "boj rate",
    "ecb meeting", "boe meeting", "boj meeting",
    "press conference"
]

# RELEVANCE FILTER
RELEVANCE_TERMS = [
    "eur", "usd", "gbp", "jpy", "chf", "aud", "cad", "nzd",
    "eur/usd", "gbp/usd", "usd/jpy", "usd/chf",
    "gold", "silver", "xau", "xag",
    "dax", "dow", "nasdaq", "s&p", "spx", "ndx",
    "oil", "brent", "wti", "crude"
]

# PRIMARY ASSET DETECTION
PAIR_RULES = [
    ("eur/usd", "EURUSD"), ("eurusd", "EURUSD"),
    ("gbp/usd", "GBPUSD"), ("gbpusd", "GBPUSD"),
    ("usd/jpy", "USDJPY"), ("usdjpy", "USDJPY"),
    ("aud/usd", "AUDUSD"), ("audusd", "AUDUSD"),
    ("usd/cad", "USDCAD"), ("usdcad", "USDCAD"),
    ("nzd/usd", "NZDUSD"), ("nzdusd", "NZDUSD"),
]

NONFX_PRIMARY_RULES = [
    ("gold", "GOLD"), ("xauusd", "GOLD"),
    ("silver", "SILVER"), ("xagusd", "SILVER"),
    ("wti", "WTI"), ("brent", "BRENT"),
    ("nasdaq", "NASDAQ"), ("spx", "SP500"),
    ("dow", "DOWJONES"), ("dax", "DAX"),
    ("oil", "OIL"),
]

def load_state():
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))

def save_state(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f)

def strip_html(text):
    return re.sub(r"\s+", " ", re.sub(r"<.*?>", "", text or "")).strip()

def safe_text(s):
    return html.escape(s or "", quote=False)

def safe_url(url):
    return quote((url or "").strip(), safe=":/?&=#+@;%.,-_~")

def contains_any(lst, text):
    t = (text or "").lower()
    return any(x in t for x in lst)

def is_relevant(text):
    return contains_any(RELEVANCE_TERMS, text)

def is_high_impact(title, summary):
    t = f"{title} {summary}".lower()
    return any(k in t for k in HIGH_IMPACT_TERMS)

def detect_primary_asset(text):
    t = (text or "").lower()
    for k, v in PAIR_RULES:
        if k in t:
            return v
    for k, v in NONFX_PRIMARY_RULES:
        if k in t:
            return v
    return ""

def infer_direction(text):
    t = (text or "").lower()
    if any(w in t for w in ["rises", "rise", "gains", "gain", "strengthens", "surges", "jumps", "climbs"]):
        return "Higher / strengthening"
    if any(w in t for w in ["falls", "fall", "drops", "drop", "weakens", "slides", "declines", "tumbles"]):
        return "Lower / weakening"
    if any(w in t for w in ["pauses", "pause", "range-bound", "range bound", "flat", "stalls", "steady"]):
        return "Paused / range-bound"
    return "Direction not explicitly stated"

def send_to_telegram(msg):
    if not BOT_TOKEN or not CHANNEL:
        raise RuntimeError("Missing NEWS_BOT_TOKEN or NEWS_CHANNEL secrets.")
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHANNEL,
            "text": msg[:MAX_MESSAGE_LEN],
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    if r.status_code != 200:
        print("Telegram error:", r.status_code, r.text[:800])
        return False
    return True

def build_message(source, title, summary, published, link):
    clean_summary = strip_html(summary)
    combined = f"{title} {summary} {link}"

    asset = detect_primary_asset(combined)
    direction = infer_direction(combined)

    # Keep it readable
    happened = clean_summary
    if len(happened) > 850:
        happened = happened[:850].rsplit(" ", 1)[0] + "..."

    parts = [
        "✅ <b>MARKET NEWS</b>\n",
        "📰 <b>Headline</b>",
        safe_text(title) + "\n",
        "📌 <b>What happened?</b>",
        safe_text(happened) + "\n",
        "📊 <b>Impact</b>",
        f"<b>Asset:</b> {safe_text(asset or 'N/A')}",
        f"<b>Direction:</b> {safe_text(direction)}\n",
        "🕒 <b>Source & time</b>",
        f"<b>Source:</b> {safe_text(source)}",
        f"<b>Date:</b> {safe_text(published)}\n",
        f"🔗 <a href=\"{safe_url(link)}\">Read full article</a>",
    ]

    if asset:
        parts.append(f"\n#{asset}")

    msg = "\n".join(parts)
    return msg[:MAX_MESSAGE_LEN]

def main():
    posted = load_state()

    for source, url in FEEDS.items():
        feed = feedparser.parse(url)
        for e in feed.entries:
            uid = e.get("id") or e.get("guid") or e.get("link")
            if not uid or uid in posted:
                continue

            title = e.get("title", "") or ""
            summary = e.get("summary", "") or e.get("description", "") or ""
            link = e.get("link", "") or ""
            published = e.get("published", "") or e.get("updated", "") or ""

            combined = f"{title} {summary} {link}"

            if not is_relevant(combined):
                continue
            if not is_high_impact(title, summary):
                continue

            msg = build_message(source, title, summary, published, link)
            if send_to_telegram(msg):
                posted.add(uid)

    save_state(posted)

if __name__ == "__main__":
    main()
