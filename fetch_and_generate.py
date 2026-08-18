#!/usr/bin/env python3
"""
Global Supply Chain Bulletin — Fallback Generator

Zero-cost continuity pipeline: pulls headlines from public RSS feeds,
asks a free GROQ-hosted model to synthesize them into a briefing, and
renders a static index.html for GitHub Pages.

This is deliberately simpler than the Claude-powered version of this
project. It does NOT do live web research, multi-source verification,
or the Three-Pillar narrative-vs-telemetry checks the main bulletin
does — it summarizes whatever the RSS feeds already reported. Treat it
as a "something is always better than nothing" fallback, not a
like-for-like replacement.

Requires: GROQ_API_KEY in the environment (see README.md).
"""

import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import feedparser

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Real, verified-live public RSS feeds covering shipping, freight,
# commodities, and general geopolitics. Feeds do go stale/change URLs
# over time -- if one starts failing, the fetch step just skips it
# rather than crashing the whole run.
FEEDS = [
    ("gCaptain", "https://gcaptain.com/feed/"),
    ("Splash247", "https://splash247.com/feed/"),
    ("The Loadstar", "https://theloadstar.com/feed/"),
    ("FreightWaves", "https://www.freightwaves.com/news/feed"),
    ("Mining.com", "https://www.mining.com/feed/"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

LOOKBACK_HOURS = 30  # a bit more than the 12h refresh cadence, for slack


def fetch_feed_entries(name, url):
    """Fetch one feed, return recent entries. Never raises -- logs and
    returns [] on any failure so one broken feed can't kill the run."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        parsed = feedparser.parse(raw)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
        entries = []
        for e in parsed.entries[:20]:
            published = None
            for key in ("published_parsed", "updated_parsed"):
                if getattr(e, key, None):
                    published = datetime(*getattr(e, key)[:6], tzinfo=timezone.utc)
                    break
            if published and published < cutoff:
                continue
            summary = getattr(e, "summary", "") or getattr(e, "description", "")
            entries.append({
                "source": name,
                "title": getattr(e, "title", "").strip(),
                "summary": summary.strip()[:200],
                "url": getattr(e, "link", ""),
                "published": published.isoformat() if published else None,
            })
        print(f"  {name}: {len(entries)} recent entries", file=sys.stderr)
        return entries
    except Exception as exc:
        print(f"  {name}: FAILED ({exc}) -- skipping", file=sys.stderr)
        return []


MAX_ENTRIES_FOR_GROQ = 50  # keeps the digest well under the free-tier TPM limit


def collect_all_entries():
    print("Fetching RSS feeds...", file=sys.stderr)
    all_entries = []
    for name, url in FEEDS:
        all_entries.extend(fetch_feed_entries(name, url))
    all_entries.sort(key=lambda e: e["published"] or "", reverse=True)
    return all_entries[:MAX_ENTRIES_FOR_GROQ]


def call_groq(entries):
    """Send the collected headlines to GROQ and ask for a structured
    JSON briefing. Returns a dict matching the schema below, or raises
    on failure (caller decides what to do with a failed cycle)."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")

    digest = "\n\n".join(
        f"SOURCE: {e['source']}\nTITLE: {e['title']}\nSUMMARY: {e['summary']}\nURL: {e['url']}"
        for e in entries
    )

    system_prompt = (
        "You are a supply-chain and trade-geopolitics news editor. You will be "
        "given a batch of raw RSS headlines and summaries from the last ~30 hours. "
        "Select the most globally significant items related to supply chains, "
        "shipping, commodities, trade policy, or geopolitics affecting trade flows. "
        "Do not invent facts, prices, or events not present in the source material. "
        "If a claim's specifics (a number, a date) are not in the source text, omit "
        "that specific rather than guessing it.\n\n"
        "Return ONLY valid JSON, no markdown fences, matching exactly this schema:\n"
        "{\n"
        '  "lead": {"title": str, "summary": str, "source": str, "url": str},\n'
        '  "today_read": [str, str, str],\n'
        '  "stories": [\n'
        '    {"title": str, "summary": str, "source": str, "url": str}\n'
        "    ... ranked by significance\n"
        "  ]\n"
        "}\n"
        "The lead should be the single most significant item. today_read is 3 short "
        "synthesis sentences connecting patterns across multiple stories, not a "
        "restatement of the lead. stories should not repeat the lead. Include AT LEAST "
        "8 items in stories if the source material supports it (aim for 8-12) — do not "
        "artificially narrow the list to only the top 2-3."
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": digest},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "max_tokens": 3000,
        "reasoning_effort": "low",  # gpt-oss burns max_tokens on hidden reasoning otherwise,
                                     # starving the actual JSON output
    }

    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"GROQ request failed: HTTP {exc.code}\nResponse body: {body}", file=sys.stderr)
        raise

    content = result["choices"][0]["message"]["content"]
    return json.loads(content)


def esc(s):
    return html.escape(s or "", quote=True)


