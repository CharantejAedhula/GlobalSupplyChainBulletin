# Global Supply Chain Bulletin — Fallback Edition

A zero-cost continuity pipeline for the bulletin, independent of any Claude
subscription. Runs entirely on GitHub Actions (free for public repos) and a
free-tier GROQ API key. If the Claude-powered version ever stops updating
(subscription lapse, etc.), this keeps a simpler version of the page alive.

**What this is not:** a like-for-like replacement. The Claude version does
live web research, cross-checks claims across independent sources, and
applies the Three-Pillar narrative-vs-telemetry verification. This fallback
only summarizes whatever a handful of RSS feeds already published in the
last ~30 hours, using a fast open-weight model. Treat it as "something
always publishing" insurance, not equivalent editorial quality.

## One-time setup (you need to do this part — I can't create accounts for you)

### 1. Get a free GROQ API key
1. Go to https://console.groq.com and sign up (no credit card required).
2. Once logged in, go to **API Keys** in the left sidebar.
3. Click **Create API Key**, name it anything (e.g. `bulletin-fallback`), and copy the key — you won't be able to see it again.

### 2. Create the GitHub repository
1. Go to https://github.com/new
2. Name it whatever you like (e.g. `global-chain-bulletin-fallback`).
3. Leave it **empty** — do not initialize with a README, .gitignore, or license.
4. Click **Create repository**, then copy the remote URL it shows you (something like `https://github.com/YOUR_USERNAME/global-chain-bulletin-fallback.git`).

Send me that URL and I'll push this code to it.

### 3. Add the GROQ key as a repo secret
1. In the new repo on GitHub, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `GROQ_API_KEY`. Value: paste the key from step 1.
4. Save.

### 4. Enable GitHub Pages
1. In the repo, go to **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to `Deploy from a branch`.
3. Branch: `main`, folder: `/ (root)`. Save.
4. GitHub will show you the public URL (usually `https://YOUR_USERNAME.github.io/REPO_NAME/`) — that's your fallback link.

### 5. First run
Once the secret is set, go to the **Actions** tab in the repo, select
**Refresh Bulletin (Fallback)**, and click **Run workflow** to trigger it
manually the first time rather than waiting for the next scheduled slot.
Check the run log if it fails — the most common issue is the API key not
being saved correctly.

## How it works

- `fetch_and_generate.py` pulls recent items from a fixed list of public RSS
  feeds (gCaptain, Splash247, The Loadstar, FreightWaves, Mining.com, Al
  Jazeera), sends the raw headlines to GROQ's `openai/gpt-oss-120b`
  model with instructions to synthesize a lead story, a "Today's Read"
  summary, and a ranked list of other stories — as JSON, not free text.
- The script renders that JSON into `index.html` using a fixed template
  (the model never writes raw HTML directly, which avoids broken markup).
- `.github/workflows/refresh.yml` runs the script on a schedule matching
  the main site (6am/6pm IST) and commits the result if it changed, using
  GitHub's own built-in Actions token — no separate GitHub PAT needed,
  which sidesteps the account-linking issue the Claude-based sync job hit.
- If fewer than 5 fresh RSS items are found across all feeds, the script
  exits without writing a file rather than publishing something threadbare.

## Extending it

- Add more feeds to the `FEEDS` list in `fetch_and_generate.py`. Test any
  new URL with `curl -I <url>` first — feed URLs do go stale.
- Adjust `LOOKBACK_HOURS` if you want a wider or narrower news window.
- The cron schedule is UTC in the workflow file; `30 0,12 * * *` = 6:00am
  and 6:00pm IST.
