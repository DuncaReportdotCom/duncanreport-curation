#!/usr/bin/env python3
"""
DuncanReport.com site builder v3 - per-section crawl + 3-day merge + headline image.

SECTION env (from the workflow dropdown): "all" (default) refreshes every page; "sports" (etc.)
refreshes only that page and leaves the others as-is.

Each section crawls ONLY its own outlets (DOMAINS). A refreshed section MERGES fresh stories with
what is already live and keeps articles 3 days from their ORIGINAL publish time (deduped by URL),
then they expire. Sports scoreboard and market prices are handled by the site's link-outs.

Live curation uses the Claude API (ANTHROPIC_API_KEY). On any failure a section keeps its current
live data (or the built-in first-stab seed), so a run never publishes a blank page.
"""
import os, json, shutil, time, re, datetime, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
LIVE = "https://duncanreport.com"
SECTIONS = ["main", "sports", "world", "markets", "politics", "life-culture"]
MODEL = os.environ.get("MODEL", "claude-sonnet-5")
CANDIDATE_MODELS = [MODEL, "claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001",
                    "claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest"]
_WORKING_MODEL = None

def working_model(client):
    """Pick the first candidate model this API account actually accepts, and cache it."""
    global _WORKING_MODEL
    if _WORKING_MODEL:
        return _WORKING_MODEL
    seen = set()
    for m in CANDIDATE_MODELS:
        if not m or m in seen:
            continue
        seen.add(m)
        try:
            client.messages.create(model=m, max_tokens=4, messages=[{"role": "user", "content": "ping"}])
            _WORKING_MODEL = m
            print("  using model:", m)
            return m
        except Exception:
            continue
    _WORKING_MODEL = MODEL
    return _WORKING_MODEL
THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000

CORE = json.loads(r"""
"===== SCHEMA.md =====\n# DuncanReport.com — stories.json SCHEMA (CORE · INVARIANT)\n\nEvery curation engine, for every section, MUST emit a `stories.json` that matches this\nstructure exactly. This is a hard contract — the site's rendering and the deploy/merge\npipeline both depend on it. Do not add, rename, or drop fields.\n\n## Structure\n\n```json\n{\n  \"lastUpdated\": 1753372800000,\n  \"hero\": {\n    \"headline\": \"HERO HEADLINE IN ALL CAPS\",\n    \"url\": \"https://example.com/main-story\",\n    \"image\": \"https://example.com/lead-photo.jpg\",\n    \"sublinks\": [\n      { \"text\": \"Related angle one\", \"url\": \"https://example.com/main-story-a\" },\n      { \"text\": \"Related angle two\", \"url\": \"https://example.com/main-story-b\" }\n    ]\n  },\n  \"groups\": [\n    {\n      \"title\": \"NARRATIVE-ARC PANEL TITLE IN ALL CAPS\",\n      \"stories\": [\n        { \"headline\": \"Story Headline In Title Case\", \"url\": \"https://example.com/x\", \"timestamp\": 1753369200000 },\n        { \"headline\": \"Second Story In Title Case\", \"url\": \"https://example.com/y\", \"timestamp\": 1753365600000 }\n      ]\n    }\n  ],\n  \"columns\": {\n    \"left\":   [ { \"headline\": \"Story In Title Case\", \"url\": \"https://example.com/a\", \"timestamp\": 1753369200000 } ],\n    \"center\": [ { \"headline\": \"Story In Title Case\", \"url\": \"https://example.com/b\", \"timestamp\": 1753366000000 } ],\n    \"right\":  [ { \"headline\": \"Story In Title Case\", \"url\": \"https://example.com/c\", \"timestamp\": 1753362400000 } ]\n  }\n}\n```\n\n## Field rules\n\n- **`lastUpdated`** — Unix time in **milliseconds** (integer), the moment the file was generated.\n- **`hero.headline`** — ALL CAPS. `hero.url` — absolute URL. `hero.sublinks` — 0+ items, each\n  `{text, url}`; every sublink must point at the **same story** as the hero headline (a related\n  angle of it, not a different story).\n- **`hero.image`** — OPTIONAL absolute URL of the headline picture (the lead story's photo /\n  `og:image`), displayed at the top of the page. Must be a directly-hotlinkable image URL. Omit\n  the field entirely if there is no good image.\n- **`groups[]`** — narrative-arc panels. `title` ALL CAPS. `stories[]` are the stories in that\n  panel. Only create a group when 2+ stories genuinely support one arc.\n- **`columns.left/center/right`** — flat lists of standalone stories per column.\n- **Every story object** (`hero` aside) is `{headline, url, timestamp}`:\n  - `headline` — Title Case, acronyms preserved.\n  - `url` — absolute, unique. No two stories share a URL.\n  - `timestamp` — Unix **milliseconds**, the story's actual publication time. This drives the\n    3-day expiry in merge; a wrong/old value makes the story expire immediately.\n\n## Invariants (never violate)\n\n- Timestamps are Unix ms, integers, and reflect real publication time — never fabricated.\n- URLs are absolute and unique across the whole file.\n- Field names and nesting are exactly as above. No extra keys (no age labels, category tags,\n  or image fields — the front end does not render them).\n\n\n===== FORMAT-LOCK.md =====\n# DuncanReport.com — FORMATTING LOCKED · DO NOT CHANGE\n\n**Status:** Frozen as of 2026-07-24 per Darin's instruction. Any curation engine, deploy\nscript, or session must preserve these exactly. Do not \"improve,\" normalize, or refactor them.\nIf a change seems necessary, stop and ask first.\n\n## CSS spacing (exact values — do not alter)\n\n- `#header` — padding `10px 10px 2px`\n- `#top-nav` — padding `5px 0`\n- `#source-bar` — padding `4px 10px`\n- `.col` — padding `4px 8px`\n- `.col-section` — margin-bottom `4px`, padding-top `3px`\n- `.col-section-title` — margin-bottom `2px`\n- `.col-link` — margin `0`, line-height `1.15`\n- `.sub-headline` — margin `1px 0`\n\n## Typography & links\n\n- Hero headline: ALL CAPS\n- Group panel titles: ALL CAPS\n- Column story headlines: Title Case with acronyms preserved (punctuation-stripping\n  `toTitleCase` function)\n- All links: dark blue `#00008B`\n- Underline behavior (as live): top-nav links and `.col-section-title` links are underlined\n  at rest; `.col-link` and `.sub-headline` links are NOT underlined at rest — they underline\n  on hover only\n- `.sub-headline`: ALL CAPS (`text-transform: uppercase`)\n\n## Layout & separators\n\n- Gray separator lines ONLY between unrelated stories in columns — not within grouped\n  stories, not above the first column story, not between the hero area and columns\n- Each story gets its own `col-section`; no topic-based stacking\n- Sub-links must cover the exact same story as their headline\n- Hero sub-links render as a centered cluster below the headline\n- Group panels distributed round-robin across left, center, and right columns\n  (not all in the left column)\n\n## Structural elements that must NOT be touched\n\n- Source bar: half left-leaning, half right-leaning outlets — intentional, signals the\n  editorial mission. Do not reorder, rebalance, or restyle.\n- No age labels, no colored category tags. ONE headline image is allowed at the very top of the\n  page (the hero photo); no images anywhere else — not in columns, panels, or the source bar\n- Satire entries: small grey \"Satire\" badge (`.satire-tag` CSS class + `tagPrefix()` helper)\n\n---\n_This block is the canonical formatting lock. Paste it into Project Instructions so every\nscoped curation chat inherits it._\n\n\n===== DEPLOY-CONTRACT.md =====\n# DuncanReport.com — DEPLOY CONTRACT (CORE · INVARIANT)\n\nWhat every curation engine must satisfy so its `stories.json` survives the merge and deploys\ncleanly. The engine produces the file; `deploy-stories.sh` and `merge_stories.py` do the rest.\nDeployment is fully automatic — there is no human review step before publish.\n\n## What the engine hands off\n\n- A single valid `stories.json` for its section, matching `SCHEMA.md` exactly.\n- Timestamps in Unix **milliseconds**, reflecting real publication time.\n- Absolute, unique URLs for every story.\n\n## What the pipeline does with it\n\n**`deploy-stories.sh`** (bash):\n1. Validates the fresh JSON.\n2. Pulls the currently live `stories.json`.\n3. Runs the merge (below).\n4. Reassembles the site bundle.\n5. Deploys via the Wrangler CLI to Cloudflare Pages (project `duncanreport`).\n\n**`merge_stories.py`** (python):\n- **3-day expiry** — any story whose `timestamp` is older than 3 days is dropped. This is why\n  a wrong/backdated timestamp makes a story vanish on the first merge.\n- **Original-timestamp-wins** — if a story re-appears in a later cycle, the *earliest* timestamp\n  is kept, so its age is measured from first publication, not re-discovery.\n- **URL-overlap panel matching** — panels (groups) are matched/deduplicated by overlapping\n  story URLs, NOT by panel title. Titles get reframed as narratives evolve; URL overlap is\n  the stable key. This is why URLs must be exact and unique.\n\n## Rules the engine must follow so merge behaves\n\n- Never fabricate or round a timestamp — use the real publication time in Unix ms.\n- Keep URLs canonical and stable — the same story should carry the same URL across cycles, or\n  URL-overlap matching will treat it as new and produce a duplicate panel.\n- Do not rely on panel titles for identity — reframing a title is fine; changing which URLs a\n  panel contains is what the merge sees.\n\n## After publish\n\nNo pre-publish QA gate. Bad links or bad calls are handled post-publish via prompt/rules\nrefinement or manual deletion — not by holding the deploy.\n\n\n"
""")

