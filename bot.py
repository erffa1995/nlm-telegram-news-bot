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

# -----------------------------
# STRICT HIGH IMPACT FILTER (Tier-1 only)
# -----------------------------
HIGH_IMPACT_TERMS = [
    # Inflation (Tier 1)
    "cpi", "core cpi", "pce", "core pce", "inflation",

    # Jobs (Tier 1)
    "non-farm payroll", "nonfarm payroll", "nfp", "payrolls",
    "unemployment rate", "jobs report",

    # Fed / FOMC (Tier 1)
    "fomc", "federal reserve", "fed rate", "rate decision",
    "fed statement", "fed minutes", "powell",

    # Major CB decisions (Tier 1)
    "ecb rate", "boe rate", "boj rate",
    "ecb meeting", "boe meeting", "boj meeting",
    "press conference"
]

# Optional Tier 2 (OFF by default)
HIGH_IMPACT_OPTIONAL = ["gdp", "pmi"]
ALLOW_TIER2 = False  # keep strict

# -----------------------------
# RELEVANCE FILTER (markets you want)
# -----------------------------
RELEVANCE_TERMS = [
    # FX / currencies / pairs
    "eur", "usd", "gbp", "jpy", "chf", "aud", "cad", "nzd",
    "eur/usd", "gbp/usd", "usd/jpy", "usd/chf", "aud/usd", "usd/cad", "nzd/usd",
    "euro", "dollar", "pound", "sterling", "yen",

    # Metals
    "gold", "silver", "xau", "xag",

    # Indices
    "dax", "dow", "nasdaq", "s&p", "spx", "ndx",

    # Energy
    "oil", "brent", "wti", "crude"
]

# -----------------------------
# ONE HASHTAG ONLY (primary asset)
# Priority: FX pair > non-FX asset > single currency fallback
# -----------------------------
PAIR_RULES = [
    ("eur/usd", "#EURUSD"), ("eurusd", "#EURUSD"),
    ("gbp/usd", "#GBPUSD"), ("gbpusd", "#GBPUSD"),
    ("usd/jpy", "#USDJPY"), ("usdjpy", "#USDJPY"),
    ("usd/chf", "#USDCHF"), ("usdchf", "#USDCHF"),
    ("aud/usd", "#AUDUSD"), ("audusd", "#AUDUSD"),
    ("usd/cad", "#USDCAD"), ("usdcad", "#USDCAD"),
    ("nzd/usd", "#NZDUSD"), ("nzdusd", "#NZDUSD"),
    ("eur/gbp", "#EURGBP"), ("eurgbp", "#EURGBP"),
    ("eur/jpy", "#EURJPY"), ("eurjpy", "#EURJPY"),
    ("gbp/jpy", "#GBPJPY"), ("gbpjpy", "#GBPJPY"),
]

NONFX_PRIMARY_RULES = [
    ("xauusd", "#GOLD"), ("gold", "#GOLD"),
    ("xagusd", "#SILVER"), ("silver", "#SILVER"),
    ("wtiusd", "#WTI"), ("wti", "#WTI"),
    ("brnusd", "#BRENT"), ("brent", "#BRENT"),
    ("ndx", "#NASDAQ"), ("nasdaq", "#NASDAQ"),
    ("spx", "#SP500"), ("s&p", "#SP500"),
    ("dji", "#DOWJONES"), ("dow", "#DOWJONES"),
    ("daxeur", "#DAX"), ("dax", "#DAX"),
    ("crude", "#OIL"), ("oil", "#OIL"),
]

CURRENCY_FALLBACK_RULES = [
    (" usd ", "#USD"), ("dollar", "#USD"),
    (" eur ", "#EUR"), ("euro", "#EUR"),
    (" gbp ", "#GBP"), ("pound", "#GBP"), ("sterling", "#GBP"),
    (" jpy ", "#JPY"), ("yen", "#JPY"),
    (" chf ", "#CHF"),
    (" aud ", "#AUD"),
    (" cad ", "#CAD"),
    (" nzd ", "#NZD"),
]

# -----------------------------
# Helpers
# -----------------------------
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

def contains_any(term_list, text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in term_list)

def is_relevant(text: str) -> bool:
    return contains_any(RELEVANCE_TERMS, text)

def is_high_impact(title: str, summary: str) -> bool:
    t = f"{title} {summary}".lower()

    # Strict Tier-1
    if any(k in t for k in HIGH_IMPACT_TERMS):
        return True

    # Optional Tier-2 (disabled by default)
    if ALLOW_TIER2 and any(k in t for k in HIGH_IMPACT_OPTIONAL):
        return True

    return False

def detect_primary_hashtag(text: str) -> str:
    lower = (text or "").lower()

    # 1) FX pair first
    for needle, tag in PAIR_RULES:
        if needle in lower:
            return tag

    # 2) non-FX
    for needle, tag in NONFX_PRIMARY_RULES:
        if needle in lower:
            return tag

    # 3) single currency fallback
    padded = f" {lower} "
    for needle, tag in CURRENCY_FALLBACK_RULES:
        if needle in padded:
            return tag

    return ""

def general_market_impact(text: str) -> str:
    """
    A single, cautious, educational line.
    No entries, targets, stop-losses, or calls-to-action.
    Uses can/could/often language.
    """
    t = (text or "").lower()

    # Inflation
    if any(k in t for k in ["cpi", "inflation", "pce", "core cpi", "core pce"]):
        if any(k in t for k in ["cool", "softer", "lower", "eased", "downside surprise"]):
            return "Softer inflation can strengthen rate-cut expectations, which often weighs on the USD and can support gold and risk assets."
        if any(k in t for k in ["hot", "higher", "sticky", "upside surprise", "accelerated"]):
            return "Hotter inflation can lift rate expectations, which often supports the USD and can pressure gold and rate-sensitive assets."

    # Jobs
    if any(k in t for k in ["non-farm payroll", "nonfarm payroll", "nfp", "jobs report", "unemployment rate", "payrolls"]):
        if any(k in t for k in ["soft", "weaker", "cool", "slower", "edged higher", "missed"]):
            return "Softer jobs data can increase rate-cut expectations, which often weighs on the USD and can support gold and risk assets."
        if any(k in t for k in ["strong", "hot", "higher", "beat", "surprise to the upside"]):
            return "Stronger jobs data can reduce rate-cut expectations, which often supports the USD and can pressure gold and rate-sensitive assets."

    # Central bank decisions / guidance
    if any(k in t for k in ["fomc", "federal reserve", "fed", "ecb", "boe", "boj", "rate decision", "press conference", "minutes", "powell"]):
        if any(k in t for k in ["dovish", "cut", "easing", "earlier cuts"]):
            return "A more dovish policy signal can weaken the currency and support risk assets, depending on expectations and guidance."
        if any(k in t for k in ["hawkish", "hike", "tightening", "higher for longer"]):
            return "A more hawkish policy signal can support the currency and pressure risk assets, depending on expectations and guidance."

    return ""

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
    happened_raw = happened_raw.strip()

    # Make "What happened?" readable
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

            # Must be relevant AND high impact (strict)
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
