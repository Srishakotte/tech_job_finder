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

from .config import comment_keyword, load_environment
from .media.card import with_defaults
from .integrations import link_store
from .integrations.instagram import find_media, list_recent_media, publish_reel
from .integrations.terabox_links import create_short_link
from .media.reel import create_job_post, create_static_job_reel
from .maintenance.output import clean_expired_output, cleanup_output_files, prune_completed_outputs
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


def _pending_output_paths():
    """Protect output files used by any pending Telegram approval/publish flow."""
    keys = ("video_path", "caption_path", "card_path", "static_image_path", "brand_image_path", "background_audio_path")
    return [
        data.get(key)
        for data in pending_jobs.values()
        for key in keys
        if data.get(key)
    ]


def _run_output_cleanup(*, startup=False):
    try:
        if startup:
            removed = clean_expired_output()
            logger.info("Output startup cleanup removed %d stale files/directories", removed)
        else:
            removed = prune_completed_outputs(protected_paths=_pending_output_paths())
            logger.info("Output retention cleanup removed %d old job assets", removed)
    except Exception:
        logger.exception("Output cleanup failed; continuing without interrupting the bot")

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


def card_ctc(data):
    """Only print salaries the post actually states; estimates would look fake."""
    return None if data.get("ctc_source") == "estimated" else data.get("ctc")


def format_job_preview(data):
    values, defaulted = with_defaults({
        "company": data.get("company"), "job_title": data.get("job_title"),
        "location": data.get("location"), "ctc": card_ctc(data),
        "eligibility": data.get("eligibility"), "experience": data.get("experience"),
        "skills": data.get("skills"), "job_type": data.get("employment_type"),
    })

    def show(key, label):
        mark = "  ⚠️ default" if key in defaulted else ""
        return f"{label}: {values[key]}{mark}\n"

    return (
        "📋 JOB PREVIEW\n\n"
        f"Company: {values['company'] or '❗ Not detected (please edit)'}\n"
        + show("job_title", "Role")
        + show("job_type", "Job type")
        + show("location", "Location")
        + show("ctc", "Salary")
        + show("eligibility", "Qualification")
        + show("experience", "Experience")
        + f"Skills: {values['skills'] or '— (hidden on Reel)'}\n"
        f"Application: {data.get('application_link') or 'Not provided yet'}\n\n"
        "⚠️ default = not in the post, so a safe default will be shown on the Reel.\n"
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
            "I’ll parse it, let you edit the details, design an animated job Reel "
            "(scan the QR or comment to get the link by DM), send it here for review, "
            "then ask before publishing to Instagram."
        )


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("📩 Send the complete job post in your next message.")


def _is_admin(update: Update):
    """Optional lock: set TELEGRAM_ADMIN_IDS=123,456 to restrict admin commands."""
    allowed = {x.strip() for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()}
    return not allowed or str(update.effective_user.id) in allowed


SETLINK_HELP = (
    "🔗 Attach an apply link to a reel that's already on Instagram, so comments get a DM.\n\n"
    "Usage:\n/setlink <reel link> <short link>\n\n"
    "Example:\n/setlink https://www.instagram.com/reel/ABC123/ https://short.link/xyz\n\n"
    "Use /reels to see which recent reels are missing a link."
)


async def setlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if not _is_admin(update):
        await message.reply_text("⛔ You're not allowed to use this command.")
        return
    args = context.args or []
    if len(args) != 2:
        await message.reply_text(SETLINK_HELP)
        return
    reel_ref, short_link = args[0], args[1].rstrip(".,);]}>")
    if not is_valid_application_link(short_link):
        await message.reply_text("❌ The second part must be a link starting with http:// or https://")
        return
    try:
        media = await asyncio.to_thread(find_media, reel_ref)
        await asyncio.to_thread(link_store.save_media_link, media["id"], short_link,
                                permalink=media.get("permalink"), source="setlink")
    except (ValueError, LookupError) as exc:
        await message.reply_text(f"❌ {exc}")
        return
    except Exception as exc:
        logger.exception("/setlink failed")
        await message.reply_text(f"❌ Could not save the link: {exc}")
        return
    await message.reply_text(
        "✅ Link saved. New comments on this reel will now get a DM with:\n"
        f"{short_link}\n\n(Comments made before now won't be answered automatically.)"
    )


