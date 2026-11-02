"""Move the existing 300 X drafts into a fresh 20-day campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from x_schedule import TIMEZONE, slots


ROOT = Path(__file__).resolve().parent
CAMPAIGN = ROOT / "x-primeiro-mes-300.json"
STATE_QUEUE = ROOT / ".github" / "x-state" / "queue.json"


def schedule_campaign(queue: list[dict], campaign: list[dict], start: date) -> list[dict]:
    if len(campaign) != 300 or [post.get("number") for post in campaign] != list(range(1, 301)):
        raise ValueError("A campanha precisa conter os 300 posts numerados em ordem")
    texts = [post.get("text", "").strip() for post in campaign]
    if any(not text or len(text) > 280 for text in texts) or len(set(texts)) != 300:
        raise ValueError("A campanha contém texto vazio, longo ou repetido")

    campaign_slots = [slot for offset in range(20) for slot in slots(start + timedelta(days=offset))]
    occupied = {slot.isoformat() for slot in campaign_slots}
    if any(item.get("source") == "existing_300" and item.get("scheduled_at") in occupied for item in queue):
        raise ValueError("Esta campanha já foi importada")
    for item in queue:
        if item.get("channel") != "x" or item.get("scheduled_at") not in occupied:
            continue
        if item.get("status") != "scheduled":
            raise ValueError(f"Horário já usado por um post {item.get('status')}: {item['scheduled_at']}")
        item["status"] = "rejected"
        item["reason"] = "substituído pelo calendário de 300 posts"

    for source, slot in zip(campaign, campaign_slots, strict=True):
        post_id = hashlib.sha256(f"existing_300|{start}|{source['number']}".encode()).hexdigest()[:12]
        queue.append({
            "id": post_id,
            "channel": "x",
            "scheduled_at": slot.isoformat(),
            "status": "scheduled",
            "text": source["text"].strip(),
            "category": source.get("category", ""),
            "source": "existing_300",
            "source_index": source["number"],
            "media_required": False,
            "media_paths": [],
        })
    return queue


def main() -> None:
    parser = argparse.ArgumentParser(description="Agenda os 300 posts existentes em 20 dias")
    parser.add_argument("--start-date", type=date.fromisoformat,
                        default=datetime.now(TIMEZONE).date() + timedelta(days=1))
    args = parser.parse_args()
    campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    queue = json.loads(STATE_QUEUE.read_text(encoding="utf-8"))
    schedule_campaign(queue, campaign, args.start_date)
    STATE_QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"300 posts agendados de {args.start_date} a {args.start_date + timedelta(days=19)}")


if __name__ == "__main__":
    main()
