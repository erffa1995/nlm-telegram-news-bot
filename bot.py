import os
import feedparser
import requests
import json
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL")

STATE_FILE = "state.json"

KEYWORDS = [
    # Forex Majors
    "eurusd", "gbpusd", "usdjpy", "usdchf",
    "audusd", "usdcad", "nzdusd",

    # Forex Crosses
    "eurgbp", "eurjpy", "gbpjpy",

    # Spot Metals
    "xauusd", "gold",
    "xagusd", "silver",

    # Indices
    "dax", "daxeur",
    "dow", "dji",
    "nasdaq", "ndx",
    "s&p", "spx",

    # Energy
    "brent", "brnusd",
    "wti", "wtiusd", "crude oil"
]


FEEDS = {
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "DailyFX": "https://www.dailyfx.com/feeds/market-news",
    "Forexlive": "https://www.forexlive.com/feed/news/"
}

def load_state():
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r") as f:
        return set(json.load(f))

def save_state(ids):
    with open(STATE_FILE, "w") as f:
        json.dump(list(ids), f)

def is_relevant(text):
    text = text.lower()
    return any(k in text for k in KEYWORDS)

def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    requests.post(url, json=payload)

def detect_hashtags(text):
    tags = []

    mapping = {
        "eurusd": "#EURUSD",
        "gbpusd": "#GBPUSD",
        "usdjpy": "#USDJPY",
        "usdchf": "#USDCHF",
        "audusd": "#AUDUSD",
        "usdcad": "#USDCAD",
        "nzdusd": "#NZDUSD",
        "eurgbp": "#EURGBP",
        "eurjpy": "#EURJPY",
        "gbpjpy": "#GBPJPY",
        "xauusd": "#XAUUSD #GOLD",
        "gold": "#GOLD",
        "xagusd": "#XAGUSD #SILVER",
        "silver": "#SILVER",
        "dax": "#DAX",
        "dow": "#DOWJONES",
        "nasdaq": "#NASDAQ",
        "ndx": "#NASDAQ",
        "spx": "#SP500",
        "brent": "#BRENT",
        "wti": "#WTI",
        "crude oil": "#OIL"
    }

    lower = text.lower()
    for key, tag in mapping.items():
        if key in lower and tag not in tags:
            tags.append(tag)

    return " ".join(tags)

def main():
    posted = load_state()

    for source, url in FEEDS.items():
        feed = feedparser.parse(url)

        for entry in feed.entries:
            uid = entry.get("id", entry.get("link"))
            if uid in posted:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")

            if not is_relevant(title + summary):
                continue

            published = entry.get("published", "")
            link = entry.get("link", "")

      message = (
    f"<b>{title}</b>\n\n"
    f"{summary[:500]}...\n\n"
    f"<b>Source:</b> {source}\n"
    f"<b>Date:</b> {published}\n"
    f"<a href='{link}'>Read full article</a>\n\n"
    f"<i>This content is a direct reference to the original source and does not constitute trading advice.</i>"
    f"\n\n{hashtags}"
)


            send_to_telegram(message)
            posted.add(uid)

    save_state(posted)

if __name__ == "__main__":
    main()
