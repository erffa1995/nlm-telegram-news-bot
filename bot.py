import os
import json
import feedparser
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL")

STATE_FILE = "state.json"

# Strict scope keywords (symbols + common market words used in headlines)
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
    "wti", "wtiusd", "crude oil",

    # Common market wording (helps when symbols are not mentioned explicitly)
    "euro", "pound", "sterling", "yen", "swiss franc", "loonie", "aussie", "kiwi",
    "dollar", "u.s. dollar", "greenback",
    "fed", "fomc", "ecb", "boe",
    "cpi", "nfp", "inflation", "interest rates", "rate cut", "rate hike",
    "risk-on", "risk-off"
]

# RSS feeds (you can add more)
FEEDS = {
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "DailyFX": "https://www.dailyfx.com/feeds/market-news",
    "Forexlive": "https://www.forexlive.com/feed/news/"
}


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


def detect_hashtags(text: str) -> str:
    """
    Adds searchable tags to Telegram messages.
    Purely classification/tagging (no analysis).
    """
    tags = []
    mapping = {
        # Forex majors
        "eurusd": "#EURUSD",
        "gbpusd": "#GBPUSD",
        "usdjpy": "#USDJPY",
        "usdchf": "#USDCHF",
        "audusd": "#AUDUSD",
        "usdcad": "#USDCAD",
        "nzdusd": "#NZDUSD",

        # Forex crosses
        "eurgbp": "#EURGBP",
        "eurjpy": "#EURJPY",
        "gbpjpy": "#GBPJPY",

        # Metals
        "xauusd": "#XAUUSD #GOLD",
        "gold": "#GOLD",
        "xagusd": "#XAGUSD #SILVER",
        "silver": "#SILVER",

        # Indices
        "daxeur": "#DAXEUR #DAX",
        "dax": "#DAX",
        "dji": "#DJIUSD #DOWJONES",
        "dow": "#DOWJONES",
        "ndx": "#NDXUSD #NASDAQ",
        "nasdaq": "#NASDAQ",
        "spx": "#SPXUSD #SP500",
        "s&p": "#SP500",

        # Energy
        "brnusd": "#BRNUSD #BRENT",
        "brent": "#BRENT",
        "wtiusd": "#WTIUSD #WTI",
        "wti": "#WTI",
        "crude oil": "#OIL"
    }

    lower = (text or "").lower()
    for key, tag in mapping.items():
        if key in lower and tag not in tags:
            tags.append(tag)

    # Add general category tags (still not analysis)
    category_tags = []
    if any(x in lower for x in [
        "eurusd", "gbpusd", "usdjpy", "usdchf", "audusd", "usdcad", "nzdusd", "eurgbp", "eurjpy", "gbpjpy",
        "euro", "pound", "sterling", "yen", "swiss franc", "loonie", "aussie", "kiwi", "dollar", "greenback"
    ]):
        category_tags.append("#FOREX")
    if any(x in lower for x in ["xauusd", "xagusd", "gold", "silver"]):
        category_tags.append("#METALS")
    if any(x in lower for x in ["dax", "daxeur", "dow", "dji", "nasdaq", "ndx", "s&p", "spx"]):
        category_tags.append("#INDICES")
    if any(x in lower for x in ["brent", "wti", "crude oil", "brnusd", "wtiusd"]):
        category_tags.append("#ENERGY")

    out = " ".join(tags + category_tags).strip()
    return out


def send_to_telegram(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()


def build_interpretive_message(
    source: str,
    title: str,
    summary: str,
    published: str,
    link: str,
    hashtags: str
) -> str:
    """
    STRICT mode:
    - Source-based excerpt only (no added interpretation / forecasts)
    - No buy/sell signals
    - Adds an ALWAYS-present "Who should pay attention" section,
      but as a GENERAL educational note (not tied to this specific news).
    """

    headline = (title or "").strip() or "Market update"
    happened = (summary or "").strip()

    if not happened:
        happened = "No summary provided in the RSS feed. Please refer to the source link for full context."

    # Keep excerpt reasonably short to avoid long reposts
    happened_excerpt = happened[:700] + ("..." if len(happened) > 700 else "")

    msg_parts = []
    msg_parts.append("✅ <b>MARKET NEWS</b> – <i>Source-based | No Signal | Practical for all traders</i>\n")

    msg_parts.append("📰 <b>Headline</b>")
    msg_parts.append(headline + "\n")

    msg_parts.append("📌 <b>What happened?</b>")
    msg_parts.append(happened_excerpt + "\n")

    # Always present, GENERAL, non-directional educational note
    msg_parts.append("👥 <b>Who should pay attention</b>")
    msg_parts.append("<i>Educational note (general):</i>")
    msg_parts.append("Beginners: Focus on how scheduled news can change volatility and spreads (observe, don’t react fast).")
    msg_parts.append("Active traders: Monitor liquidity conditions and the economic calendar timing (avoid decisions without context).")
    msg_parts.append("Swing traders / Investors: Track whether the narrative connects to central bank policy or macro trends over weeks.\n")

    msg_parts.append("🕒 <b>Source & time</b>")
    msg_parts.append(f"<b>Source:</b> {source}")
    msg_parts.append(f"<b>Date:</b> {published} (as provided by the source)\n")

    msg_parts.append(f"🔗 <a href='{link}'>Read full article</a>\n")

    msg_parts.append("⚖️ <b>Disclaimer</b>")
    msg_parts.append(
        "<i>This content is a direct reference to the original source and is provided for informational and educational purposes only. "
        "It does not constitute trading or investment advice.</i>"
    )

    if hashtags:
        msg_parts.append("\n" + hashtags)

    return "\n".join(msg_parts)


def main():
    posted = load_state()

    for source, url in FEEDS.items():
        feed = feedparser.parse(url)

        for entry in feed.entries:
            uid = entry.get("id") or entry.get("guid") or entry.get("link")
            if not uid:
                continue
            if uid in posted:
                continue

            title = entry.get("title", "") or ""
            summary = entry.get("summary", "") or entry.get("description", "") or ""
            link = entry.get("link", "") or ""
            published = entry.get("published", "") or entry.get("updated", "") or ""

            combined = f"{title} {summary} {link}"
            if not is_relevant(combined):
                continue

            hashtags = detect_hashtags(combined)

            message = build_interpretive_message(
                source=source,
                title=title,
                summary=summary,
                published=published,
                link=link,
                hashtags=hashtags
            )

            send_to_telegram(message)
            posted.add(uid)

    save_state(posted)


if __name__ == "__main__":
    main()