def render_html(briefing, generated_at_iso):
    lead = briefing.get("lead", {})
    today_read = briefing.get("today_read", [])
    stories = briefing.get("stories", [])

    story_html = "".join(
        f"""
        <article class="card">
          <div class="card-src">{esc(s.get('source'))}</div>
          <h3><a href="{esc(s.get('url'))}" target="_blank" rel="noopener">{esc(s.get('title'))}</a></h3>
          <p class="dek">{esc(s.get('summary'))}</p>
        </article>"""
        for s in stories
    )

    read_html = "".join(f"<li>{esc(r)}</li>" for r in today_read)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Global Supply Chain Bulletin — Fallback Edition</title>
<style>
  :root {{
    --bg: #0c1310; --surface: #131f1a; --ink: #eee8da; --ink-dim: #93a39a;
    --ink-faint: #5f6f66; --rule: rgba(238,232,218,0.14); --accent: #ec5b57;
    --font-display: Georgia, "Times New Roman", serif;
    --font-body: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font-body); line-height: 1.5; }}
  .wrap {{ max-width: 900px; margin: 0 auto; padding: 32px 24px 80px; }}
  .banner {{
    background: var(--surface); border: 1px solid var(--rule); border-radius: 8px;
    padding: 12px 16px; margin-bottom: 28px; font-family: var(--font-mono);
    font-size: 12px; color: var(--ink-dim); text-align: center;
  }}
  h1 {{ font-family: var(--font-display); font-size: clamp(28px, 5vw, 42px); margin: 0 0 6px; }}
  .meta {{ font-family: var(--font-mono); font-size: 11px; color: var(--ink-faint); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 32px; }}
  .lead {{ border-bottom: 1px solid var(--rule); padding-bottom: 24px; margin-bottom: 24px; }}
  .lead h2 {{ font-family: var(--font-display); font-size: 28px; font-weight: 400; margin: 8px 0 12px; }}
  .lead p {{ color: var(--ink-dim); font-size: 15px; }}
  .lead a {{ color: inherit; text-decoration: none; }}
  .lead a:hover {{ color: var(--accent); }}
  .eyebrow {{ font-family: var(--font-mono); font-size: 11px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.06em; }}
  .today-read {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 8px; padding: 18px 20px; margin-bottom: 32px; }}
  .today-read h3 {{ font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; color: var(--ink-dim); margin: 0 0 10px; }}
  .today-read ul {{ margin: 0; padding-left: 18px; }}
  .today-read li {{ font-size: 13.5px; margin-bottom: 8px; }}
  .card {{ padding: 16px 0; border-bottom: 1px solid var(--rule); }}
  .card-src {{ font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-faint); text-transform: uppercase; margin-bottom: 4px; }}
  .card h3 {{ font-family: var(--font-display); font-weight: 400; font-size: 18px; margin: 0 0 6px; }}
  .card h3 a {{ color: var(--ink); text-decoration: none; }}
  .card h3 a:hover {{ color: var(--accent); }}
  .card .dek {{ color: var(--ink-dim); font-size: 13.5px; margin: 0; }}
  footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--rule); font-size: 10.5px; color: var(--ink-faint); text-align: center; font-family: var(--font-mono); }}
</style>
</head>
<body>
<div class="wrap">
  <div class="banner">FALLBACK EDITION — generated from public RSS feeds via a free GROQ model, not the Claude-powered pipeline. Simpler synthesis, no live web verification.</div>
  <h1>Global <em>Supply Chain</em> Bulletin</h1>
  <div class="meta">As of {esc(generated_at_iso)}</div>

  <div class="lead">
    <div class="eyebrow">Lead</div>
    <h2><a href="{esc(lead.get('url'))}" target="_blank" rel="noopener">{esc(lead.get('title'))}</a></h2>
    <p>{esc(lead.get('summary'))}</p>
  </div>

  <div class="today-read">
    <h3>Today's Read</h3>
    <ul>{read_html}</ul>
  </div>

  <div class="river">{story_html}</div>

  <footer>© {datetime.now().year} GLOBAL SUPPLY CHAIN BULLETIN — FALLBACK EDITION · AI-ASSISTED, RSS-SOURCED</footer>
</div>
</body>
</html>
"""


def main():
    entries = collect_all_entries()
    if len(entries) < 5:
        print(f"Only {len(entries)} entries collected -- too few to publish a "
              f"meaningful briefing. Exiting without writing output.", file=sys.stderr)
        sys.exit(1)

    print(f"Collected {len(entries)} entries total. Calling GROQ...", file=sys.stderr)
    briefing = call_groq(entries)

    if not briefing.get("stories") or not briefing.get("today_read") or not briefing.get("lead"):
        print(
            "GROQ returned an incomplete briefing (empty lead/today_read/stories) -- "
            "refusing to publish a broken page. Leaving the previous index.html in place.",
            file=sys.stderr,
        )
        sys.exit(1)

    generated_at = datetime.now(timezone.utc).strftime("%A, %B %-d, %Y · %H:%M UTC")
    output = render_html(briefing, generated_at)

    with open("index.html", "w") as f:
        f.write(output)
    print("Wrote index.html", file=sys.stderr)


if __name__ == "__main__":
    main()
