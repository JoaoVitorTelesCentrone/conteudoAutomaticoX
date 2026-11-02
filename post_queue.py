"""Build a local review queue from a content_factory JSON pack."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
QUEUE_PATH = ROOT / ".post-queue" / "queue.json"
TIMEZONE = ZoneInfo("America/Sao_Paulo")
SLOTS = {
    "x": [(day, "09:00") for day in range(7)],
    "linkedin": [(0, "10:00"), (2, "10:00"), (4, "10:00")],
    "instagram": [(1, "12:00"), (3, "12:00")],
}


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7)


def load_queue() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Fila inválida: {QUEUE_PATH}")
    return data


def save_queue(items: list[dict]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = QUEUE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(QUEUE_PATH)


def build_items(pack_path: Path, channels: list[str], start: date) -> list[dict]:
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    candidates = {
        "x": [(text, [], False) for text in pack.get("x_posts", [])[:7]],
        "linkedin": [(text, [], False) for text in pack.get("linkedin_posts", [])[:3]],
        "instagram": [
            (carousel.get("caption", ""), carousel.get("slides", []), True)
            for carousel in pack.get("carousels", [])[:2]
        ],
    }
    result = []
    source = str(pack_path.resolve())
    for channel in channels:
        for index, ((day, hour), (text, slides, needs_media)) in enumerate(
            zip(SLOTS[channel], candidates[channel])
        ):
            if not isinstance(text, str) or not text.strip():
                continue
            scheduled = datetime.combine(start + timedelta(days=day), datetime.strptime(hour, "%H:%M").time(), TIMEZONE)
            post_id = hashlib.sha256(f"{source}|{start.isoformat()}|{channel}|{index}".encode()).hexdigest()[:12]
            result.append(
                {
                    "id": post_id,
                    "channel": channel,
                    "scheduled_at": scheduled.isoformat(),
                    "status": "draft",
                    "text": text.strip(),
                    "slides": slides,
                    "media_required": needs_media,
                    "media_paths": [],
                    "source_pack": source,
                    "source_index": index,
                }
            )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara e revisa uma fila local de posts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import", help="importa posts de um pacote JSON")
    import_parser.add_argument("pack", type=Path)
    import_parser.add_argument("--channels", nargs="+", choices=SLOTS, required=True)
    import_parser.add_argument("--start-date", type=date.fromisoformat, default=None, help="primeiro dia da semana (AAAA-MM-DD)")
    import_parser.add_argument("--auto", action="store_true", help="agenda posts para publicação automática")
    month_parser = subparsers.add_parser("import-month", help="importa o calendário de 300 posts do X")
    month_parser.add_argument("campaign", type=Path)
    month_parser.add_argument("--auto", action="store_true", help="marca para publicação automática")
    subparsers.add_parser("list", help="mostra a fila")
    status_parser = subparsers.add_parser("status", help="atualiza a revisão de um post")
    status_parser.add_argument("id")
    status_parser.add_argument("value", choices=["draft", "approved", "scheduled", "rejected"])
    args = parser.parse_args()

    if args.command == "import-month":
        if not args.campaign.is_file():
            parser.error(f"calendário não encontrado: {args.campaign}")
        campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
        if not isinstance(campaign, list) or len(campaign) != 300:
            parser.error("o calendário precisa conter exatamente 300 posts")
        if len({post.get("scheduled_at") for post in campaign}) != 300:
            parser.error("há horários duplicados no calendário")
        items = load_queue()
        existing = {item["id"]: item for item in items}
        scheduled_slots = {item["scheduled_at"] for item in items if item.get("channel") == "x" and item.get("status") == "scheduled"}
        new_items = []
        updated = 0
        for post in campaign:
            message = str(post.get("text", "")).strip()
            scheduled = str(post.get("scheduled_at", ""))
            if not message or len(message) > 280:
                parser.error(f"texto inválido no post {post.get('number')}")
            try:
                when = datetime.fromisoformat(scheduled)
            except ValueError:
                parser.error(f"data inválida no post {post.get('number')}")
            if when.tzinfo is None:
                parser.error(f"fuso ausente no post {post.get('number')}")
            post_id = hashlib.sha256(f"{args.campaign.resolve()}|{post['number']}".encode()).hexdigest()[:12]
            if post_id in existing:
                old = existing[post_id]
                if old.get("status") in {"draft", "scheduled"} and old.get("source_campaign") == str(args.campaign.resolve()):
                    if old.get("text") != message:
                        old["text"] = message
                        updated += 1
                continue
            if args.auto and scheduled in scheduled_slots:
                parser.error(f"já existe post agendado para {scheduled}")
            new_items.append({
                "id": post_id,
                "channel": "x",
                "scheduled_at": scheduled,
                "status": "scheduled" if args.auto else "draft",
                "text": message,
                "category": post.get("category", ""),
                "source_campaign": str(args.campaign.resolve()),
                "source_index": post["number"],
                "media_required": False,
                "media_paths": [],
            })
            scheduled_slots.add(scheduled)
        items.extend(new_items)
        save_queue(items)
        print(f"{len(new_items)} posts adicionados, {updated} atualizados em {QUEUE_PATH}")
    elif args.command == "import":
        if not args.pack.is_file():
            parser.error(f"pacote não encontrado: {args.pack}")
        start = args.start_date or next_monday(datetime.now(TIMEZONE).date())
        if start.weekday() != 0:
            parser.error("--start-date precisa ser uma segunda-feira")
        items = load_queue()
        existing = {item["id"] for item in items}
        new_items = [item for item in build_items(args.pack, list(dict.fromkeys(args.channels)), start) if item["id"] not in existing]
        if args.auto:
            pack = json.loads(args.pack.read_text(encoding="utf-8"))
            if not pack.get("_source_material_supplied"):
                parser.error("--auto exige pacote gerado com --source-file para apoiar relatos pessoais")
            for item in new_items:
                if item["media_required"]:
                    parser.error("publicação automática de carrossel ainda exige mídia")
                if item["channel"] == "x" and len(item["text"]) > 280:
                    parser.error(f"post {item['id']} excede 280 caracteres")
                if any(old.get("channel") == item["channel"] and old.get("scheduled_at") == item["scheduled_at"] and old.get("status") == "scheduled" for old in items):
                    parser.error(f"já existe post agendado para {item['scheduled_at']}")
                item["status"] = "scheduled"
        items.extend(new_items)
        save_queue(items)
        print(f"{len(new_items)} posts adicionados em {QUEUE_PATH}")
    elif args.command == "list":
        for item in sorted(load_queue(), key=lambda post: post["scheduled_at"]):
            print(f"{item['id']}  {item['scheduled_at']}  {item['channel']:<9} {item['status']:<8} {item['text'][:70].replace(chr(10), ' ')}")
    else:
        items = load_queue()
        for item in items:
            if item["id"] == args.id:
                if args.value == "approved" and item["media_required"] and not item["media_paths"]:
                    parser.error("adicione media_paths no JSON antes de aprovar este carrossel")
                item["status"] = args.value
                save_queue(items)
                print(f"{args.id}: {args.value}")
                return
        parser.error(f"post não encontrado: {args.id}")


if __name__ == "__main__":
    main()
