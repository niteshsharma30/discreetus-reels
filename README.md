# discreetUS daily Instagram Reel

Posts one short, cinematic, animated Reel to Instagram every day, at no cost.

```
prompts/instagram_prompt.md ──► AI writes the story ──► Reel is rendered ──► posted to Instagram
     (your creative direction)    (Gemini free tier)     (Python + ffmpeg)  (Instagram API, 19:00 IST)
```

Each day:
1. **Writing.** Gemini (free tier) reads your creative direction and writes 2–4 on-screen lines that tell a small
   story, a closing line, a visual style, a colour palette, the caption and hashtags. It avoids repeating topics.
   A policy check blocks risky words (secret, affair, hookup and similar), so a risky post is never sent.
2. **Video.** `media_reels.py` renders a 10–17 second 1080×1920 Reel with an ambient soundtrack: atmospheric light,
   abstract silhouettes, drifting dust, a slow camera push-in, film grain, serif text and a brand reveal.
   Styles: `two_figures`, `window`, `orbit`, `veil`. Palettes: `midnight`, `dusk`, `rose`, `teal`.
3. **Posting.** The Reel goes to Instagram and is recorded in `data/posts.csv`.

## Try it on your computer (no accounts needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DRY_RUN=true python daily.py prepare     # writes and renders today's Reel into media/
DRY_RUN=true python daily.py publish     # shows the Instagram calls in data/requests.jsonl, sends nothing
```

Without a `GEMINI_API_KEY`, the dry run uses a built-in sample script, so you can watch a Reel straight away.
To try another day, delete today's row from `data/posts.csv` and its file from `media/`.

## What it costs: nothing

| Piece | Free option used |
| --- | --- |
| Writing | Google Gemini API free tier. Key from **aistudio.google.com/apikey** (no card) |
| Video | Drawn frame by frame in Python, encoded by the ffmpeg bundled with `imageio-ffmpeg` |
| Fonts | Cormorant Garamond and Inter in `fonts/` (SIL Open Font License, free for commercial use) |
| Hosting | A `media` branch of your GitHub repo, served by the free jsDelivr CDN. The repo must be **public** |
| Scheduler | GitHub Actions (`.github/workflows/daily-instagram.yml`), unlimited free minutes on public repos |
| Posting | Meta Graph API with a system-user token (free, doesn't expire, no Facebook Page needed) |

## Going live

### 1. Instagram access (about 20 minutes, no Facebook Page needed)
You need a personal Facebook login for Meta's developer site, but nothing is posted to Facebook and no
Facebook Page is linked.
1. In the Instagram app: **Settings → Account type and tools → Switch to professional account → Business**.
2. Sign in at **developers.facebook.com** (complete "Confirm Account" if asked) → **My Apps → Create app** →
   use case **Manage messaging & content on Instagram** → create.
3. **Use cases → Customize → API setup with Unified login.** If asked, create and select a **business portfolio**
   (free; it is not a Facebook Page).
4. **App roles → Roles → Add People → Instagram Tester** → your Instagram username. Accept the invite on
   instagram.com: **Settings → Apps and websites → Tester invites**.
5. **1. Configure your app → Create new configuration**: access token *System-user access token*, expiration
   *Never*, asset = your Instagram account, keep `instagram_basic` and `instagram_content_publish`. Select it.
6. **2. Generate access tokens → Add account** → log in → note the number under the username → `IG_USER_ID`.
7. **Generate token** → copy → `IG_ACCESS_TOKEN`. It doesn't expire.

### 2. Gemini API key (free)
1. Go to **aistudio.google.com/apikey** and sign in with a Google account.
2. Click **Create API key** and copy it into `GEMINI_API_KEY`. No card is needed.

### 3. Put it on GitHub
1. Push this folder to a **public** GitHub repo. `.env` and `media/` are git-ignored, so your keys are never uploaded.
2. In the repo, open **Settings → Secrets and variables → Actions** and add these secrets:
   `GEMINI_API_KEY`, `IG_ACCESS_TOKEN`, `IG_USER_ID`, `WAITLIST_URL`, `BRAND_NAME`.
   Leave `DRY_RUN` out for now.
3. Open **Actions → daily-instagram → Run workflow**. It runs as a dry run. Read the log, and download the video
   from the `media` branch to watch it.
4. Add the secret `DRY_RUN` = `false` and run it again. The Reel is posted. From then on it runs every day at 19:00 IST
   (change the `cron` line in the workflow; it's in UTC).

## Changing things

| To change | Edit |
| --- | --- |
| The creative direction | `prompts/instagram_prompt.md` |
| Safety rules and banned words | `RULES` and `BANNED` in `writer.py` |
| Colours, motion, timing, music | `PALETTES` and `render_reel` in `media_reels.py` |
| Post a still image instead | `DAILY_FORMAT=card` (`media_cards.py`) |
| Posting time | the `cron` line in `.github/workflows/daily-instagram.yml` |

## Troubleshooting

| Message | Meaning | Fix |
| --- | --- | --- |
| `IG_ACCESS_TOKEN is invalid or was revoked` | The token was deleted or the app lost access | Generate a new one (Instagram access, step 7) and update the secret |
| `code 10` or `code 200` | Missing permission | Make sure `instagram_business_content_publish` is granted, then generate a new token |
| `could not process the media (ERROR)` | Instagram couldn't download or read the video | Check the repo is public and the `media` branch has the file |
| `Gemini free-tier limit reached` | Google's daily limit | It runs again the next day, or press "Run workflow" later |
| `Gemini declined to write today's post` | Gemini's safety filter blocked the reply | Nothing posts that day; it tries again tomorrow |
| `Blocked by the policy check` | The AI used a banned word | Nothing posts. Delete today's row in `data/posts.csv` and run again |

## Files

| File | Job |
| --- | --- |
| `daily.py` | The commands: `prepare`, `publish`, `status`. Start reading here |
| `writer.py` | The Gemini prompt, the safety rules and the policy check |
| `media_reels.py` | Renders the Reel (video and soundtrack) |
| `media_cards.py` | Still-image alternative |
| `instagram.py` | The Instagram API calls, with dry-run logging |
| `config.py` | Settings from `.env` |
| `prompts/instagram_prompt.md` | Your creative direction |
| `data/posts.csv` | Every post: date, script, caption, status, Instagram ID |
