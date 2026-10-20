# Job Hunt Hub

Telegram bot that turns job-post text into one static 1080×1920 job graphic
with a QR code pointing to the confirmed, shortened application link. The
dark, neon-edged desk-and-card layout is inspired by the supplied reference.
`create_static_job_reel` in `job_hunt.media.reel` renders the PNG. The older
animated `create_job_post` renderer remains available for direct use.

## Run locally

Use Python 3.11 (see `.python-version`):

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If you do not already have a `.env`, copy `.env.example` to create one. Fill in
the required values, then start the bot:

```sh
python bot.py
```

`python -m job_hunt.bot` is also supported. Keep the process running to receive
Telegram messages; stop it with Ctrl+C.

## Bot workflow

1. Send a job post to the bot and review the parsed details.
2. Edit the details or attach a replacement company image if needed.
3. Confirm the job and confirm or provide the application URL.
4. The bot shortens the confirmed URL and sends one static PNG with the QR
   embedded on the image.

Instagram publishing also requires valid Meta/Instagram and Cloudinary
credentials. The comment-to-DM webhook has been removed.

## Project layout

```text
job_hunt/
  bot.py                 Telegram workflow and user interaction
  config.py              Project paths and local environment loading
  parsing/
    job_post.py          Local job-post parsing and corrections
    gemini.py            Alternate Gemini-based parser
  media/
    reel.py              Card, caption, and video composition
    qr_code.py           QR PNG generation
  integrations/
    instagram.py         Instagram publishing and Cloudinary hosting
    terabox_links.py     Application-link shortening
  maintenance/
    output.py            Expired generated-file cleanup
bot.py                   Backward-compatible bot entry point
main.py                  Standalone Reel-generation demo
examples/
  sample_caption.txt     Example Instagram caption
```

The current deployment uses one set of credentials from `.env`. Keep account
credentials at the integration boundary; a future multi-account change can add
named account profiles and pass the selected profile into the Instagram and
shortener integrations without changing Reel-generation code.

Generated assets are written to the repository's `output/` directory and
expired output is cleaned on bot startup.
