import asyncio
import logging
import os
import uuid
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import load_environment
from .integrations.instagram import publish_reel
from .integrations.terabox_links import create_short_link
from .media.reel import create_job_post, create_static_job_reel
from .parsing.job_post import parse_job_post, apply_correction

load_environment()
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from .env")

# Per-user temporary state. Keep this bot running in one process; use persistent
# storage if you later deploy multiple workers or need state to survive restarts.
pending_jobs = {}
pending_captions = {}
waiting_for_edit = set()
waiting_for_application_link = set()
waiting_for_job_photo = set()
waiting_for_job_audio = set()
waiting_for_instagram_permission = set()
publishing_instagram = set()

job_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("✅ YES, CREATE", callback_data="confirm_job"),
        InlineKeyboardButton("✏️ EDIT", callback_data="edit_job"),
    ],
    [
        InlineKeyboardButton("🖼️ Replace company image", callback_data="replace_job_image"),
        InlineKeyboardButton("↩️ Use auto-found logo", callback_data="reset_job_image"),
    ],
    [
        InlineKeyboardButton("🎵 Add licensed audio", callback_data="add_job_audio"),
        InlineKeyboardButton("🔇 Remove audio", callback_data="reset_job_audio"),
    ],
])

application_link_keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Confirm & create Reel", callback_data="confirm_application_link"),
    InlineKeyboardButton("✏️ Change link", callback_data="change_application_link"),
]])

instagram_keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Publish Reel", callback_data="publish_instagram"),
    InlineKeyboardButton("❌ Cancel", callback_data="cancel_instagram_publish"),
]])


def format_job_preview(data):
    def show(value, fallback="Not detected"):
        if value is None or value == "":
            return fallback
        if isinstance(value, list):
            return ", ".join(str(x) for x in value) if value else fallback
        return str(value)

    def format_role(value):
        text = show(value, "Role not detected")
        if len(text.split()) <= 2:
            return f"Role: {text}"
        return text

    ctc = show(data.get("ctc"))
    if data.get("ctc_source") == "estimated" and ctc != "Not detected":
        ctc = f"⚠️ EST. {ctc}"

    role_text = format_role(data.get("job_title"))

    return (
        "📋 JOB PREVIEW\n\n"
        f"Company: {show(data.get('company'))}\n"
        f"{role_text}\n"
        f"Location: {show(data.get('location') or 'India')}\n"
        f"CTC: {ctc}\n"
        f"Qualification: {show(data.get('eligibility') or 'Bachelor\'s degree / B.Tech or equivalent')}\n"
        f"Experience: {show(data.get('experience') or 'Any')}\n"
        f"Skills: {show(data.get('skills'))}\n"
        f"Application: {show(data.get('application_link'), 'Not provided yet')}\n\n"
        "Check the details, edit if needed, then confirm."
    )


