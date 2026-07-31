#!/usr/bin/env python3
"""
DuncanReport.com — build the deployable site bundle.

Runs in GitHub Actions. For each section it asks the Claude API (with web search)
to curate a fresh stories.json, validates it, and writes it into ./site — which the
workflow then publishes to Cloudflare with Wrangler.

Safety: if a section's live curation fails for any reason, it falls back to that
section's committed seed (curation/sections/<name>/stories.sample.json), and for the
main page to the currently-live /stories.json. A bad run therefore never publishes a
blank page.

Env:
  ANTHROPIC_API_KEY   required for live curation (set as a GitHub secret)
  MODEL               optional, defaults to claude-sonnet-4-20250514
  CURATE_LIVE         set to "0" to skip the API and just deploy the seeds
"""

import os, sys, json, shutil, re, time, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
SITE = os.path.join(ROOT, "site")
CORE = os.path.join(ROOT, "curation", "core")
SECT = os.path.join(ROOT, "curation", "sections")

SECTIONS = ["main", "sports", "world", "markets", "politics", "life-culture"]
MODEL = os.environ.get("MODEL", "claude-sonnet-4-20250514")
LIVE = os.environ.get("CURATE_LIVE", "1") != "0" and bool(os.environ.get("ANTHROPIC_API_KEY"))


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def core_contract():
    parts = []
    for name in ("SCHEMA.md", "FORMAT-LOCK.md", "DEPLOY-CONTRACT.md"):
        p = os.path.join(CORE, name)
        if os.path.exists(p):
            parts.append("===== %s =====\n%s" % (name, read(p)))
    return "\n\n".join(parts)


def section_prompt(section):
    d = os.path.join(SECT, section)
    parts = []
    for name in ("RULES.md", "CONFIG.md"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            parts.append("===== %s =====\n%s" % (name, read(p)))
    return "\n\n".join(parts)


def valid(data):
    if not isinstance(data, dict):
        return False
    if "hero" not in data and "scoreboard" not in data and "markets" not in data:
        return False
    cols = data.get("columns", {})
    return isinstance(cols, dict)


def extract_json(text):
    # Prefer a fenced ```json block; else the last {...} span.
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        m = re.search(r"(\{.*\})", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def curate_live(section):
    """Ask Claude (with web search) to produce this section's stories.json."""
    from anthropic import Anthropic
    client = Anthropic()  # reads ANTHROPIC_API_KEY
    today = datetime.date.today().isoformat()
    system = (
        "You are the DuncanReport.com curation engine for the '%s' section. "
        "Today is %s. Follow the CORE CONTRACT and the SECTION rules exactly. "
        "Use web search to find current, real stories (real headlines, real URLs, real "
        "publication times as Unix-millisecond timestamps). Never invent a URL or a score. "
        "Output ONLY a single JSON object that validates against SCHEMA.md, inside a ```json "
        "code block, and nothing else.\n\n===== CORE CONTRACT =====\n%s\n\n%s"
        % (section, today, core_contract(), section_prompt(section))
    )
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        messages=[{"role": "user", "content":
                   "Curate the current %s cycle now and return the stories.json." % section}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    data = extract_json(text)
    if data and valid(data):
        data["lastUpdated"] = int(time.time() * 1000)
        return data
    raise ValueError("curation for %s did not return valid JSON" % section)


def seed(section):
    """Fallback data so a page is never blank."""
    p = os.path.join(SECT, section, "stories.sample.json")
    if os.path.exists(p):
        return json.loads(read(p))
    if section == "main":
        try:
            with urllib.request.urlopen("https://duncanreport.com/stories.json", timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            pass
    return {"lastUpdated": int(time.time() * 1000), "hero": {}, "groups": [],
            "columns": {"left": [], "center": [], "right": []}}


def out_path(section):
    if section == "main":
        return os.path.join(SITE, "stories.json")
    return os.path.join(SITE, section, "stories.json")


def assemble_static():
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    for name in os.listdir(WEB):
        src = os.path.join(WEB, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(SITE, name))
    if not os.path.exists(os.path.join(SITE, "favicon.ico")):
        print("WARNING: web/favicon.ico is missing — the deploy will not include a favicon.")


def main():
    assemble_static()
    for section in SECTIONS:
        data = None
        if LIVE:
            try:
                print("Curating (live): %s ..." % section)
                data = curate_live(section)
            except Exception as e:
                print("  live curation failed for %s: %s" % (section, e))
        if data is None:
            print("  using seed for %s" % section)
            data = seed(section)
        dest = out_path(section)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("  wrote %s" % os.path.relpath(dest, ROOT))
    print("Site bundle ready at ./site")


if __name__ == "__main__":
    main()
