"""Find a fresh topic and queue one X post for the next 09:00 slot."""

from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import content_radar
import founder_radar
from post_queue import load_queue, save_queue


TIMEZONE = ZoneInfo("America/Sao_Paulo")


def main() -> None:
    content_radar.load_env()
    now = datetime.now(TIMEZONE)
    slot = datetime.combine(now.date(), time(9), TIMEZONE)
    if slot <= now:
        slot += timedelta(days=1)

    queue = load_queue()
    if any(item.get("channel") == "x" and item.get("scheduled_at") == slot.isoformat() and item.get("status") != "rejected" for item in queue):
        print(f"Já existe um post para {slot.isoformat()}.")
        return

    sources = founder_radar.discover_items()
    if not sources:
        print("Nenhuma pauta nova passou pelo filtro editorial.")
        return
    generated = founder_radar.generate_post(sources)
    known_texts = {item.get("text", "").strip() for item in queue}
    for candidate in [generated]:
        post_text = candidate.get("post_text", "").strip()
        if not post_text or len(post_text) > 280 or post_text in known_texts:
            continue
        post_id = hashlib.sha256(f"radar|{slot.isoformat()}|{post_text}".encode()).hexdigest()[:12]
        queue.append(
            {
                "id": post_id,
                "channel": "x",
                "scheduled_at": slot.isoformat(),
                "status": "scheduled",
                "text": post_text,
                "source_urls": candidate.get("source_urls", []),
                "source_title": candidate.get("source_title", ""),
                "source": "founder_radar",
                "media_required": False,
                "media_paths": [],
            }
        )
        save_queue(queue)
        founder_radar.mark_seen([item for item in sources if item.link in candidate.get("source_urls", [])])
        print(f"Post {post_id} agendado para {slot.isoformat()}.")
        return
    print("Nenhum post novo e válido foi gerado; nada agendado.")


if __name__ == "__main__":
    main()
