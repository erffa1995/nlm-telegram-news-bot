import os
import json
import feedparser
import requests
import html
from urllib.parse import quote

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL")

STATE_FILE = "state.json"

KEYWORDS = [
    "eur", "usd", "gbp", "jpy", "chf", "aud", "cad", "nzd",
    "euro", "dollar", "pound", "yen", "sterling",
    "forex", "fx",
    "gold", "silver", "xau", "xag",
    "dax", "dow", "nasdaq", "s&p", "spx", "ndx",
    "oil", "brent", "wti", "crude",
    "fed", "fomc", "ecb", "boe",
    "cpi", "nfp", "inflation",
    "interest rate", "rate hike", "rate cut",
    "risk-on", "risk-off"
]

FEEDS = {
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "DailyFX": "https://www.dailyfx.com/feeds/market-news",
    "Forexlive": "https://www.forexlive.com/feed/news/"
}

GENERAL_HASHTAGS = "#MARKET_NEWS #FOREX #MACRO #EDUCATIONAL #NO_SIGNAL"
MAX_MESSAGE_LEN = 3800


def load_state():
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_state(ids_set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids_set), f)


def is_relevant(text: str) -> bool:
    return any(k in (text or "").lower() for k in KEYWORDS)


def safe_text(s: str) -> str:
    return html.escape(s or "", quote=False)


def safe_url(url: str) -> str:
    return quote((url or "").strip(), safe=":/?&=#+@;%.,-_~")


def send_to_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL,
        "text": message[:MAX_MESSAGE_LEN],
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code != 200:
        print("Telegram error:", r.status_code, r.text[:500])
        return False
    return True


def build_message(source, title, summary, published, link):
    headline = safe_text(title or "Market update")

    happened_raw = summary or (
        "No detailed summary was provided in the RSS feed. "
        "Please refer to the original source for full context."
    )
    happened = safe_text(happened_raw)
    happened_excerpt = happened[:700] + ("..." if len(happened) > 700 else "")

    src = safe_text(source or "")
    dt = safe_text(published or "")
    href = safe_url(link)

    parts = []
    parts.append("✅ <b>MARKET NEWS</b> – <i>Source-based | No Signal</i>\n")

    parts.append("📰 <b>Headline</b>")
    parts.append(headline + "\n")

    parts.append("📌 <b>What happened?</b>")
    parts.append(happened_excerpt + "\n")

    parts.append("🕒 <b>Source & time</b>")
    parts.append(f"<b>Source:</b> {src}")
    parts.append(f"<b>Date:</b> {dt} (as provided by the source)\n")

    if href:
        parts.append(f"🔗 <a href=\"{href}\">Read full article</a>\n")

    parts.append("⚖️ <b>Disclaimer</b>")
    parts.append(
        "<i>This content is a direct reference to the original source and is provided "
        "for informational and educational purposes only. It does not constitute "
        "trading or investment advice.</i>\n"
    )

    parts.append(GENERAL_HASHTAGS)

    msg = "\n".join(parts)
    return msg[:MAX_MESSAGE_LEN]


def main():
    posted = load_state()

    for source, url in FEEDS.items():
        feed = feedparser.parse(url)

        for entry in feed.entries:
            uid = entry.get("id") or entry.get("guid") or entry.get("link")
            if not uid or uid in posted:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")
            published = entry.get("published", "") or entry.get("updated", "")

            if not is_relevant(f"{title} {summary} {link}"):
                continue

            message = build_message(source, title, summary, published, link)

            if send_to_telegram(message):
                posted.add(uid)

    save_state(posted)


if __name__ == "__main__":
    main()
