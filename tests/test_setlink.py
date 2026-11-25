import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from job_hunt import bot
from job_hunt.integrations import instagram, link_store


MEDIA = [{"id": "111", "permalink": "https://www.instagram.com/reel/ABC123/", "caption": "Hevo hiring\nmore"},
         {"id": "222", "permalink": "https://www.instagram.com/reel/XYZ789/", "caption": "KPMG hiring"}]


def fake_update(user_id=1):
    message = SimpleNamespace(replies=[])

    async def reply_text(text, **kwargs):
        message.replies.append(text)

    message.reply_text = reply_text
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=user_id))


class SetLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        mock.patch.object(link_store, "DATA_DIR", Path(self.tmp.name)).start()
        mock.patch.dict(os.environ, {"MONGODB_URI": "", "TELEGRAM_ADMIN_IDS": ""}).start()
        mock.patch.object(instagram, "list_recent_media", return_value=MEDIA).start()
        mock.patch.object(bot, "list_recent_media", return_value=MEDIA).start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def run_cmd(self, handler, args, user_id=1):
        update = fake_update(user_id)
        asyncio.run(handler(update, SimpleNamespace(args=args)))
        return update.message.replies[-1]

    def test_find_media_by_url_and_id(self):
        self.assertEqual(instagram.find_media("https://www.instagram.com/reel/XYZ789/?igsh=abc")["id"], "222")
        self.assertEqual(instagram.find_media("https://www.instagram.com/tech_job_finder/reel/ABC123")["id"], "111")
        self.assertEqual(instagram.find_media("999")["id"], "999")
        with self.assertRaises(LookupError):
            instagram.find_media("https://www.instagram.com/reel/NOPE/")

    def test_setlink_saves_and_reels_shows_status(self):
        reply = self.run_cmd(bot.setlink_command, ["https://www.instagram.com/reel/ABC123/", "https://sh.rt/x"])
        self.assertIn("Link saved", reply)
        self.assertEqual(link_store.get_media_record("111")["short_link"], "https://sh.rt/x")
        listing = self.run_cmd(bot.reels_command, [])
        self.assertIn("✅  Hevo hiring", listing)
        self.assertIn("❌ no link  KPMG hiring", listing)

    def test_setlink_usage_and_validation(self):
        self.assertIn("Usage", self.run_cmd(bot.setlink_command, []))
        self.assertIn("http", self.run_cmd(bot.setlink_command, ["https://www.instagram.com/reel/ABC123/", "notalink"]))

    def test_admin_lock(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_ADMIN_IDS": "42"}):
            self.assertIn("not allowed", self.run_cmd(bot.setlink_command, ["a", "b"], user_id=7))


if __name__ == "__main__":
    unittest.main()
