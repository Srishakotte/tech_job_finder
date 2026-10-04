import os
import asyncio
import logging
from urllib.parse import urlparse

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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
    ]
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

🛠 Skills
{skills_text}

🔗 Application
{show(data.get("application_link"))}

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
    await query.answer()

    user_id = query.from_user.id

    if user_id not in pending_jobs:
        await query.message.reply_text(
            "No pending job found. Send the job post again."
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
        await query.message.reply_text("⏳ Creating the short application link...")

        try:
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

            print("✅ Short link + updated caption sent; awaiting publish choice.")

        except Exception as e:
            print("❌ LINK SHORTENING ERROR:", e)
            waiting_for_application_link.add(user_id)
            await query.message.reply_text(
                f"❌ Could not create or send the short link.\n\n{e}",
                reply_markup=application_link_keyboard,
            )
        return

    if query.data == "confirm_job":
        data = pending_jobs[user_id]

        await query.message.reply_text(
            "🎨 Creating your Reel and caption..."
        )

        try:
            result = create_job_post(
                job_title=data.get("job_title"),
                company=data.get("company"),
                location=data.get("location"),
                ctc=data.get("ctc"),
                eligibility=data.get("eligibility"),
                skills=(
                    " · ".join(data["skills"])
                    if isinstance(data.get("skills"), list)
                    else data.get("skills")
                ),
                job_description=data.get("job_description"),
                company_description=data.get("company_description"),
                application_link=None,
                ctc_source=data.get("ctc_source", "not_available"),
            )

            video_path = result["video"]
            caption_path = result["caption"]
            data["video_path"] = video_path

            with open(video_path, "rb") as video:
                await query.message.reply_video(
                    video=video,
                    caption="🎬 Your job Reel is ready!",
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

        except Exception as e:
            print("❌ GENERATION ERROR:", e)
            await query.message.reply_text(
                f"❌ Failed to create the post.\n\n{e}"
            )

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
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("✅ Bot is running. Waiting for messages...")
    app.run_polling()

if __name__ == "__main__":
    main()
