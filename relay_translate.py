import os
import json
import requests

from argostranslate import package, translate

BOT_TOKEN = os.getenv("TRANSLATOR_BOT_TOKEN")
SOURCE_USERNAME = (os.getenv("SOURCE_CHANNEL_USERNAME") or "").lstrip("@").lower()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")

STATE_FILE = "relay_state.json"
MAX_MESSAGE_LEN = 3800


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
    pkg = candidates[0]
    path = pkg.download()
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


def translate_keep_format(message_text: str) -> str:
    """
    Keeps the exact same structure/lines.
    - Keeps emoji lines, headings, hashtags, and links unchanged
    - Translates only content lines
    """
    lines = (message_text or "").splitlines()
    out = []

    for line in lines:
        s = line.strip()

        if not s:
            out.append("")
            continue

        # Keep hashtags unchanged
        if s.startswith("#"):
            out.append(s)
            continue

        # Keep raw URLs unchanged
        if s.startswith("http://") or s.startswith("https://"):
            out.append(s)
            continue

        # Keep HTML links unchanged
        if "<a href=" in s:
            out.append(s)
            continue

        # Keep the fixed section headers (structure must stay)
        fixed_headers = {
            "✅ <b>MARKET NEWS</b>",
            "📰 <b>Headline</b>",
            "📌 <b>What happened?</b>",
            "📊 <b>Impact</b>",
            "🕒 <b>Source & time</b>",
        }
        if s in fixed_headers:
            out.append(line)
            continue

        # Keep labels but translate values where appropriate
        low = s.lower()
        if low.startswith("<b>source:</b>"):
            out.append(line)  # source name should stay
            continue
        if low.startswith("<b>date:</b>"):
            out.append(line)  # date should stay
            continue
        if low.startswith("<b>asset:</b>"):
            out.append(line)  # asset tag should stay
            continue
        if low.startswith("<b>direction:</b>"):
            # translate only the direction text after </b>
            # example: "<b>Direction:</b> Higher / strengthening"
            parts = line.split("</b>", 1)
            if len(parts) == 2:
                left = parts[0] + "</b>"
                right = parts[1].strip()
                out.append(f"{left} {tr_en_fa(right)}")
            else:
                out.append(line)
            continue

        # Translate everything else
        out.append(tr_en_fa(s))

    return "\n".join(out).strip()


def main():
    if not BOT_TOKEN or not SOURCE_USERNAME or not TARGET_CHANNEL:
        raise RuntimeError(
            "Missing secrets: TRANSLATOR_BOT_TOKEN, SOURCE_CHANNEL_USERNAME, TARGET_CHANNEL"
        )

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

        fa_text = translate_keep_format(text)
        if len(fa_text) > MAX_MESSAGE_LEN:
            fa_text = fa_text[: MAX_MESSAGE_LEN - 3] + "..."

        tg_send_message(fa_text)
        sent += 1

    state["offset"] = next_offset
    save_state(state)
    print(f"Done. Sent {sent} translated posts. Next offset: {next_offset}")


if __name__ == "__main__":
    main()
