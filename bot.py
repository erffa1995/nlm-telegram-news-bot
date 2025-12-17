import os
import json
import feedparser
import requests
import html
import re
from urllib.parse import quote

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL")

STATE_FILE = "state.json"
MAX_MESSAGE_LEN = 3800

FEEDS = {
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "DailyFX": "https://www.dailyfx.com/feeds/market-news",
    "Forexlive": "https://www.forexlive.com/feed/news/"
}

# 1) HIGH IMPACT ONLY (keyword-based)
# Keep this list tight to avoid noise.
HIGH_IMPACT_TERMS = [
    "cpi", "inflation", "core inflation", "pce",
    "non-farm payroll", "nonfarm payroll", "nfp", "payrolls",
    "unemployment rate", "jobs report", "employment",
    "fomc", "fed meeting", "federal reserve",
    "interest rate decision", "rate decision", "rate hike", "rate cut",
    "ecb", "boe", "boj", "sn b", "snb", "rba", "boc", "rbnz",
    "gdp", "pmi",
    "cpi report", "pce report"
]

# 2) Relevance filter (markets you care about)
RELEVANCE_TERMS = [
    # FX / major currencies
    "usd", "eur", "gbp", "jpy", "chf", "aud", "cad", "nzd",
    "dollar", "euro", "pound", "sterling", "yen",

    # Metals
    "gold", "silver", "xau", "xag",

    # Indices
    "dax", "dow", "nasdaq", "s&p", "spx", "ndx",

    # Energy
    "oil", "brent", "wti", "crude"
]

# 3) Single hashtag: only the primary asset of the news (ONE hashtag only)
# Order matters: first match wins.
PRIMARY_ASSET_RULES = [
    # Spot metals
    ("xauusd", "#GOLD"), ("gold", "#GOLD"),
    ("xagusd", "#SILVER"), ("silver", "#SILVER"),

    # Energy
    ("wtiusd", "#WTI"), ("wti", "#WTI"),
    ("brnusd", "#BRENT"), ("brent", "#BRENT"),
    ("crude", "#OIL"), ("oil", "#OIL"),

    # Indices
    ("ndx", "#NASDAQ"), ("nasdaq", "#NASDAQ"),
    ("spx", "#SP500"), ("s&p", "#SP500"),
    ("dji", "#DOWJONES"), ("dow", "#DOWJONES"),
    ("daxeur", "#DAX"), ("dax", "#DAX"),

    # FX (if a specific currency dominates)
    ("eurusd", "#EUR"), ("euro", "#EUR"), (" eur ", "#EUR"),
    ("gbpusd", "#GBP"), ("sterling", "#GBP"), (" pound ", "#GBP"),
    ("usdjpy", "#JPY"), (" yen ", "#JPY"),
    ("usd", "#USD"), ("dollar", "#USD"),
]

def load_state():
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))

def save_state(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f)

def strip_html(text: str) -> str:
    clean = re.sub(r"<.*?>", "", text or "")
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()

def safe_text(s: str) -> str:
    return html.escape(s or "", quote=False)

def safe_url(url: str) -> str:
    return quote((url or "").strip(), safe=":/?&=#+@;%.,-_~")

def has_any(term_list, text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in term_list)

def is_high_impact(text: str) -> bool:
    return has_any(HIGH_IMPACT_TERMS, text)

def is_relevant(text: str) -> bool:
    return has_any(RELEVANCE_TERMS, text)

def detect_primary_hashtag(text: str) -> str:
    lower = (text or "").lower()
    for needle, tag in PRIMARY_ASSET_RULES:
        if needle in lower:
            return tag
    return ""  # If nothing matches, no hashtag.

