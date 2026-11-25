"""One HTTP server for the whole Render web service.

Routes
  POST /<WEBHOOK_PATH>        Telegram updates (secret-token checked)
  GET  /instagram/webhook     Meta verification handshake
  POST /instagram/webhook     Instagram comment events -> comment-to-DM
  GET  /  and  /health        health check for Render / uptime pingers

Tornado is already installed by python-telegram-bot[webhooks], so this adds no
new dependency.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import signal

from telegram import Update
from telegram.ext import Application
from tornado.httpserver import HTTPServer
from tornado.web import Application as WebApp, RequestHandler

from . import legal_pages
from .integrations import comment_dm

logger = logging.getLogger(__name__)
INSTAGRAM_PATH = "/instagram/webhook"
MAX_BODY = 1024 * 1024
_background = set()


def _spawn(coro):
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


class HealthHandler(RequestHandler):
    def get(self):
        self.write("ok")

    def head(self):
        self.set_status(200)


class LegalPageHandler(RequestHandler):
    def initialize(self, render):
        self.render_page = render

    def get(self):
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.write(self.render_page())


class TelegramHandler(RequestHandler):
    def initialize(self, app: Application, secret: str):
        self.app, self.secret = app, secret

    async def post(self):
        supplied = self.request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, self.secret):
            self.set_status(403)
            return
        try:
            update = Update.de_json(json.loads(self.request.body), self.app.bot)
        except (ValueError, TypeError):
            self.set_status(400)
            return
        await self.app.update_queue.put(update)
        self.set_status(200)


class InstagramHandler(RequestHandler):
    def get(self):
        challenge = comment_dm.verify_subscription(
            self.get_query_argument("hub.mode", ""),
            self.get_query_argument("hub.verify_token", ""),
            self.get_query_argument("hub.challenge", ""),
        )
        if challenge is None:
            self.set_status(403)
            self.write("Verification failed")
            return
        self.write(challenge)

    async def post(self):
        body = self.request.body
        if not body or len(body) > MAX_BODY:
            self.set_status(413)
            return
        if not comment_dm.signature_is_valid(body, self.request.headers.get("X-Hub-Signature-256", "")):
            logger.warning("Rejected Instagram webhook with an invalid signature")
            self.set_status(403)
            return
        try:
            payload = json.loads(body)
        except ValueError:
            self.set_status(400)
            return
        # Answer Meta immediately; send DMs in the background.
        for value, account_id in comment_dm.comment_events(payload):
            _spawn(self._handle(value, account_id))
        self.write("EVENT_RECEIVED")

    @staticmethod
    async def _handle(value, account_id):
        try:
            status = await asyncio.to_thread(comment_dm.process_comment, value, account_id)
            logger.info("Instagram comment %s -> %s", value.get("id"), status)
        except Exception:
            logger.exception("Comment-to-DM processing crashed")


def make_web_app(app: Application, telegram_path: str | None, telegram_secret: str | None):
    routes = [
        (r"/", HealthHandler),
        (r"/health", HealthHandler),
        (INSTAGRAM_PATH, InstagramHandler),
        (r"/privacy", LegalPageHandler, {"render": legal_pages.privacy_policy}),
        (r"/data-deletion", LegalPageHandler, {"render": legal_pages.data_deletion}),
    ]
    if telegram_path:
        routes.append((f"/{telegram_path}", TelegramHandler, {"app": app, "secret": telegram_secret}))
    return WebApp(routes)


async def _wait_for_shutdown():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: Ctrl+C raises KeyboardInterrupt instead
    await stop.wait()


async def run(app: Application, mode: str):
    """Run Telegram (webhook or polling) and the HTTP server in one event loop."""
    port = int(os.getenv("PORT", "10000"))
    telegram_path = telegram_secret = None

    if mode == "webhook":
        base_url = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
        telegram_path = os.getenv("WEBHOOK_PATH", "").strip().strip("/")
        telegram_secret = os.getenv("WEBHOOK_SECRET", "").strip()
        if not base_url or not telegram_path or not telegram_secret:
            raise RuntimeError("Webhook mode requires RENDER_EXTERNAL_URL (or PUBLIC_URL), "
                               "WEBHOOK_PATH and WEBHOOK_SECRET.")

    serve_http = mode == "webhook" or bool(os.getenv("META_WEBHOOK_VERIFY_TOKEN"))
    server = None
    async with app:
        if mode == "webhook":
            await app.bot.set_webhook(
                url=f"{base_url}/{telegram_path}", secret_token=telegram_secret,
                allowed_updates=Update.ALL_TYPES, drop_pending_updates=False,
            )
        else:
            await app.bot.delete_webhook()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await app.start()
        if serve_http:
            server = HTTPServer(make_web_app(app, telegram_path, telegram_secret),
                                max_body_size=MAX_BODY, xheaders=True)
            server.listen(port, address="0.0.0.0")
            print(f"HTTP server on :{port} (Instagram webhook at {INSTAGRAM_PATH})")
        try:
            await _wait_for_shutdown()
        finally:
            if server:
                server.stop()
            if app.updater and app.updater.running:
                await app.updater.stop()
            await app.stop()
