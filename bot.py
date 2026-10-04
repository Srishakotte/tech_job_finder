import os
import asyncio
import logging
import uuid
from urllib.parse import urlparse

from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from parser import parse_job_post, apply_correction
from instagram_publisher import publish_reel
from instagram_webhook_client import register_published_media
from link_shortener import create_short_link
from main import add_application_link_to_caption, create_job_post
from clean_output import clean_expired_output

load_dotenv()

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from .env")

pending_jobs = {}
waiting_for_edit = set()
waiting_for_application_link = set()
pending_captions = {}
publishing_instagram = set()
waiting_for_job_photo = set()
waiting_for_job_audio = set()

keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "✅ YES, CREATE",
            callback_data="confirm_job",
        ),
        InlineKeyboardButton(
            "✏️ EDIT",
            callback_data="edit_job",
        ),
    ],
    [
        InlineKeyboardButton(
            "🖼️ Replace company image",
            callback_data="replace_job_image",
        ),
        InlineKeyboardButton(
            "↩️ Use auto-found logo",
            callback_data="reset_job_image",
        ),
    ],
    [
        InlineKeyboardButton(
            "🎵 Add licensed audio (10%)",
            callback_data="add_job_audio",
        ),
        InlineKeyboardButton(
            "🔇 Remove audio",
            callback_data="reset_job_audio",
        ),
    ],
])

application_link_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "✅ Confirm & shorten",
            callback_data="confirm_application_link",
        ),
        InlineKeyboardButton(
            "✏️ Change link",
            callback_data="change_application_link",
        ),
    ]
])

instagram_publish_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "📲 Publish this Reel",
            callback_data="publish_instagram",
        ),
        InlineKeyboardButton(
            "Skip for now",
            callback_data="skip_instagram",
        ),
    ]
])

instagram_mapping_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "🔁 Retry saving link",
            callback_data="retry_instagram_mapping",
        ),
        InlineKeyboardButton(
            "Finish",
            callback_data="finish_instagram",
        ),
    ]
])