PROMPTS = json.loads(r"""
{
 "main": "# DuncanReport.com — Main Page Editorial Curation Logic (Prompt v4)\n\n**Section:** main\n**Reads with the core contract:** `curation/core/SCHEMA.md`, `curation/core/FORMAT-LOCK.md`,\n`curation/core/DEPLOY-CONTRACT.md`. This file governs *what* the main page runs; the core\ngoverns *how* it is shaped and deployed.\n\n## Mission\n\nFactual, multi-source news coverage spanning the ideological spectrum. Source diversity is the\nstructural answer to media-reliability concerns — not ideological counter-programming.\n\n## Scope\n\n21 fixed outlets, drawn evenly across left- and right-leaning sources. The outlet list lives in\n`CONFIG.md`.\n\n## Story selection\n\n- **Frequency-ranked selection.** Rank candidate stories by how many of the fixed outlets are\n  covering them; the most-covered stories surface first.\n- **Op-eds as news.** An opinion/op-ed piece is only eligible if 3 or more outlets cover the\n  piece itself as news (not merely the underlying topic).\n\n## Panels & narrative arcs\n\n- **Narrative-arc panel titles.** When 2 or more stories support a larger narrative arc, group\n  them under a panel with an arc-level title.\n- **Panel membership is matched by URL overlap, not title** (narrative reframing changes titles\n  and breaks title-based dedup). This aligns with `DEPLOY-CONTRACT.md`.\n\n## Oddity slots\n\n- 3–4 oddity slots per cycle.\n- 48-hour freshness window — oddities older than 48 hours are not eligible.\n\n## Satire\n\n- Include satire from Babylon Bee and Not the Bee.\n- Tag every satire entry (grey \"Satire\" badge — see `FORMAT-LOCK.md`).\n- **Substitution test for political targets:** a satire piece is only eligible if its target could\n  plausibly be substituted across the political spectrum — i.e., it isn't one-sided targeting.\n\n## Independent journalism (dynamic class)\n\n- A dynamic class of independent journalists — examples: Greenwald, Taibbi, Silver, Weiss.\n- Capped at 2 column slots, unless an independent story is dominant by frequency (then it may\n  exceed the cap on its own merit).\n\n## Publishing model\n\n- Deployment is fully automatic — no human review step.\n- Bad links / errors are handled post-publish via prompt refinement or manual deletion, not\n  pre-publish QA gates.\n- Stories expire after 3 days; original publication timestamp wins for re-appearing stories.\n  (Mechanically enforced by `merge_stories.py` per `DEPLOY-CONTRACT.md`.)\n\n\n# main — CONFIG\n\n**Cadence:** daily\n**Data directory:** `/home/duncxnay/data/main/` (`sources.json`, `stories.json`, `narratives.json`)\n**Editorial voice:** general front-page — the whole-spectrum top news of the moment.\n\n## Fixed outlets (21, drawn evenly left/right)\n\nSeeded from the live source bar — CONFIRM and complete to 21.\n\nLeft-leaning:\n- ABC — https://abcnews.go.com\n- AP — https://apnews.com\n- BBC — https://www.bbc.com/news\n- CBS — https://www.cbsnews.com\n- CNN — https://www.cnn.com\n- NBC — https://www.nbcnews.com\n- NPR — https://www.npr.org\n- NY Times — https://www.nytimes.com\n- Politico — https://www.politico.com\n- The Guardian — https://www.theguardian.com\n\nRight-leaning:\n- Breitbart — https://www.breitbart.com\n- Daily Caller — https://dailycaller.com\n- Fox News — https://www.foxnews.com\n- NewsMax — https://www.newsmax.com\n- NY Post — https://nypost.com\n- Wash Examiner — https://www.washingtonexaminer.com\n- Wash Times — https://www.washingtontimes.com\n- WSJ — https://www.wsj.com\n\n> NOTE: 18 outlets are listed above (from the live source bar). RULES.md specifies **21 fixed\n> outlets** — add the remaining 3 and rebalance left/right if needed. Satire (Babylon Bee, Not\n> the Bee) and the independent-journalism class are handled separately per RULES.md and are NOT\n> counted in the 21.\n",
 "sports": "# DuncanReport.com — Sports Page Editorial Curation Logic (Prompt v4)\n\n**Section:** sports\n**Reads with the core contract:** `curation/core/SCHEMA.md`, `curation/core/FORMAT-LOCK.md`,\n`curation/core/DEPLOY-CONTRACT.md`.\n\n## Mission\n\nUS sports — the day's games and scores first, then the stories driving the sports world.\n\n## Special: today's games (`scoreboard` field)\n\n- Every cycle, populate the `scoreboard` array in `stories.json` (per SCHEMA.md) with the day's\n  games across active major leagues (MLB, NBA, NFL, WNBA, MLS, majors, as in season).\n- Each game shows either the scheduled start time (`state: scheduled`, scores null), the live\n  score (`state: live`, with the game state in `note`), or the final score (`state: final`).\n- Pull live/final status from the league or ESPN scoreboard each run — scores age fast.\n\n## Scope\n\n16 fixed outlets plus league scoreboards (see `CONFIG.md`).\n\n## Story selection\n\n- Games/scoreboard lead. Then **frequency-ranked** stories across the fixed outlets; most-covered\n  first (trades, injuries, results, marquee events).\n- **Op-eds/columns as news** only if 3+ outlets cover the piece itself.\n\n## Panels & narrative arcs\n\n- Group 2+ stories on one arc (e.g. a trade-deadline cluster) under an ALL-CAPS arc title.\n- Panel membership matched by URL overlap, not title.\n\n## Oddity slots\n\n- 1–2 optional sports-oddity items per cycle, 48-hour freshness.\n\n## Satire\n\n- None by default.\n\n## Independent journalism (dynamic class)\n\n- Independent sports reporters/newsletters where they break a story. Capped at 2 slots unless\n  dominant by frequency.\n\n## Publishing model\n\n- Fully automatic; no pre-publish QA. 3-day expiry; original timestamp wins (per DEPLOY-CONTRACT).\n- Scores are a live snapshot; they age within the hour — refresh each cycle.\n\n\n# sports — CONFIG\n\n**Cadence:** daily\n**Data directory:** `/home/duncxnay/data/sports/`\n**Editorial voice:** sports desk; scores first, punchy headlines.\n\n## Scoreboard sources (populate `scoreboard` each cycle)\n\n- ESPN scoreboards — https://www.espn.com (per-league /mlb/scoreboard, /nba/scoreboard, etc.)\n- League sites: MLB.com https://www.mlb.com · NBA.com https://www.nba.com ·\n  NFL.com https://www.nfl.com · WNBA.com https://www.wnba.com · MLS https://www.mlssoccer.com\n\n## Fixed outlets (16)\n\n- ESPN — https://www.espn.com\n- The Athletic — https://www.nytimes.com/athletic/\n- CBS Sports — https://www.cbssports.com\n- Yahoo Sports — https://sports.yahoo.com\n- Bleacher Report — https://bleacherreport.com\n- Sports Illustrated — https://www.si.com\n- Fox Sports — https://www.foxsports.com\n- NBC Sports — https://www.nbcsports.com\n- AP Sports — https://apnews.com/hub/sports\n- USA Today Sports — https://www.usatoday.com/sports/\n- The Ringer — https://www.theringer.com\n- Front Office Sports — https://frontofficesports.com\n- SB Nation — https://www.sbnation.com\n- The Score — https://www.thescore.com\n- Barstool Sports — https://www.barstoolsports.com\n- Deadspin — https://www.deadspin.com\n",
 "world": "# DuncanReport.com — World Page Editorial Curation Logic (Prompt v4)\n\n**Section:** world\n**Reads with the core contract:** `curation/core/SCHEMA.md`, `curation/core/FORMAT-LOCK.md`,\n`curation/core/DEPLOY-CONTRACT.md`.\n\n## Mission\n\nInternational news — conflicts, diplomacy, economies, disasters, and major foreign developments —\ncovered factually from a diverse set of global outlets.\n\n## Scope\n\n16 fixed outlets spanning US, UK, European, and pan-Arab/global wires (see `CONFIG.md`).\nNon-US-domestic stories; US foreign policy belongs here when the center of gravity is abroad.\n\n## Story selection\n\n- **Frequency-ranked** across the fixed outlets; most-covered first. Prefer wire-confirmed\n  (AP/Reuters/AFP) facts for breaking events.\n- **Op-eds as news** only if 3+ outlets cover the piece itself.\n\n## Panels & narrative arcs\n\n- Group 2+ stories on one arc (e.g. a war and its oil-market fallout) under an ALL-CAPS arc title.\n- Panel membership matched by URL overlap, not title.\n\n## Oddity slots\n\n- 1–2 optional international human-interest / oddity items per cycle, 48-hour freshness.\n\n## Satire\n\n- Rare. Only widely-syndicated international satire, tagged, subject to the substitution test.\n\n## Independent journalism (dynamic class)\n\n- Independent foreign correspondents / outlets where they lead coverage. Capped at 2 slots unless\n  dominant by frequency.\n\n## Publishing model\n\n- Fully automatic; no pre-publish QA. 3-day expiry; original timestamp wins (per DEPLOY-CONTRACT).\n\n\n# world — CONFIG\n\n**Cadence:** daily\n**Data directory:** `/home/duncxnay/data/world/`\n**Editorial voice:** international desk; wire-grade neutrality, global not US-domestic.\n\n## Fixed outlets (16)\n\n- BBC News — https://www.bbc.com/news\n- Reuters — https://www.reuters.com\n- Associated Press — https://apnews.com\n- Agence France-Presse — https://www.afp.com/en\n- Al Jazeera English — https://www.aljazeera.com\n- The Guardian — https://www.theguardian.com/world\n- CNN International — https://edition.cnn.com\n- Bloomberg — https://www.bloomberg.com\n- Financial Times — https://www.ft.com\n- The New York Times (World) — https://www.nytimes.com/section/world\n- The Washington Post (World) — https://www.washingtonpost.com/world\n- Deutsche Welle — https://www.dw.com/en\n- France 24 — https://www.france24.com/en\n- Euronews — https://www.euronews.com\n- The Times (UK) — https://www.thetimes.com\n- NPR World — https://www.npr.org/sections/world\n\n> Runner-ups: Sky News, Times of Israel, Anadolu Agency.\n",
 "markets": "# DuncanReport.com — Business / Markets Page Editorial Curation Logic (Prompt v4)\n\n**Section:** markets\n**Reads with the core contract:** `curation/core/SCHEMA.md`, `curation/core/FORMAT-LOCK.md`,\n`curation/core/DEPLOY-CONTRACT.md`.\n\n## Mission\n\nBusiness, markets, and the economy — factual, fast, and numbers-forward. Markets first, then the\nstories moving them.\n\n## Special: live market prices (`markets` field)\n\n- Every cycle, populate the `markets` array in `stories.json` (per SCHEMA.md) with current levels:\n  at minimum S&P 500, Dow Jones, and Nasdaq, plus a rotating set of key assets (10-yr Treasury\n  yield, gold, oil/Brent, Bitcoin). Each entry carries value, change, and % change.\n- Refresh these from the source feed each run; a leading `-` marks a down move.\n\n## Scope\n\n16 fixed outlets (see `CONFIG.md`). Earnings, the Fed, markets, deals, tariffs/trade, and the\nmacro economy.\n\n## Story selection\n\n- **Frequency-ranked** across the fixed outlets; most-covered first. Prefer primary numbers\n  (earnings figures, index closes) confirmed by 2+ outlets.\n- **Op-eds/analysis as news** only if 3+ outlets cover the piece itself.\n\n## Panels & narrative arcs\n\n- Group 2+ stories on one arc (e.g. a market sell-off and its drivers) under an ALL-CAPS arc title.\n- Panel membership matched by URL overlap, not title.\n\n## Oddity slots\n\n- None. Business runs straight.\n\n## Satire\n\n- None by default.\n\n## Independent journalism (dynamic class)\n\n- Independent finance writers/newsletters where they lead. Capped at 2 slots unless dominant.\n\n## Publishing model\n\n- Fully automatic; no pre-publish QA. 3-day expiry; original timestamp wins (per DEPLOY-CONTRACT).\n- Market levels are a live snapshot; they age — refresh each cycle.\n\n\n# markets — CONFIG\n\n**Cadence:** daily\n**Data directory:** `/home/duncxnay/data/markets/`\n**Editorial voice:** business desk; numbers-forward, neutral, fast.\n\n## Live market strip (populate `markets` each cycle)\n\nMinimum: S&P 500, Dow Jones, Nasdaq. Rotating: 10-Yr Treasury yield, Gold, Brent crude, Bitcoin.\nSource feeds: Yahoo Finance, CNBC, MarketWatch.\n\n## Fixed outlets (16)\n\n- The Wall Street Journal — https://www.wsj.com\n- Bloomberg — https://www.bloomberg.com\n- CNBC — https://www.cnbc.com\n- Financial Times — https://www.ft.com\n- Reuters — https://www.reuters.com\n- MarketWatch — https://www.marketwatch.com\n- Barron's — https://www.barrons.com\n- Forbes — https://www.forbes.com\n- Fortune — https://fortune.com\n- Business Insider — https://www.businessinsider.com\n- Yahoo Finance — https://finance.yahoo.com\n- The Motley Fool — https://www.fool.com\n- Investopedia — https://www.investopedia.com\n- Investor's Business Daily — https://www.investors.com\n- Seeking Alpha — https://seekingalpha.com\n- The Economist — https://www.economist.com\n",
 "politics": "# DuncanReport.com — Politics Page Editorial Curation Logic (Prompt v4)\n\n**Section:** politics\n**Reads with the core contract:** `curation/core/SCHEMA.md`, `curation/core/FORMAT-LOCK.md`,\n`curation/core/DEPLOY-CONTRACT.md`.\n\n## Mission\n\nUS politics & government, covered factually across the ideological spectrum. Source diversity —\nnot counter-programming — is the answer to media-reliability concerns.\n\n## Scope\n\n16 fixed outlets, split evenly left/right (see `CONFIG.md`). Federal government, elections,\nCongress, the courts, campaigns, and major state-level political stories with national weight.\n\n## Story selection\n\n- **Frequency-ranked.** Rank by how many fixed outlets cover a story; most-covered surfaces first.\n- **Op-eds as news.** An op-ed is eligible only if 3+ outlets cover the piece itself as news.\n\n## Panels & narrative arcs\n\n- Group 2+ stories that support one arc under an ALL-CAPS arc title.\n- Panel membership matched by URL overlap, not title.\n\n## Oddity slots\n\n- None. Politics runs straight news; leave oddities to Life & Culture.\n\n## Satire\n\n- Include political satire from Babylon Bee and Not the Bee, tagged, subject to the substitution\n  test (eligible only if the target could plausibly be substituted across the spectrum).\n\n## Independent journalism (dynamic class)\n\n- Independent political journalists (e.g. Greenwald, Taibbi, Silver, Weiss). Capped at 2 column\n  slots unless one is dominant by frequency.\n\n## Publishing model\n\n- Fully automatic; no pre-publish QA. 3-day expiry; original timestamp wins (per DEPLOY-CONTRACT).\n\n\n# politics — CONFIG\n\n**Cadence:** daily\n**Data directory:** `/home/duncxnay/data/politics/`\n**Editorial voice:** hard US political news, spectrum-balanced, no editorializing in headlines.\n\n## Fixed outlets (16, even left/right)\n\nLeft-leaning:\n- CNN Politics — https://www.cnn.com/politics\n- MSNBC — https://www.msnbc.com\n- The New York Times — https://www.nytimes.com\n- The Washington Post — https://www.washingtonpost.com\n- NPR Politics — https://www.npr.org/sections/politics\n- Politico — https://www.politico.com\n- NBC News Politics — https://www.nbcnews.com/politics\n- Democracy Now! — https://www.democracynow.org\n\nRight-leaning:\n- Fox News Politics — https://www.foxnews.com/politics\n- The Washington Times — https://www.washingtontimes.com\n- New York Post — https://nypost.com\n- Breitbart — https://www.breitbart.com\n- National Review — https://www.nationalreview.com\n- Washington Examiner — https://www.washingtonexaminer.com\n- The Daily Wire — https://www.dailywire.com\n- Newsmax — https://www.newsmax.com\n\n> Center/wire swap-ins if you want a neutral spine: The Hill, Axios, Reuters, AP.\n",
 "life-culture": "# DuncanReport.com — Life & Culture Page Editorial Curation Logic (Prompt v4)\n\n**Section:** life-culture\n**Reads with the core contract:** `curation/core/SCHEMA.md`, `curation/core/FORMAT-LOCK.md`,\n`curation/core/DEPLOY-CONTRACT.md`.\n\n## Mission\n\nEntertainment, celebrity, film/TV, music, arts, lifestyle, health, food, travel, science-culture,\nand viral human-interest — the culture of the moment, covered breadth-first.\n\n## Scope\n\n16 fixed outlets (see `CONFIG.md`). This is the home for lighter and viral material that doesn't\nbelong on the hard-news pages.\n\n## Story selection\n\n- **Frequency-ranked** across the fixed outlets; most-covered first.\n- **Op-eds / reviews as news** only if 3+ outlets cover the piece/album/film itself.\n\n## Panels & narrative arcs\n\n- Group 2+ stories on one event (e.g. a festival or awards show) under an ALL-CAPS arc title.\n- Panel membership matched by URL overlap, not title.\n\n## Oddity slots\n\n- 3–4 oddity / viral slots per cycle, 48-hour freshness. This page is the primary home for\n  oddities.\n\n## Satire\n\n- Entertainment/culture satire from Babylon Bee and Not the Bee, tagged, subject to the\n  substitution test.\n\n## Independent journalism (dynamic class)\n\n- Independent culture writers/newsletters where they lead a story. Capped at 2 slots unless\n  dominant by frequency.\n\n## Publishing model\n\n- Fully automatic; no pre-publish QA. 3-day expiry; original timestamp wins (per DEPLOY-CONTRACT).\n\n\n# life-culture — CONFIG\n\n**Cadence:** daily\n**Data directory:** `/home/duncxnay/data/life-culture/`\n**Editorial voice:** lively culture desk; playful is fine, factual on names/dates.\n\n## Fixed outlets (16)\n\n- People — https://people.com\n- Variety — https://variety.com\n- The Hollywood Reporter — https://www.hollywoodreporter.com\n- Rolling Stone — https://www.rollingstone.com\n- Entertainment Weekly — https://ew.com\n- TMZ — https://www.tmz.com\n- Deadline — https://deadline.com\n- E! News — https://www.eonline.com\n- Vanity Fair — https://www.vanityfair.com\n- Vulture — https://www.vulture.com\n- The Atlantic — https://www.theatlantic.com\n- Billboard — https://www.billboard.com\n- USA Today Life — https://www.usatoday.com/life\n- The New York Times (Arts) — https://www.nytimes.com/section/arts\n- Pitchfork — https://pitchfork.com\n- Entertainment Tonight — https://www.etonline.com\n\n> Runner-ups: The Wrap, IGN, NPR Pop Culture.\n"
}
""")

