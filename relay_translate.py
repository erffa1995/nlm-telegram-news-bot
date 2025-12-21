import os
import json
import re
import requests
from argostranslate import package, translate

BOT_TOKEN = os.getenv("TRANSLATOR_BOT_TOKEN")
SOURCE_USERNAME = (os.getenv("SOURCE_CHANNEL_USERNAME") or "").lstrip("@").lower()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")

STATE_FILE = "relay_state.json"
MAX_MESSAGE_LEN = 3800

URL_RE = re.compile(r"(https?://[^\s)>\]]+)", re.IGNORECASE)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"offset": 0}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def ensure_argos_en_fa():
    installed = translate.get_installed_languages()
    en = next((l for l in installed if l.code == "en"), None)
    fa = next((l for l in installed if l.code == "fa"), None)
    if en and fa and en.get_translation(fa):
        return

    package.update_package_index()
    available = package.get_available_packages()
    candidates = [p for p in available if p.from_code == "en" and p.to_code == "fa"]
    if not candidates:
        raise RuntimeError("No Argos package found for en->fa.")
    path = candidates[0].download()
    package.install_from_path(path)

def tr_en_fa(text: str) -> str:
    if not text or not text.strip():
        return text
    return translate.translate(text, "en", "fa")

def tg_get_updates(offset: int):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {
        "offset": offset,
        "timeout": 0,
        "allowed_updates": json.dumps(["channel_post"]),
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("result", [])

def tg_send_message(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TARGET_CHANNEL,
        "text": text[:MAX_MESSAGE_LEN],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()

def is_from_source_channel(update: dict) -> bool:
    post = update.get("channel_post") or {}
    chat = post.get("chat") or {}
    username = (chat.get("username") or "").lower()
    return username == SOURCE_USERNAME

def extract_url_from_entities(post: dict) -> str:
    # Entities can contain URLs in two forms: "url" (text contains URL) or "text_link" (url field)
    entities = post.get("entities") or post.get("caption_entities") or []
    text = post.get("text") or post.get("caption") or ""
    for e in entities:
        t = e.get("type")
        if t == "text_link" and e.get("url"):
            return e["url"]
        if t == "url":
            off = e.get("offset", 0)
            ln = e.get("length", 0)
            if ln > 0:
                return text[off:off+ln]
    return ""

def extract_best_url(post: dict, text: str) -> str:
    # 1) raw URL in text
    m = URL_RE.search(text or "")
    if m:
        return m.group(1)
    # 2) from entities
    u = extract_url_from_entities(post)
    if u:
        return u
    return ""

def looks_like_market_news(text: str) -> bool:
    # avoid relaying random channel posts
    t = text or ""
    return ("✅" in t and "MARKET NEWS" in t)

def translate_keep_structure(text: str) -> str:
    """
    Translate only content lines, keep structure, hashtags, and link lines.
    """
    lines = (text or "").splitlines()
    out = []

    for line in lines:
        s = line.strip()

        if not s:
            out.append("")
            continue

        # Keep hashtags
        if s.startswith("#"):
            out.append(s)
            continue

        # Keep HTML links or raw urls as-is
        if "<a href=" in s or s.startswith("http://") or s.startswith("https://"):
            out.append(line)
            continue

        # Keep fixed headers (your template)
        fixed = [
            "✅ <b>MARKET NEWS</b>",
            "📰 <b>Headline</b>",
            "📌 <b>What happened?</b>",
            "📊 <b>Impact</b>",
            "🕒 <b>Source & time</b>",
        ]
        if s in fixed:
            out.append(line)
            continue

        # Keep label keys; translate some values only
        low = s.lower()
        if low.startswith("<b>source:</b>") or low.startswith("<b>date:</b>") or low.startswith("<b>asset:</b>"):
            out.append(line)
            continue

        if low.startswith("<b>direction:</b>"):
            parts = line.split("</b>", 1)
            if len(parts) == 2:
                left = parts[0] + "</b>"
                right = parts[1].strip()
                out.append(f"{left} {tr_en_fa(right)}")
            else:
                out.append(line)
            continue

        # Translate other lines
        out.append(tr_en_fa(s))

    return "\n".join(out).strip()

def ensure_link_present(fa_text: str, url: str) -> str:
    if not url:
        return fa_text
    if ("http://" in fa_text) or ("https://" in fa_text) or ("<a href=" in fa_text):
        return fa_text
    # add link at end in your style
    return (fa_text.rstrip() + "\n\n" + f'🔗 <a href="{url}">Read full article</a>').strip()

def main():
    if not BOT_TOKEN or not SOURCE_USERNAME or not TARGET_CHANNEL:
        raise RuntimeError("Missing secrets: TRANSLATOR_BOT_TOKEN, SOURCE_CHANNEL_USERNAME, TARGET_CHANNEL")

    ensure_argos_en_fa()

    state = load_state()
    offset = int(state.get("offset", 0))

    updates = tg_get_updates(offset=offset)

    next_offset = offset
    sent = 0

    for upd in updates:
        uid = upd.get("update_id", 0)
        if uid >= next_offset:
            next_offset = uid + 1

        if not is_from_source_channel(upd):
            continue

        post = upd.get("channel_post") or {}
        text = post.get("text") or post.get("caption") or ""
        if not text.strip():
            continue

        # only relay your news template posts
        if not looks_like_market_news(text):
            continue

        url = extract_best_url(post, text)

        fa_text = translate_keep_structure(text)
        fa_text = ensure_link_present(fa_text, url)

        if len(fa_text) > MAX_MESSAGE_LEN:
            fa_text = fa_text[:MAX_MESSAGE_LEN - 3] + "..."

        tg_send_message(fa_text)
        sent += 1

    state["offset"] = next_offset
    save_state(state)
    print(f"Done. Sent {sent} translated posts. Next offset: {next_offset}")

if __name__ == "__main__":
    main()
