# DuncanReport.com — stories.json SCHEMA (CORE · INVARIANT)

Every curation engine, for every section, MUST emit a `stories.json` that matches this
structure exactly. This is a hard contract — the site's rendering and the deploy/merge
pipeline both depend on it. Do not add, rename, or drop fields.

## Structure

```json
{
  "lastUpdated": 1753372800000,
  "hero": {
    "headline": "HERO HEADLINE IN ALL CAPS",
    "url": "https://example.com/main-story",
    "sublinks": [
      { "text": "Related angle one", "url": "https://example.com/main-story-a" },
      { "text": "Related angle two", "url": "https://example.com/main-story-b" }
    ]
  },
  "groups": [
    {
      "title": "NARRATIVE-ARC PANEL TITLE IN ALL CAPS",
      "stories": [
        { "headline": "Story Headline In Title Case", "url": "https://example.com/x", "timestamp": 1753369200000 },
        { "headline": "Second Story In Title Case", "url": "https://example.com/y", "timestamp": 1753365600000 }
      ]
    }
  ],
  "columns": {
    "left":   [ { "headline": "Story In Title Case", "url": "https://example.com/a", "timestamp": 1753369200000 } ],
    "center": [ { "headline": "Story In Title Case", "url": "https://example.com/b", "timestamp": 1753366000000 } ],
    "right":  [ { "headline": "Story In Title Case", "url": "https://example.com/c", "timestamp": 1753362400000 } ]
  }
}
```

## Field rules

- **`lastUpdated`** — Unix time in **milliseconds** (integer), the moment the file was generated.
- **`hero.headline`** — ALL CAPS. `hero.url` — absolute URL. `hero.sublinks` — 0+ items, each
  `{text, url}`; every sublink must point at the **same story** as the hero headline (a related
  angle of it, not a different story).
- **`groups[]`** — narrative-arc panels. `title` ALL CAPS. `stories[]` are the stories in that
  panel. Only create a group when 2+ stories genuinely support one arc.
- **`columns.left/center/right`** — flat lists of standalone stories per column.
- **Every story object** (`hero` aside) is `{headline, url, timestamp}`:
  - `headline` — Title Case, acronyms preserved.
  - `url` — absolute, unique. No two stories share a URL.
  - `timestamp` — Unix **milliseconds**, the story's actual publication time. This drives the
    3-day expiry in merge; a wrong/old value makes the story expire immediately.

## Invariants (never violate)

- Timestamps are Unix ms, integers, and reflect real publication time — never fabricated.
- URLs are absolute and unique across the whole file.
- Field names and nesting are exactly as above. No extra keys (no age labels, category tags,
  or image fields — the front end does not render them).
