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
    "fomc", "fed minutes", "fed statement", "powell",
    "federal reserve", "fed rate", "rate decision", "interest rate decision",

    # Major CB decisions (Tier 1)
    "ecb rate", "boe rate", "boj rate",
    "ecb meeting", "boe meeting", "boj meeting",
    "press conference"
]

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
# Primary asset detection (ONE hashtag only)
# Priority: FX pair > non-FX asset > currency fallback
# -----------------------------
PAIR_RULES = [
    ("eur/usd", "EURUSD"), ("eurusd", "EURUSD"),
    ("gbp/usd", "GBPUSD"), ("gbpusd", "GBPUSD"),
    ("usd/jpy", "USDJPY"), ("usdjpy", "USDJPY"),
    ("usd/chf", "USDCHF"), ("usdchf", "USDCHF"),
    ("aud/usd", "AUDUSD"), ("audusd", "AUDUSD"),
    ("usd/cad", "USDCAD"), ("usdcad", "USDCAD"),
    ("nzd/usd", "NZDUSD"), ("nzdusd", "NZDUSD"),
    ("eur/gbp", "EURGBP"), ("eurgbp", "EURGBP"),
    ("eur/jpy", "EURJPY"), ("eurjpy", "EURJPY"),
    ("gbp/jpy", "GBPJPY"), ("gbpjpy", "GBPJPY"),
]

NONFX_PRIMARY_RULES = [
    ("xauusd", "GOLD"), ("gold", "GOLD"),
    ("xagusd", "SILVER"), ("silver", "SILVER"),
    ("wtiusd", "WTI"), ("wti", "WTI"),
    ("brnusd", "BRENT"), ("brent", "BRENT"),
    ("ndx", "NASDAQ"), ("nasdaq", "NASDAQ"),
    ("spx", "SP500"), ("s&p", "SP500"),
    ("dji", "DOWJONES"), ("dow", "DOWJONES"),
    ("daxeur", "DAX"), ("dax", "DAX"),
    ("crude", "OIL"), ("oil", "OIL"),
]

CURRENCY_FALLBACK_RULES = [
    (" usd ", "USD"), ("dollar", "USD"),
    (" eur ", "EUR"), ("euro", "EUR"),
    (" gbp ", "GBP"), ("pound", "GBP"), ("sterling", "GBP"),
    (" jpy ", "JPY"), ("yen", "JPY"),
    (" chf ", "CHF"),
    (" aud ", "AUD"),
    (" cad ", "CAD"),
    (" nzd ", "NZD"),
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
    return any(k in t for k in HIGH_IMPACT_TERMS)

def detect_primary_asset(text: str) -> str:
    lower = (text or "").lower()

    for needle, sym in PAIR_RULES:
        if needle in lower:
            return sym

    for needle, sym in NONFX_PRIMARY_RULES:
        if needle in lower:
            return sym

    padded = f" {lower} "
    for needle, sym in CURRENCY_FALLBACK_RULES:
        if needle in padded:
            return sym

    return ""

def primary_hashtag(asset: str) -> str:
    return f"#{asset}" if asset else ""

def infer_direction(text: str, primary: str) -> str:
    """
    Direction inferred only from explicit wording in title/summary.
    Returns: UP / DOWN / NEUTRAL / VOLATILITY / UNCLEAR
    """
    t = (text or "").lower()

    up_words = ["rises", "rise", "rallies", "rally", "gains", "gain", "jumps", "surges", "climbs", "advances", "strengthens"]
    down_words = ["falls", "fall", "drops", "drop", "slides", "slide", "tumbles", "declines", "decline", "weakens", "sinks"]
    neutral_words = ["pauses", "stalls", "steady", "range-bound", "range bound", "flat", "sideways", "consolidates", "consolidation"]
    vol_words = ["volatile", "volatility", "whipsaw", "swings", "choppy"]

    has_up = any(w in t for w in up_words)
    has_down = any(w in t for w in down_words)
    has_neutral = any(w in t for w in neutral_words)
    has_vol = any(w in t for w in vol_words)

    if has_vol or (has_up and has_down):
        return "VOLATILITY"
    if has_neutral and not (has_up or has_down):
        return "NEUTRAL"
    if has_up and not has_down:
        return "UP"
    if has_down and not has_up:
        return "DOWN"

    # Mechanical FX inference only when text explicitly says a currency strengthens/weakens
    fx_pairs = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "EURGBP", "EURJPY", "GBPJPY"}
    if primary in fx_pairs:
        base = primary[:3]
        quote = primary[3:]

        def c_strengthens(ccy: str) -> bool:
            return (f" {ccy.lower()} " in f" {t} ") and ("strengthens" in t)

        def c_weakens(ccy: str) -> bool:
            return (f" {ccy.lower()} " in f" {t} ") and ("weakens" in t)

        if c_strengthens(base):
            return "UP"
        if c_weakens(base):
            return "DOWN"
        if c_strengthens(quote):
            return "DOWN"
        if c_weakens(quote):
            return "UP"

        if quote == "USD" and "usd" in t and "strengthens" in t:
            return "DOWN"
        if quote == "USD" and "usd" in t and "weakens" in t:
            return "UP"

    return "UNCLEAR"

def infer_affected_assets(primary: str, text: str):
    """
    Short list of affected assets (non-directional).
    """
    t = (text or "").lower()
    affected = []

    def add(x):
        if x and x not in affected:
            affected.append(x)

    add(primary)

    if len(primary) == 6 and primary.isalpha():
        add(primary[:3])
        add(primary[3:])

    if any(k in t for k in ["fed", "fomc", "powell", "federal reserve"]):
        add("USD")
        add("DXY")
    if "ecb" in t:
        add("EUR")
    if "boe" in t:
        add("GBP")
    if "boj" in t:
        add("JPY")

    if primary in ["GOLD", "SILVER"]:
        add("USD")
        add("US Yields")
    if primary in ["WTI", "BRENT", "OIL"]:
        add("USD")
    if primary in ["NASDAQ", "SP500", "DOWJONES"]:
        add("US Yields")

    return affected[:4]

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
    if len(happened_raw) > 850:
        happened_raw = happened_raw[:850].rsplit(" ", 1)[0] + "..."

    happened = safe_text(happened_raw)

    combined = f"{title} {summary} {link}"

    primary = detect_primary_asset(combined)
    direction = infer_direction(combined, primary)
    affected = infer_affected_assets(primary, combined)

    direction_map = {
        "UP": "Higher / strengthening (explicit wording in the source)",
        "DOWN": "Lower / weakening (explicit wording in the source)",
        "NEUTRAL": "Paused / range-bound (explicit wording in the source)",
        "VOLATILITY": "Higher volatility / choppy conditions (explicit wording in the source)",
        "UNCLEAR": "Direction not explicitly stated (monitor for volatility)"
    }

    tag = primary_hashtag(primary)

    parts = []
    parts.append("✅ <b>MARKET NEWS</b> – <i>Source-based | No Signal</i>\n")

    parts.append("📰 <b>Headline</b>")
    parts.append(headline + "\n")

    parts.append("📌 <b>What happened?</b>")
    parts.append(happened + "\n")

    parts.append("📊 <b>Impact (source-wording based)</b>")
    parts.append(f"<b>Primary:</b> {safe_text(primary or 'N/A')}")
    parts.append(f"<b>Direction:</b> {safe_text(direction_map.get(direction, 'N/A'))}")
    parts.append(f"<b>Most affected:</b> {safe_text(', '.join(affected) if affected else 'N/A')}\n")

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
