# DuncanReport.com — DEPLOY CONTRACT (CORE · INVARIANT)

What every curation engine must satisfy so its `stories.json` survives the merge and deploys
cleanly. The engine produces the file; `deploy-stories.sh` and `merge_stories.py` do the rest.
Deployment is fully automatic — there is no human review step before publish.

## What the engine hands off

- A single valid `stories.json` for its section, matching `SCHEMA.md` exactly.
- Timestamps in Unix **milliseconds**, reflecting real publication time.
- Absolute, unique URLs for every story.

## What the pipeline does with it

**`deploy-stories.sh`** (bash):
1. Validates the fresh JSON.
2. Pulls the currently live `stories.json`.
3. Runs the merge (below).
4. Reassembles the site bundle.
5. Deploys via the Wrangler CLI to Cloudflare Pages (project `duncanreport`).

**`merge_stories.py`** (python):
- **3-day expiry** — any story whose `timestamp` is older than 3 days is dropped. This is why
  a wrong/backdated timestamp makes a story vanish on the first merge.
- **Original-timestamp-wins** — if a story re-appears in a later cycle, the *earliest* timestamp
  is kept, so its age is measured from first publication, not re-discovery.
- **URL-overlap panel matching** — panels (groups) are matched/deduplicated by overlapping
  story URLs, NOT by panel title. Titles get reframed as narratives evolve; URL overlap is
  the stable key. This is why URLs must be exact and unique.

## Rules the engine must follow so merge behaves

- Never fabricate or round a timestamp — use the real publication time in Unix ms.
- Keep URLs canonical and stable — the same story should carry the same URL across cycles, or
  URL-overlap matching will treat it as new and produce a duplicate panel.
- Do not rely on panel titles for identity — reframing a title is fine; changing which URLs a
  panel contains is what the merge sees.

## After publish

No pre-publish QA gate. Bad links or bad calls are handled post-publish via prompt/rules
refinement or manual deletion — not by holding the deploy.