async def reels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if not _is_admin(update):
        await message.reply_text("⛔ You're not allowed to use this command.")
        return
    try:
        media_items = await asyncio.to_thread(list_recent_media, 10)
        lines = []
        for item in media_items:
            record = await asyncio.to_thread(link_store.get_media_record, item["id"])
            mark = "✅" if record and record.get("short_link") else "❌ no link"
            title = (item.get("caption") or "").split("\n")[0][:45]
            lines.append(f"{mark}  {title}\n{item.get('permalink', item['id'])}")
    except Exception as exc:
        logger.exception("/reels failed")
        await message.reply_text(f"❌ Could not load your reels: {exc}")
        return
    if not lines:
        await message.reply_text("No posts found on the Instagram account.")
        return
    await message.reply_text(
        "📋 Your last reels (❌ = comments won't get a DM yet):\n\n" + "\n\n".join(lines)
        + "\n\nFix one with:\n/setlink <reel link> <short link>",
        disable_web_page_preview=True,
    )


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
            ctc=card_ctc(data),
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
                ctc=card_ctc(data),
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
                job_type=data.get("employment_type"),
                logo_hint_url=data.get("application_link"),
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
                ctc=card_ctc(data),
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
                job_type=data.get("employment_type"),
                logo_hint_url=data.get("application_link"),
            )

        video_path = result.get("video")
        caption_path = result.get("caption")
        if not video_path or not os.path.isfile(video_path):
            raise RuntimeError("Reel generator did not return an existing MP4 video.")
        if not caption_path or not os.path.isfile(caption_path):
            raise RuntimeError("Reel generator did not return an existing caption file.")

        data["video_path"] = video_path
        data["caption_path"] = caption_path
        data["card_path"] = result.get("card")
        data["cover_offset_ms"] = result.get("cover_offset_ms")
        data["application_link_confirmation_complete"] = True
        data["job_creation_complete"] = True
        pending_captions[user_id] = caption_path

        await message.reply_text(f"✅ Short application link:\n{short_link}")
        await message.reply_video(
            video=video_path,
            caption="🎬 Your job Reel is ready. Review it before publishing.",
            supports_streaming=True,
        )
        # The generated MP4 now contains the selected logo/audio. Remove duplicate
        # preview imagery and user-supplied source assets only after Telegram accepted
        # the final video. Keep the final card, MP4, and caption for approval/retry.
        final_card_path = result.get("card")
        if static_path and final_card_path and os.path.abspath(static_path) != os.path.abspath(final_card_path):
            cleanup_output_files([static_path])
        cleanup_output_files([data.get("brand_image_path"), data.get("background_audio_path")])
        data.pop("brand_image_path", None)
        data.pop("background_audio_path", None)
        _run_output_cleanup(startup=False)
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
        result = await asyncio.to_thread(
            publish_reel, video_path, caption, cover_offset_ms=data.get("cover_offset_ms"),
        )
        media_id = result.get("media_id")
        if not media_id:
            raise RuntimeError("Instagram did not return a published media ID.")
        data["instagram_media_id"] = media_id
        text = f"✅ Reel published to Instagram!\nMedia ID: {media_id}"
        keyword = comment_keyword()
        if keyword and data.get("short_application_link"):
            try:
                await asyncio.to_thread(
                    link_store.save_media_link, media_id, data["short_application_link"],
                    role=data.get("job_title"), company=data.get("company"),
                    original_link=data.get("application_link"),
                )
                text += f"\n💬 Comment-to-DM is live: anyone who comments gets the link by DM."
            except Exception as exc:
                logger.exception("Could not save media link for comment-to-DM")
                text += f"\n⚠️ Comment-to-DM will fall back to the caption link ({exc})."
        if result.get("permalink"):
            text += f"\n🔗 {result['permalink']}"
        if result.get("cleanup_error"):
            text += "\n⚠️ Published, but temporary Cloudinary cleanup failed: " + str(result["cleanup_error"])
        await query.message.reply_text(text)
        # No local archive is needed: once Instagram confirms publication, delete
        # the final files. Telegram already has the Reel, and it can be regenerated.
        cleanup_output_files([
            video_path,
            caption_path,
            data.get("card_path"),
            data.get("static_image_path"),
            data.get("brand_image_path"),
            data.get("background_audio_path"),
        ])
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
        cancelled_data = pending_jobs.get(user_id, {})
        cleanup_output_files([
            cancelled_data.get("video_path"),
            cancelled_data.get("caption_path"),
            cancelled_data.get("card_path"),
            cancelled_data.get("static_image_path"),
            cancelled_data.get("brand_image_path"),
            cancelled_data.get("background_audio_path"),
        ])
        waiting_for_instagram_permission.discard(user_id)
        pending_jobs.pop(user_id, None)
        pending_captions.pop(user_id, None)
        waiting_for_application_link.discard(user_id)
        await query.message.reply_text("❎ Publishing cancelled. Local generated files were removed; the Reel remains in this Telegram chat if you need to review it.")
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    _run_output_cleanup(startup=True)
    # Local development defaults to polling. On Render, set TELEGRAM_MODE=webhook
    # and configure WEBHOOK_PATH and WEBHOOK_SECRET (Render sets RENDER_EXTERNAL_URL).
    telegram_mode = os.getenv("TELEGRAM_MODE", "polling").strip().lower()
    if telegram_mode not in {"polling", "webhook"}:
        raise RuntimeError("TELEGRAM_MODE must be either 'polling' or 'webhook'.")
    builder = (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(30)
    )
    if telegram_mode == "webhook":
        builder = builder.updater(None)
    app = builder.build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CommandHandler("setlink", setlink_command))
    app.add_handler(CommandHandler("reels", reels_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Telegram + the Instagram comment-to-DM webhook share one process and port.
    from .server import run

    try:
        asyncio.run(run(app, telegram_mode))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
