import os
import json
import feedparser
import requests
import html
from urllib.parse import quote

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL")

STATE_FILE = "state.json"

# Keywords to decide whether a news item is relevant
KEYWORDS = [
    # Forex & macro wording
    "eur", "usd", "gbp", "jpy", "chf", "aud", "cad", "nzd",
    "euro", "dollar", "pound", "yen", "sterling",
    "forex", "fx",

    # Metals
    "gold", "silver", "xau", "xag",

    # Indices
    "dax", "dow", "nasdaq", "s&p", "spx", "ndx",

    # Energy
    "oil", "brent", "wti", "crude",

    # Macro events
    "fed", "fomc", "ecb", "boe",
    "cpi", "nfp", "inflation",
    "interest rate", "rate hike", "rate cut",
    "risk-on", "risk-off"
]

# RSS feeds (free & public)
FEEDS = {
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "DailyFX": "https://www.dailyfx.com/feeds/market-news",
    "Forexlive": "https://www.forexlive.com/feed/news/"
}

# Fixed, general hashtags (same for all posts)
GENERAL_HASHTAGS = "#MARKET_NEWS #FOREX #MACRO #EDUCATIONAL #NO_SIGNAL"

# Telegram hard limit is 4096 chars; keep margin for safety
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
    t = (text or "").lower()
    return any(k in t for k in KEYWORDS)


def safe_text(s: str) -> str:
    """Escape text for Telegram HTML parse_mode."""
    return html.escape(s or "", quote=False)


def safe_url(url: str) -> str:
    """
    Make URL safer inside href. Keeps : / ? & = # but escapes spaces and odd chars.
    """
    url = (url or "").strip()
    if not url:
        return ""
    return quote(url, safe=":/?&=#+@;%.,-_~")


def send_to_telegram(message: str) -> bool:
    """
    Send message; if Telegram rejects due to HTML/entity issues, log details and skip that item
    instead of failing the whole run.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL,
        "text": message[:MAX_MESSAGE_LEN],
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            # Print Telegram error body to Actions logs
            print("Telegram sendMessage failed:", r.status_code, r.text[:1000])
            return False
        return True
    except Exception as e:
        print("Telegram sendMessage exception:", repr(e))
        return False


def build_message(source, title, summary, published, link):
    """
    Strict source-based template.
    No personal analysis. No forecasts. No trading signals.
    """
    headline = safe_text((title or "").strip() or "Market update")

    # RSS summaries often include HTML. feedparser sometimes keeps it. We escape it.
    happened_raw = (summary or "").strip()
    if not happened_raw:
        happened_raw = (
            "No detailed summary was provided in the RSS feed. "
            "Please refer to the original source for full context."
        )

    happened = safe_text(happened_raw)
    happened_excerpt = happened[:700] + ("..." if len(happened) > 700 else "")

    src = safe_text(source or "")
    dt = safe_text(published or "")

    href = safe_url(link)
    if href:
        read_more = f"🔗 <a href=\"{href}\">Read full article</a>\n"
    else:
        read_more = "🔗 Read full article (link unavailable)\n"

    parts = []
    parts.append("✅ <b>MARKET NEWS</b> – <i>Source-based | No Signal | Practical for all traders</i>\n")

    parts.append("📰 <b>Headline</b>")
    parts.append(headline + "\n")

    parts.append("📌 <b>What happened?</b>")
    parts.append(happened_excerpt + "\n")

    parts.append("👥 <b>Who should pay attention</b>")
    parts.append(
        "Anyone following FX, metals, indices, or oil—especially around major "
        "economic releases, when volatility and market conditions can change quickly.\n"
    )

    parts.append("🕒 <b>Source & time</b>")
    parts.append(f"<b>Source:</b> {src}")
    parts.append(f"<b>Date:</b> {dt} (as provided by the source)\n")

    parts.append(read_more)

    parts.append("⚖️ <b>Disclaimer</b>")
    parts.append(
        "<i>This content is a direct reference to the original source and is provided "
        "for informational and educational purposes only. It does not constitute "
        "trading or investment advice.</i>\n"
    )

    parts.append(GENERAL_HASHTAGS)

    msg = "\n".join(parts)

    # Final safety trim
    if len(msg) > MAX_MESSAGE_LEN:
        msg = msg[:MAX_MESSAGE_LEN - 3] + "..."

    return msg


def main():
    posted = load_state()

    for source, url in FEEDS.items():
        feed = feedparser.parse(url)

        for entry in feed.entries:
            uid = entry.get("id") or entry.get("guid") or entry.get("link")
            if not uid or uid in posted:
                continue

            title = entry.get("title", "") or ""
            summary = entry.get("summary", "") or entry.get("description", "") or ""
            link = entry.get("link", "") or ""
            published = entry.get("published", "") or entry.get("updated", "") or ""

            combined_text = f"{title} {summary} {link}"
            if not is_relevant(combined_text):
                continue

            message = build_message(
                source=source,
                title=title,
                summary=summary,
                published=published,
                link=link
            )

            ok = send_to_telegram(message)
            if ok:
                posted.add(uid)
            else:
                # Skip this item (don’t mark as posted so it can be retried later if needed)
                print("Skipped item due to Telegram error. UID:", uid)

    save_state(posted)


if __name__ == "__main__":
    main()
