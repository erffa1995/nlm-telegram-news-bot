name: Relay EN->FA (Telegram)

on:
  workflow_dispatch:
  schedule:
    - cron: "*/5 * * * *"

jobs:
  relay:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Restore relay state cache
        uses: actions/cache@v4
        with:
          path: relay_state.json
          key: relay-state-${{ github.repository }}-v2

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install requests argostranslate

      - name: Debug env (shows only whether secrets exist)
        run: |
          python - <<'PY'
          import os
          print("TRANSLATOR_BOT_TOKEN set?:", bool(os.getenv("TRANSLATOR_BOT_TOKEN")))
          print("SOURCE_CHANNEL_USERNAME set?:", bool(os.getenv("SOURCE_CHANNEL_USERNAME")))
          print("TARGET_CHANNEL set?:", bool(os.getenv("TARGET_CHANNEL")))
          PY
        env:
          TRANSLATOR_BOT_TOKEN: ${{ secrets.TRANSLATOR_BOT_TOKEN }}
          SOURCE_CHANNEL_USERNAME: ${{ secrets.SOURCE_CHANNEL_USERNAME }}
          TARGET_CHANNEL: ${{ secrets.TARGET_CHANNEL }}

      - name: Run relay_translate.py
        env:
          TRANSLATOR_BOT_TOKEN: ${{ secrets.TRANSLATOR_BOT_TOKEN }}
          SOURCE_CHANNEL_USERNAME: ${{ secrets.SOURCE_CHANNEL_USERNAME }}
          TARGET_CHANNEL: ${{ secrets.TARGET_CHANNEL }}
        run: |
          python relay_translate.py

      - name: Save relay state cache
        uses: actions/cache@v4
        with:
          path: relay_state.json
          key: relay-state-${{ github.repository }}-v2
