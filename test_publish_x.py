import argparse
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import post_queue
import publish_x
import content_radar
import founder_radar


class PublishQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        queue_path = Path(self.temp.name) / "queue.json"
        for module in (post_queue, publish_x):
            queue_patch = patch.object(module, "QUEUE_PATH", queue_path)
            queue_patch.start()
            self.addCleanup(queue_patch.stop)
        post_queue.save_queue(
            [{
                "id": "test-post",
                "channel": "x",
                "scheduled_at": (datetime.now(publish_x.TIMEZONE) - timedelta(minutes=1)).isoformat(),
                "status": "scheduled",
                "text": "Teste de publicação",
            }]
        )

    def test_success_is_recorded_and_not_repeated(self):
        with patch.object(publish_x.content_radar, "load_env"), patch.object(
            publish_x, "credentials_from_env", return_value={}
        ), patch.object(publish_x, "publish", return_value="123") as send:
            publish_x.run(argparse.Namespace(execute=True, limit=1))
            publish_x.run(argparse.Namespace(execute=True, limit=1))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(post_queue.load_queue()[0]["status"], "published")
        self.assertEqual(post_queue.load_queue()[0]["x_post_id"], "123")

    def test_checkpoint_records_publishing_before_request(self):
        statuses = []
        def checkpoint():
            statuses.append(post_queue.load_queue()[0]["status"])

        with patch.object(publish_x.content_radar, "load_env"), patch.object(
            publish_x, "credentials_from_env", return_value={}
        ), patch.object(publish_x, "publish", return_value="123"):
            publish_x.run(argparse.Namespace(execute=True, limit=1), checkpoint=checkpoint)

        self.assertEqual(statuses, ["publishing", "published"])

    def test_checkpoint_failure_prevents_request(self):
        with patch.object(publish_x.content_radar, "load_env"), patch.object(
            publish_x, "credentials_from_env", return_value={}
        ), patch.object(publish_x, "publish") as send:
            with self.assertRaisesRegex(RuntimeError, "state unavailable"):
                publish_x.run(
                    argparse.Namespace(execute=True, limit=1),
                    checkpoint=lambda: (_ for _ in ()).throw(RuntimeError("state unavailable")),
                )
        send.assert_not_called()

    def test_ambiguous_failure_requires_manual_check(self):
        with patch.object(publish_x.content_radar, "load_env"), patch.object(
            publish_x, "credentials_from_env", return_value={}
        ), patch.object(publish_x, "publish", side_effect=TimeoutError) as send:
            with self.assertRaisesRegex(RuntimeError, "confira no X"):
                publish_x.run(argparse.Namespace(execute=True, limit=1))
            publish_x.run(argparse.Namespace(execute=True, limit=1))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(post_queue.load_queue()[0]["status"], "uncertain")

    def test_old_post_expires_without_publishing(self):
        items = post_queue.load_queue()
        items[0]["scheduled_at"] = (datetime.now(publish_x.TIMEZONE) - timedelta(hours=7)).isoformat()
        post_queue.save_queue(items)
        with patch.object(publish_x, "publish") as send:
            publish_x.run(argparse.Namespace(execute=True, limit=1))
        send.assert_not_called()
        self.assertEqual(post_queue.load_queue()[0]["status"], "expired")


class FounderRadarTests(unittest.TestCase):
    def item(self, title):
        return content_radar.FeedItem(title, "https://example.com", "", "", "test")

    def test_relevant_ai_product_story_beats_timeline_noise(self):
        self.assertGreaterEqual(founder_radar.score_item(self.item("Anthropic Claude model for software developers")), 5)
        self.assertLess(founder_radar.score_item(self.item("$4 to $80,000 trading challenge")), 5)
        self.assertLess(founder_radar.score_item(self.item("Counter-Strike game clip")), 5)
        self.assertLess(founder_radar.score_item(self.item("Government AI training program")), 5)
        self.assertLess(founder_radar.score_item(self.item("AI to repair PlayStation software")), 5)


class XRequestTests(unittest.TestCase):
    def test_request_uses_user_oauth_and_text_body(self):
        credentials = {
            "X_API_KEY": "key",
            "X_API_SECRET": "secret",
            "X_ACCESS_TOKEN": "user-token",
            "X_ACCESS_TOKEN_SECRET": "user-secret",
        }
        response = io.BytesIO(b'{"data":{"id":"456"}}')
        with patch.object(publish_x.urllib.request, "urlopen", return_value=response) as send:
            post_id = publish_x.publish("Um post de teste", credentials)
        request = send.call_args.args[0]
        self.assertEqual(post_id, "456")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://api.x.com/2/tweets")
        self.assertEqual(json.loads(request.data), {"text": "Um post de teste"})
        self.assertTrue(request.get_header("Authorization").startswith("OAuth "))


if __name__ == "__main__":
    unittest.main()