SEEDS = json.loads(r"""
{
 "sports": {
  "lastUpdated": 1784908800000,
  "scoreboard": [
   {
    "league": "MLB",
    "away": "Colorado Rockies",
    "home": "Milwaukee Brewers",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "4:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Kansas City Royals",
    "home": "Detroit Tigers",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:40 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Chicago Cubs",
    "home": "Pittsburgh Pirates",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:40 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Arizona Diamondbacks",
    "home": "Washington Nationals",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:45 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "New York Yankees",
    "home": "Philadelphia Phillies",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:45 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Atlanta Braves",
    "home": "Baltimore Orioles",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:05 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Los Angeles Dodgers",
    "home": "New York Mets",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Cleveland Guardians",
    "home": "Tampa Bay Rays",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "San Diego Padres",
    "home": "Miami Marlins",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Toronto Blue Jays",
    "home": "Boston Red Sox",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:15 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Houston Astros",
    "home": "Chicago White Sox",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:40 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Seattle Mariners",
    "home": "Texas Rangers",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:05 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Oakland Athletics",
    "home": "Minnesota Twins",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Cincinnati Reds",
    "home": "St. Louis Cardinals",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:15 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Los Angeles Angels",
    "home": "San Francisco Giants",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "10:15 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "WNBA",
    "away": "All-Star 3-Point Contest",
    "home": "Shooting Stars",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:00 PM ET · Chicago",
    "url": "https://www.espn.com/wnba/scoreboard"
   }
  ],
  "hero": {
   "headline": "WNBA ALL-STAR WEEKEND TIPS OFF IN CHICAGO WITH 3-POINT CONTEST AND SHOOTING STARS",
   "url": "https://ticket760.iheart.com/content/2026-07-24-wnba-all-star-weekend-kicks-off-in-chicago/",
   "sublinks": [
    {
     "text": "Fudd, Mabrey, Howard in 3-point field",
     "url": "https://www.espn.com/wnba/story/_/id/49420142/fudd-mabrey-howard-wnba-all-star-3-point-contestants"
    },
    {
     "text": "How to watch tonight",
     "url": "https://www.nbcchicago.com/wnba/all-star-3-point-contest-shooting-stars-date-time-channel-stream/3965115/"
    },
    {
     "text": "Clark, Ionescu skip 3-point contest",
     "url": "https://frontofficesports.com/sabrina-ionescu-caitlin-clark-skipping-wnba-3-point-contest/"
    }
   ]
  },
  "groups": [
   {
    "title": "MLB TRADE DEADLINE HEATS UP",
    "stories": [
     {
      "headline": "Trade Deadline Tracker: Skubal, Mets Arms, Mason Miller Buzz",
      "url": "https://www.espn.com/mlb/story/_/id/49410877/2026-mlb-trade-deadline-tracker-rumors-alerts-news-latest-updates-analysis",
      "timestamp": 1784894400000
     },
     {
      "headline": "Rumors: Hunter Greene, Phillies, Yankees, Mariners, Red Sox",
      "url": "https://www.cbssports.com/mlb/news/mlb-rumors-trade-deadline-phillies-rotation-yankees/",
      "timestamp": 1784829600000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Panthers DE Nic Scourton Tears ACL in First Camp Practice",
     "url": "https://www.nfl.com/news/nfl-news-roundup-latest-league-updates-from-thursday-july-23",
     "timestamp": 1784833200000
    }
   ],
   "center": [
    {
     "headline": "Raiders, No. 1 Pick Fernando Mendoza Agree to Rookie Deal",
     "url": "https://ca.sports.yahoo.com/news/nfl-news-live-updates-training-camp-2026-schedule-injury-news-163112222.html",
     "timestamp": 1784826000000
    }
   ],
   "right": [
    {
     "headline": "NBA Offseason Tracker: Jaylen Brown Buzz, Summer League Intel",
     "url": "https://sports.yahoo.com/nba/article/2026-nba-offseason-trade-tracker-deal-details-analysis-220745003.html",
     "timestamp": 1784844000000
    }
   ]
  }
 },
 "world": {
  "lastUpdated": 1784908800000,
  "hero": {
   "headline": "U.S. STRIKES IRAN FOR 13TH STRAIGHT NIGHT AS TEHRAN REJECTS CEASEFIRE; OIL TOPS $100",
   "url": "https://www.cnn.com/2026/07/23/world/live-news/iran-war-trump",
   "sublinks": [
    {
     "text": "Oil tops $100 after Houthi Red Sea attacks",
     "url": "https://www.bloomberg.com/news/articles/2026-07-23/how-houthis-red-sea-attacks-worsen-oil-shock"
    },
    {
     "text": "Mediators push 10-day ceasefire",
     "url": "https://www.cnbc.com/2026/07/21/us-iran-war-trump-hormuz-houthis.html"
    },
    {
     "text": "Background: the 2026 Iran War",
     "url": "https://www.britannica.com/event/2026-Iran-war"
    }
   ]
  },
  "groups": [
   {
    "title": "RED SEA OIL SHOCK",
    "stories": [
     {
      "headline": "Saudi Oil Tanker Attacked in Red Sea as War Risks Widen",
      "url": "https://www.washingtonpost.com/world/2026/07/23/least-one-saudi-oil-tanker-is-attacked-red-sea-war-risks-widen/",
      "timestamp": 1784804400000
     },
     {
      "headline": "Experts Watch Red Sea Tankers for Clarity on Houthi Blockade",
      "url": "https://www.aljazeera.com/economy/2026/7/24/as-oil-soars-experts-watch-red-sea-tankers-for-clarity-on-houthi-blockade",
      "timestamp": 1784883600000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Some 40,000 Evacuated as Wildfire Rages in Southwest France",
     "url": "https://www.france24.com/en/live-news/20260724-some-40-000-people-evacuated-due-to-wildfire-in-southwest-france-minister",
     "timestamp": 1784887200000
    },
    {
     "headline": "Trump's Latest Tariffs Blasted by EU, Brazil and Australia",
     "url": "https://www.forbes.com/sites/siladityaray/2026/07/24/unjustified-eu-brazil-and-others-criticize-latest-trump-tariffs/",
     "timestamp": 1784894400000
    }
   ],
   "center": [
    {
     "headline": "At Least 21 Killed as Ukraine and Russia Trade Attacks",
     "url": "https://www.aljazeera.com/news/2026/7/24/at-least-11-killed-in-ukraine-as-moscow-and-kyiv-continue-to-trade-attacks",
     "timestamp": 1784880000000
    }
   ],
   "right": [
    {
     "headline": "Indian Activist Wangchuk Ends 26-Day Hunger Strike",
     "url": "https://www.usnews.com/news/world/articles/2026-07-23/indian-activist-wangchuk-ends-26-day-hunger-strike",
     "timestamp": 1784811600000
    },
    {
     "headline": "Mexican Mayor Shot Dead in Town Hall After Surviving Earlier Attempt",
     "url": "https://www.bloomberg.com/news/articles/2026-07-23/mexican-mayor-shot-dead-in-his-office-after-surviving-earlier-hit",
     "timestamp": 1784772000000
    }
   ]
  }
 },
 "markets": {
  "lastUpdated": 1784908800000,
  "markets": [
   {
    "name": "S&P 500",
    "value": "7,408.30",
    "change": "-90.66",
    "changePct": "-1.2%"
   },
   {
    "name": "Dow Jones",
    "value": "51,711.65",
    "change": "-506.93",
    "changePct": "-1.0%"
   },
   {
    "name": "Nasdaq",
    "value": "25,137.69",
    "change": "-553.21",
    "changePct": "-2.2%"
   },
   {
    "name": "10-Yr Treasury",
    "value": "4.71%",
    "change": "+0.06",
    "changePct": ""
   },
   {
    "name": "Gold",
    "value": "$4,055.82",
    "change": "",
    "changePct": ""
   },
   {
    "name": "Bitcoin",
    "value": "$64,304.50",
    "change": "-1,046",
    "changePct": "-1.6%"
   },
   {
    "name": "Brent Crude",
    "value": "$100.69",
    "change": "+6.60",
    "changePct": "+7.0%"
   }
  ],
  "hero": {
   "headline": "TRUMP HITS 60 ECONOMIES WITH NEW 10%-12.5% TARIFFS AS BLANKET LEVIES EXPIRE",
   "url": "https://www.bloomberg.com/news/articles/2026-07-24/here-s-the-full-list-of-trump-s-new-tariffs-on-60-economies",
   "sublinks": [
    {
     "text": "CNN: tariffs target dozens of countries",
     "url": "https://www.cnn.com/2026/07/23/economy/trump-new-tariffs"
    },
    {
     "text": "NBC: new 10%-12.5% rates on 60 partners",
     "url": "https://www.nbcnews.com/business/economy/trump-tariffs-60-countries-forced-labor-rcna588972"
    },
    {
     "text": "What investors should watch",
     "url": "https://www.chase.com/personal/investments/learning-and-insights/article/trump-tariffs-key-considerations-for-investors-before-july-24-2026"
    }
   ]
  },
  "groups": [
   {
    "title": "MARKETS SELL OFF ON AI SPENDING AND OIL",
    "stories": [
     {
      "headline": "Dow Drops 500 Points as Brent Surges Above $100",
      "url": "https://www.cnbc.com/2026/07/22/stock-market-today-live-updates.html",
      "timestamp": 1784750400000
     },
     {
      "headline": "Alphabet Q2 Beats but Stock Sinks on $200B Capex Hike",
      "url": "https://www.cnbc.com/2026/07/22/google-earnings-q2-goog-live-updates.html",
      "timestamp": 1784754000000
     },
     {
      "headline": "Tesla Q2 Revenue Beats, Profit Misses; Stock Tumbles 14.5%",
      "url": "https://electrek.co/2026/07/22/tesla-tsla-q2-2026-financial-results/",
      "timestamp": 1784755800000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Brent Crude Crosses $100 After Tankers Struck Off Saudi Arabia",
     "url": "https://www.cnbc.com/2026/07/23/oil-prices-today-wti-brent-trump-iran-hormuz.html",
     "timestamp": 1784808000000
    },
    {
     "headline": "Intel Q2 Beats: Revenue Up 25% to $16.1B; Shares Jump 12%",
     "url": "https://www.tradingkey.com/analysis/stocks/us-stocks/262050823-intel-earnings-report-q2-2026-intc-ai-data-center-intel-foundry-tradingkey",
     "timestamp": 1784844000000
    }
   ],
   "center": [
    {
     "headline": "Wall Street Rebounds Friday as Oil Falls on U.S.-Iran Talk Hopes",
     "url": "https://finance.yahoo.com/markets/live/stock-market-today-friday-july-24-dow-sp-500-nasdaq-081854465.html",
     "timestamp": 1784898000000
    },
    {
     "headline": "10-Year Treasury Yield Climbs to 4.71%, Highest Since January 2025",
     "url": "https://finance.yahoo.com/personal-finance/investing/article/bitcoin-and-ethereum-prices-today-friday-july-24-2026-crypto-prices-retreat-on-higher-us-treasury-yields-152200068.html",
     "timestamp": 1784836800000
    }
   ],
   "right": [
    {
     "headline": "Fed's Warsh Turns Hawkish; Rate-Hike Odds Rise Before July 29",
     "url": "https://www.forbes.com/sites/investor-hub/article/fed-meeting-tracker-interest-rate-strategy/",
     "timestamp": 1784822400000
    }
   ]
  }
 },
 "politics": {
  "lastUpdated": 1784908800000,
  "hero": {
   "headline": "IRAN REJECTS U.S. CEASEFIRE AS AMERICAN STRIKES HIT 13TH STRAIGHT NIGHT",
   "url": "https://www.cnn.com/2026/07/23/world/live-news/iran-war-trump",
   "sublinks": [
    {
     "text": "House votes 214-208 to halt the war",
     "url": "https://rollcall.com/2026/07/23/23warpowersvote/"
    },
    {
     "text": "Oil tops $100 as war squeezes supply",
     "url": "https://www.cnn.com/2026/07/24/business/oil-prices-inflation-bonds-iran-war"
    },
    {
     "text": "Tehran rejects reported truce",
     "url": "https://www.haaretz.com/middle-east-news/iran/2026-07-24/ty-article/iran-rejects-reported-trump-truce-as-u-s-completes-13th-night-of-strikes/0000019f-936e-d1a3-adff-f3ff9a1d0000"
    }
   ]
  },
  "groups": [
   {
    "title": "THE IRAN WAR ON CAPITOL HILL",
    "stories": [
     {
      "headline": "House Again Votes to Halt Trump's Iran War in 214-208 Rebuke",
      "url": "https://www.bloomberg.com/news/articles/2026-07-23/us-house-rebukes-trump-on-iran-votes-again-to-end-war",
      "timestamp": 1784840400000
     },
     {
      "headline": "Fallen U.S. Troops Return to Dover in Flag-Draped Caskets",
      "url": "https://www.militarytimes.com/news/your-military/2026/07/22/4-us-soldiers-killed-in-iran-war-return-to-american-soil/",
      "timestamp": 1784743200000
     },
     {
      "headline": "Trump Says Saudi Nuclear Deal Now Hinges on Abraham Accords",
      "url": "https://www.cnn.com/2026/07/23/politics/saudi-arabia-nuclear-deal-trump",
      "timestamp": 1784815200000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "DOJ Drops Subpoenas of New York Times Reporters After Judge's Rebuke",
     "url": "https://www.cnn.com/2026/07/23/media/new-york-times-subpoenas-trump-doj-prosecutors",
     "timestamp": 1784820600000
    },
    {
     "headline": "NYC Landlords Sue to Overturn Mamdani-Backed Rent Freeze",
     "url": "https://www.bloomberg.com/news/articles/2026-07-22/nyc-landlords-sue-to-invalidate-mamdani-backed-rent-freeze",
     "timestamp": 1784725200000
    }
   ],
   "center": [
    {
     "headline": "Man Who Killed Minnesota Lawmaker Melissa Hortman Gets Two Life Sentences",
     "url": "https://www.cnn.com/2026/07/23/us/mn-lawmakers-killing-sentencing",
     "timestamp": 1784826000000
    }
   ],
   "right": [
    {
     "headline": "Trump Cites Anti-Slavery Trade Law to Hit 60 Trading Partners With Tariffs",
     "url": "https://www.npr.org/2026/07/24/nx-s1-5906301/us-global-trump-tariffs-reaction",
     "timestamp": 1784890800000
    },
    {
     "headline": "Fox Power Rankings: GOP Redistricting Offsets Democrats' 2026 Edge",
     "url": "https://www.foxnews.com/politics/fox-news-power-rankings-democrats-lead-house-redistricting-keeps-gop-game",
     "timestamp": 1784736000000
    }
   ]
  }
 },
 "life-culture": {
  "lastUpdated": 1784908800000,
  "hero": {
   "headline": "SAN DIEGO COMIC-CON 2026 TAKES OVER — POP CULTURE'S BIGGEST WEEKEND IS UNDERWAY",
   "url": "https://www.kpbs.org/news/arts-culture/2026/07/23/comic-con-2026-marvel-returns-hall-h-spaceballs-sequel-hype-begins",
   "sublinks": [
    {
     "text": "Johnny Depp surprises as Ebenezer Scrooge",
     "url": "https://variety.com/2026/film/news/johnny-depp-comic-con-surprise-ebenezer-scrooge-1236819764/"
    },
    {
     "text": "Marvel returns to Hall H",
     "url": "https://www.nbclosangeles.com/news/local/comic-con-2026-marvel-returns-to-hall-h-and-spaceballs-sequel-hype-begins/3921035/"
    },
    {
     "text": "All the Marvel news recap",
     "url": "https://www.marvel.com/articles/live-events/sdcc-2026-san-diego-comic-con-all-the-marvel-news-recap"
    }
   ]
  },
  "groups": [
   {
    "title": "COMIC-CON HEADLINES",
    "stories": [
     {
      "headline": "Johnny Depp Debuts 'Ebenezer' Trailer in Hall H Surprise",
      "url": "https://variety.com/2026/film/news/johnny-depp-comic-con-surprise-ebenezer-scrooge-1236819764/",
      "timestamp": 1784847600000
     },
     {
      "headline": "Marvel Builds 'Avengers: Doomsday' Hype Before Saturday Panel",
      "url": "https://www.nbclosangeles.com/news/local/comic-con-2026-marvel-returns-to-hall-h-and-spaceballs-sequel-hype-begins/3921035/",
      "timestamp": 1784836800000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Sean 'Diddy' Combs in Solitary After Prison Fight at Fort Dix",
     "url": "https://www.nbcnews.com/news/us-news/sean-diddy-combs-solitary-confinement-fight-new-jersey-federal-prison-rcna589047",
     "timestamp": 1784898000000
    },
    {
     "headline": "'The Odyssey' Eyes Record Second Weekend for Nolan",
     "url": "https://deadline.com/2026/07/box-office-the-odyssey-tuesday-second-weekend-1236999819/",
     "timestamp": 1784818800000
    }
   ],
   "center": [
    {
     "headline": "Charli XCX Releases 'Music, Fashion, Film' to Critical Acclaim",
     "url": "http://www.thefader.com/2026/07/24/charli-xcx-music-fashion-film-album-review",
     "timestamp": 1784887200000
    }
   ],
   "right": [
    {
     "headline": "Scientists Build a Tiny 'Diving Suit' for Cyborg Cockroaches",
     "url": "https://www.popsci.com/technology/cockroach-diving-suit/",
     "timestamp": 1784815200000
    },
    {
     "headline": "News of the Weird, Week of July 23",
     "url": "https://shepherdexpress.com/puzzles/news-of-the-weird/news-of-the-weird-week-of-july-23-2026/",
     "timestamp": 1784797200000
    }
   ]
  }
 }
}
""")

