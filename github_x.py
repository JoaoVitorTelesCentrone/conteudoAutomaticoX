"""Run the X pipeline in GitHub Actions with durable, committed state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, time, timedelta
from pathlib import Path

import auto_x_daily
import content_radar
import founder_radar
import post_queue
import publish_x


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa geração ou publicação no GitHub Actions")
    parser.add_argument("operation", choices=("generate", "publish"))
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
        now = datetime.now(auto_x_daily.TIMEZONE)
        slot = datetime.combine(now.date(), time(9), auto_x_daily.TIMEZONE)
        if slot <= now:
            slot += timedelta(days=1)
        if not any(
            item.get("channel") == "x"
            and item.get("scheduled_at") == slot.isoformat()
            and item.get("status") == "scheduled"
            for item in post_queue.load_queue()
        ):
            raise RuntimeError(f"Nenhum post foi agendado para {slot.isoformat()}")
    else:
        content_radar.load_env()
        publish_x.credentials_from_env()
        with publish_x.queue_lock():
            publish_x.run(argparse.Namespace(execute=True, limit=1), checkpoint=checkpoint)


if __name__ == "__main__":
    main()
