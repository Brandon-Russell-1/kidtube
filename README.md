# KidTube

A YouTube player for one six-year-old. Every night a job picks through trusted
channels, has Claude screen each new video against rules written by a parent,
and publishes a short daily lineup to a simple site with no search box, no
recommendations, and no way out to YouTube.

- **Kid site:** https://brandonrussell.io/kidtube/
- **Parent controls:** [`rules.yaml`](rules.yaml)
- **Audit trail:** [`data/approved.json`](data/approved.json) and [`data/rejected.json`](data/rejected.json)

## How it works

```
rules.yaml ──► nightly GitHub Action ──► data/approved.json ──► kid site (GitHub Pages)
               1. read trusted channels   data/rejected.json
               2. hard filters            data/lineup.json
               3. Claude screens each
               4. build today's lineup
```

1. **Gather.** The job reads the recent uploads of every channel in
   `trusted_channels` (regular videos only; YouTube leaves Shorts and live
   streams out of that list), and runs one of your `search_terms`, a different
   one each night. Videos already in `approved.json` or `rejected.json` are skipped.
2. **Hard filters**, before any AI cost: the video must be public, embeddable,
   not age-restricted, within your length limits, not from a blocked channel,
   not a Short, and not a live stream. Videos marked "made for kids" go to the
   front of the queue.
3. **AI screening.** Each survivor goes to Claude with your rules, along with
   the title, description, tags, and the transcript when YouTube will hand it
   over. Claude returns `approve`, an `educational_score` from 1 to 10, `topics`,
   and a `reason`. It is told to reject when unsure, and to be stricter with
   search results than with your trusted channels. Each run screens up to
   `max_videos_screened_per_run` new videos, trusted channels first, with up to
   a fifth of the slots kept for search results. Videos left over wait for the
   next run.
4. **Lineup.** The job picks `daily_lineup_count` videos from the approved pool,
   favoring your higher-weighted topics, spreading picks across channels, and
   skipping anything shown in the last `repeat_after_days` days. Up to
   `fun_videos_per_day` of them come from your fun channels (see below).
5. **Publish.** The three JSON files are committed back to the repo and GitHub
   Pages serves them to the kid site.

Hosting is free: GitHub Pages, GitHub Actions on a public repo, and the YouTube
Data API's free quota. The one thing that costs money is the Anthropic API,
which is pay-as-you-go. With the small model this job uses, screening costs
about 3 cents per 100 videos; a full night of 150 cost about 4 cents. Once the
backlog from your channels is worked through, most
nights only see a handful of new uploads. Every run summary shows what that
run actually cost.

## Setup

### 1. Get a YouTube Data API key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and sign in.
2. Create a project (top bar → project picker → **New Project**). Any name works.
3. Open **APIs & Services → Library**, search for **YouTube Data API v3**, and
   click **Enable**.
4. Open **APIs & Services → Credentials → Create credentials → API key**.
5. Click the new key, and under **API restrictions** choose **Restrict key** and
   tick only **YouTube Data API v3**. Leave **Application restrictions** set to
   **None**, because GitHub's servers call from changing addresses.
6. Copy the key.

No billing account is needed. The free quota is 10,000 units a day and a normal
run uses a few hundred.

### 2. Get an Anthropic API key

