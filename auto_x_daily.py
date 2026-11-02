"""Prepare fifteen reviewed X posts for the following São Paulo day."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import content_radar
import founder_radar
from post_queue import load_queue, save_queue
from x_schedule import TIMEZONE, slots


def target_day():
    return datetime.now(TIMEZONE).date() + timedelta(days=1)


def pending_slots(queue: list[dict], day) -> list[datetime]:
    occupied = {
        item.get("scheduled_at")
        for item in queue
        if item.get("channel") == "x" and item.get("status") != "rejected"
    }
    return [slot for slot in slots(day) if slot.isoformat() not in occupied]


def main() -> None:
    content_radar.load_env()
    day = target_day()
    queue = load_queue()
    missing = pending_slots(queue, day)
    if not missing:
        print(f"Os 15 posts de {day} já estão agendados.")
        return

    sources = founder_radar.discover_items()
    known_texts = [item.get("text", "").strip() for item in queue if item.get("text")]
    generated = founder_radar.generate_posts(sources, len(missing), known_texts)
    for slot, candidate in zip(missing, generated, strict=True):
        post_text = candidate["post_text"]
        post_id = hashlib.sha256(f"radar|{slot.isoformat()}|{post_text}".encode()).hexdigest()[:12]
        queue.append({
            "id": post_id,
            "channel": "x",
            "scheduled_at": slot.isoformat(),
            "status": "scheduled",
            "text": post_text,
            "source_urls": candidate["source_urls"],
            "source_title": candidate["source_title"],
            "source": "founder_radar",
            "media_required": False,
            "media_paths": [],
        })
    save_queue(queue)
    used_urls = {url for candidate in generated for url in candidate["source_urls"]}
    founder_radar.mark_seen([item for item in sources if item.link in used_urls])
    print(f"{len(missing)} posts agendados para {day} ({len(slots(day))} no total).")


if __name__ == "__main__":
    main()
