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
               4. build today's lineup    data/channels.json (icons)
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
5. **Publish.** The JSON files are committed back to the repo and GitHub
   Pages serves them to the kid site. `channels.json` holds each channel's
   icon for the feed, refreshed monthly.

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
- **`daily_watch_limit_minutes`, `parent_pin`, `search_buttons`, and
  `channel_buttons`** reach the site with the next lineup.
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

The AI rejects violence by default, which rules out most superhero and action
cartoons. To allow a show's cartoon action, name the show in
`free_text_guidance` and say what is fine, as the starter rules do for TMNT,
Batman, and the rest. The AI follows your guidance there, but never approves
gore or realistic, graphic violence.

Move a channel into `fun_channels` and the videos the AI rejected from it are
judged again under the fun rules on the next run. Take a channel out and its
fun approvals leave the pool on the next run.

Search buttons look through the whole approved pool, fun videos included, so a
button for a fun show (like "bluey"), or for the word "fun", lets him watch
more of those than `fun_videos_per_day`.

### Topics that are okay in small doses

`topics_low_priority` is for things you don't want banned but don't want much
of, like toy unboxing. A video mainly about one of these can be approved, and
is then picked for the daily lineup about a tenth as often as other videos,
tends to sit late in the feed, and comes last under a word or channel button.
It still has to pass every other check. A learning video must reach
`min_educational_score`, which these rarely do, so in practice they come from
your fun channels. To ban a topic outright, move it to `topics_banned`.

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

## Put it on a tablet

### iPad

#### Add to the Home Screen

1. On the iPad, open **Safari** and go to
   https://brandonrussell.io/kidtube/
2. Tap the **Share** button (the square with an arrow).
3. Tap **Add to Home Screen**, then **Add**.

Opening KidTube from the new icon runs it full screen with no address bar or tabs.

Chrome works too on iPadOS 16.4 or newer: tap the **Share** button at the end
of the address bar, then **Add to Home Screen**.

#### Lock the iPad to it with Guided Access

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

### Amazon Fire tablet

Menu names differ a little between Fire OS versions, so yours may not match
these word for word.

#### In an Amazon Kids profile

A Kids profile has no Home Screen shortcuts and only opens websites a parent
has added, so you add KidTube to his profile as a website.

1. Open the **Amazon Kids** app from your own (adult) profile and tap the
   settings gear next to his profile.
2. Tap **Add Content**, then **Add Websites**.
3. Enter `https://brandonrussell.io/kidtube/` and add it.
4. In his profile's settings, make sure the **web browser** is turned on and
   set to hand-selected websites only, so the browser opens nothing but the
   sites you added.

In his profile, KidTube now appears as a tile with his other content, usually
under a **Web** or **Websites** tab. Tapping it opens the site in the kids'
browser.

The videos themselves are served by YouTube inside the KidTube page. If the
page opens but videos stay blank, the kids' browser is blocking them. KidTube
then cannot play in a Kids profile on that tablet. Do not fix it by adding
youtube.com to his websites, which would give him all of YouTube. Use the
Silk steps below instead.

#### In a regular profile, with the Silk browser

1. Open **Silk** and go to https://brandonrussell.io/kidtube/
2. Tap the **menu** button (three dots or three lines).
3. Tap **Add to Home Screen**, then **Add**.

The icon lands on the Fire tablet's Home Screen and opens KidTube full screen.
To keep him inside it, turn on **Settings → Security & Privacy → App Pinning**
(called Screen Pinning on some versions), open KidTube, open the recent-apps
view, and pin it. Leaving a pinned app takes your lock-screen PIN.

## The kid site

