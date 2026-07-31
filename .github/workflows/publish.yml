name: Publish DuncanReport

on:
  schedule:
    - cron: "0 11 * * *"        # daily, all sections (laptop-off auto-refresh)
  workflow_dispatch:
    inputs:
      section:
        description: "Which page to refresh"
        type: choice
        default: all
        options:
          - all
          - main
          - sports
          - world
          - markets
          - politics
          - life-culture

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install Python packages
        run: pip install anthropic
      - name: Build the site
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SECTION: ${{ github.event.inputs.section || 'all' }}
        run: python curate.py
      - name: Publish to Cloudflare Pages
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: b2b76296956fb323c9573be5467c8037
        run: npx wrangler@3 pages deploy site --project-name=duncanreport

