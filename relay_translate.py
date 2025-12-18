name: Relay EN->FA (Telegram)

on:
  workflow_dispatch:
  schedule:
    - cron: "*/5 * * * *"

jobs:
  relay:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Restore relay state cache
        uses: actions/cache@v4
        with:
          path: relay_state.json
          key: relay-state-${{ github.repository }}-v1

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests argostranslate

      - name: Run translator
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
          key: relay-state-${{ github.repository }}-v1