1. Go to the [Claude Console](https://platform.claude.com/) and sign in.
2. Under **Billing**, add a small amount of credit. $5 lasts a long time here.
   Setting a monthly spend limit on the same page is a good idea.
3. Under **API keys**, click **Create key** and copy it. It is shown only once.

### 3. Add both keys as repository secrets

In this repo on GitHub: **Settings → Secrets and variables → Actions → New
repository secret**. Add two secrets with exactly these names:

| Name | Value |
| --- | --- |
| `YOUTUBE_API_KEY` | the key from step 1 |
| `ANTHROPIC_API_KEY` | the key from step 2 |

Or from a terminal with the GitHub CLI, which prompts you to paste each key:

```
gh secret set YOUTUBE_API_KEY --repo Brandon-Russell-1/kidtube
gh secret set ANTHROPIC_API_KEY --repo Brandon-Russell-1/kidtube
```

Keys live only in GitHub's secret store. They are never written to the repo or
to the run logs.

### 4. Run the job once

See [Trigger a run manually](#trigger-a-run-manually). The first run fills the
approved pool and builds the first lineup. The site updates a minute or two later.

## Editing the rules

Open [`rules.yaml`](rules.yaml) on GitHub, click the pencil icon, change what
you want, and click **Commit changes**. Every setting has a comment explaining
it. The parent page on the kid site has a button that goes straight to the editor.

Changes take effect on the next run. To see them right away, trigger a run by hand.

What happens when you change things:

- **Length limits and blocked channels** are re-checked every run. Loosen a
  limit and videos that were rejected for it get another chance. Block a
  channel and its approved videos are removed.
- **Topics, score threshold, and guidance** apply to videos screened from then
  on. Past AI decisions are not re-run. To have a video judged again under new
  rules, delete its entry from `data/rejected.json` or `data/approved.json`.
- **`daily_watch_limit_minutes`, `parent_pin`, and `search_buttons`** reach the
  site with the next lineup.
- **`daily_lineup_count`** can only be met once the approved pool is that big.
  Until then the lineup shows every approved video. Raising
  `max_videos_screened_per_run` grows the pool faster.

### Fun channels

`fun_channels` is for shows he loves that are mostly entertainment, like Bluey
or PAW Patrol. Their videos skip `min_educational_score`, but the AI still
checks each one for safety, age-appropriateness, banned topics, and your
guidance. Each day's lineup includes up to `fun_videos_per_day` of them, spread
through the list, and they never appear in "Watch again", so the daily number
holds. A fun-channel video that does reach `min_educational_score` counts as an
ordinary learning video.

Move a channel into `fun_channels` and the videos the AI rejected from it are
judged again under the fun rules on the next run. Take a channel out and its
fun approvals leave the pool on the next run.

Search buttons look through the whole approved pool, fun videos included, so a
button for a fun show (like "bluey"), or for the word "fun", lets him watch
more of those than `fun_videos_per_day`.

### Adding channels

A handle like `"@SciShowKids"` is easiest. Handles
can be given up and claimed by copycats, so the job skips any handle that
points at a channel with fewer than 10,000 subscribers and says so in the run
summary. To trust a small channel on purpose, list it by its channel ID
(`"UC..."`), which never changes hands. The summary's warning gives you the ID.

### Removing a video

To remove one video by hand, delete its entry from `data/approved.json` and add
its channel to `blocked_channels` if you want the whole channel gone. A video
you only delete will be screened again and may come back, so to keep a single
video out for good, move its entry into `data/rejected.json` instead.

## Trigger a run manually

On GitHub: **Actions** tab → **Screen videos** in the left column → **Run
workflow** → **Run workflow**.

Or from a terminal:

```
gh workflow run screen.yml --repo Brandon-Russell-1/kidtube
```

The run takes a few minutes. Click into it to see a summary: how many videos
were approved and rejected, how much YouTube quota was used, what the AI
screening cost, and any problems.
A red ✗ means something needs your attention, usually a missing or wrong key,
and the summary says which. Even then, the site keeps working from the videos
already approved.

The job also runs on its own every night at about 09:17 UTC. If GitHub ever
emails you that the schedule was paused for inactivity, open the Actions tab
and re-enable it.

## Auditing decisions

Everything the job decides is in two files you can read on GitHub:

- [`data/approved.json`](data/approved.json): each approved video with its
  score, topics, the AI's reason, whether a transcript was used, and when it
  was last in a lineup.
- [`data/rejected.json`](data/rejected.json): each rejected video with the
  reason. `"stage": "hard_filter"` means a fixed rule rejected it before the AI
  saw it. `"stage": "ai"` means Claude rejected it or scored it below your
  threshold.

The parent page on the kid site shows the most recent entries from both.

## Put it on the iPad

### Add to the Home Screen

1. On the iPad, open **Safari** and go to
   https://brandonrussell.io/kidtube/
2. Tap the **Share** button (the square with an arrow).
3. Tap **Add to Home Screen**, then **Add**.

Opening KidTube from the new icon runs it full screen with no address bar or tabs.

### Lock the iPad to it with Guided Access

Guided Access keeps the iPad inside one app until you enter a passcode.

One-time setup:

1. Open **Settings → Accessibility → Guided Access** and turn it on.
2. Tap **Passcode Settings → Set Guided Access Passcode** and choose a passcode
   he doesn't know. You can also allow Face ID or Touch ID to end a session.

Each time he watches:

1. Open KidTube from the Home Screen.
2. Triple-click the top button (or the Home button on iPads that have one).
3. Tap **Start**.

To exit, triple-click the same button, enter the passcode, and tap **End**.

Guided Access is the real lock. Without it, he can swipe out of KidTube like
any other app.

## The kid site

- **Today's videos:** big thumbnails from today's lineup.
- **Search buttons:** big word buttons from `search_buttons` in `rules.yaml`,
  such as 🚀 Space or 🦕 Dinosaurs. Tapping one shows the approved videos that
  match it; ☀️ Today goes back to the daily lineup. There is still no text box.
  A button only filters `approved.json`, which the iPad has already
  downloaded, so tapping never reaches YouTube or the AI and costs nothing.
  A button with no matches stays hidden until the nightly job approves one,
  and the job screens videos matching your buttons first.
- **Watch again:** videos he has already watched or that were in earlier lineups.
- **Player:** a back button, play/pause, buttons to jump back or forward 10
  seconds, and a progress bar he can tap or drag to move through the video.
  When a video ends he lands back on the grid.
- **Daily limit:** watch time is counted while a video is playing. When it
  reaches `daily_watch_limit_minutes`, an "All done for today" screen replaces
  everything until tomorrow.

### Parent page

Press and hold the **top-right corner** of the screen for two seconds, then
enter the PIN from `rules.yaml` (`2468` until you change it). It shows today's
lineup, recent approvals and rejections with reasons, today's watch time, a
link to edit `rules.yaml`, and buttons to give 15 more minutes or reset today's
watch time.

**The PIN is a speed bump, not security.** This repo is public, the site is
static, and the PIN check runs in the browser. Anyone who can read the code can
get past it. All it guards is a read-only audit view and the watch-time
buttons. It keeps a six-year-old out and nothing more. Changing the rules
requires signing in to GitHub, which is the real protection.

## Limits you should know about

- **The AI can be wrong.** It mostly judges from the title, description, and
  tags, because YouTube usually refuses transcript requests from GitHub's
  servers. Trusted channels are the main safeguard, so choose them with care
  and skim `approved.json` now and then. Each entry's `"source"` says whether
  it came from a trusted channel or from search.
- **Everything here is public.** The repo, the lists of approved and rejected
  videos, and the site address can be seen by anyone who finds them. Nothing
  identifies your child unless you write it into `rules.yaml`.
- **The watch limit lives on the device.** It is stored in the browser, per
  device. Clearing Safari's website data resets it.
- **YouTube controls the video frame.** The site covers the player with
  transparent shields, sandboxes it so its links cannot open, and closes it
  before the end screen. YouTube may still show ads inside the frame on some
  videos; they cannot be tapped through.
- **Shorts** have no flag in YouTube's API. The job treats anything up to 60
  seconds or tagged `#shorts` as a Short, checks every video of three minutes
  or less against youtube.com, and `min_video_minutes: 3` keeps out the rest.
  If you lower that setting, the youtube.com check is what stands between a
  Short and the AI, and it can fail open when YouTube doesn't answer.

## Development

```
pip install -r requirements.txt
python -m pytest
```

To run the job locally, set `YOUTUBE_API_KEY` and `ANTHROPIC_API_KEY` in your
environment and run `python -m screener.run`. To preview the site, run
`python -m http.server` in the repo root and open http://localhost:8000.

| Path | What it is |
| --- | --- |
| `rules.yaml` | Parent controls |
| `screener/config.py` | Model ID, per-run caps, quota limits |
| `screener/filters.py` | Hard filters |
| `screener/ai.py` | The prompt and the Claude call |
| `screener/lineup.py` | Daily lineup picker |
| `screener/run.py` | The job itself |
| `index.html`, `site/` | Kid site |
| `.github/workflows/screen.yml` | Nightly and manual screening job |
| `tests/` | Unit tests for the filters and the lineup picker |
