# Job Hunt Hub

Telegram bot that turns job-post text into a polished, animated 7-second
Instagram Reel (1080×1920 artwork, 720p/24 fps MP4). Viewers can apply two ways:

* **Scan the QR code** on the Reel, or
* **Comment** (e.g. `LINK`, or anything) and get the apply link by **DM**
  automatically (Instagram comment-to-DM webhook).

`job_hunt.media.card` draws the layered card, `job_hunt.media.motion` animates
it, and `create_job_post` in `job_hunt.media.reel` writes the PNG, MP4 and caption.

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

## Reel look

* Background: a glass office tower with the company's name and logo on it
  (`media/scene.py`). To use real photos instead, put them in
  `job_hunt/assets/images/buildings/`: `<company>.jpg` for one company, or
  files starting with `office`/`generic`/`bg` as random backdrops.
* Hook headline ("Deloitte Hiring Alert / For Freshers"), stickers (salary,
  Freshers Eligible), white job card, QR + "Comment LINK" box, trust footer.
* Missing details get safe defaults (Location India, Role "Multiple Roles",
  Salary "As per company norms", ...). The Telegram preview marks them ⚠️.
* Logos: employer domain from the apply link -> Logo.dev by company name ->
  favicon. Set `LOGO_DEV_TOKEN`.
* Caption: details, comment CTA, trust lines and 30 hashtags (Instagram's max).

## Bot workflow

1. Send a job post to the bot and review the parsed details.
2. Edit the details or attach a replacement company image if needed.
3. Confirm the job and confirm or provide the application URL.
4. The bot shortens the confirmed URL and sends one static PNG with the QR
   embedded on the image.

Instagram publishing also requires valid Meta/Instagram and Cloudinary
credentials. After publishing, the Reel's media ID and short link are saved so
the comment-to-DM webhook knows which link to send.

## Comment-to-DM setup (Instagram API with Instagram Login)

1. In your Meta app, add the permissions `instagram_business_basic`,
   `instagram_business_manage_comments` and `instagram_business_manage_messages`,
   and generate `INSTA_TOKEN` with them.
2. Webhooks → Instagram → callback URL `https://<your-render-app>.onrender.com/instagram/webhook`,
   verify token = `META_WEBHOOK_VERIFY_TOKEN`; subscribe to the **comments** field.
3. Set `META_APP_SECRET` (Instagram app secret) so webhook signatures are checked.
4. While the app is in Development mode only accounts with a role on the app get
   DMs; switch it to Live (after App Review for the permissions above) for everyone.

Behaviour is controlled by `COMMENT_*` variables in `.env.example`: trigger on any
comment or only keywords, one DM per user per Reel, optional public reply.
Instagram allows one private reply per comment, within 7 days.

## Deploy on Render

`render.yaml` is a Blueprint: Render → New → Blueprint → select this repo, then
fill the secret env vars. One free web service runs the Telegram webhook, the
Instagram webhook and `/health` on the same port. Render's disk is wiped on
restart, so set `MONGODB_URI` (a free MongoDB Atlas cluster works) to keep
media→link mappings; without it the webhook falls back to the link in the caption.
The free plan sleeps after 15 minutes idle; the first webhook wakes it (Meta retries).

## Project layout

```text
job_hunt/
  bot.py                 Telegram workflow and user interaction
  config.py              Project paths and local environment loading
  parsing/
    job_post.py          Local job-post parsing and corrections
    gemini.py            Alternate Gemini-based parser
  media/
    card.py              Layered job-card design (QR + comment CTA)
    motion.py            Card animation for the Reel
    reel.py              Caption, logo lookup, and video encoding
    qr_code.py           QR PNG generation
  integrations/
    instagram.py         Instagram publishing and Cloudinary hosting
    comment_dm.py        Comment-to-DM automation
    link_store.py        Media → link mapping (MongoDB or local JSON)
  server.py              HTTP server: Telegram + Instagram webhooks, /health
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
