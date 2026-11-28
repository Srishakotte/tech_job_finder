import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tornado.testing import AsyncHTTPTestCase

from job_hunt.integrations import comment_dm, link_store
from job_hunt.server import make_web_app


def comment(text="LINK", user_id="111", comment_id="c1", media_id="m1"):
    return {"id": comment_id, "text": text, "media": {"id": media_id},
            "from": {"id": user_id, "username": "asha"}}


class CommentDmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {
            "INSTAGRAM_USER_ID": "999", "INSTA_TOKEN": "t", "MONGODB_URI": "",
            "COMMENT_DM_TRIGGER": "any", "COMMENT_TO_DM_ENABLED": "true",
            "COMMENT_PUBLIC_REPLY": "true",
        })
        self.env.start()
        self.store = mock.patch.object(link_store, "DATA_DIR", Path(self.tmp.name))
        self.store.start()
        link_store.save_media_link("m1", "https://sh.rt/x", role="SDE", company="Acme")
        # Plain-text path; the button path is exercised in its own tests below.
        mock.patch.dict(os.environ, {"COMMENT_DM_BUTTON": "false"}).start()
        self.dm = mock.patch.object(comment_dm, "send_private_reply", return_value="mid").start()
        self.reply = mock.patch.object(comment_dm, "send_public_reply").start()

    def tearDown(self):
        mock.patch.stopall()
        self.env.stop()
        self.tmp.cleanup()

    def test_any_comment_gets_dm_with_link_and_public_reply(self):
        self.assertEqual(comment_dm.process_comment(comment("wow nice")), "sent")
        text = self.dm.call_args.args[1]
        self.assertIn("https://sh.rt/x", text)
        self.assertIn("SDE at Acme", text)
        self.assertIn("@asha", text)
        self.reply.assert_called_once()

    def test_duplicate_and_same_user_get_one_dm(self):
        comment_dm.process_comment(comment())
        self.assertEqual(comment_dm.process_comment(comment()), "duplicate")
        self.assertEqual(comment_dm.process_comment(comment(comment_id="c2")), "already-sent-to-user")
        self.assertEqual(self.dm.call_count, 1)

    def test_own_reply_is_ignored(self):
        self.assertEqual(comment_dm.process_comment(comment(user_id="999")), "own-comment")
        self.dm.assert_not_called()

    def test_keyword_mode(self):
        with mock.patch.dict(os.environ, {"COMMENT_DM_TRIGGER": "keyword", "COMMENT_KEYWORD": "LINK"}):
            self.assertEqual(comment_dm.process_comment(comment("great post")), "no-match")
            self.assertEqual(comment_dm.process_comment(comment("Link pls", comment_id="c3")), "sent")

    def test_failed_dm_releases_claim(self):
        self.dm.side_effect = RuntimeError("boom")
        self.assertEqual(comment_dm.process_comment(comment()), "dm-failed")
        self.dm.side_effect = None
        self.assertEqual(comment_dm.process_comment(comment()), "sent")

    def test_caption_fallback_when_not_stored(self):
        with mock.patch.object(comment_dm, "_caption_link", return_value="https://cap/l") as cap:
            self.assertEqual(comment_dm.process_comment(comment(media_id="m2")), "sent")
            cap.assert_called_once_with("m2")
            self.assertIn("https://cap/l", self.dm.call_args.args[1])


class ButtonDmTests(unittest.TestCase):
    def setUp(self):
        mock.patch.dict(os.environ, {"COMMENT_DM_BUTTON": "true", "INSTAGRAM_USER_ID": "999",
                                     "INSTA_TOKEN": "t"}).start()
        self.post = mock.patch.object(comment_dm, "_post", return_value={"message_id": "m1"}).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_sends_tappable_button_with_short_link(self):
        comment_dm.deliver_link("c9", "asha", {"role": "SDE", "company": "Acme"}, "https://sh.rt/x")
        body = self.post.call_args.kwargs["json_body"]
        payload = body["message"]["attachment"]["payload"]
        self.assertEqual(body["recipient"], {"comment_id": "c9"})
        self.assertEqual(payload["template_type"], "button")
        self.assertEqual(payload["buttons"][0], {"type": "web_url", "url": "https://sh.rt/x", "title": "Apply Now"})
        self.assertIn("SDE at Acme", payload["text"])
        self.assertLessEqual(len(payload["text"]), 640)

    def test_falls_back_to_text_when_button_refused(self):
        self.post.side_effect = [RuntimeError("template not supported"), {"message_id": "m2"}]
        comment_dm.deliver_link("c9", "asha", None, "https://sh.rt/x")
        self.assertEqual(self.post.call_count, 2)
        text = self.post.call_args.kwargs["json_body"]["message"]["text"]
        self.assertIn("https://sh.rt/x", text)


class InstagramWebhookTests(AsyncHTTPTestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"META_WEBHOOK_VERIFY_TOKEN": "vt", "META_APP_SECRET": "sec"})
        self.env.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.env.stop()

    def get_app(self):
        return make_web_app(None, None, None)

    def test_verification(self):
        ok = self.fetch("/instagram/webhook?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=42")
        self.assertEqual(ok.body, b"42")
        bad = self.fetch("/instagram/webhook?hub.mode=subscribe&hub.verify_token=no&hub.challenge=42")
        self.assertEqual(bad.code, 403)

    def test_signed_event_is_processed(self):
        body = json.dumps({"object": "instagram", "entry": [
            {"id": "999", "changes": [{"field": "comments", "value": comment()}]}]}).encode()
        sig = "sha256=" + hmac.new(b"sec", body, hashlib.sha256).hexdigest()
        with mock.patch.object(comment_dm, "process_comment", return_value="sent") as proc:
            res = self.fetch("/instagram/webhook", method="POST", body=body,
                             headers={"X-Hub-Signature-256": sig})
            self.assertEqual(res.code, 200)
            self.io_loop.run_sync(lambda: __import__("asyncio").sleep(0.2))
            proc.assert_called_once()
        bad = self.fetch("/instagram/webhook", method="POST", body=body,
                         headers={"X-Hub-Signature-256": "sha256=00"})
        self.assertEqual(bad.code, 403)

    def test_health(self):
        self.assertEqual(self.fetch("/health").body, b"ok")


if __name__ == "__main__":
    unittest.main()