def is_valid_application_link(value):
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except (TypeError, ValueError):
        return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "👋 Send me a complete job post.\n\n"
            "I’ll parse it, let you edit the details, create a static job card, "
            "turn that card into an MP4 Reel with optional licensed audio, send "
            "the Reel and caption here, then ask before publishing to Instagram."
        )


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("📩 Send the complete job post in your next message.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    user_id = update.effective_user.id
    text = message.text.strip()

    if user_id in waiting_for_job_photo:
        await message.reply_text("Please send a company logo/photo as an image, or tap “Use auto-found logo”.")
        return
    if user_id in waiting_for_job_audio:
        await message.reply_text("Please send an audio file you own or have permission to use.")
        return

    if user_id in waiting_for_application_link:
        if not is_valid_application_link(text):
            await message.reply_text("Please send a valid URL starting with http:// or https://.")
            return
        data = pending_jobs.get(user_id)
        if not data:
            waiting_for_application_link.discard(user_id)
            await message.reply_text("No pending job found. Send the job post again.")
            return
        data["application_link"] = text.rstrip(".,);]}>")
        data.pop("short_application_link", None)
        data.pop("application_link_confirmation_complete", None)
        data.pop("job_creation_complete", None)
        waiting_for_application_link.discard(user_id)
        await message.reply_text(
            f"🔗 Please confirm this application link:\n{data['application_link']}",
            reply_markup=application_link_keyboard,
        )
        return

    if user_id in waiting_for_edit:
        await handle_edit(update, context)
        return

    status = await message.reply_text("⏳ Parsing the job post...")
    try:
        data = parse_job_post(text)
        data["job_id"] = uuid.uuid4().hex[:8]
        pending_jobs[user_id] = data
        pending_captions.pop(user_id, None)
        waiting_for_job_photo.discard(user_id)
        waiting_for_job_audio.discard(user_id)
        waiting_for_instagram_permission.discard(user_id)
        await status.edit_text(format_job_preview(data), reply_markup=job_keyboard)
    except Exception as exc:
        logger.exception("Job parsing failed")
        await status.edit_text(f"❌ Could not parse the post.\n\n{exc}")


async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message
    if not message or not message.text:
        return
    data = pending_jobs.get(user_id)
    if not data:
        waiting_for_edit.discard(user_id)
        await message.reply_text("No pending job found. Send the job post again.")
        return

    try:
        updated = apply_correction(data, message.text.strip())
        updated.pop("job_creation_complete", None)
        updated.pop("application_link_confirmation_complete", None)
        updated.pop("video_path", None)
        updated.pop("caption_path", None)
        updated.pop("static_image_path", None)
        pending_jobs[user_id] = updated
        waiting_for_edit.discard(user_id)
        pending_captions.pop(user_id, None)
        await message.reply_text(format_job_preview(updated), reply_markup=job_keyboard)
    except Exception as exc:
        logger.exception("Could not apply job correction")
        await message.reply_text(f"❌ Could not apply that correction.\n{exc}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.photo:
        return
    user_id = update.effective_user.id
    data = pending_jobs.get(user_id)
    if user_id not in waiting_for_job_photo or not data:
        await message.reply_text("Send a job post first, then tap “Replace company image” to attach a photo.")
        return

    destination_dir = "output"
    os.makedirs(destination_dir, exist_ok=True)
    destination = os.path.join(destination_dir, f"job_{user_id}_{data['job_id']}_company_image.jpg")
    try:
        telegram_file = await context.bot.get_file(message.photo[-1].file_id)
        await telegram_file.download_to_drive(custom_path=destination)
        with Image.open(destination) as image:
            converted = image.convert("RGB")
            converted.save(destination, format="JPEG", quality=92)
            converted.close()
    except (OSError, UnidentifiedImageError) as exc:
        if os.path.exists(destination):
            os.remove(destination)
        logger.exception("Could not process uploaded company image")
        await message.reply_text(f"❌ Could not read that image. Please try another one. ({exc})")
        return

    old_path = data.get("brand_image_path")
    data["brand_image_path"] = destination
    data.pop("application_link_confirmation_complete", None)
    data.pop("job_creation_complete", None)
    pending_captions.pop(user_id, None)
    waiting_for_job_photo.discard(user_id)
    if old_path and old_path != destination and os.path.isfile(old_path):
        os.remove(old_path)
    await message.reply_text("✅ Company image saved.", reply_markup=job_keyboard)
    await message.reply_text(format_job_preview(data), reply_markup=job_keyboard)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    user_id = update.effective_user.id
    data = pending_jobs.get(user_id)
    if user_id not in waiting_for_job_audio or not data:
        await message.reply_text("Send a job post first, then tap “Add licensed audio”.")
        return

    media = message.audio or (message.document if message.document and
                              (message.document.mime_type or "").startswith("audio/") else None)
    if not media:
        await message.reply_text("Please send an audio file (MP3, M4A, WAV, OGG, or AAC).")
        return

    filename = getattr(media, "file_name", "") or ""
    extension = os.path.splitext(filename)[1].lower()
    mime = getattr(media, "mime_type", "") or ""
    if not extension:
        extension = {
            "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/wav": ".wav",
            "audio/x-wav": ".wav", "audio/ogg": ".ogg", "audio/aac": ".aac",
        }.get(mime, "")
    if extension not in {".mp3", ".m4a", ".wav", ".ogg", ".aac"}:
        await message.reply_text("Unsupported audio format. Please send MP3, M4A, WAV, OGG, or AAC.")
        return
    if media.file_size and media.file_size > 20 * 1024 * 1024:
        await message.reply_text("That audio file is over 20 MB. Please send a smaller licensed track.")
        return

    os.makedirs("output", exist_ok=True)
    destination = os.path.join("output", f"job_{user_id}_{data['job_id']}_background{extension}")
    try:
        telegram_file = await context.bot.get_file(media.file_id)
        await telegram_file.download_to_drive(custom_path=destination)
    except Exception as exc:
        logger.exception("Could not download audio")
        await message.reply_text(f"❌ Could not download that audio. ({exc})")
        return

    old_path = data.get("background_audio_path")
    data["background_audio_path"] = destination
    data.pop("job_creation_complete", None)
    data.pop("application_link_confirmation_complete", None)
    pending_captions.pop(user_id, None)
    waiting_for_job_audio.discard(user_id)
    if old_path and old_path != destination and os.path.isfile(old_path):
        os.remove(old_path)
    await message.reply_text(
        "✅ Licensed background audio saved. It will be mixed at 20% volume.",
        reply_markup=job_keyboard,
    )


async def create_reel_and_send(message, user_id, data):
    if data.get("job_creation_in_progress"):
        await message.reply_text("⏳ This Reel is already being created. Please wait.")
        return
    data["job_creation_in_progress"] = True
    try:
        application_link = data.get("application_link")
        if not is_valid_application_link(application_link or ""):
            waiting_for_application_link.add(user_id)
            await message.reply_text("🔗 Send a valid application URL to include in the job card.")
            return

        await message.reply_text("⏳ Creating the short link, static job card, and MP4 Reel...")
        short_link = data.get("short_application_link")
        if not short_link:
            short_link = await asyncio.to_thread(create_short_link, application_link)
            if not is_valid_application_link(short_link):
                # Some shorteners return a non-URL on failure; don't put that into the card.
                raise RuntimeError(f"The short-link service returned an invalid URL: {short_link!r}")
            data["short_application_link"] = short_link

        static_path = await asyncio.to_thread(
            create_static_job_reel,
            company=data.get("company"),
            job_title=data.get("job_title"),
            location=data.get("location"),
            ctc=data.get("ctc"),
            eligibility=data.get("eligibility"),
            experience=data.get("experience"),
            skills=data.get("skills"),
            application_link=short_link,
            brand_image_path=data.get("brand_image_path"),
            job_id=data.get("job_id"),
            job_type=data.get("employment_type"),
            posted_on=data.get("posted_on"),
            role_note=data.get("role_note"),
            location_note=data.get("location_note"),
            ctc_note=data.get("ctc_note"),
            experience_note=data.get("experience_note"),
        )
        data["static_image_path"] = static_path

        # create_job_post is the existing project function that renders the MP4
        # Reel; background audio is optional and must be supplied by the user.
        try:
            result = await asyncio.to_thread(
                create_job_post,
                job_title=data.get("job_title"),
                company=data.get("company"),
                location=data.get("location"),
                ctc=data.get("ctc"),
                eligibility=data.get("eligibility"),
                experience=data.get("experience"),
                skills=data.get("skills"),
                job_description=data.get("job_description"),
                company_description=data.get("company_description"),
                application_link=short_link,
                ctc_source=data.get("ctc_source", "not_available"),
                brand_image_path=data.get("brand_image_path"),
                job_id=data.get("job_id"),
                background_audio_path=data.get("background_audio_path"),
                background_volume=0.20,
                demo_mode=False,
                reel_style="reference",
                static_image_path=static_path,
            )
        except RuntimeError as exc:
            if "Could not download a logo" not in str(exc):
                raise
            logger.warning("Logo download failed; retrying Reel creation without external logo")
            result = await asyncio.to_thread(
                create_job_post,
                job_title=data.get("job_title"),
                company=data.get("company"),
                location=data.get("location"),
                ctc=data.get("ctc"),
                eligibility=data.get("eligibility"),
                experience=data.get("experience"),
                skills=data.get("skills"),
                job_description=data.get("job_description"),
                company_description=data.get("company_description"),
                application_link=short_link,
                ctc_source=data.get("ctc_source", "not_available"),
                brand_image_path=None,
                job_id=data.get("job_id"),
                background_audio_path=data.get("background_audio_path"),
                background_volume=0.20,
                demo_mode=False,
                reel_style="reference",
                static_image_path=static_path,
            )

        video_path = result.get("video")
        caption_path = result.get("caption")
        if not video_path or not os.path.isfile(video_path):
            raise RuntimeError("Reel generator did not return an existing MP4 video.")
        if not caption_path or not os.path.isfile(caption_path):
            raise RuntimeError("Reel generator did not return an existing caption file.")

        data["video_path"] = video_path
        data["caption_path"] = caption_path
        data["application_link_confirmation_complete"] = True
        data["job_creation_complete"] = True
        pending_captions[user_id] = caption_path

        await message.reply_text(f"✅ Short application link:\n{short_link}")
        await message.reply_video(
            video=video_path,
            caption="🎬 Your job Reel is ready. Review it before publishing.",
            supports_streaming=True,
        )
        with open(caption_path, "r", encoding="utf-8") as handle:
            caption_text = handle.read().strip()
        await message.reply_document(
            document=caption_path,
            caption="📝 Instagram caption",
        )
        await message.reply_text(
            "Your Reel has been sent here. Publish it to Instagram?",
            reply_markup=instagram_keyboard,
        )
        waiting_for_instagram_permission.add(user_id)
        logger.info("Reel created for user %s at %s; caption length=%d",
                    user_id, video_path, len(caption_text))
    except Exception as exc:
        logger.exception("Reel creation failed")
        waiting_for_application_link.add(user_id)
        await message.reply_text(
            f"❌ Could not create the Reel.\n\n{exc}",
            reply_markup=application_link_keyboard,
        )
    finally:
        data["job_creation_in_progress"] = False


async def publish_reel_to_instagram(query, user_id):
    data = pending_jobs.get(user_id)
    if not data:
        await query.message.reply_text("No pending job found. Send the job post again.")
        return
    if user_id in publishing_instagram:
        await query.message.reply_text("⏳ This Reel is already being published.")
        return
    if data.get("instagram_media_id"):
        await query.message.reply_text(f"✅ Already published. Media ID: {data['instagram_media_id']}")
        return

    video_path = data.get("video_path")
    caption_path = pending_captions.get(user_id) or data.get("caption_path")
    if not video_path or not os.path.isfile(video_path):
        await query.message.reply_text("❌ The MP4 Reel is missing. Please create it again.")
        return
    if not caption_path or not os.path.isfile(caption_path):
        await query.message.reply_text("❌ The caption file is missing. Please create the Reel again.")
        return

    publishing_instagram.add(user_id)
    try:
        await query.message.reply_text("⏳ Uploading the MP4 and publishing to Instagram...")
        with open(caption_path, "r", encoding="utf-8") as handle:
            caption = handle.read().strip()
        result = await asyncio.to_thread(publish_reel, video_path, caption)
        media_id = result.get("media_id")
        if not media_id:
            raise RuntimeError("Instagram did not return a published media ID.")
        data["instagram_media_id"] = media_id
        text = f"✅ Reel published to Instagram!\nMedia ID: {media_id}"
        if result.get("permalink"):
            text += f"\n🔗 {result['permalink']}"
        if result.get("cleanup_error"):
            text += "\n⚠️ Published, but temporary Cloudinary cleanup failed: " + str(result["cleanup_error"])
        await query.message.reply_text(text)
        pending_jobs.pop(user_id, None)
        pending_captions.pop(user_id, None)
        waiting_for_instagram_permission.discard(user_id)
        waiting_for_application_link.discard(user_id)
    except Exception as exc:
        logger.exception("Instagram publishing failed")
        await query.message.reply_text(
            f"❌ Instagram publishing failed.\n\n{exc}",
            reply_markup=instagram_keyboard,
        )
    finally:
        publishing_instagram.discard(user_id)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer()
    except BadRequest as exc:
        if "query is too old" in str(exc).lower() or "query id is invalid" in str(exc).lower():
            return
        raise

    user_id = query.from_user.id
    action = query.data or ""

    # Handle publish/cancel before checking for a pending job: those callbacks
    # belong to the already-generated Reel and must never be blocked by a guard.
    if action == "publish_instagram":
        if user_id not in waiting_for_instagram_permission:
            await query.message.reply_text("Please generate a Reel and review it before publishing.")
            return
        await publish_reel_to_instagram(query, user_id)
        return
    if action == "cancel_instagram_publish":
        waiting_for_instagram_permission.discard(user_id)
        pending_jobs.pop(user_id, None)
        pending_captions.pop(user_id, None)
        waiting_for_application_link.discard(user_id)
        await query.message.reply_text("❎ Instagram publishing cancelled. The Reel and caption were already sent here.")
        return

    data = pending_jobs.get(user_id)
    if not data:
        await query.message.reply_text("No pending job found. Send the job post again.")
        return

    if action == "edit_job":
        waiting_for_edit.add(user_id)
        await query.message.reply_text(
            "✏️ Send corrections like:\n"
            "company: Example Corp\nrole: Software Engineer\nlocation: Hyderabad\n"
            "ctc: 12 LPA\neligibility: B.Tech 2026\nskills: Python, Java, SQL"
        )
        return

    if action == "replace_job_image":
        waiting_for_job_photo.add(user_id)
        await query.message.reply_text("🖼️ Send the company logo or job image as a photo now.")
        return

    if action == "reset_job_image":
        old = data.pop("brand_image_path", None)
        if old and os.path.isfile(old):
            os.remove(old)
        data.pop("job_creation_complete", None)
        data.pop("application_link_confirmation_complete", None)
        data.pop("static_image_path", None)
        await query.message.reply_text("↩️ The Reel will use the auto-found logo again.", reply_markup=job_keyboard)
        return

    if action == "add_job_audio":
        waiting_for_job_audio.add(user_id)
        await query.message.reply_text(
            "🎵 Send MP3, M4A, WAV, OGG, or AAC audio that you own or have permission to use."
        )
        return

    if action == "reset_job_audio":
        old = data.pop("background_audio_path", None)
        if old and os.path.isfile(old):
            os.remove(old)
        data.pop("job_creation_complete", None)
        data.pop("application_link_confirmation_complete", None)
        await query.message.reply_text("🔇 Audio removed. The next Reel will be silent unless you add a track.", reply_markup=job_keyboard)
        return

    if action == "change_application_link":
        data.pop("short_application_link", None)
        data.pop("application_link_confirmation_complete", None)
        data.pop("job_creation_complete", None)
        waiting_for_application_link.add(user_id)
        await query.message.reply_text("✏️ Send the corrected application URL.")
        return

    if action == "confirm_job":
        link = data.get("application_link")
        if is_valid_application_link(link or ""):
            await query.message.reply_text(
                f"🔗 Confirm this application link:\n{link}",
                reply_markup=application_link_keyboard,
            )
        else:
            waiting_for_application_link.add(user_id)
            await query.message.reply_text("🔗 Send the application URL to include in the job card.")
        return

    if action == "confirm_application_link":
        if data.get("job_creation_complete") and data.get("video_path") and os.path.isfile(data["video_path"]):
            await query.message.reply_text("✅ This Reel is already generated. Use the publish buttons above if you want to post it.")
            return
        waiting_for_application_link.discard(user_id)
        await create_reel_and_send(query.message, user_id, data)
        return


def main():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    for noisy_logger in [
        "telegram",
        "telegram.ext",
        "httpx",
        "httpcore",
        "urllib3",
        "requests",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    print("Bot ready. Send a job post to the Telegram bot and confirm the Reel before publishing.")
    os.makedirs("output", exist_ok=True)
    app = (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Local development defaults to polling. On Render, set TELEGRAM_MODE=webhook
    # and configure RENDER_EXTERNAL_URL, WEBHOOK_PATH, and WEBHOOK_SECRET.
    telegram_mode = os.getenv("TELEGRAM_MODE", "polling").strip().lower()

    if telegram_mode == "webhook":
        base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
        webhook_path = os.getenv("WEBHOOK_PATH", "").strip().strip("/")
        webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()

        if not base_url or not webhook_path or not webhook_secret:
            raise RuntimeError(
                "Webhook mode requires RENDER_EXTERNAL_URL, WEBHOOK_PATH, "
                "and WEBHOOK_SECRET to be configured."
            )

        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", "10000")),
            url_path=webhook_path,
            webhook_url=f"{base_url}/{webhook_path}",
            secret_token=webhook_secret,
            allowed_updates=Update.ALL_TYPES,
        )
    elif telegram_mode == "polling":
        # Use polling for local testing; no public webhook URL is needed.
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    else:
        raise RuntimeError(
            "TELEGRAM_MODE must be either 'polling' or 'webhook'."
        )


if __name__ == "__main__":
    main()