DOMAINS = json.loads(r"""{
 "main": [
  "abcnews.go.com",
  "apnews.com",
  "bbc.com",
  "cbsnews.com",
  "cnn.com",
  "nbcnews.com",
  "npr.org",
  "nytimes.com",
  "politico.com",
  "theguardian.com",
  "breitbart.com",
  "dailycaller.com",
  "foxnews.com",
  "newsmax.com",
  "nypost.com",
  "washingtonexaminer.com",
  "washingtontimes.com",
  "wsj.com",
  "newsnationnow.com",
  "notthebee.com",
  "reuters.com",
  "axios.com",
  "thehill.com",
  "semafor.com",
  "businessinsider.com",
  "theatlantic.com",
  "thedailybeast.com",
  "motherjones.com",
  "rollingstone.com",
  "salon.com",
  "nationalreview.com",
  "thefp.com",
  "dailywire.com",
  "thefederalist.com",
  "dailymail.co.uk",
  "thesmokinggun.com",
  "pagesix.com",
  "telegraph.co.uk",
  "ynetnews.com",
  "jpost.com"
 ],
 "politics": [
  "cnn.com",
  "msnbc.com",
  "nytimes.com",
  "washingtonpost.com",
  "npr.org",
  "politico.com",
  "nbcnews.com",
  "democracynow.org",
  "foxnews.com",
  "washingtontimes.com",
  "nypost.com",
  "breitbart.com",
  "nationalreview.com",
  "washingtonexaminer.com",
  "dailywire.com",
  "newsmax.com"
 ],
 "markets": [
  "wsj.com",
  "bloomberg.com",
  "cnbc.com",
  "ft.com",
  "reuters.com",
  "marketwatch.com",
  "barrons.com",
  "forbes.com",
  "fortune.com",
  "businessinsider.com",
  "finance.yahoo.com",
  "fool.com",
  "investopedia.com",
  "investors.com",
  "seekingalpha.com",
  "economist.com"
 ],
 "world": [
  "bbc.com",
  "reuters.com",
  "apnews.com",
  "afp.com",
  "aljazeera.com",
  "theguardian.com",
  "cnn.com",
  "bloomberg.com",
  "ft.com",
  "nytimes.com",
  "washingtonpost.com",
  "dw.com",
  "france24.com",
  "euronews.com",
  "thetimes.com",
  "npr.org"
 ],
 "sports": [
  "espn.com",
  "nytimes.com",
  "cbssports.com",
  "sports.yahoo.com",
  "bleacherreport.com",
  "si.com",
  "foxsports.com",
  "nbcsports.com",
  "apnews.com",
  "usatoday.com",
  "theringer.com",
  "frontofficesports.com",
  "sbnation.com",
  "thescore.com",
  "barstoolsports.com",
  "deadspin.com"
 ],
 "life-culture": [
  "people.com",
  "variety.com",
  "hollywoodreporter.com",
  "rollingstone.com",
  "ew.com",
  "tmz.com",
  "deadline.com",
  "eonline.com",
  "vanityfair.com",
  "vulture.com",
  "theatlantic.com",
  "billboard.com",
  "usatoday.com",
  "nytimes.com",
  "pitchfork.com",
  "etonline.com",
  "smithsonianmag.com",
  "atlasobscura.com",
  "aeon.co",
  "phys.org",
  "sciencenews.org",
  "theconversation.com",
  "mentalfloss.com",
  "thisiscolossal.com",
  "npr.org",
  "arstechnica.com",
  "nautil.us",
  "lithub.com",
  "bigthink.com",
  "sciencealert.com",
  "insidehook.com",
  "gearpatrol.com",
  "robbreport.com",
  "gq.com",
  "esquire.com",
  "uncrate.com",
  "theverge.com",
  "wired.com",
  "techcrunch.com",
  "caranddriver.com",
  "motortrend.com",
  "thedrive.com",
  "eater.com",
  "seriouseats.com",
  "thepointsguy.com",
  "afar.com"
 ]
}""")

# Standing narrative arcs the engine actively hunts every cycle (wider window than
# breaking news) so long-running stories, breadth, and oddity keep showing up.
# Editable config: add/adjust an arc's search query to steer coverage. Main page only for now.
NARRATIVES = json.loads(r"""{
 "main": [
  {
   "arc": "Trump presidency",
   "q": "Trump (approval OR investigation OR lawsuit OR administration OR staff)"
  },
  {
   "arc": "2026 elections",
   "q": "2026 (midterm OR Senate race OR House race OR governor race OR primary)"
  },
  {
   "arc": "Mideast war",
   "q": "(Iran OR Israel OR Gaza OR \"West Bank\") (strike OR war OR escalation OR ceasefire OR attack)"
  },
  {
   "arc": "Economy anxiety",
   "q": "(inflation OR layoffs OR housing OR \"cost of living\" OR bailout OR recession OR tariffs) economy"
  },
  {
   "arc": "AI and tech dystopia",
   "q": "(\"artificial intelligence\" OR AI) (jobs OR danger OR deepfake OR lawsuit OR outage OR scandal)"
  },
  {
   "arc": "Immigration and border",
   "q": "(immigration OR border OR deportation OR ICE OR migrants) United States"
  },
  {
   "arc": "Crime and mayhem",
   "q": "(shooting OR murder OR manhunt OR stabbing OR arrested) US"
  },
  {
   "arc": "Culture war",
   "q": "(transgender OR DEI OR \"free speech\" OR abortion OR religion OR woke) controversy"
  },
  {
   "arc": "Press freedom and overreach",
   "q": "(\"press freedom\" OR journalist OR subpoena OR surveillance OR censorship OR whistleblower)"
  },
  {
   "arc": "Weird and human-interest",
   "q": "(bizarre OR strange OR unbelievable OR shocking) (man OR woman OR police OR neighbor)"
  },
  {
   "arc": "Science and religion curiosities",
   "q": "(archaeology OR ancient OR discovery OR study OR space OR fossil) scientists"
  },
  {
   "arc": "Disasters and weather",
   "q": "(earthquake OR hurricane OR wildfire OR flood OR tornado OR eruption) warning"
  }
 ],
 "sports": [
  {
   "arc": "NFL",
   "q": "NFL (game OR trade OR injury OR playoff OR quarterback)"
  },
  {
   "arc": "NBA",
   "q": "NBA (game OR trade OR playoff OR injury OR star)"
  },
  {
   "arc": "MLB",
   "q": "MLB (game OR trade OR playoff OR pitcher OR \"World Series\")"
  },
  {
   "arc": "NHL",
   "q": "NHL (game OR trade OR playoff OR \"Stanley Cup\")"
  },
  {
   "arc": "Soccer (global)",
   "q": "soccer (\"World Cup\" OR \"Premier League\" OR \"Champions League\" OR CONCACAF OR MLS OR transfer)"
  },
  {
   "arc": "Tennis",
   "q": "tennis (\"Grand Slam\" OR \"US Open\" OR Wimbledon OR ATP OR WTA OR final)"
  },
  {
   "arc": "Golf",
   "q": "golf (PGA OR major OR \"Ryder Cup\" OR leaderboard OR tournament)"
  },
  {
   "arc": "UFC and MMA",
   "q": "(UFC OR MMA) (fight OR event OR card OR knockout OR champion)"
  },
  {
   "arc": "Boxing",
   "q": "boxing (fight OR title OR bout OR knockout OR heavyweight)"
  },
  {
   "arc": "Cycling",
   "q": "cycling (\"Tour de France\" OR Giro OR Vuelta OR peloton OR stage)"
  },
  {
   "arc": "Olympics",
   "q": "Olympics (medal OR qualifying OR \"Team USA\" OR games OR record)"
  },
  {
   "arc": "Track and running",
   "q": "(\"track and field\" OR marathon OR sprint OR \"world record\" OR mile) running"
  },
  {
   "arc": "Winter sports",
   "q": "(skiing OR snowboarding OR \"figure skating\" OR \"winter sports\" OR slalom)"
  },
  {
   "arc": "Women's sports",
   "q": "(WNBA OR \"women's sports\" OR \"women's soccer\" OR \"Caitlin Clark\")"
  },
  {
   "arc": "College sports",
   "q": "college (football OR basketball) (ranking OR playoff OR upset OR recruit)"
  },
  {
   "arc": "World records and milestones",
   "q": "sports (\"world record\" OR \"record-breaking\" OR historic OR milestone OR fastest)"
  },
  {
   "arc": "Athlete news and business",
   "q": "athlete (scandal OR arrested OR retirement OR contract OR feud OR comeback)"
  },
  {
   "arc": "Upsets, oddity and viral",
   "q": "sports (upset OR bizarre OR shocking OR viral OR \"caught on camera\")"
  }
 ],
 "world": [
  {
   "arc": "Mideast conflict",
   "q": "(Iran OR Israel OR Gaza OR Syria OR Lebanon) conflict"
  },
  {
   "arc": "Russia-Ukraine",
   "q": "(Russia OR Ukraine) (war OR offensive OR strike OR \"peace talks\")"
  },
  {
   "arc": "China and Taiwan",
   "q": "China (Taiwan OR military OR economy OR Xi OR tensions)"
  },
  {
   "arc": "Europe",
   "q": "Europe (election OR protest OR EU OR crisis OR \"far-right\")"
  },
  {
   "arc": "Latin America",
   "q": "(Mexico OR Venezuela OR Brazil OR Argentina) (crisis OR election OR cartel)"
  },
  {
   "arc": "Africa",
   "q": "Africa (conflict OR coup OR election OR crisis)"
  },
  {
   "arc": "Migration",
   "q": "(migrants OR refugees OR migration) (border OR crisis OR Europe)"
  },
  {
   "arc": "Global economy",
   "q": "\"global economy\" (trade OR tariffs OR IMF OR crisis)"
  },
  {
   "arc": "Terrorism and security",
   "q": "(terrorism OR attack OR ISIS OR extremist) international"
  },
  {
   "arc": "Disasters abroad",
   "q": "(earthquake OR flood OR typhoon OR famine) international"
  },
  {
   "arc": "Diplomacy and summits",
   "q": "(summit OR UN OR NATO OR treaty OR diplomacy) leaders"
  },
  {
   "arc": "Human rights",
   "q": "(\"human rights\" OR protest OR crackdown OR dissident) government"
  }
 ],
 "markets": [
  {
   "arc": "Fed and rates",
   "q": "(\"Federal Reserve\" OR \"interest rates\" OR Powell OR \"rate cut\")"
  },
  {
   "arc": "Stock market",
   "q": "stock market (record OR selloff OR rally OR Dow OR \"S&P 500\")"
  },
  {
   "arc": "Big Tech earnings",
   "q": "(Apple OR Microsoft OR Nvidia OR Amazon OR Google) (earnings OR stock)"
  },
  {
   "arc": "Crypto",
   "q": "(bitcoin OR crypto OR ethereum) (price OR SEC OR rally OR crash)"
  },
  {
   "arc": "Oil and energy",
   "q": "(\"oil prices\" OR OPEC OR energy OR \"natural gas\")"
  },
  {
   "arc": "Housing",
   "q": "(\"housing market\" OR \"mortgage rates\" OR \"real estate\" OR \"home prices\")"
  },
  {
   "arc": "Inflation and jobs",
   "q": "(inflation OR \"jobs report\" OR unemployment OR CPI OR wages)"
  },
  {
   "arc": "Mergers and IPOs",
   "q": "(merger OR acquisition OR IPO OR buyout) company"
  },
  {
   "arc": "Retail and consumer",
   "q": "(retail OR \"consumer spending\" OR Amazon OR Walmart OR \"holiday sales\")"
  },
  {
   "arc": "Banking",
   "q": "(bank OR banking OR \"Wall Street\" OR JPMorgan OR credit)"
  },
  {
   "arc": "AI business",
   "q": "(\"artificial intelligence\" OR AI) (investment OR startup OR chips OR boom)"
  },
  {
   "arc": "Layoffs and downturn",
   "q": "(layoffs OR \"job cuts\" OR bankruptcy OR recession) company"
  }
 ],
 "politics": [
  {
   "arc": "Trump administration",
   "q": "Trump (administration OR \"executive order\" OR cabinet OR policy)"
  },
  {
   "arc": "Congress",
   "q": "Congress (bill OR Senate OR House OR vote OR shutdown)"
  },
  {
   "arc": "2026 midterms",
   "q": "2026 (midterm OR \"Senate race\" OR \"House race\" OR candidate)"
  },
  {
   "arc": "Courts and SCOTUS",
   "q": "(\"Supreme Court\" OR \"federal court\" OR ruling OR judge) case"
  },
  {
   "arc": "Immigration policy",
   "q": "immigration (policy OR border OR deportation OR ICE OR Congress)"
  },
  {
   "arc": "Culture-war policy",
   "q": "(abortion OR transgender OR DEI OR guns) (law OR policy OR court)"
  },
  {
   "arc": "Scandals and investigations",
   "q": "(investigation OR indictment OR scandal OR subpoena) politician"
  },
  {
   "arc": "State politics",
   "q": "(governor OR \"state legislature\" OR statehouse) (law OR election)"
  },
  {
   "arc": "Executive actions",
   "q": "(\"executive order\" OR \"White House\" OR administration) action"
  },
  {
   "arc": "Polls and approval",
   "q": "(poll OR \"approval rating\" OR survey) (Trump OR Congress OR election)"
  },
  {
   "arc": "Foreign-policy politics",
   "q": "(\"foreign policy\" OR sanctions OR tariffs OR NATO) administration"
  },
  {
   "arc": "Elections and voting",
   "q": "(voting OR election OR ballot OR redistricting) law"
  }
 ],
 "life-culture": [
  {
   "arc": "Celebrity",
   "q": "celebrity (interview OR profile OR split OR feud OR death OR baby)"
  },
  {
   "arc": "Hollywood and film",
   "q": "(movie OR film OR Hollywood OR \"box office\") (release OR review OR casting OR premiere)"
  },
  {
   "arc": "Music",
   "q": "music (album OR artist OR tour OR chart OR review OR Grammy)"
  },
  {
   "arc": "TV and streaming",
   "q": "(TV OR streaming OR Netflix OR series OR show) (premiere OR review OR finale OR cancel)"
  },
  {
   "arc": "Fashion and style",
   "q": "(fashion OR style OR \"red carpet\" OR designer OR runway)"
  },
  {
   "arc": "Science and discovery",
   "q": "(scientists OR researchers OR study) (discover OR invent OR surprising OR bizarre OR breakthrough OR build)"
  },
  {
   "arc": "Ideas and culture",
   "q": "(essay OR \"the case for\" OR \"why we\" OR rethinking OR cultural criticism) ideas"
  },
  {
   "arc": "Books and literature",
   "q": "(book OR novel OR author OR memoir OR poetry OR literature) (review OR release OR interview)"
  },
  {
   "arc": "Arts and museums",
   "q": "(art OR museum OR exhibition OR gallery OR painting OR sculpture OR theater)"
  },
  {
   "arc": "History and archaeology",
   "q": "(history OR archaeology OR ancient OR artifact OR excavation OR historians)"
  },
  {
   "arc": "Psychology and behavior",
   "q": "(psychology OR \"human behavior\" OR happiness OR loneliness OR memory OR habits) study"
  },
  {
   "arc": "Design and architecture",
   "q": "(architecture OR design OR building OR interiors OR urbanism OR typography)"
  },
  {
   "arc": "Space and nature",
   "q": "(space OR astronomy OR NASA OR ocean OR wildlife OR nature OR animals) discovery"
  },
  {
   "arc": "Food culture",
   "q": "(food OR cuisine OR chef OR culinary OR recipe OR restaurant) (culture OR history OR science)"
  },
  {
   "arc": "Travel and places",
   "q": "(travel OR destination OR \"hidden gem\" OR \"off the beaten path\" OR village OR island)"
  },
  {
   "arc": "Human-interest and the unusual",
   "q": "(unusual OR delightful OR fascinating OR quirky OR strange OR \"you won't believe\") (man OR woman OR town OR creature OR discovery)"
  },
  {
   "arc": "Tech and gadgets",
   "q": "(tech OR gadget OR smartphone OR AI OR startup OR \"consumer electronics\") (review OR launch OR new)"
  },
  {
   "arc": "Cars and driving",
   "q": "(car OR cars OR automotive OR EV OR \"electric vehicle\" OR driving) (review OR new OR unveiled)"
  },
  {
   "arc": "Gear, watches and style",
   "q": "(gear OR watch OR whiskey OR menswear OR grooming OR \"home bar\" OR cocktail) (best OR guide OR review)"
  }
 ]
}""")

