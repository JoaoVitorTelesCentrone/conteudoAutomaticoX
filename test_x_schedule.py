import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import auto_x_daily
import founder_radar
import post_queue
import schedule_x_campaign
from x_schedule import slots


class CampaignScheduleTests(unittest.TestCase):
    def test_all_300_fill_20_days_and_replace_prior_draft(self):
        campaign = json.loads(schedule_x_campaign.CAMPAIGN.read_text(encoding="utf-8"))
        start = date(2026, 11, 3)
        original = {
            "id": "existing", "channel": "x", "status": "scheduled",
            "scheduled_at": slots(start)[1].isoformat(), "text": "Post gerado anteriormente",
        }
        queue = schedule_x_campaign.schedule_campaign([original], campaign, start)
        self.assertEqual(original["status"], "rejected")
        scheduled = [item for item in queue if item["status"] == "scheduled"]
        self.assertEqual(len(scheduled), 300)
        self.assertEqual(len({item["scheduled_at"] for item in scheduled}), 300)
        self.assertEqual(len({item["text"] for item in scheduled}), 300)
        for offset in range(20):
            day = start + timedelta(days=offset)
            self.assertEqual(
                {item["scheduled_at"] for item in scheduled if item["scheduled_at"][:10] == day.isoformat()},
                {slot.isoformat() for slot in slots(day)},
            )
        with self.assertRaisesRegex(ValueError, "já foi importada"):
            schedule_x_campaign.schedule_campaign(queue, campaign, start)

    def test_generator_skips_full_campaign_day(self):
        with tempfile.TemporaryDirectory() as temp:
            queue_path = Path(temp) / "queue.json"
            day = date(2026, 11, 4)
            with patch.object(post_queue, "QUEUE_PATH", queue_path), patch.object(
                auto_x_daily, "target_day", return_value=day
            ), patch.object(auto_x_daily.content_radar, "load_env"), patch.object(
                auto_x_daily.founder_radar, "discover_items"
            ) as discover:
                post_queue.save_queue([
                    {"channel": "x", "scheduled_at": slot.isoformat(), "status": "scheduled", "text": str(slot)}
                    for slot in slots(day)
                ])
                auto_x_daily.main()
                discover.assert_not_called()
                self.assertEqual(len(post_queue.load_queue()), 15)

    def test_generator_fills_only_missing_slots_once(self):
        with tempfile.TemporaryDirectory() as temp:
            queue_path = Path(temp) / "queue.json"
            day = date(2026, 11, 23)
            existing = {
                "channel": "x", "scheduled_at": slots(day)[0].isoformat(),
                "status": "scheduled", "text": "Texto anterior",
            }
            generated = [
                {"post_text": f"Novo texto diferente {number}", "source_urls": [], "source_title": ""}
                for number in range(14)
            ]
            with patch.object(post_queue, "QUEUE_PATH", queue_path), patch.object(
                auto_x_daily, "target_day", return_value=day
            ), patch.object(auto_x_daily.content_radar, "load_env"), patch.object(
                auto_x_daily.founder_radar, "discover_items", return_value=[]
            ), patch.object(auto_x_daily.founder_radar, "generate_posts", return_value=generated) as generate, patch.object(
                auto_x_daily.founder_radar, "mark_seen"
            ):
                post_queue.save_queue([existing])
                auto_x_daily.main()
                auto_x_daily.main()
                queue = post_queue.load_queue()
                generate.assert_called_once_with([], 14, ["Texto anterior"])
                self.assertEqual(len(queue), 15)
                self.assertEqual({item["scheduled_at"] for item in queue}, {slot.isoformat() for slot in slots(day)})

    def test_batch_rejects_repeated_ai_posts(self):
        repeated = "Um fluxo de IA precisa de um jeito claro de corrigir a resposta quando ela erra, senão o usuário perde tempo consertando o que deveria ajudar."
        with patch.dict("os.environ", {"OPENAI_API_KEY": "fake-key"}), patch.object(
            founder_radar, "_batch_response", return_value={"posts": [
                {"post_text": repeated, "source_url": ""} for _ in range(15)
            ]}
        ) as response:
            with self.assertRaisesRegex(ValueError, "não passou"):
                founder_radar.generate_posts([], 15, [])
        self.assertEqual(response.call_count, 3)


if __name__ == "__main__":
    unittest.main()