# 4) General impact (public, conditional, no signal)
def general_market_impact(text: str) -> str:
    """
    Very light, educational mapping.
    Uses cautious language: could / may / often.
    No entries, targets, stop-loss, or instructions.
    """
    t = (text or "").lower()

    # Labor market / jobs softening -> earlier cuts expectations
    if any(k in t for k in ["non-farm payroll", "nonfarm payroll", "nfp", "jobs report", "unemployment rate", "payrolls"]):
        if any(k in t for k in ["soft", "weaker", "cool", "slower", "rise in unemployment", "edged higher", "missed"]):
            return ("Softer jobs data can increase expectations of earlier rate cuts. "
                    "That often weighs on the USD and can be supportive for gold and risk assets, though reactions vary.")
        if any(k in t for k in ["strong", "hot", "higher", "beat", "surprise to the upside"]):
            return ("Stronger jobs data can reduce rate-cut expectations. "
                    "That often supports the USD and can pressure gold and rate-sensitive assets, though reactions vary.")

    # Inflation / CPI / PCE
    if any(k in t for k in ["cpi", "inflation", "pce", "core inflation"]):
        if any(k in t for k in ["cool", "softer", "lower", "eased", "downside surprise"]):
            return ("Softer inflation can strengthen rate-cut expectations. "
                    "That often pressures the USD and can support gold and equities, though reactions vary.")
        if any(k in t for k in ["hot", "higher", "sticky", "upside surprise", "accelerated"]):
            return ("Hotter inflation can push rate expectations higher. "
                    "That often supports the USD and can pressure gold and equities, though reactions vary.")

    # Rate decisions / central banks
    if any(k in t for k in ["rate decision", "interest rate decision", "fomc", "fed meeting", "ecb", "boe", "boj", "rba", "boc", "rbnz", "snb"]):
        if any(k in t for k in ["cut", "dovish", "easing", "earlier cuts"]):
            return ("A more dovish tone or rate-cut signal can weaken the currency and support risk assets, "
                    "depending on market positioning and forward guidance.")
        if any(k in t for k in ["hike", "hawkish", "tightening", "higher for longer"]):
            return ("A more hawkish tone or higher-for-longer signal can support the currency and pressure risk assets, "
                    "depending on expectations and guidance.")

    # Oil-specific (if high impact related to supply shocks, geopolitics—often appears in high impact feeds)
    if any(k in t for k in ["wti", "brent", "oil", "crude"]):
        if any(k in t for k in ["supply", "opec", "disruption", "geopolitical", "sanctions"]):
            return ("Supply risks or disruptions can be supportive for oil prices, while improving supply expectations can pressure prices. "
                    "Market reaction often depends on inventories and demand signals.")

    return ""  # if we can't say something safely, we say nothing.

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
        print("Telegram error:", r.status_code, r.text[:800])
        return False
    return True

def build_message(source, title, summary, published, link):
    clean_summary = strip_html(summary or "")
    headline = safe_text((title or "Market update").strip())

    happened_raw = clean_summary or (
        "No detailed summary was provided in the RSS feed. Please refer to the original source for full context."
    )

    # Keep it readable: short excerpt, not raw dump
    happened_raw = happened_raw.strip()
    if len(happened_raw) > 850:
        happened_raw = happened_raw[:850].rsplit(" ", 1)[0] + "..."

    happened = safe_text(happened_raw)

    combined = f"{title} {summary} {link}"
    tag = detect_primary_hashtag(combined)

    impact = general_market_impact(combined)
    impact_line = safe_text(impact) if impact else ""

    parts = []
    parts.append("✅ <b>MARKET NEWS</b> – <i>Source-based | No Signal</i>\n")

    parts.append("📰 <b>Headline</b>")
    parts.append(headline + "\n")

    parts.append("📌 <b>What happened?</b>")
    parts.append(happened + "\n")

    if impact_line:
        parts.append("📍 <b>General market impact (educational)</b>")
        parts.append(impact_line + "\n")

    parts.append("🕒 <b>Source & time</b>")
    parts.append(f"<b>Source:</b> {safe_text(source)}")
    parts.append(f"<b>Date:</b> {safe_text(published)} (as provided by the source)\n")

    if link:
        parts.append(f"🔗 <a href=\"{safe_url(link)}\">Read full article</a>\n")

    parts.append("⚖️ <b>Disclaimer</b>")
    parts.append(
        "<i>This content is a direct reference to the original source and is provided for informational and educational purposes only. "
        "It does not constitute trading or investment advice.</i>"
    )

    if tag:
        parts.append("\n" + tag)

    msg = "\n".join(parts)
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

            combined = f"{title} {summary} {link}"

            # Only relevant + high impact
            if not is_relevant(combined):
                continue
            if not is_high_impact(combined):
                continue

            msg = build_message(source, title, summary, published, link)
            if send_to_telegram(msg):
                posted.add(uid)

    save_state(posted)

if __name__ == "__main__":
    main()
