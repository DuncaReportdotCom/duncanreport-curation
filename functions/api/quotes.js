// Cloudflare Pages Function: GET /api/quotes?symbols=^GSPC,^DJI,^IXIC,^TNX,GC=F,CL=F
//
// Live market quotes for the Markets strip. Browsers can't call Yahoo Finance directly (no CORS),
// so the page calls this same-origin endpoint and we proxy Yahoo server-side - the SAME source the
// daily curation uses, so the numbers stay consistent. Returns
// { "<symbol>": { price, prev, state } } where `state` is Yahoo's marketState (REGULAR when open).
// On any failure a symbol is simply omitted and the page keeps its curated value, so this can never
// break the strip.
//
// HARD TIMEOUT on every upstream call (this was the bug: without it, one stalled Yahoo request hung
// the whole endpoint indefinitely, the browser's fetch timed out, and the strip silently froze on
// the curated numbers). Each symbol tries query1 then query2 with a short abort timeout, so the
// endpoint always returns quickly with whatever it could get.
const HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"];
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/124.0.0.0 Safari/537.36";
const TIMEOUT_MS = 4500;

async function fetchWithTimeout(u) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    return await fetch(u, {
      headers: { "User-Agent": UA, "Accept": "application/json" },
      cf: { cacheTtl: 15, cacheEverything: true },
      signal: ctrl.signal,
    });
  } finally {
    clearTimeout(t);
  }
}

async function quote(sym) {
  for (const host of HOSTS) {
    try {
      const y = "https://" + host + "/v8/finance/chart/" + encodeURIComponent(sym);
      const r = await fetchWithTimeout(y);
      if (!r.ok) continue;
      const j = await r.json();
      const meta =
        j && j.chart && j.chart.result && j.chart.result[0]
          ? j.chart.result[0].meta
          : null;
      if (!meta || meta.regularMarketPrice == null) continue;
      const prev =
        meta.chartPreviousClose != null
          ? meta.chartPreviousClose
          : meta.previousClose != null
          ? meta.previousClose
          : null;
      return { price: meta.regularMarketPrice, prev: prev, state: meta.marketState || "" };
    } catch (e) {
      /* aborted or errored on this host - try the next one */
    }
  }
  return null; // omit this symbol; the page falls back to its curated value
}

export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  const raw = (url.searchParams.get("symbols") || "").trim();
  const symbols = raw
    ? raw.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 12)
    : [];

  const out = {};
  await Promise.all(
    symbols.map(async (sym) => {
      const q = await quote(sym);
      if (q) out[sym] = q;
    })
  );

  return new Response(JSON.stringify(out), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "cache-control": "public, max-age=15",
    },
  });
}