- **Today's videos** is a feed. It shows today's lineup, loads more as he
  scrolls, and ends with a "you reached the end" note.
  - **Shelves:** after every 12 videos comes a sideways shelf of one search
    button's videos from the rest of the approved pool (🐢 Ninja Turtles,
    🚀 Space, ...), plus 🆕 New, ❤️ My favorites, and ⭐ Watch again shelves.
    Learning and cartoon shelves take turns. Tapping a shelf's title opens
    that button.
    Shelves draw from the whole pool, like the buttons, so they show more
    cartoons than `fun_videos_per_day` alone.
  - **Order:** the feed reshuffles each time he opens the app, or comes back
    after five minutes away. While he browses it holds still, so leaving a
    video puts him back where he was. Your mix of learning and fun videos
    stays as the lineup set it. Within each, new videos and the ones he likes
    tend to come first, and videos he has watched move to the end.
  - **Favorites:** the iPad notes what he watches for at least a minute, by
    channel, topic, and button. Interest fades by half every two weeks. This
    stays on the iPad, and the parent page lists the channels it has learned.
  - **Keep watching:** a video he leaves partway through goes on a ▶️ Keep
    watching shelf at the top of the feed, with a bar showing how far he got.
    Tapping it picks up a few seconds before where he stopped. A video he
    left in the first 30 seconds, or within a minute of the end, is not kept.
  - **NEW:** videos approved in the last two days get a NEW tag. Each video
    shows its channel's icon, which the nightly job saves in
    `data/channels.json`.
- **Search buttons:** a sideways row of word buttons from `search_buttons` in
  `rules.yaml`, such as 🚀 Space or 🦕 Dinosaurs. Tapping one shows the approved videos that
  match it; ☀️ Today goes back to the daily lineup. There is still no text box.
  A button only filters `approved.json`, which the iPad has already
  downloaded, so tapping never reaches YouTube or the AI and costs nothing.
  A button with no matches stays hidden until the nightly job approves one,
  and the job screens videos matching your buttons first.
- **Channel buttons:** under the word buttons, a sideways row of up to 24
  round channel icons. Tapping one shows that channel's approved videos.
  Channels you list in `channel_buttons` come first, in your order. The rest
  of the row is the channels with the most approved videos, the ones he
  watches most first. Like the word buttons, the row includes fun channels.
- **Player:** a back button, play/pause, buttons to jump back or forward 10
  seconds, a ❤️ button, and a progress bar he can tap or drag to move through
  the video. The back button returns him to the feed where he left it.
- **Hearts:** tapping ❤️ in the player saves the video. Saved videos get a
  ❤️ Favorites button in the top row and a shelf in the feed. Hearts stay on
  the iPad.
- **What next?:** when a video ends he gets four more to pick from: up to two
  from the same channel, then learning videos on the same topics. Nothing
  plays by itself. Cartoons are offered only after a cartoon, and only from
  that cartoon's channel.
- **Daily limit:** watch time is counted while a video is playing. When it
  reaches `daily_watch_limit_minutes`, an "All done for today" screen replaces
  everything until tomorrow.

### Parent page

Press and hold the **top-right corner** of the screen for two seconds, then
enter the PIN from `rules.yaml` (`2468` until you change it). It shows today's
lineup, recent approvals and rejections with reasons, today's watch time, what
he watched on that device over the last 7 days, a link to edit `rules.yaml`,
and buttons to give 15 more minutes or reset today's watch time.

### Weekly summary

Every Sunday the "Weekly summary" workflow posts an issue in this repo with
the week's screening: how many videos were approved and rejected, the new
videos by channel, and a sample of what the AI turned down with its reasons.
GitHub emails new issues to the repo owner, so this arrives as an email with
no mail server to set up. If it doesn't arrive, check that email is turned on
for "Participating" under GitHub → Settings → Notifications. Each new summary
closes the one before it. To get one now, run the workflow by hand from the
Actions tab.

What he watched is not in the email. That history never leaves the iPad, and
the issue is public like the rest of the repo. It is on the parent page.

**The PIN is a speed bump, not security.** This repo is public, the site is
static, and the PIN check runs in the browser. Anyone who can read the code can
get past it. All it guards is a read-only audit view, the watch history, and
the watch-time buttons. It keeps a six-year-old out and nothing more. Changing the rules
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
- **Watch time, hearts, and history live on the device.**
  They are stored in the browser, per device. Clearing Safari's website data
  resets them.
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
| `screener/channels.py` | Channel icon cache and channel buttons |
| `screener/weekly.py` | The weekly summary |
| `screener/run.py` | The job itself |
| `index.html`, `site/` | Kid site |
| `.github/workflows/screen.yml` | Nightly and manual screening job |
| `.github/workflows/weekly.yml` | Sunday summary, posted as an issue |
| `tests/` | Unit tests for the rules, filters, lineup picker, matching, channels, and weekly summary |