EMPHASIS = {
    'life-culture': '\n\n===== LIFE & CULTURE EMPHASIS =====\nKeep the reader in mind: assume a mostly male, white-collar, often-married audience. Cover what that reader genuinely finds interesting - cars and driving, travel and destinations, tech and gadgets, food and drink, gear, watches, whiskey and cocktails, home and style - woven together with thoughtful material (science and discovery, big ideas, history, books, arts) and a lighter thread of celebrity and entertainment (kept, but not dominant). Favor smart, well-made lifestyle journalism (InsideHook, Gear Patrol, GQ, Esquire, Robb Report, The Points Guy, and similar) and the delightful, surprising, "wow, I didn\'t know that" story over routine gossip. Because heavy analysis is often paywalled, lean on free sources - Smithsonian, Atlas Obscura, Aeon, NPR, Phys.org, The Conversation, Ars Technica, The Verge - for the thoughtful picks. This is the page to make the most interesting on the whole site. AVOID pure product endorsements and shopping/affiliate content. A piece about a category, trend, or idea is welcome ("Every Man Needs a Black Turtleneck Sweater"), but skip buying guides and brand endorsements ("Every Man Needs an LL Bean Black Turtleneck Sweater", deal roundups, "the best X to buy", "shop now" listicles). Favor editorial substance - profiles, essays, reviews with a point of view, real reporting - over commerce.\n',
    'sports': "\n\n===== SPORTS EMPHASIS =====\nWeight coverage by popularity: the major US leagues lead - NFL is biggest, then NBA, MLB, NHL - followed by soccer (MLS plus the big international competitions: World Cup, European leagues, CONCACAF, Champions League). Give those DEEP, detailed coverage. In ADDITION, give BROAD coverage of the wider sports world every cycle: tennis, golf, UFC/MMA (name the week's main event even though it has no scoreboard), boxing, cycling (Tour de France and the grand tours), the Olympics, track and field and distance running, winter sports and skiing, WNBA and women's sports, and college sports. ALWAYS surface any world record or historic milestone (for example a new mile record) prominently - records are major news. Pick as hero the single biggest sports story of the day, whatever the sport.\n",
}



def now_ms(): return int(time.time() * 1000)

def empty():
    return {"lastUpdated": now_ms(), "hero": {}, "groups": [], "columns": {"left": [], "center": [], "right": []}}

def valid(d):
    return isinstance(d, dict) and ("hero" in d or "scoreboard" in d or "markets" in d) and isinstance(d.get("columns", {}), dict)

def _loads(s):
    try:
        return json.loads(s)
    except Exception:
        try:
            return json.loads(re.sub(r'\\([^"\\/bfnrtu])', r'\1', s))
        except Exception:
            return None

def extract_json(text):
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        d = _loads(m.group(1))
        if d is not None:
            return d
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return _loads(text[start:i + 1])
    return None

def _stamp_posted(stories):
    """Give every story a postedAt (its 3-day clock start) if it doesn't have one yet."""
    now = now_ms()
    for s in (stories or []):
        if not s.get("postedAt"):
            s["postedAt"] = now
    return stories

def _expire(stories):
    # Retention is 3 days from when a link was POSTED to the page (postedAt), NOT from the
    # article's publication date. A story missing postedAt is treated as just-posted.
    now = now_ms()
    return [s for s in (stories or []) if (now - (s.get("postedAt") or now)) < THREE_DAYS_MS]

def _orig_ts(existing):
    m = {}
    def add(stories):
        for s in (stories or []):
            u, t = s.get("url"), s.get("timestamp")
            if u and t:
                m[u] = min(m.get(u, t), t)
    c = existing.get("columns") or {}
    for k in ("left", "center", "right"):
        add(c.get(k))
    for g in (existing.get("groups") or []):
        add(g.get("stories"))
    return m

def _stamp_fresh(stories, orig):
    now = now_ms(); out = []
    for s in (stories or []):
        s = dict(s); u = s.get("url")
        s["timestamp"] = orig.get(u) or s.get("timestamp") or now
        out.append(s)
    return out

def _merge_list(existing, fresh, orig):
    fresh_stamped = _expire(_stamp_fresh(fresh, orig))
    live = _expire(existing)
    furls = {s.get("url") for s in fresh_stamped}
    kept = [s for s in live if s.get("url") not in furls]
    return fresh_stamped + kept

def _merge_groups(existing, fresh, orig):
    fresh_titles = {g.get("title") for g in (fresh or [])}
    fresh_out = []
    for g in (fresh or []):
        st = _expire(_stamp_fresh(g.get("stories"), orig))
        if st:
            fresh_out.append({**g, "stories": st})
    old_kept = []
    for g in (existing or []):
        if g.get("title") not in fresh_titles:
            st = _expire(g.get("stories"))
            if st:
                old_kept.append({**g, "stories": st})
    return fresh_out + old_kept

NEW_PER_HOUR = float(os.environ.get("NEW_PER_HOUR", "1"))
NEW_MIN = int(os.environ.get("NEW_MIN", "3"))
NEW_MAX = int(os.environ.get("NEW_MAX", "30"))

def _has_content(d):
    c = (d or {}).get("columns") or {}
    if any(c.get(k) for k in ("left", "center", "right")):
        return True
    return bool((d or {}).get("groups"))

def _new_cap(existing):
    """How many brand-new stories this run may add, auto-scaled by time since last update."""
    last = (existing or {}).get("lastUpdated")
    if not last or not _has_content(existing):
        return 10 ** 6                      # first/empty build -> fill the page
    hours = max(0.0, (now_ms() - last) / 3600000.0)
    return max(NEW_MIN, min(NEW_MAX, int(hours * NEW_PER_HOUR + 0.999)))

def merge(existing, fresh):
    ex = existing or {}; fr = fresh or {}
    orig = _orig_ts(ex)
    today = datetime.date.today().isoformat()
    cap = _new_cap(ex)

    # stamp a posted time on every existing story (legacy ones get 'now' as a one-time migration)
    for _k in ("left", "center", "right"):
        _stamp_posted((ex.get("columns") or {}).get(_k))
    for _g in (ex.get("groups") or []):
        _stamp_posted(_g.get("stories"))

    # base = existing page, expired stories trimmed, order preserved
    ex_cols = {k: _expire((ex.get("columns") or {}).get(k)) for k in ("left", "center", "right")}
    ex_groups = []
    for g in (ex.get("groups") or []):
        st = _expire(g.get("stories"))
        if st:
            ex_groups.append({**g, "stories": st})

    have = set()
    for k in ("left", "center", "right"):
        for s in ex_cols[k]:
            if s.get("url"):
                have.add(s["url"])
    for g in ex_groups:
        for s in g["stories"]:
            if s.get("url"):
                have.add(s["url"])

    # collect brand-new fresh stories, tagged with where fresh placed them
    newc = []
    for k in ("left", "center", "right"):
        for s in ((fr.get("columns") or {}).get(k) or []):
            u = s.get("url")
            if u and u not in have:
                newc.append((s.get("timestamp") or now_ms(), ("col", k), s))
    for g in (fr.get("groups") or []):
        for s in (g.get("stories") or []):
            u = s.get("url")
            if u and u not in have:
                newc.append((s.get("timestamp") or now_ms(), ("group", g.get("title")), s))

    # newest first, dedupe by url, admit at most `cap`
    seen = set(); ordered = []
    for ts, loc, s in sorted(newc, key=lambda x: x[0], reverse=True):
        u = s.get("url")
        if u in seen:
            continue
        seen.add(u); ordered.append((loc, s))
    selected = ordered[:cap]

    # place new stories at the TOP of their location; existing clusters stay put
    add_cols = {"left": [], "center": [], "right": []}
    ex_group_by_title = {g.get("title"): g for g in ex_groups}
    brand_new = {}
    for loc, s in selected:
        s = dict(s); s["timestamp"] = orig.get(s.get("url")) or s.get("timestamp") or now_ms()
        s["postedAt"] = now_ms()
        kind, key = loc
        if kind == "group" and key in ex_group_by_title:
            ex_group_by_title[key]["stories"].insert(0, s)      # extend an existing cluster
        elif kind == "group":
            brand_new.setdefault(key, []).append(s)             # candidate new cluster
        else:
            add_cols[key].append(s)

    for k in ("left", "center", "right"):
        ex_cols[k] = add_cols[k] + ex_cols[k]                   # new standalone on top

    new_groups = []; rr = ["left", "center", "right"]; i = 0
    for title, stories in brand_new.items():
        if len(stories) >= 2:
            new_groups.append({"title": title, "stories": stories})
        else:
            for s in stories:                                   # lone item -> a column
                ex_cols[rr[i % 3]].insert(0, s); i += 1
    groups = new_groups + ex_groups                            # new clusters above existing

    # hero: locked once per day, unless the model flags a dominant override
    ex_hero = ex.get("hero") or {}
    override = bool(fr.get("heroOverride"))
    if ex_hero.get("headline") and ex.get("heroSetDate") == today and not override:
        hero, hero_date = dict(ex_hero), ex.get("heroSetDate")
        fr_lu = (fr.get("hero") or {}).get("liveUpdates")   # live-updates refresh every run
        if fr_lu:
            hero["liveUpdates"] = fr_lu
        else:
            hero.pop("liveUpdates", None)
    else:
        hero, hero_date = (fr.get("hero") or ex_hero or {}), today

    out = {"lastUpdated": now_ms(), "heroSetDate": hero_date, "hero": hero,
           "groups": groups,
           "columns": {k: _expire(ex_cols[k]) for k in ("left", "center", "right")}}
    for key in ("scoreboard", "markets"):
        if key in fr:
            out[key] = fr[key]
        elif key in ex:
            out[key] = ex[key]
    return out

