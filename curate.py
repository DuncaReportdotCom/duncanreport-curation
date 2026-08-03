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

DOMAINS = json.loads(r"""
{
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
  "wsj.com"
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
  "etonline.com"
 ]
}
""")

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

def _expire(stories):
    now = now_ms()
    return [s for s in (stories or []) if (now - (s.get("timestamp") or now)) < THREE_DAYS_MS]

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

def merge(existing, fresh):
    ex = existing or {}; fr = fresh or {}
    orig = _orig_ts(ex)
    cols = lambda d, k: (d.get("columns") or {}).get(k)
    out = {
        "lastUpdated": now_ms(),
        "hero": fr.get("hero") or ex.get("hero") or {},
        "groups": _merge_groups(ex.get("groups"), fr.get("groups"), orig),
        "columns": {
            "left": _merge_list(cols(ex, "left"), cols(fr, "left"), orig),
            "center": _merge_list(cols(ex, "center"), cols(fr, "center"), orig),
            "right": _merge_list(cols(ex, "right"), cols(fr, "right"), orig),
        },
    }
    for key in ("scoreboard", "markets"):
        if key in fr:
            out[key] = fr[key]
        elif key in ex:
            out[key] = ex[key]
    return out

def live_url(section):
    return LIVE + ("/stories.json" if section == "main" else "/%s/stories.json" % section)

def live_current(section):
    with urllib.request.urlopen(live_url(section) + "?t=" + str(now_ms()), timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def seed(section):
    if section in SEEDS:
        return SEEDS[section]
    try:
        return live_current(section)
    except Exception:
        return empty()

GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"

def _fetch_bytes(url, timeout=25, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 (DuncanReport bot)"})
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

def curate_live(section):
    from anthropic import Anthropic
    client = Anthropic()
    cands = google_news_candidates(section)
    if not cands:
        raise ValueError("no Google News candidates for %s" % section)
    by_id = {"c%d" % i: c for i, c in enumerate(cands)}
    cand_json = json.dumps([{"id": "c%d" % i, "title": c["title"], "source": c["source"], "ts": c["ts"]}
                            for i, c in enumerate(cands)], ensure_ascii=False)
    today = datetime.date.today().isoformat()
    system = ("You are the DuncanReport.com curation engine for the '%s' section. Today is %s. Follow the "
              "CORE CONTRACT and the SECTION rules. You are given CANDIDATE stories pulled from this "
              "section's own outlets via Google News. SELECT and ORGANIZE ONLY from these candidates - do "
              "not invent stories, headlines, or URLs. In your output set each story's url field to that candidate's id (e.g. c7), NOT a real URL, and use its ts (Unix ms) as "
              "the timestamp. Rank by how many candidates/outlets cover the same story (frequency-ranked), "
              "and build hero, groups, and columns per SCHEMA.md. Output ONLY the JSON object in a ```json "
              "block.\n\n===== CORE CONTRACT =====\n%s\n\n%s\n\n===== CANDIDATE STORIES (JSON) =====\n%s"
              % (section, today, CORE, PROMPTS.get(section, ""), cand_json))
    msg = client.messages.create(model=working_model(client), max_tokens=16000, system=system,
        messages=[{"role": "user",
                   "content": "Curate the current %s cycle from the candidates and return the stories.json." % section}])
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
    data["lastUpdated"] = now_ms()
    return data

STATUS = {}

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
            return merge(existing, fresh)
        except Exception as e:
            STATUS[section] = "curate-FAILED: " + repr(e)[:400]
            print("  live curation failed for %s: %s" % (section, e))
    try:
        d = live_current(section)
        if section not in STATUS:
            STATUS[section] = "preserved-live (not curated this run)"
        return d
    except Exception:
        if section not in STATUS:
            STATUS[section] = "seed-or-empty"
        return seed(section)


def _img_dest(section):
    return os.path.join(SITE, "hero.jpg") if section == "main" else os.path.join(SITE, section, "hero.jpg")

def _download_image(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (DuncanReport bot)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ct = (r.headers.get("Content-Type") or "").lower()
        blob = r.read()
    if "image" not in ct or len(blob) < 800:
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(blob)
    return True

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

def og_image_url(article_url):
    """Pull the article's og:image / twitter:image URL."""
    html = _fetch_bytes(article_url).decode("utf-8", "ignore")[:80000]
    for pat in (r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image',
                r'name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None

def ensure_hero_image(section, data):
    """Store the lead photo in the deploy at a fixed path so the page serves it from
    our own server. Falls back to persisting the currently-live image; if nothing is
    available the page shows its built-in default."""
    dest = _img_dest(section)
    img = (data.get("hero") or {}).get("image")
    if img and str(img).startswith("http"):
        try:
            if _download_image(img, dest):
                print("    hero image saved for", section); return
        except Exception as e:
            print("    hero image download failed for %s: %s" % (section, e))
    hero_url = (data.get("hero") or {}).get("url")
    if hero_url and "news.google.com" in str(hero_url):
        try:
            real = decode_gnews(hero_url)
            img_url = og_image_url(real) if real else None
            if img_url and _download_image(img_url, dest):
                print("    hero og:image saved for", section)
                return
        except Exception as e:
            print("    hero image resolve failed for %s: %s" % (section, e))
    live_img = LIVE + ("/hero.jpg" if section == "main" else "/%s/hero.jpg" % section)
    try:
        if _download_image(live_img, dest):
            return
    except Exception:
        pass

def build():
    target = (os.environ.get("SECTION", "all") or "all").strip().lower()
    targets = SECTIONS if target in ("", "all") else [target]
    print("Refreshing:", ", ".join(targets))
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    src = os.path.join(ROOT, "index.html")
    if not os.path.isfile(src):
        raise SystemExit("ERROR: index.html missing from repo root.")
    shutil.copy2(src, os.path.join(SITE, "index.html"))
    fav = os.path.join(ROOT, "favicon.ico")
    if os.path.isfile(fav):
        shutil.copy2(fav, os.path.join(SITE, "favicon.ico"))
    with open(os.path.join(SITE, "_redirects"), "w", encoding="utf-8") as f:
        f.write("/*    /index.html   200\n")
    for sec in SECTIONS:
        data = data_for(sec, sec in targets)
        dest = os.path.join(SITE, "stories.json") if sec == "main" else os.path.join(SITE, sec, "stories.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("  wrote", sec)
        ensure_hero_image(sec, data)
    with open(os.path.join(SITE, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"model_default": MODEL, "model_used": _WORKING_MODEL, "key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
                   "target": os.environ.get("SECTION", "all"), "sections": STATUS}, f, indent=2)
    print("Site ready at ./site")

if __name__ == "__main__":
    build()
