"""Publish due X posts from the local queue. Safe by default: use --execute to send."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import msvcrt
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Callable
from zoneinfo import ZoneInfo

import content_radar
from post_queue import QUEUE_PATH, load_queue, save_queue


POST_URL = "https://api.x.com/2/tweets"
TIMEZONE = ZoneInfo("America/Sao_Paulo")


@contextmanager
def queue_lock():
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with (QUEUE_PATH.parent / "publish.lock").open("a+b") as lock:
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Outra execução do publicador está em andamento") from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def encoded(value: str) -> str:
    return urllib.parse.quote(value, safe="~-._")


def oauth_header(credentials: dict[str, str]) -> str:
    params = {
        "oauth_consumer_key": credentials["X_API_KEY"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": credentials["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    parameter_string = "&".join(f"{encoded(key)}={encoded(value)}" for key, value in sorted(params.items()))
    signature_base = "&".join(["POST", encoded(POST_URL), encoded(parameter_string)])
    signing_key = f"{encoded(credentials['X_API_SECRET'])}&{encoded(credentials['X_ACCESS_TOKEN_SECRET'])}"
    signature = base64.b64encode(hmac.new(signing_key.encode(), signature_base.encode(), hashlib.sha1).digest()).decode()
    params["oauth_signature"] = signature
    return "OAuth " + ", ".join(f'{encoded(key)}="{encoded(value)}"' for key, value in sorted(params.items()))


def credentials_from_env() -> dict[str, str]:
    names = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
    result = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in result.items() if not value]
    if missing:
        raise RuntimeError("Configure no .env: " + ", ".join(missing))
    return result


def publish(text: str, credentials: dict[str, str]) -> str:
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        POST_URL,
        data=body,
        headers={"Authorization": oauth_header(credentials), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"X API HTTP {exc.code}: {detail[:500]}") from exc
    post_id = payload.get("data", {}).get("id")
    if not post_id:
        raise RuntimeError("X API não retornou o ID do post")
    return str(post_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publica no X os posts agendados e vencidos")
    parser.add_argument("--execute", action="store_true", help="envia de verdade; sem esta opção, apenas mostra")
    parser.add_argument("--limit", type=int, default=1, help="máximo de posts por execução (padrão: 1)")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit precisa ser positivo")

    with queue_lock():
        run(args)


def run(args: argparse.Namespace, checkpoint: Callable[[], None] | None = None) -> None:

    now = datetime.now(TIMEZONE)
    items = load_queue()
    expired = False
    for item in items:
        if item.get("channel") == "x" and item.get("status") == "scheduled":
            if datetime.fromisoformat(item["scheduled_at"]) < now - timedelta(hours=6):
                if args.execute:
                    item["status"] = "expired"
                    expired = True
    if expired:
        save_queue(items)
        if checkpoint:
            checkpoint()
    due = sorted(
        (
            item for item in items
            if item.get("channel") == "x"
            and item.get("status") == "scheduled"
            and datetime.fromisoformat(item["scheduled_at"]) >= now - timedelta(hours=6)
            and datetime.fromisoformat(item["scheduled_at"]) <= now
        ),
        key=lambda item: item["scheduled_at"],
    )[: args.limit]
    if not due:
        print("Nenhum post do X pendente para agora.")
        return
    if not args.execute:
        for item in due:
            print(f"TESTE {item['id']} {item['scheduled_at']}: {item['text']}")
        return

    content_radar.load_env()
    credentials = credentials_from_env()
    for item in due:
        # A request may succeed even if the local process then fails. Never retry automatically.
        item["status"] = "publishing"
        save_queue(items)
        if checkpoint:
            checkpoint()
        try:
            post_id = publish(item["text"], credentials)
        except Exception as exc:
            item["status"] = "uncertain"
            item["error"] = str(exc)
            save_queue(items)
            if checkpoint:
                checkpoint()
            raise RuntimeError(f"Falha no post {item['id']}; confira no X antes de reagendar") from exc
        item["status"] = "published"
        item["x_post_id"] = post_id
        item["published_at"] = datetime.now(TIMEZONE).isoformat()
        save_queue(items)
        if checkpoint:
            checkpoint()
        print(f"Publicado: https://x.com/i/status/{post_id}")


if __name__ == "__main__":
    main()