def live_url(section):
    return LIVE + ("/stories.json" if section == "main" else "/%s/stories.json" % section)

def _has_real_content(d):
    if not isinstance(d, dict):
        return False
    if (d.get("hero") or {}).get("headline"):
        return True
    c = d.get("columns") or {}
    if any(c.get(k) for k in ("left", "center", "right")):
        return True
    return bool(d.get("groups") or d.get("scoreboard") or d.get("markets"))

def live_current(section):
    """Fetch the section's currently-deployed stories.json, with retries and validation so a
    transient hiccup does not look like 'no content'. Rejects the SPA HTML fallback and empty
    pages so we never preserve/revert to junk."""
    last = "?"
    for attempt in range(3):
        try:
            raw = _fetch_bytes(live_url(section) + "?t=" + str(now_ms()) + str(attempt), timeout=20)
            data = json.loads(raw.decode("utf-8"))
            if _has_real_content(data):
                return data
            last = "empty/invalid"
        except Exception as e:
            last = repr(e)[:120]
        time.sleep(2)
    raise ValueError("live_current failed for %s: %s" % (section, last))

def seed(section):
    # Preserve the currently-live page first; if it truly cannot be read, show an honest empty
    # page (fixed by the next curation) rather than resurrecting the weeks-old built-in sample.
    try:
        return live_current(section)
    except Exception:
        return empty()

GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

def _fetch_bytes(url, timeout=25, data=None, ua=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": ua or "Mozilla/5.0 (DuncanReport bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def _pub_ms(s):
    try:
        return int(parsedate_to_datetime(s).timestamp() * 1000)
    except Exception:
        return now_ms()

def google_news_candidates(section):
    """Fetch recent stories from this section's own outlets via Google News RSS (not crawler-blocked)."""
    sites = DOMAINS.get(section) or []
    items, seen = [], set()
    for site in sites:
        url = GNEWS % urllib.parse.quote("site:%s when:2d" % site)
        try:
            root = ET.fromstring(_fetch_bytes(url))
        except Exception as e:
            print("    gnews failed for %s: %s" % (site, e)); continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not title or not link or link in seen:
                continue
            seen.add(link)
            src_el = it.find("source")
            source = (src_el.text if (src_el is not None and src_el.text) else site)
            if title.endswith(" - " + source):
                title = title[: -(len(source) + 3)].strip()
            items.append({"title": unescape(title), "url": link, "source": source,
                          "ts": _pub_ms(it.findtext("pubDate") or "")})
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:60]

DRUDGE_URL = "https://www.drudgereport.com/"
DRUDGE_BLOCK = ("drudgereport.com", "freestar", "apps.apple.com", "play.google.com",
                "mailto", "trends.google", "boxofficemojo", "thefutoncritic",
                "charts.youtube", "economist.com/interactive", "pressreader.com",
                "earthquake.usgs.gov", "zoom.earth", "apnews.com/projects",
                "reuters.com/news/archive", "news.sky.com/story")

RC_DOMAINS = {
    "main": ["realclearinvestigations.com", "realclearpolitics.com", "realclearpolling.com"],
    "politics": ["realclearpolitics.com", "realclearpolling.com", "realclearinvestigations.com"],
    "world": ["realclearworld.com"],
    "markets": ["realclearmarkets.com"],
    "life-culture": ["realclearscience.com", "realclearhistory.com", "realcleareducation.com",
                     "realclearbooks.com", "realclearhealth.com", "realclearreligion.com"],
}

def realclear_candidates(section, per_site=5):
    """RealClear originals (Investigations, staff pieces, and the topical verticals) on a wide
    window, since these publish less often than daily news. Routed per matching page."""
    items = []
    for dom in RC_DOMAINS.get(section, []):
        try:
            root = ET.fromstring(_fetch_bytes(GNEWS % urllib.parse.quote("site:%s when:10d" % dom)))
        except Exception as e:
            print("    realclear %s failed: %s" % (dom, e)); continue
        n = 0
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not title or not link:
                continue
            src_el = it.find("source")
            source = (src_el.text if (src_el is not None and src_el.text) else dom)
            if source and title.endswith(" - " + source):
                title = title[: -(len(source) + 3)].strip()
            items.append({"title": unescape(title), "url": link, "source": source,
                          "ts": _pub_ms(it.findtext("pubDate") or ""), "arc": "RealClear"})
            n += 1
            if n >= per_site:
                break
    return items

def drudge_candidates(limit=40):
    """Pull the links Drudge Report is currently featuring - a hand-curated human feed."""
    try:
        html = _fetch_bytes(DRUDGE_URL).decode("utf-8", "ignore")
    except Exception as e:
        print("    drudge fetch failed: %s" % e)
        return []
    items, seen = [], set()
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        url = m.group(1).strip()
        text = unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if not url.startswith("http"):
            continue
        low = url.lower()
        if any(b in low for b in DRUDGE_BLOCK):
            continue
        try:
            p = urllib.parse.urlparse(url)
        except Exception:
            continue
        if len(p.path.strip("/")) < 4 and not p.query:     # skip homepage/outlet-directory links
            continue
        t = re.sub(r"\.\.\.$", "", text.strip().strip("*").strip()).strip()
        if len(t) < 8 or len(t.split()) < 2:
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": t, "url": url, "source": "Drudge Report",
                      "ts": now_ms(), "arc": "Drudge pick"})
        if len(items) >= limit:
            break
    return items

def narrative_candidates(section):
    """Hunt the section's standing narrative arcs on a wide window so long-running stories,
    breadth, and oddity keep surfacing (open sourcing, not just the fixed outlet list)."""
    arcs = NARRATIVES.get(section) or []
    items, seen = [], set()
    for a in arcs:
        url = GNEWS % urllib.parse.quote("%s when:12d" % a["q"])
        try:
            root = ET.fromstring(_fetch_bytes(url))
        except Exception as e:
            print("    arc gnews failed for %s: %s" % (a["arc"], e)); continue
        n = 0
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not title or not link or link in seen:
                continue
            seen.add(link)
            src_el = it.find("source")
            source = (src_el.text if (src_el is not None and src_el.text) else "")
            if source and title.endswith(" - " + source):
                title = title[: -(len(source) + 3)].strip()
            items.append({"title": unescape(title), "url": link, "source": source or a["arc"],
                          "ts": _pub_ms(it.findtext("pubDate") or ""), "arc": a["arc"]})
            n += 1
            if n >= 6:
                break
    return items

OPINION_DOMAINS = ["nationalreview.com", "thefederalist.com", "spectator.org", "reason.com",
    "thedispatch.com", "dailywire.com", "freebeacon.com", "city-journal.org", "washingtonexaminer.com",
    "thenation.com", "newrepublic.com", "motherjones.com", "vox.com", "slate.com", "jacobin.com",
    "theatlantic.com", "prospect.org", "currentaffairs.org"]

def editorial_candidates(per_site=2):
    """Opinion/editorial pieces from clearly-leaning outlets (left + right). The outlet name is the
    label - a proxy for its lean. Used to attach editorials to major narratives on the main page."""
    items = []
    for dom in OPINION_DOMAINS:
        try:
            root = ET.fromstring(_fetch_bytes(GNEWS % urllib.parse.quote("site:%s when:5d" % dom)))
        except Exception:
            continue
        n = 0
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not title or not link:
                continue
            src_el = it.find("source")
            source = (src_el.text if (src_el is not None and src_el.text) else dom)
            if source and title.endswith(" - " + source):
                title = title[: -(len(source) + 3)].strip()
            items.append({"title": unescape(title), "url": link, "source": source,
                          "ts": _pub_ms(it.findtext("pubDate") or ""), "arc": "editorial"})
            n += 1
            if n >= per_site:
                break
    return items

def _islive(title):
    return bool(re.search(r"live updates?|liveblog|live blog|^live[:\s]|: live$", (title or ""), re.I))

_SHORT_SOURCE = {"The Wall Street Journal": "WSJ", "Wall Street Journal": "WSJ", "BBC News": "BBC",
                 "The New York Times": "NYT", "The Washington Post": "Wash Post",
                 "Associated Press": "AP", "The Guardian": "Guardian", "National Review": "Natl Review",
                 "Sky News": "Sky News"}
def _clean_source(s):
    s = (s or "").strip()
    return _SHORT_SOURCE.get(s, s)

def curate_live(section):
    from anthropic import Anthropic
    client = Anthropic()
    breaking = google_news_candidates(section)
    for c in breaking:
        c.setdefault("arc", "breaking")
    arcs = narrative_candidates(section)
    drudge = drudge_candidates() if section == "main" else []
    realclear = realclear_candidates(section)
    editorials = editorial_candidates() if section == "main" else []
    cands, seen = [], set()
    for c in (realclear[:18] + editorials[:24] + drudge[:28] + arcs[:30] + breaking[:30]):
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        cands.append(c)
    cands = [c for c in cands if not _suppressed(c.get("url"), c.get("title"))]
    for c in cands:
        c["live"] = _islive(c.get("title"))
    cands = cands[:120]
    if not cands:
        raise ValueError("no Google News candidates for %s" % section)
    by_id = {"c%d" % i: c for i, c in enumerate(cands)}
    cand_json = json.dumps([{"id": "c%d" % i, "title": c["title"], "source": c["source"],
                             "ts": c["ts"], "arc": c.get("arc", "breaking"), "live": bool(c.get("live"))}
                            for i, c in enumerate(cands)], ensure_ascii=False)
    today = datetime.date.today().isoformat()
    editorial = ""
    if NARRATIVES.get(section):
        arc_names = ", ".join(a["arc"] for a in NARRATIVES[section])
        editorial = (
            "\n\n===== EDITORIAL DIRECTION (Drudge-style) =====\n"
            "Each candidate has an 'arc' tag naming the long-running narrative it belongs to "
            "('breaking' = fresh top-of-outlet news). Do NOT simply rank by how many outlets carry a "
            "story - consensus-ranking produces a sterile, homogeneous page. Instead:\n"
            "- BREADTH: the finished page must span many DIFFERENT arcs and subjects; never cluster "
            "several items on the same story. Pull across these arcs: %s.\n"
            "- CONTINUITY: for an ongoing arc, choose its newest development and frame the headline as "
            "the NEXT BEAT of a story readers already follow - advance it, don't just restate it.\n"
            "- ODDITY: reserve at least 2-3 slots for offbeat, human-interest, crime-weird, celebrity, "
            "or science/religion curiosities - the surprising picks that give the page personality.\n"
            "- JUXTAPOSITION: deliberately vary tone and subject between adjacent items.\n"
            "- SOURCING: welcome tabloid, foreign, and niche outlets alongside wire and mainstream.\n"
            "- HAND-PICKED: candidates tagged 'Drudge pick' come from a veteran human editor's "
            "front page - weight them as high-quality, distinctive story ideas worth featuring.\n"
            "- ORIGINALS: give extra weight to distinctive, free, staff-written analysis and "
            "investigations - especially RealClearInvestigations and RealClear staff pieces (sources "
            "that begin with 'RealClear') - and feature them prominently when they fit the page.\n"
            % arc_names)
    editorial += EMPHASIS.get(section, "")
    try:
        live_hero = (live_current(section) or {}).get("hero") or {}
    except Exception:
        live_hero = {}
    if live_hero.get("headline") and NARRATIVES.get(section):
        editorial += (
            "\n\n===== HEADLINE (choose a FRESH one) =====\n"
            "The headline currently showing is: \"%s\". Choose today's hero as the single biggest "
            "CURRENT story - something published in roughly the last day or two. Prefer a DIFFERENT "
            "story than the one above so the front page changes day to day; do NOT re-use a days-old "
            "ongoing topic as the hero just because it is prominent. Keep the same hero ONLY if that "
            "exact story is still the clearly dominant breaking news - in that case set the top-level "
            "boolean \"heroOverride\": true; otherwise set \"heroOverride\": false."
            % live_hero.get("headline"))
    system = ("You are the DuncanReport.com curation engine for the '%s' section. Today is %s. Follow the "
              "CORE CONTRACT and the SECTION rules. You are given CANDIDATE stories pulled from this "
              "section's outlets and its narrative arcs via Google News. SELECT and ORGANIZE ONLY from "
              "these candidates - do not invent stories, headlines, or URLs. In your output set each "
              "story's url field to that candidate's id (e.g. c7), NOT a real URL, and use its ts (Unix "
              "ms) as the timestamp. Build hero, groups, and columns per SCHEMA.md, following the "
              "EDITORIAL DIRECTION. For hero.sublinks pick 2-4 DIFFERENT candidates about the same hero "
              "story, each a distinct angle (a development, reaction, analysis, or key detail); write each "
              "sublink text to describe its OWN unique angle - never restate the headline or repeat "
              "another sublink. CRITICAL: each distinct news event may appear ONLY ONCE across the entire page (hero, groups, and columns combined). If several candidates cover the same event, use only the single best one; never list the same event as multiple items and never repeat the hero story in the groups or columns. For MAJOR narrative groups (main page) you MAY add an \"editorials\" array to a group: 2-4 candidate ids of opinion pieces (arc='editorial') about that narrative, from DIFFERENT outlets spanning left and right (the outlet name is the label; there is no 'center'). If the hero is a major, still-developing breaking event and some candidates have \"live\": true, add a \"liveUpdates\" array to the hero: up to 3 candidate ids of live-update pages from different major outlets. Use candidate ids for editorials and liveUpdates too - never invent URLs; omit these fields when they do not apply. Output ONLY the JSON object in a ```json block."
              "%s\n\n===== CORE CONTRACT =====\n%s\n\n%s\n\n===== CANDIDATE STORIES (JSON) =====\n%s"
              % (section, today, editorial, CORE, PROMPTS.get(section, ""), cand_json))
    model = working_model(client)
    msgs = [{"role": "user",
             "content": "Curate the current %s cycle from the candidates and return the stories.json." % section}]
    try:
        # Stream so the model's reasoning plus the full JSON answer are not capped by the
        # non-streaming size limit. The main page's answer is large enough to overrun a
        # 16k non-streaming call, which was leaving that page blank.
        parts = []
        with client.messages.stream(model=model, max_tokens=30000, system=system, messages=msgs) as st:
            for chunk in st.text_stream:
                parts.append(chunk)
        text = "".join(parts)
    except Exception as e:
        print("    stream failed (%s); non-streaming fallback" % e)
        msg = client.messages.create(model=model, max_tokens=16000, system=system, messages=msgs)
        text = "".join((getattr(b, "text", "") or "") for b in msg.content)
    data = extract_json(text)
    if not data:
        info = "stop=%s blocks=%s" % (getattr(msg, "stop_reason", "?"),
                                      [getattr(bl, "type", "?") for bl in msg.content])
        raise ValueError("no JSON parsed (len=%d, %s): %s" % (len(text), info, text[:1200].replace(chr(10), " ")))
    if not valid(data):
        raise ValueError("JSON wrong shape, keys=%s" % list(data.keys()))
    def fix_story(s):
        if isinstance(s, dict) and s.get("url") in by_id:
            c = by_id[s["url"]]
            s["url"] = c["url"]
            s["timestamp"] = c["ts"]
    hero = data.get("hero") or {}
    if hero.get("url") in by_id:
        hero["url"] = by_id[hero["url"]]["url"]
    for sl in (hero.get("sublinks") or []):
        if isinstance(sl, dict) and sl.get("url") in by_id:
            sl["url"] = by_id[sl["url"]]["url"]
    for k in ("left", "center", "right"):
        for s in ((data.get("columns") or {}).get(k) or []):
            fix_story(s)
    for g in (data.get("groups") or []):
        for s in (g.get("stories") or []):
            fix_story(s)
    def map_links(ids):
        out = []
        for i in (ids or []):
            c = by_id.get(i)
            if c and c.get("url"):
                out.append({"source": _clean_source(c["source"]), "url": c["url"]})
        return out
    if isinstance(hero.get("liveUpdates"), list):
        hero["liveUpdates"] = map_links(hero["liveUpdates"])
    for g in (data.get("groups") or []):
        if isinstance(g.get("editorials"), list):
            g["editorials"] = map_links(g["editorials"])
    data["lastUpdated"] = now_ms()
    return data

