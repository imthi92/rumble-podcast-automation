# Rumble Podcast Automation

Fully automatic podcast pipeline that generates a video from a script and uploads it to Rumble. Runs entirely in GitHub Actions — **no laptop needed, no daily login**.

## How it works

```
Script (.txt) → edge-tts audio → ffmpeg video → Rumble upload (Playwright)
```

- Runs daily at 11:00 UTC via GitHub Actions cron (see `.github/workflows/daily_rumble.yml`)
- Audio: free Microsoft edge-tts voices (no API key)
- Upload: Playwright automates Rumble's web upload form
- Login: headless with `RUMBLE_EMAIL` / `RUMBLE_PASSWORD` secrets

## One-time setup (do once, then never again)

### 1. Add secrets to the repo

GitHub → **Settings → Secrets and variables → Actions** → add:

| Secret | Value |
|--------|-------|
| `RUMBLE_EMAIL` | Your Rumble login email |
| `RUMBLE_PASSWORD` | Your Rumble login password |

### 2. (Optional) Test locally

```bash
pip install -r requirements.txt
playwright install chromium

# Generate a video
python generate_video.py scripts/episode_01_pilot.txt

# Upload manually (uses RUMBLE_EMAIL/RUMBLE_PASSWORD env vars)
python rumble_upload.py --video output/episode_*/final_video.mp4 --title "Test"
```

### 3. Trigger the workflow

Run the "Daily Rumble Podcast" workflow manually once from the **Actions** tab to verify it works. After that it runs itself daily.

## Usage

### Upload an existing video

```bash
python rumble_upload.py --video video.mp4 --title "Episode Title" [--description "..."] [--tags "a,b,c"] [--thumbnail thumb.png]
```

### One-time interactive login (optional)

Useful if headless login is blocked (e.g., captcha). Login once in a browser, session saved to `rumble_session.json`:

```bash
python rumble_upload.py --login
```

If `rumble_session.json` exists, the script uses it and skips login.

### Debug a failed upload

```bash
python rumble_upload.py --video video.mp4 --title "Test" --headed
```

Screenshots are saved to `rumble_debug_*.png` on failure.

## Adding new episodes

Drop a `.txt` script into `scripts/` with lines in this format:

```
Speaker 1: First line of dialogue
Speaker 2: Second line of dialogue
```

The workflow picks the first script alphabetically.

## Troubleshooting

- **Login fails / captcha**: Run `--login` locally once and commit the session, or use `--headed` to see the issue.
- **Upload page changed**: Rumble has no public API, so if they change their UI, update the `SELECTORS` dict at the top of `rumble_upload.py`.
- **Video generation fails**: ensure `ffmpeg` is installed (`ffmpeg -version`).