def is_valid_application_link(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


async def ask_to_confirm_application_link(message, user_id, application_link):
    waiting_for_application_link.add(user_id)
    await message.reply_text(
        "🔗 Please confirm the application link before I shorten it:\n"
        f"{application_link}\n\n"
        "You can confirm it or send a corrected link.",
        reply_markup=application_link_keyboard,
    )


def format_job_preview(data):
    def show(value, fallback="Not detected"):
        return value if value else fallback

    skills = data.get("skills") or []
    skills_text = " · ".join(skills) if skills else "Not detected"

    ctc = show(data.get("ctc"))
    if data.get("ctc_source") == "estimated":
        ctc = f"⚠️ EST. {ctc}"

    return f"""
📋 JOB PREVIEW

🏢 Company
{show(data.get("company"))}

💼 Role
{show(data.get("job_title"))}

📍 Location
{show(data.get("location"))}

💰 CTC
{ctc}

🎓 Eligibility
{show(data.get("eligibility"))}

🧭 Experience
{show(data.get("experience"))}

🛠 Skills
{skills_text}

🔗 Application
{show(data.get("application_link"))}

🖼️ Image
{"Custom image supplied" if data.get("brand_image_path") else "Auto-found company logo (replace it below if needed)"}

🎵 Audio
{"Uploaded background track at 10% volume" if data.get("background_audio_path") else "None"}

────────────────────
This was parsed locally from your Telegram message.
Please check it before creating.
"""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    print("\n📩 NEW TELEGRAM MESSAGE")
    print(text)

    if user_id in waiting_for_job_photo:
        await update.message.reply_text(
            "Please send the company logo/photo as an image, or tap “Use auto-found logo”."
        )
        return

    if user_id in waiting_for_job_audio:
        await update.message.reply_text(
            "Please send an audio file (MP3, M4A, WAV, or OGG) that you own or have permission to use."
        )
        return

    if user_id in waiting_for_application_link:
        application_link = text.rstrip(".,);]}>")
        if not is_valid_application_link(application_link):
            await update.message.reply_text(
                "Please send a valid application URL starting with http:// or https://."
            )
            return

        data = pending_jobs.get(user_id)
        if not data:
            waiting_for_application_link.discard(user_id)
            await update.message.reply_text(
                "No pending job found. Send the job post again."
            )
            return

        data["application_link"] = application_link
        data.pop("short_application_link", None)
        waiting_for_application_link.discard(user_id)
        await ask_to_confirm_application_link(
            update.message,
            user_id,
            application_link,
        )
        return

    if user_id in waiting_for_edit:
        await handle_edit(update, context)
        return

    msg = await update.message.reply_text(
        "⏳ Parsing the job post..."
    )

    try:
        data = parse_job_post(text)
        data["job_id"] = uuid.uuid4().hex[:8]
        waiting_for_job_photo.discard(user_id)
        waiting_for_job_audio.discard(user_id)
        pending_jobs[user_id] = data

        await msg.edit_text(
            format_job_preview(data),
            reply_markup=keyboard,
        )

    except Exception as e:
        print("❌ PARSER ERROR:", e)
        await msg.edit_text(
            f"❌ Could not parse the post.\n\n{e}"
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        return

    user_id = update.effective_user.id
    data = pending_jobs.get(user_id)
    if user_id not in waiting_for_job_photo or not data:
        await update.message.reply_text(
            "First send a job post, then tap “Replace company image” to attach a photo to that job."
        )
        return

    photo = update.message.photo[-1]
    destination = os.path.join(
        "output",
        f"job_{user_id}_{data['job_id']}_company_image.jpg",
    )

    try:
        telegram_file = await context.bot.get_file(photo.file_id)
        await telegram_file.download_to_drive(custom_path=destination)
        with Image.open(destination) as image:
            image.convert("RGB").save(destination, format="JPEG", quality=92)
    except (OSError, UnidentifiedImageError) as error:
        if os.path.exists(destination):
            os.remove(destination)
        logger.exception("Could not process user-supplied job image.")
        await update.message.reply_text(
            f"Could not read that image. Please try another photo. ({error})"
        )
        return

    old_image = data.get("brand_image_path")
    data["brand_image_path"] = destination
    waiting_for_job_photo.discard(user_id)

    if old_image and old_image != destination and os.path.isfile(old_image):
        os.remove(old_image)

    await update.message.reply_photo(
        photo=destination,
        caption="✅ Image set for this Reel. It will replace the auto-found company logo.",
    )
    await update.message.reply_text(
        format_job_preview(data),
        reply_markup=keyboard,
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user_id = update.effective_user.id
    data = pending_jobs.get(user_id)
    if user_id not in waiting_for_job_audio or not data:
        await update.message.reply_text(
            "First send a job post, then tap “Add licensed audio (10%)” to attach audio to that Reel."
        )
        return

    media = update.message.audio or update.message.document
    if not media:
        await update.message.reply_text("Please send an audio file.")
        return

    filename = getattr(media, "file_name", None) or ""
    extension = os.path.splitext(filename)[1].lower()
    mime_type = getattr(media, "mime_type", "") or ""
    if not extension:
        extension = {
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "audio/wav": ".wav",
            "audio/ogg": ".ogg",
        }.get(mime_type, "")
    if extension not in {".mp3", ".m4a", ".wav", ".ogg", ".aac"}:
        await update.message.reply_text(
            "Unsupported audio format. Please send MP3, M4A, WAV, OGG, or AAC."
        )
        return

    if media.file_size and media.file_size > 20 * 1024 * 1024:
        await update.message.reply_text(
            "That audio file is over 20 MB. Please send a shorter/smaller licensed track."
        )
        return

    destination = os.path.join(
        "output",
        f"job_{user_id}_{data['job_id']}_background{extension}",
    )
    try:
        telegram_file = await context.bot.get_file(media.file_id)
        await telegram_file.download_to_drive(custom_path=destination)
    except Exception as error:
        logger.exception("Could not download user-supplied audio.")
        await update.message.reply_text(
            f"Could not download that audio file. Please try again. ({error})"
        )
        return

    old_audio = data.get("background_audio_path")
    data["background_audio_path"] = destination
    waiting_for_job_audio.discard(user_id)
    if old_audio and old_audio != destination and os.path.isfile(old_audio):
        os.remove(old_audio)

    await update.message.reply_text(
        "✅ Background audio added. It will be mixed at 10% volume; use music only if you own it or have permission.",
        reply_markup=keyboard,
    )
    await update.message.reply_text(
        format_job_preview(data),
        reply_markup=keyboard,
    )

async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    correction = update.message.text.strip()

    if user_id not in pending_jobs:
        waiting_for_edit.discard(user_id)
        await update.message.reply_text(
            "No pending job found. Send the job post again."
        )
        return

    print("\n✏️ USER CORRECTION")
    print(correction)

    data = pending_jobs[user_id]
    data = apply_correction(data, correction)

    pending_jobs[user_id] = data
    waiting_for_edit.discard(user_id)

    await update.message.reply_text(
        format_job_preview(data),
        reply_markup=keyboard,
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest as error:
        if "query is too old" in str(error).lower() or "query id is invalid" in str(error).lower():
            logger.info("Ignoring expired Telegram callback query.")
            return
        raise

    user_id = query.from_user.id

    if user_id not in pending_jobs:
        await query.message.reply_text(
            "No pending job found. Send the job post again."
        )
        return

    if query.data == "replace_job_image":
        waiting_for_job_photo.add(user_id)
        await query.message.reply_text(
            "🖼️ Send the company logo or a relevant job photo as an image now. "
            "It will replace the auto-found logo in the Reel."
        )
        return

    if query.data == "reset_job_image":
        data = pending_jobs[user_id]
        old_image = data.pop("brand_image_path", None)
        waiting_for_job_photo.discard(user_id)
        if old_image and os.path.isfile(old_image):
            os.remove(old_image)
        await query.message.reply_text(
            "↩️ The Reel will use the auto-found company logo again.",
            reply_markup=keyboard,
        )
        return

    if query.data == "add_job_audio":
        waiting_for_job_audio.add(user_id)
        await query.message.reply_text(
            "🎵 Send an MP3, M4A, WAV, OGG, or AAC track that you own or have permission to use. "
            "I’ll mix it at 10% volume."
        )
        return

    if query.data == "reset_job_audio":
        data = pending_jobs[user_id]
        old_audio = data.pop("background_audio_path", None)
        waiting_for_job_audio.discard(user_id)
        if old_audio and os.path.isfile(old_audio):
            os.remove(old_audio)
        await query.message.reply_text(
            "🔇 Background audio removed; this Reel will be silent.",
            reply_markup=keyboard,
        )
        return

    if query.data == "edit_job":
        waiting_for_edit.add(user_id)

        data = pending_jobs[user_id]

        def edit_value(value, fallback=""):
            if isinstance(value, list):
                return ", ".join(str(x) for x in value) if value else fallback
            return str(value) if value else fallback

        ctc = edit_value(data.get("ctc"))

        # Message 1: show what was parsed
        current_job = f"""
    ✏️ EDIT JOB

    Here is what I detected:

    🏢 Company
    {edit_value(data.get("company"), "Not detected")}

    💼 Role
    {edit_value(data.get("job_title"), "Not detected")}

    📍 Location
    {edit_value(data.get("location"), "Not detected")}

    💰 CTC
    {ctc if ctc else "Not detected"}

    🎓 Eligibility
    {edit_value(data.get("eligibility"), "Not detected")}

    🧭 Experience
    {edit_value(data.get("experience"), "Not detected")}

    🛠 Skills
    {edit_value(data.get("skills"), "Not detected")}

    🔗 Application
    {edit_value(data.get("application_link"), "Not detected")}
    """

        await query.message.reply_text(current_job)

        # Message 2: clean copy-paste/edit message
        change_template = f"""company: {edit_value(data.get("company"))}
    role: {edit_value(data.get("job_title"))}
    location: {edit_value(data.get("location"))}
    ctc: {edit_value(data.get("ctc"))}
    eligibility: {edit_value(data.get("eligibility"))}
    experience: {edit_value(data.get("experience"))}
    skills: {edit_value(data.get("skills"))}"""

        await query.message.reply_text(change_template)

        return

    if query.data == "change_application_link":
        waiting_for_application_link.add(user_id)
        await query.message.reply_text(
            "✏️ Send the corrected application URL."
        )
        return

    if query.data == "publish_instagram":
        if user_id in publishing_instagram:
            await query.message.reply_text("⏳ This Reel is already being published.")
            return

        data = pending_jobs[user_id]
        if data.get("instagram_media_id"):
            await query.message.reply_text(
                f"✅ This Reel was already published. Media ID: "
                f"{data['instagram_media_id']}"
            )
            return

        caption_path = pending_captions.get(user_id)
        video_path = data.get("video_path")
        if not caption_path or not video_path:
            await query.message.reply_text(
                "The generated Reel or caption is no longer available. "
                "Please create the post again."
            )
            return

        publishing_instagram.add(user_id)
        await query.message.reply_text("⏳ Uploading and publishing the Reel to Instagram...")

        try:
            with open(caption_path, "r", encoding="utf-8") as caption_file:
                caption_text = caption_file.read()

            result = await asyncio.to_thread(
                publish_reel,
                video_path,
                caption_text,
            )
            media_id = result["media_id"]
            data["instagram_media_id"] = media_id

            message = f"✅ Reel published to Instagram. Media ID: {media_id}"
            short_link = data.get("short_application_link")
            mapping_saved = not bool(short_link)
            if short_link:
                try:
                    await asyncio.to_thread(
                        register_published_media,
                        media_id,
                        short_link,
                    )
                    mapping_saved = True
                    message += "\n✅ This Reel is connected to its application link for comment replies."
                except Exception as error:
                    logger.exception("Reel published but its comment-link mapping was not saved.")
                    message += (
                        "\n⚠️ The Reel is live, but its auto-reply link could not be saved. "
                        f"Do not publish it again. Mapping error: {error}"
                    )
            else:
                message += "\n⚠️ No short application link was available to connect to comments."

            if result["cleanup_error"]:
                message += (
                    "\n⚠️ The Reel was published, but the temporary Cloudinary "
                    f"copy could not be deleted: {result['cleanup_error']}"
                )
            await query.message.reply_text(message)

            if mapping_saved:
                pending_captions.pop(user_id, None)
                pending_jobs.pop(user_id, None)
                waiting_for_application_link.discard(user_id)
            else:
                await query.message.reply_text(
                    "Once the webhook is hosted, retry saving this Reel’s link "
                    "mapping here. Do not publish the Reel again.",
                    reply_markup=instagram_mapping_keyboard,
                )
            print(f"✅ Instagram Reel published: {media_id}")

        except Exception as e:
            print("❌ INSTAGRAM PUBLISH ERROR:", e)
            await query.message.reply_text(
                f"❌ Instagram publishing failed.\n\n{e}",
                reply_markup=instagram_publish_keyboard,
            )
        finally:
            publishing_instagram.discard(user_id)
        return

    if query.data == "retry_instagram_mapping":
        data = pending_jobs.get(user_id)
        media_id = data.get("instagram_media_id") if data else None
        short_link = data.get("short_application_link") if data else None
        if not media_id or not short_link:
            await query.message.reply_text(
                "No published Reel/link mapping is pending."
            )
            return

        try:
            await asyncio.to_thread(
                register_published_media,
                media_id,
                short_link,
            )
        except Exception as error:
            logger.exception("Could not save the published Reel's comment-link mapping.")
            await query.message.reply_text(
                f"Could not save the mapping yet: {error}",
                reply_markup=instagram_mapping_keyboard,
            )
            return

        pending_captions.pop(user_id, None)
        pending_jobs.pop(user_id, None)
        waiting_for_application_link.discard(user_id)
        await query.message.reply_text(
            "✅ This Reel is connected to its application link for comment replies."
        )
        return

    if query.data == "finish_instagram":
        pending_captions.pop(user_id, None)
        pending_jobs.pop(user_id, None)
        waiting_for_application_link.discard(user_id)
        await query.message.reply_text(
            "Finished. The Reel is published, but comment-to-link replies won't work unless its mapping is saved."
        )
        return

    if query.data == "skip_instagram":
        pending_captions.pop(user_id, None)
        pending_jobs.pop(user_id, None)
        waiting_for_application_link.discard(user_id)
        await query.message.reply_text(
            "Skipped Instagram publishing. Your Reel and caption are ready in this chat."
        )
        return

    if query.data == "confirm_application_link":
        data = pending_jobs[user_id]
        if data.get("application_link_confirmation_complete"):
            await query.message.reply_text(
                "✅ The short link and updated caption are already ready. "
                "Use the existing Publish button to continue."
            )
            return
        if data.get("application_link_confirmation_in_progress"):
            await query.message.reply_text(
                "⏳ The short link is already being prepared. Please wait."
            )
            return

        application_link = data.get("application_link")
        caption_path = pending_captions.get(user_id)

        if not caption_path:
            await query.message.reply_text(
                "No generated caption is pending. Please create the Reel again."
            )
            return

        if not application_link or not is_valid_application_link(application_link):
            waiting_for_application_link.add(user_id)
            await query.message.reply_text(
                "Please send a valid application URL starting with http:// or https://."
            )
            return

        waiting_for_application_link.discard(user_id)
        data["application_link_confirmation_in_progress"] = True

        try:
            await query.message.reply_text("⏳ Creating the short application link...")
            short_link = data.get("short_application_link")
            if not short_link:
                short_link = await asyncio.to_thread(
                    create_short_link,
                    application_link,
                )
                data["short_application_link"] = short_link

            add_application_link_to_caption(caption_path, short_link)

            await query.message.reply_text(
                f"✅ Short application link:\n{short_link}"
            )
            with open(caption_path, "rb") as caption:
                await query.message.reply_document(
                    document=caption,
                    caption="📝 Caption updated with the short application link",
                )

            await query.message.reply_text(
                "Would you like me to publish this Reel to Instagram now?",
                reply_markup=instagram_publish_keyboard,
            )

            data["application_link_confirmation_complete"] = True
            print("✅ Short link + updated caption sent; awaiting publish choice.")

        except Exception as e:
            print("❌ LINK SHORTENING ERROR:", e)
            waiting_for_application_link.add(user_id)
            await query.message.reply_text(
                f"❌ Could not create or send the short link.\n\n{e}",
                reply_markup=application_link_keyboard,
            )
        finally:
            data["application_link_confirmation_in_progress"] = False
        return

    if query.data == "confirm_job":
        data = pending_jobs[user_id]
        if data.get("job_creation_complete"):
            await query.message.reply_text(
                "✅ This Reel has already been created. Use the existing link-confirmation buttons."
            )
            return
        if data.get("job_creation_in_progress"):
            await query.message.reply_text(
                "⏳ This Reel is already being created. Please wait."
            )
            return

        data["job_creation_in_progress"] = True

        try:
            await query.message.reply_text(
                "🎨 Creating your Reel and caption..."
            )
            result = create_job_post(
                job_title=data.get("job_title"),
                company=data.get("company"),
                location=data.get("location"),
                ctc=data.get("ctc"),
                eligibility=data.get("eligibility"),
                experience=data.get("experience"),
                skills=(
                    " · ".join(data["skills"])
                    if isinstance(data.get("skills"), list)
                    else data.get("skills")
                ),
                job_description=data.get("job_description"),
                company_description=data.get("company_description"),
                application_link=None,
                ctc_source=data.get("ctc_source", "not_available"),
                brand_image_path=data.get("brand_image_path"),
                job_id=data.get("job_id"),
                background_audio_path=data.get("background_audio_path"),
                comment_dm_enabled=(
                    os.getenv("INSTAGRAM_COMMENT_DM_ENABLED", "").lower()
                    in {"1", "true", "yes"}
                ),
            )

            video_path = result["video"]
            caption_path = result["caption"]
            data["video_path"] = video_path

            with open(result["card"], "rb") as preview_image:
                await query.message.reply_photo(
                    photo=preview_image,
                    caption="🖼️ Still preview of the exact Reel layout. Check the job details and image below.",
                )

            with open(video_path, "rb") as video:
                await query.message.reply_video(
                    video=video,
                    caption="🎬 Full animated Reel preview. Publishing still requires your confirmation.",
                )

            pending_captions[user_id] = caption_path
            application_link = data.get("application_link")
            if application_link and is_valid_application_link(application_link):
                await ask_to_confirm_application_link(
                    query.message,
                    user_id,
                    application_link,
                )
            else:
                waiting_for_application_link.add(user_id)
                await query.message.reply_text(
                    "🔗 I couldn't find an application link in the job post. "
                    "Please send the correct application URL."
                )

            print("✅ Reel sent; waiting for application-link confirmation.")
            data["job_creation_complete"] = True

        except Exception as e:
            print("❌ GENERATION ERROR:", e)
            await query.message.reply_text(
                f"❌ Failed to create the post.\n\n{e}"
            )
        finally:
            data["job_creation_in_progress"] = False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me any raw job post.\n\n"
        "I'll parse it locally, show you a preview, "
        "and let you correct it before generating the Reel."
    )

async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 Now send the complete job post."
    )

def main():
    print("🚀 Starting Job Hunt Hub bot...")

    try:
        removed = clean_expired_output()
        print(f"🧹 Removed {removed} expired output entries.")
    except OSError as error:
        logger.warning("Output cleanup failed (%s); continuing bot startup.", error)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.AUDIO | filters.Document.AUDIO,
            handle_audio,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("✅ Bot is running. Waiting for messages...")
    app.run_polling()

if __name__ == "__main__":
    main()