STATUS = {}

_STOP = set(("the a an of to in on for and or with as at by from is are was were be been "
             "his her its their this that these those over amid after before into new news says say "
             "said will would could can may up down out off about who what when where why how has have "
             "had not but than then more most first last two three back off amid vs").split())

def _sig(headline):
    words = re.findall(r"[a-z0-9]+", (headline or "").lower())
    return set(w for w in words if len(w) > 3 and w not in _STOP)

def _is_dup(sig, seen):
    if not sig:
        return False
    for s in seen:
        inter = len(sig & s)
        if inter >= 3 or (inter >= 2 and inter / max(1, min(len(sig), len(s))) >= 0.66):
            return True
    return False

def dedup_page(data):
    """Ensure each distinct news event appears at most once across the page. The hero claims
    its story; near-duplicate headlines in groups/columns (same event, different outlet) are
    dropped. Hero sublinks are left alone - they are the hero story's own angles."""
    seen = []
    hero = data.get("hero") or {}
    if hero.get("headline"):
        seen.append(_sig(hero["headline"]))
    new_groups = []
    for g in (data.get("groups") or []):
        kept = []
        for st in (g.get("stories") or []):
            sig = _sig(st.get("headline"))
            if _is_dup(sig, seen):
                continue
            seen.append(sig); kept.append(st)
        if kept:
            new_groups.append({**g, "stories": kept})
    data["groups"] = new_groups
    cols = data.get("columns") or {}
    for k in ("left", "center", "right"):
        kept = []
        for st in (cols.get(k) or []):
            sig = _sig(st.get("headline"))
            if _is_dup(sig, seen):
                continue
            seen.append(sig); kept.append(st)
        cols[k] = kept
    data["columns"] = cols
    return data

def data_for(section, is_target):
    if is_target and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            print("  curating (live):", section)
            fresh = curate_live(section)
            try:
                existing = live_current(section)
            except Exception:
                existing = None
            STATUS[section] = "curated-live"
            return dedup_page(resolve_source_links(merge(existing, fresh)))
        except Exception as e:
            STATUS[section] = "curate-FAILED: " + repr(e)[:400]
            print("  live curation failed for %s: %s" % (section, e))
    try:
        d = live_current(section)
        if section not in STATUS:
            STATUS[section] = "preserved-live (not curated this run)"
        return dedup_page(resolve_source_links(d))
    except Exception:
        if section not in STATUS:
            STATUS[section] = "seed-or-empty"
        return dedup_page(resolve_source_links(seed(section)))


def _img_dest(section):
    return os.path.join(SITE, "hero.jpg") if section == "main" else os.path.join(SITE, section, "hero.jpg")

def _download_image(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=12) as r:
        ct = (r.headers.get("Content-Type") or "").lower()
        blob = r.read()
    if "image" not in ct or len(blob) < 2000:
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(blob)
    return True

_URL_CACHE = {}

def resolve_link(u):
    """Turn a Google News redirect URL into the real source URL (cached, graceful)."""
    if not u or "news.google.com" not in str(u):
        return u
    if u in _URL_CACHE:
        return _URL_CACHE[u]
    real = u
    try:
        r = decode_gnews(u)
        if r and str(r).startswith("http"):
            real = r
    except Exception:
        pass
    _URL_CACHE[u] = real
    return real

def resolve_source_links(data):
    """Rewrite every story link in the file to point directly at its source outlet."""
    hero = data.get("hero") or {}
    if hero.get("url"):
        hero["url"] = resolve_link(hero["url"])
    for sl in (hero.get("sublinks") or []):
        if isinstance(sl, dict) and sl.get("url"):
            sl["url"] = resolve_link(sl["url"])
    for k in ("left", "center", "right"):
        for s in ((data.get("columns") or {}).get(k) or []):
            if isinstance(s, dict) and s.get("url"):
                s["url"] = resolve_link(s["url"])
    for g in (data.get("groups") or []):
        for s in (g.get("stories") or []):
            if isinstance(s, dict) and s.get("url"):
                s["url"] = resolve_link(s["url"])
        for ed in (g.get("editorials") or []):
            if isinstance(ed, dict) and ed.get("url"):
                ed["url"] = resolve_link(ed["url"])
    for lu in ((data.get("hero") or {}).get("liveUpdates") or []):
        if isinstance(lu, dict) and lu.get("url"):
            lu["url"] = resolve_link(lu["url"])
    return data


def decode_gnews(gn_url):
    """Resolve a Google News redirect link to the real article URL."""
    page = _fetch_bytes(gn_url).decode("utf-8", "ignore")
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    art = gn_url.split("/articles/")[1].split("?")[0]
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
            None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            art, int(ts.group(1)), sg.group(1)])
    body = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]])}).encode()
    resp = _fetch_bytes("https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
                        data=body).decode("utf-8", "ignore")
    m = re.search(r'(https?://[^"\\]+)', resp.split("garturlres", 1)[-1])
    return m.group(1) if m else None

def og_image_url(article_url, timeout=9):
    """Pull the article's og:image / twitter:image URL."""
    html = _fetch_bytes(article_url, timeout=timeout, ua=BROWSER_UA).decode("utf-8", "ignore")[:80000]
    for pat in (r'property=["\']og:image(?::url)?["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image',
                r'name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)'):
        m = re.search(pat, html)
        if m:
            return unescape(m.group(1))
    return None

# Image hosts/CDNs known to burn in source branding, watermarks, or credits (e.g. a
# "The Guardian" wordmark on their social cards). The hero must never show attribution
# ON the image, so these are skipped and the fallback picks a clean photo. Extend as needed.
WATERMARK_IMG = ("guim.co.uk", "gu-web-static", "gstatic-guardian")

def _is_junk_img(url):
    u = (url or "").lower()
    if any(w in u for w in WATERMARK_IMG):
        return True
    return any(b in u for b in ("google.com", "gstatic", "googleusercontent", "ggpht",
                                "favicon", "default", "placeholder", "sprite", "blank", "/logo"))


def ensure_hero_image(section, data):
    """Self-host a real hero photo. Try the hero article, then its sublinks (same story), then
    the top cluster/column stories, until one yields a genuine og:image. Reject Google/logo/
    placeholder images. If nothing works, write no file so the branded default renders."""
    dest = _img_dest(section)
    hero = data.get("hero") or {}
    cands = []
    if hero.get("image"):
        cands.append(hero["image"])
    if hero.get("url"):
        cands.append(hero["url"])
    for sl in (hero.get("sublinks") or []):
        if sl.get("url"):
            cands.append(sl["url"])
    for g in (data.get("groups") or []):
        for s in (g.get("stories") or [])[:3]:
            if s.get("url"):
                cands.append(s["url"])
    for k in ("left", "center", "right"):
        for s in ((data.get("columns") or {}).get(k) or [])[:5]:
            if s.get("url"):
                cands.append(s["url"])
    seen, tries = set(), 0
    for u in cands:
        if not u or u in seen:
            continue
        seen.add(u)
        try:
            if re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", str(u), re.I) and not _is_junk_img(u):
                if _download_image(u, dest):
                    return
                continue
            real = decode_gnews(u) if "news.google.com" in str(u) else u
            if not real:
                continue
            tries += 1
            img_url = og_image_url(real)
            if img_url and not _is_junk_img(img_url) and _download_image(img_url, dest):
                print("    hero image saved for %s" % section)
                return
        except Exception:
            continue
        if tries >= 14:
            break
    try:
        if os.path.exists(dest):
            os.remove(dest)
    except Exception:
        pass

ESPN_LEAGUES = {
    "NFL": "football/nfl", "NBA": "basketball/nba", "MLB": "baseball/mlb",
    "NHL": "hockey/nhl", "MLS": "soccer/usa.1",
}

def sports_scoreboard(per_league=10, total=24):
    """Upcoming / live / final games from ESPN's public scoreboard API. Each game hotlinks
    to Yahoo's live scoreboard for its league in the front end."""
    order = {"in": 0, "pre": 1, "post": 2}
    games = []
    for league, path in ESPN_LEAGUES.items():
        try:
            data = json.loads(_fetch_bytes(
                "https://site.web.api.espn.com/apis/site/v2/sports/%s/scoreboard" % path,
                timeout=15, ua=BROWSER_UA))
        except Exception as e:
            print("    espn %s failed: %s" % (league, e)); continue
        for ev in (data.get("events") or [])[:per_league]:
            try:
                comp = ev["competitions"][0]; cs = comp["competitors"]
                home = next(c for c in cs if c.get("homeAway") == "home")
                away = next(c for c in cs if c.get("homeAway") == "away")
                st = (ev.get("status") or {}).get("type") or {}
                state = st.get("state") or "pre"
                # Skip games more than 5 days out (e.g. an off-season league whose next game is
                # months away). Keeps this week's slate + near-term events; drops far-future ones.
                gd = (ev.get("date") or "")[:10]
                if gd:
                    try:
                        if (datetime.date.fromisoformat(gd) - datetime.date.today()).days > 5:
                            continue
                    except Exception:
                        pass
                g = {"league": league,
                     "home": home["team"].get("abbreviation") or home["team"].get("shortDisplayName") or "",
                     "away": away["team"].get("abbreviation") or away["team"].get("shortDisplayName") or "",
                     "state": "scheduled" if state == "pre" else state,
                     "note": st.get("shortDetail") or st.get("detail") or "",
                     "_o": order.get(state, 3)}
                if state != "pre":
                    g["homeScore"] = home.get("score"); g["awayScore"] = away.get("score")
                else:
                    g["homeScore"] = None; g["awayScore"] = None
                games.append(g)
            except Exception:
                continue
    games.sort(key=lambda x: x.get("_o", 3))
    for g in games:
        g.pop("_o", None)
    return games[:total]

CF_ACCOUNT_ID = "b2b76296956fb323c9573be5467c8037"
CF_SITE_TAG = "4bd359c547e34407a7d42aafe056f6f3"

