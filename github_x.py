"""Run the X pipeline in GitHub Actions with durable, committed state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import auto_x_daily
import content_radar
import founder_radar
import post_queue
import publish_x
from x_schedule import TIMEZONE, slots


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / ".github" / "x-state"
STATE_FILES = (
    (STATE_DIR / "queue.json", post_queue.QUEUE_PATH),
    (STATE_DIR / "founder-state.json", founder_radar.STATE_FILE),
)


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def restore_state() -> None:
    for committed, runtime in STATE_FILES:
        if not committed.is_file():
            raise FileNotFoundError(f"Estado versionado ausente: {committed}")
        data = json.loads(committed.read_text(encoding="utf-8"))
        if committed.name == "queue.json" and not isinstance(data, list):
            raise ValueError("A fila versionada precisa ser uma lista JSON")
        if committed.name == "founder-state.json" and not isinstance(data, dict):
            raise ValueError("O histórico versionado precisa ser um objeto JSON")
        runtime.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(committed, runtime)


def checkpoint() -> None:
    for committed, runtime in STATE_FILES:
        if runtime.is_file():
            shutil.copyfile(runtime, committed)
    paths = [str(path.relative_to(ROOT)) for path, _ in STATE_FILES]
    git("add", "--", *paths)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *paths], cwd=ROOT, check=False
    ).returncode
    if changed == 0:
        return
    if changed != 1:
        raise RuntimeError("Não foi possível verificar as alterações do estado")
    git(
        "-c", "user.name=x-automation[bot]",
        "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", "chore: save X automation state",
    )
    branch = os.environ["AUTOMATION_BRANCH"]
    git("push", "origin", f"HEAD:{branch}")


def prepare_publish_now(queue: list[dict], now: datetime) -> bool:
    """Move the first campaign post to now, keeping all future daily slots full."""
    previous = next((item for item in queue if item.get("manual_test")), None)
    if previous:
        if previous.get("status") == "published":
            print(f"Teste já publicado: https://x.com/i/status/{previous['x_post_id']}")
            return False
        raise RuntimeError("O teste já foi iniciado; confira o post no X e o estado da fila")

    campaign = sorted(
        (item for item in queue if item.get("source") == "existing_300" and item.get("status") == "scheduled"),
        key=lambda item: item["scheduled_at"],
    )
    if len(campaign) != 300:
        raise RuntimeError("O teste imediato só pode ser iniciado antes da campanha de 300 posts")
    planned = [item["scheduled_at"] for item in campaign]
    if datetime.fromisoformat(planned[0]) <= now:
        raise RuntimeError("A campanha já começou; use a operação publish para posts vencidos")
    replacement = next((
        item for item in queue
        if item.get("channel") == "x" and item.get("status") == "rejected"
        and item.get("reason") == "substituído pelo calendário de 300 posts"
    ), None)
    if replacement is None:
        raise RuntimeError("O post de reposição não foi encontrado; a agenda não foi alterada")

    first = campaign[0]
    first["manual_test"] = True
    first["original_scheduled_at"] = first["scheduled_at"]
    first["scheduled_at"] = (now - timedelta(seconds=1)).isoformat()
    for item, slot in zip(campaign[1:], planned[:-1], strict=True):
        item["scheduled_at"] = slot
    replacement["scheduled_at"] = planned[-1]
    replacement["status"] = "scheduled"
    replacement.pop("reason", None)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa geração ou publicação no GitHub Actions")
    parser.add_argument("operation", choices=("generate", "publish", "publish_now"))
    args = parser.parse_args()
    if os.getenv("GITHUB_ACTIONS") != "true":
        parser.error("Este comando só deve ser executado no GitHub Actions")
    if not os.getenv("AUTOMATION_BRANCH"):
        parser.error("AUTOMATION_BRANCH não configurada")

    restore_state()
    if args.operation == "generate":
        if not os.getenv("OPENAI_API_KEY", "").strip():
            parser.error("Configure OPENAI_API_KEY nos Secrets do repositório")
        auto_x_daily.main()
        checkpoint()
        day = auto_x_daily.target_day()
        scheduled = {
            item.get("scheduled_at")
            for item in post_queue.load_queue()
            if item.get("channel") == "x" and item.get("status") == "scheduled"
        }
        missing = [slot.isoformat() for slot in slots(day) if slot.isoformat() not in scheduled]
        if missing:
            raise RuntimeError(f"Faltam {len(missing)} posts agendados para {day}")
    elif args.operation == "publish_now":
        content_radar.load_env()
        publish_x.credentials_from_env()
        with publish_x.queue_lock():
            queue = post_queue.load_queue()
            if not prepare_publish_now(queue, datetime.now(TIMEZONE)):
                return
            post_queue.save_queue(queue)
            checkpoint()
            publish_x.run(argparse.Namespace(execute=True, limit=1), checkpoint=checkpoint)
    else:
        content_radar.load_env()
        publish_x.credentials_from_env()
        with publish_x.queue_lock():
            publish_x.run(argparse.Namespace(execute=True, limit=1), checkpoint=checkpoint)


if __name__ == "__main__":
    main()