def cloudflare_traffic(days=7):
    """Per-page views/visits from Cloudflare Web Analytics (RUM) via the GraphQL API.
    Returns None (dashboard shows 'not connected') if the token is absent or the call fails."""
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN")
    if not token:
        return None
    now = datetime.datetime.utcnow()
    since = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    query = ("query($a:String!,$s:String!,$since:Time!,$until:Time!){viewer{accounts(filter:{accountTag:$a})"
             "{rumPageloadEventsAdaptiveGroups(limit:500,orderBy:[count_DESC],"
             "filter:{datetime_geq:$since,datetime_leq:$until,siteTag:$s}){count sum{visits} dimensions{requestPath}}}}}")
    body = json.dumps({"query": query, "variables": {"a": CF_ACCOUNT_ID, "s": CF_SITE_TAG,
                                                      "since": since, "until": until}}).encode()
    req = urllib.request.Request("https://api.cloudflare.com/client/v4/graphql", data=body,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print("  cloudflare traffic fetch failed:", e); return None
    if resp.get("errors"):
        print("  cloudflare graphql errors:", str(resp["errors"])[:300]); return None
    try:
        groups = resp["data"]["viewer"]["accounts"][0]["rumPageloadEventsAdaptiveGroups"]
    except Exception:
        return None
    pathmap = {"/": "main", "/index.html": "main", "/sports": "sports", "/world": "world",
               "/markets": "markets", "/politics": "politics", "/life-culture": "life-culture"}
    out = {s: {"views": 0, "visits": 0} for s in SECTIONS}
    out["_days"] = days
    for g in groups:
        p = ((g.get("dimensions") or {}).get("requestPath") or "").rstrip("/") or "/"
        sec = pathmap.get(p)
        if not sec:
            continue
        out[sec]["views"] += int(g.get("count") or 0)
        out[sec]["visits"] += int((g.get("sum") or {}).get("visits") or 0)
    return out



SUPPRESS = json.loads(r"""
{
 "urls": [],
 "domains": [],
 "keywords": []
}
""")

def _suppressed(url, text=""):
    u = (url or "").lower(); t = (text or "").lower()
    if u and any(u == x.lower() for x in SUPPRESS.get("urls", [])):
        return True
    if u and any(dom.lower() in u for dom in SUPPRESS.get("domains", [])):
        return True
    if t and any(kw.lower() in t for kw in SUPPRESS.get("keywords", [])):
        return True
    return False

def apply_suppress(data):
    """Remove any suppressed article/domain/keyword from a page (hero, sublinks, groups,
    columns). If the hero itself is suppressed, promote the top remaining story so the page
    is never left blank, and unset heroSetDate so the next run picks a fresh hero cleanly."""
    def bad(s):
        return _suppressed(s.get("url"), s.get("headline") or s.get("text"))
    cols = data.get("columns") or {}
    for k in ("left", "center", "right"):
        cols[k] = [s for s in (cols.get(k) or []) if not bad(s)]
    data["columns"] = cols
    groups = []
    for g in (data.get("groups") or []):
        st = [s for s in (g.get("stories") or []) if not bad(s)]
        if st:
            groups.append({**g, "stories": st})
    data["groups"] = groups
    hero = data.get("hero") or {}
    if hero.get("sublinks"):
        hero["sublinks"] = [sl for sl in hero["sublinks"] if not bad(sl)]
    if hero.get("liveUpdates"):
        hero["liveUpdates"] = [lu for lu in hero["liveUpdates"] if not _suppressed(lu.get("url"), lu.get("source"))]
    for g in (data.get("groups") or []):
        if g.get("editorials"):
            g["editorials"] = [ed for ed in g["editorials"] if not _suppressed(ed.get("url"), ed.get("source"))]
    if hero.get("url") and _suppressed(hero.get("url"), hero.get("headline")):
        repl = next((cols[k][0] for k in ("left", "center", "right") if cols.get(k)), None)
        if repl:
            data["hero"] = {"headline": repl["headline"], "url": repl["url"], "sublinks": []}
        else:
            data["hero"] = {}
        data["heroSetDate"] = None
    return data

MANUAL_PICKS = {
    "life-culture": [
        {"headline": 'How to Stock Your Home Bar, According to a Woman', "url": 'https://www.insidehook.com/drinks/every-grown-man-should-stock-home-bar', "added": '2026-08-06'},
    ],
}

def apply_manual_picks(section, data):
    """Inject hand-placed articles directly onto a page (guaranteed to appear). Each shows
    for 3 days from its \"added\" date, then ages off like any story."""
    now = now_ms()
    for p in (MANUAL_PICKS.get(section) or []):
        try:
            y, m, d = [int(x) for x in p["added"].split("-")]
            added = int(datetime.datetime(y, m, d).timestamp() * 1000)
        except Exception:
            added = now
        url = p.get("url")
        if not url or now - added >= THREE_DAYS_MS:
            continue
        cols = data.setdefault("columns", {})
        seen = any(s.get("url") == url for k in ("left", "center", "right") for s in (cols.get(k) or []))
        for g in (data.get("groups") or []):
            seen = seen or any(s.get("url") == url for s in (g.get("stories") or []))
        if seen:
            continue
        cols.setdefault("left", []).insert(0,
            {"headline": p["headline"], "url": url, "timestamp": added, "postedAt": added})
    return data
def build_metrics(per_section, target, traffic=None):
    now = now_ms()
    out = {"generatedAt": now, "target": target,
           "model": _WORKING_MODEL or MODEL, "keyPresent": bool(os.environ.get("ANTHROPIC_API_KEY")),
           "cadence": {"curation": "daily 08:00 Central (13:00 UTC)", "review": "biweekly, 1st & 15th"},
           "trafficProvider": ("Cloudflare Web Analytics" if traffic else None),
           "trafficDays": (traffic or {}).get("_days"), "sections": {}}
    for sec in SECTIONS:
        data = per_section.get(sec) or {}
        cols = data.get("columns") or {}
        flat = []
        for k in ("left", "center", "right"):
            flat += cols.get(k) or []
        for g in (data.get("groups") or []):
            flat += g.get("stories") or []
        hero = data.get("hero") or {}
        fresh = sum(1 for s in flat if now - (s.get("timestamp") or now) < 24 * 3600 * 1000)
        sb = data.get("scoreboard") or []
        sb_counts = {"live": sum(1 for g in sb if g.get("state") == "in"),
                     "scheduled": sum(1 for g in sb if g.get("state") == "scheduled"),
                     "final": sum(1 for g in sb if g.get("state") == "post")}
        out["sections"][sec] = {
            "content": {"lastUpdated": data.get("lastUpdated"),
                        "stories": len(flat) + (1 if hero.get("headline") else 0),
                        "clusters": len(data.get("groups") or []),
                        "fresh24h": fresh, "aging": len(flat) - fresh},
            "hero": {"headline": hero.get("headline"), "setDate": data.get("heroSetDate")},
            "health": {"status": STATUS.get(sec, "not run this cycle")},
            "scoreboard": (sb_counts if sec == "sports" else None),
            "marketsStrip": ("static Yahoo Finance quote links" if sec == "markets" else None),
            "traffic": ((traffic or {}).get(sec) if traffic else None),
            "config": {
                "outlets": {"count": len(DOMAINS.get(sec, [])), "list": DOMAINS.get(sec, [])},
                "arcs": [{"arc": a["arc"], "q": a["q"]} for a in NARRATIVES.get(sec, [])],
                "drudgeSource": sec == "main",
                "limits": {"retentionDays": 3, "heroOncePerDay": True,
                           "heroOverride": "a dominant breaking story can replace the hero mid-day",
                           "newPerRun": {"perHour": NEW_PER_HOUR, "min": NEW_MIN, "max": NEW_MAX},
                           "candidatePoolCap": 95, "breakingWindow": "2 days", "arcWindow": "12 days",
                           "thinkingBudget": 6000, "maxTokens": 16000}},
        }
    return out


def propose_arcs(client, section, current_names, headlines):
    system = ("You are refining the standing 'narrative arcs' for the DuncanReport.com '%s' page. An arc is a "
              "recurring story theme the page hunts every cycle, defined by a Google News search query. Given the "
              "CURRENT arcs and a sample of recent headlines from this page's world, propose NEW arcs that clearly "
              "recur in the headlines but are NOT already covered by a current arc. For each: a short arc name, a "
              "Google News search query (use OR and quoted phrases), and a one-line rationale. Return ONLY JSON: "
              '{"proposed":[{"arc":"..","q":"..","why":".."}]} with 4-8 items.' % section)
    user = "CURRENT ARCS: %s\n\nRECENT HEADLINES:\n- %s" % (", ".join(current_names), "\n- ".join(headlines[:120]))
    base = dict(model=working_model(client), max_tokens=4000, system=system,
                messages=[{"role": "user", "content": user}])
    try:
        msg = client.messages.create(thinking={"type": "enabled", "budget_tokens": 3000}, **base)
    except Exception:
        msg = client.messages.create(**base)
    text = "".join((getattr(b, "text", "") or "") for b in msg.content)
    d = extract_json(text) or {}
    return d.get("proposed") or []


def narrative_review():
    """Every cycle it runs: list each page's current arcs and propose new ones based on what is
    actually recurring in that page's crawl but is not yet covered."""
    from anthropic import Anthropic
    client = Anthropic()
    out = {"generatedAt": now_ms(), "sections": {}}
    for sec in SECTIONS:
        proposed = []
        try:
            pool = narrative_candidates(sec) + google_news_candidates(sec)[:40]
            if sec == "main":
                try:
                    pool += drudge_candidates()
                except Exception:
                    pass
            heads = [c["title"] for c in pool]
            proposed = propose_arcs(client, sec, [a["arc"] for a in NARRATIVES.get(sec, [])], heads)
            print("  review %s: %d proposed" % (sec, len(proposed)))
        except Exception as e:
            print("  review failed for %s: %s" % (sec, e))
        out["sections"][sec] = {"current": [{"arc": a["arc"], "q": a["q"]} for a in NARRATIVES.get(sec, [])],
                                "proposed": proposed}
    return out


def _preserve_review():
    """Keep the last review.json alive across the site rebuild (site/ is wiped each run)."""
    try:
        raw = _fetch_bytes(LIVE + "/review.json", timeout=15)
        with open(os.path.join(SITE, "review.json"), "wb") as f:
            f.write(raw)
    except Exception:
        pass


def build():
    target = (os.environ.get("SECTION", "all") or "all").strip().lower()
    review_mode = target in ("narrative-review", "review", "arcs-review")
    if target in ("deploy-only", "deploy", "none", "site") or review_mode:
        targets = []
        print(("Narrative-review" if review_mode else "Deploy-only") + ": no article curation this run.")
    else:
        targets = SECTIONS if target in ("", "all") else [target]
        print("Refreshing:", ", ".join(targets))
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    src = os.path.join(ROOT, "index.html")
    if not os.path.isfile(src):
        raise SystemExit("ERROR: index.html missing from repo root.")
    shutil.copy2(src, os.path.join(SITE, "index.html"))
    for extra in ("favicon.ico", "dashboard.html", "review.html", "archive.html",
                  "about.html", "contact.html", "privacy.html", "terms.html", "how-we-curate.html", "ads.txt"):
        p = os.path.join(ROOT, extra)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(SITE, extra))
    with open(os.path.join(SITE, "_redirects"), "w", encoding="utf-8") as f:
        f.write("/*    /index.html   200\n")

    per_section = {}
    sb_debug = "n/a"
    for sec in SECTIONS:
        data = data_for(sec, sec in targets)
        data = apply_manual_picks(sec, data)
        data = apply_suppress(data)
        if sec == "sports":
            try:
                sb = sports_scoreboard()
                sb_debug = "%d games" % len(sb)
                if sb:
                    data["scoreboard"] = sb
                    print("  scoreboard: %d games" % len(sb))
            except Exception as e:
                sb_debug = "error: " + repr(e)[:160]
                print("  scoreboard fetch failed:", e)
        dest = os.path.join(SITE, "stories.json") if sec == "main" else os.path.join(SITE, sec, "stories.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("  wrote", sec)
        ensure_hero_image(sec, data)
        per_section[sec] = data
        # Archive a dated snapshot of real content to the repo (recovery + history).
        # Skipped for empty pages so a bad run never overwrites a good same-day snapshot.
        if _has_real_content(data):
            adest = os.path.join(ROOT, "archive", datetime.date.today().isoformat(),
                                 "main.json" if sec == "main" else "%s.json" % sec)
            os.makedirs(os.path.dirname(adest), exist_ok=True)
            with open(adest, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    # ---- health check: flag anything that broke so the workflow can alert on it ----
    problems = []
    for _s, _st in STATUS.items():
        _l = str(_st).lower()
        if "failed" in _l or "credit" in _l or "error" in _l:
            problems.append("%s: %s" % (_s, str(_st)[:160]))
    for _s in SECTIONS:
        if not _has_real_content(per_section.get(_s) or {}):
            problems.append("%s page is EMPTY" % _s)
    if isinstance(sb_debug, str) and sb_debug.startswith("error"):
        problems.append("sports scoreboard fetch: %s" % sb_debug[:120])
    if targets and os.environ.get("ANTHROPIC_API_KEY") and not _WORKING_MODEL:
        problems.append("no working Anthropic model (API key / credit / model problem)")
    critical = [p for p in problems if "EMPTY" in p]     # a broken/empty page must NOT go live
    ok = not problems
    deployable = not critical
    if ok:
        print("HEALTH: all good")
    else:
        print("HEALTH: %d problem(s)%s:" % (len(problems),
              "" if deployable else "  <-- INCLUDES A BROKEN PAGE; deploy will be blocked"))
        for _p in problems:
            print("  - %s" % _p)

    with open(os.path.join(SITE, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"model_default": MODEL, "model_used": _WORKING_MODEL,
                   "key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
                   "target": os.environ.get("SECTION", "all"), "scoreboard": sb_debug,
                   "ok": ok, "deployable": deployable, "problems": problems,
                   "critical": critical, "sections": STATUS}, f, indent=2)

    try:
        traffic = cloudflare_traffic()
    except Exception as e:
        traffic = None; print("  traffic fetch error:", e)
    with open(os.path.join(SITE, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(build_metrics(per_section, target, traffic), f, ensure_ascii=False, indent=2)
    print("  wrote metrics.json (traffic: %s)" % ("yes" if traffic else "no"))

    if review_mode and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            rv = narrative_review()
            with open(os.path.join(SITE, "review.json"), "w", encoding="utf-8") as f:
                json.dump(rv, f, ensure_ascii=False, indent=2)
            print("  wrote review.json")
        except Exception as e:
            print("  narrative review failed:", e)
            _preserve_review()
    else:
        _preserve_review()

    # ---- daily public archive: add today's hero images, refresh the manifest, publish it ----
    archive_root = os.path.join(ROOT, "archive")
    os.makedirs(archive_root, exist_ok=True)
    tdir = os.path.join(archive_root, datetime.date.today().isoformat())
    if os.path.isdir(tdir):
        for sec in SECTIONS:
            img = _img_dest(sec)
            if os.path.exists(img):
                shutil.copy2(img, os.path.join(tdir, "main.jpg" if sec == "main" else "%s.jpg" % sec))
    dates = sorted([d for d in os.listdir(archive_root)
                    if re.match(r"\d{4}-\d{2}-\d{2}$", d) and os.path.isdir(os.path.join(archive_root, d))],
                   reverse=True)
    with open(os.path.join(archive_root, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates, "sections": SECTIONS, "updated": now_ms()}, f, indent=2)
    shutil.copytree(archive_root, os.path.join(SITE, "archive"), dirs_exist_ok=True)
    print("  archive: %d day(s)" % len(dates))

    # ---- sitemap.xml for search engines (regenerated each build so lastmod stays fresh) ----
    _today = datetime.date.today().isoformat()
    _pages = [("/", "daily", "1.0"), ("/sports", "daily", "0.8"), ("/world", "daily", "0.8"),
              ("/markets", "daily", "0.8"), ("/politics", "daily", "0.8"), ("/life-culture", "daily", "0.8"),
              ("/archive", "daily", "0.4"), ("/about", "monthly", "0.3"), ("/contact", "monthly", "0.3"),
              ("/privacy", "monthly", "0.2"), ("/terms", "monthly", "0.2"), ("/how-we-curate", "monthly", "0.4")]
    _sm = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for _loc, _cf, _pri in _pages:
        _sm.append("  <url><loc>%s%s</loc><lastmod>%s</lastmod><changefreq>%s</changefreq><priority>%s</priority></url>"
                   % (LIVE, _loc, _today, _cf, _pri))
    _sm.append("</urlset>")
    with open(os.path.join(SITE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(_sm) + "\n")
    print("  wrote sitemap.xml (%d urls)" % len(_pages))

    print("Site ready at ./site")

if __name__ == "__main__":
    build()
