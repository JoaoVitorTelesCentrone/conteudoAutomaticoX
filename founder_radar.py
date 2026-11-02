"""Curated topic discovery and X copy for João's founder profile."""

from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import content_radar


ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".content-radar" / "founder-state.json"
FEEDS = [
    "https://news.google.com/rss/search?q=%22intelig%C3%AAncia+artificial%22+%22software%22+OR+%22produto+digital%22+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://news.google.com/rss/search?q=SaaS+startup+%22intelig%C3%AAncia+artificial%22+OR+%22desenvolvedor%22+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://hnrss.org/frontpage?q=AI%20agents",
    "https://hnrss.org/frontpage?q=developer%20tools",
]
POSITIVE = {
    "saas": 6,
    "software": 5,
    "developer": 5,
    "desenvolvedor": 5,
    "produto digital": 5,
    "product management": 5,
    "onboarding": 5,
    "open source": 4,
    "agent": 4,
    "agente": 4,
    "llm": 4,
    "inteligência artificial": 4,
    "inteligencia artificial": 4,
    "generative ai": 4,
    "startup": 3,
    "automação": 3,
    "automacao": 3,
    "api": 3,
    "model": 2,
    "modelo": 2,
    "claude": 4,
    "anthropic": 4,
    "openai": 4,
    "copilot": 4,
}
NEGATIVE = {
    "crypto": 12,
    "criptomoeda": 12,
    "trading": 12,
    "futures trader": 12,
    "aposta": 12,
    "ganhe dinheiro": 12,
    "eleição": 10,
    "eleicao": 10,
    "candidato": 10,
    "futebol": 10,
    "esports": 10,
    "counter-strike": 10,
    "jogo": 7,
    "meme": 7,
    "celebridade": 7,
    "clinic": 6,
    "clínica": 6,
}
COPY_CLICHES = (
    "compliance", "ecossistema", "diferencial", "alavancar", "impulsionar",
    "revolucionar", "prioridade:", "estratégia:", "vira demo",
)
BUILDER_ANCHORS = (
    "saas", "software", "developer", "desenvolvedor", "produto", "product",
    "onboarding", "open source", "agent", "agente",
    "claude", "anthropic", "openai", "copilot", "startup",
)
EXCLUDED_CONTEXT = (
    "playstation", "xbox", "counter-strike", "esports", "videogame",
    "trading", "casino", "aposta", "eleição", "election",
)


def score_item(item: content_radar.FeedItem) -> int:
    text = f"{item.title} {item.summary}".lower()
    if any(term in text for term in EXCLUDED_CONTEXT):
        return 0
    if not any(anchor in text for anchor in BUILDER_ANCHORS) and not re.search(r"\b(api|llm)\b", text):
        return 0
    topical = sum(weight for term, weight in POSITIVE.items() if term in text)
    if re.search(r"\bai\b", text):
        topical += 4
    if topical == 0:
        return 0
    score = topical - sum(weight for term, weight in NEGATIVE.items() if term in text)
    published = content_radar.published_datetime(item.published)
    if published and published >= datetime.now(timezone.utc) - timedelta(days=3):
        score += 2
    return score


def load_seen() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def mark_seen(items: list[content_radar.FeedItem]) -> None:
    seen = load_seen()
    timestamp = datetime.now(timezone.utc).isoformat()
    for item in items:
        seen[item.link or item.title.lower()] = timestamp
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_items() -> list[content_radar.FeedItem]:
    seen = load_seen()
    collected = []
    for feed in FEEDS:
        try:
            collected.extend(content_radar.fetch_feed(feed))
        except Exception as exc:
            print(f"[aviso] fonte indisponível: {exc}")
    unique = {}
    for item in collected:
        key = item.link or item.title.lower()
        if key in seen or key in unique:
            continue
        if item.title.lower().startswith("show hn:"):
            continue
        published = content_radar.published_datetime(item.published)
        if published and published < datetime.now(timezone.utc) - timedelta(days=7):
            continue
        item.score = score_item(item)
        if item.score >= 5:
            unique[key] = item
    return sorted(unique.values(), key=lambda item: item.score, reverse=True)[:8]


def generate_post(items: list[content_radar.FeedItem]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY precisa estar configurada")
    profile = json.loads((ROOT / "content-profile.json").read_text(encoding="utf-8"))
    sources = [
        {"title": item.title, "summary": item.summary[:500], "url": item.link, "source": item.source}
        for item in items
    ]
    instructions = f"""Escreva exatamente um post para o perfil pessoal @{profile['creator']['handle'].lstrip('@')}.
Posicionamento: {profile['creator']['positioning']}
Público: fundadores e pessoas que constroem software com IA.
Pilares: IA aplicada a produto, decisões de SaaS, qualidade de software, distribuição e clareza para agir.

Escolha a fonte mais relevante e extraia UMA observação específica para quem constrói produto.
O post tem de 120 a 220 caracteres, em português brasileiro falado, com no máximo duas frases. Não faça lista nem use dois-pontos.
Evite generalizações como "IA barateia criar software". Mostre uma tarefa, decisão ou atrito concreto de quem constrói software.
Não use jargões como "compliance", "ecossistema", "diferencial", "canais", "estratégia", "prioridade" ou "parcerias".
Referências de naturalidade (não copie):
- "Modelo novo é legal. O teste que vale pra quem constrói produto é abrir um bug real e ver se ele ajuda sem criar mais dois."
- "IA em produto fica interessante quando diminui uma tarefa chata do usuário. Se só deixa a demo mais bonita, ainda falta trabalho de produto."
Não use hashtag, emoji, CTA ou manchete reescrita.
Não use primeira pessoa (eu, meu, minha, nós, me, comigo). Não invente experiência, conversa, número ou resultado do João.
Não repita uma afirmação factual da fonte sem ter apoio no título ou resumo fornecido. Se a fonte só relata uma alegação, trate-a como alegação.
Use a notícia como ponto de partida para uma observação sobre trabalho de produto. Evite citar nomes de empresas, modelos e lançamentos no post.
Não publique promessa de dinheiro rápido, apostas, política, esportes, memes ou anúncio de terceiros.
Mencione Broto Space somente se houver conexão direta com clareza mental, revisão de ideias ou ação intencional; não force propaganda.
Devolva também a URL exata da fonte escolhida."""
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "instructions": instructions,
        "input": json.dumps(sources, ensure_ascii=False),
        "reasoning": {"effort": "low"},
        "text": {
            "format": {
                "type": "json_schema",
                "name": "founder_x_post",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "post_text": {"type": "string"},
                        "source_url": {"type": "string"},
                    },
                    "required": ["post_text", "source_url"],
                },
            }
        },
        "store": False,
    }
    source_by_url = {item.link: item for item in items}
    issue = ""
    for attempt in range(2):
        if attempt:
            body["instructions"] = instructions + f"\n\nA tentativa anterior foi rejeitada: {issue}. Reescreva com uma única ideia concreta e português natural."
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenAI API HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}") from exc
        generated = json.loads(content_radar.extract_output_text(result))
        text = generated["post_text"].strip()
        source_url = generated["source_url"].strip()
        valid = (
            120 <= len(text) <= 220
            and text.count(":") == 0
            and not re.search(r"\b(eu|meu|minha|meus|minhas|nós|me|comigo)\b", text, re.IGNORECASE)
            and not any(term in text.lower() for term in COPY_CLICHES)
            and source_url in source_by_url
        )
        if not valid:
            issue = "tamanho, fonte, primeira pessoa ou linguagem artificial"
            continue
        approved, issue = review_post(text, source_by_url[source_url], api_key)
        if approved:
            return {"post_text": text, "source_urls": [source_url], "source_title": source_by_url[source_url].title}
    raise ValueError("Post gerado não passou na revisão automática de voz e fonte")


def review_post(text: str, source: content_radar.FeedItem, api_key: str) -> tuple[bool, str]:
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "instructions": (
            "Você é um editor rigoroso do perfil de um fundador brasileiro de SaaS. "
            "Aprove só texto que soe como português falado, tenha uma ideia específica "
            "e seja útil para quem constrói software com IA. Rejeite sintaxe truncada, "
            "tradução literal, enumeração de jargões, conselho genérico, promoção de "
            "ferramenta de terceiros e qualquer afirmação factual que não esteja apoiada "
            "pelo título ou resumo da fonte. Rejeite posts que repitam nomes de "
            "empresas ou anúncios em vez de extrair uma observação de produto. "
            "Na dúvida, rejeite. Responda com uma "
            "justificativa curta e concreta."
        ),
        "input": json.dumps({"post": text, "source_title": source.title, "source_summary": source.summary[:500]}, ensure_ascii=False),
        "reasoning": {"effort": "low"},
        "text": {
            "format": {
                "type": "json_schema",
                "name": "founder_x_quality_review",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"approved": {"type": "boolean"}, "issue": {"type": "string"}},
                    "required": ["approved", "issue"],
                },
            }
        },
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI API HTTP {exc.code} na revisão") from exc
    verdict = json.loads(content_radar.extract_output_text(result))
    return bool(verdict["approved"]), str(verdict["issue"])


def _batch_response(api_key: str, name: str, schema: dict[str, Any], instructions: str, data: Any) -> Any:
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "instructions": instructions,
        "input": json.dumps(data, ensure_ascii=False),
        "reasoning": {"effort": "low"},
        "max_output_tokens": 6500,
        "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}") from exc
    return json.loads(content_radar.extract_output_text(result))


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _similar(first: str, second: str) -> bool:
    a, b = _normalized(first), _normalized(second)
    if a == b or SequenceMatcher(None, a, b).ratio() >= 0.82:
        return True
    words_a, words_b = set(a.split()), set(b.split())
    return bool(words_a and words_b and len(words_a & words_b) / len(words_a | words_b) >= 0.70)


def generate_posts(items: list[content_radar.FeedItem], count: int, known_texts: list[str]) -> list[dict[str, Any]]:
    """Generate a reviewed, distinct batch; never return a partial day."""
    if count < 1 or count > 15:
        raise ValueError("count precisa estar entre 1 e 15")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY precisa estar configurada")
    profile = json.loads((ROOT / "content-profile.json").read_text(encoding="utf-8"))
    source_by_url = {item.link: item for item in items if item.link}
    sources = [
        {"title": item.title, "summary": item.summary[:500], "url": item.link}
        for item in items
    ]
    post_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"post_text": {"type": "string"}, "source_url": {"type": "string"}},
        "required": ["post_text", "source_url"],
    }
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"posts": {"type": "array", "items": post_schema}},
        "required": ["posts"],
    }
    instructions = f"""Crie exatamente {count} posts diferentes para @{profile['creator']['handle'].lstrip('@')}, em português brasileiro natural.
Público: fundadores e pessoas que constroem SaaS e software com IA. Pilares: IA em produto, qualidade, experiência do usuário, distribuição, decisões de fundador e clareza para agir.
Cada post deve ter 120 a 220 caracteres e no máximo duas frases. Varie os temas e as estruturas; cada texto precisa de uma observação concreta e útil, sem fórmula repetida.
No máximo 5 posts podem comentar notícias. Para esses, escolha URLs distintas da lista de fontes e use a notícia apenas como ponto de partida para uma observação de produto. Os demais são ideias atemporais e devem usar source_url vazio.
Não invente fatos, resultados, números, experiências pessoais, citações ou funcionalidades. Evite primeira pessoa, hashtag, emoji, CTA, pergunta genérica, propaganda e manchete reescrita. Não use dois-pontos nem jargões corporativos.
Não copie nem parafraseie os textos anteriores. Responda somente com os {count} objetos solicitados."""
    payload = {"sources": sources, "recent_posts": known_texts[-60:]}
    issue = ""
    for attempt in range(3):
        prompt = instructions + (f"\nA tentativa anterior falhou: {issue}. Corrija todos os posts." if attempt else "")
        generated = _batch_response(api_key, "founder_x_daily_batch", schema, prompt, payload)
        posts = generated.get("posts", []) if isinstance(generated, dict) else []
        if len(posts) != count:
            issue = f"foram gerados {len(posts)} posts; exigidos {count}"
            continue
        accepted: list[dict[str, Any]] = []
        for candidate in posts:
            text = candidate.get("post_text", "").strip() if isinstance(candidate, dict) else ""
            source_url = candidate.get("source_url", "").strip() if isinstance(candidate, dict) else ""
            if (
                not 120 <= len(text) <= 220
                or ":" in text or "#" in text
                or re.search(r"\b(eu|meu|minha|meus|minhas|nós|me|comigo)\b", text, re.IGNORECASE)
                or any(term in text.lower() for term in COPY_CLICHES)
                or (source_url and source_url not in source_by_url)
                or any(_similar(text, old) for old in known_texts)
                or any(_similar(text, old["post_text"]) for old in accepted)
            ):
                issue = "tamanho, linguagem, fonte ou texto parecido com outro post"
                break
            accepted.append({
                "post_text": text,
                "source_urls": [source_url] if source_url else [],
                "source_title": source_by_url[source_url].title if source_url else "",
            })
        if len(accepted) != count:
            continue
        used_sources = [post["source_urls"][0] for post in accepted if post["source_urls"]]
        if len(used_sources) > 5 or len(set(used_sources)) != len(used_sources):
            issue = "mais de cinco notícias ou uma fonte repetida"
            continue
        review_schema = {
            "type": "object", "additionalProperties": False,
            "properties": {"approved": {"type": "boolean"}, "issue": {"type": "string"}},
            "required": ["approved", "issue"],
        }
        review_data = [
            {"post": post["post_text"], "source": {
                "title": source_by_url[post["source_urls"][0]].title,
                "summary": source_by_url[post["source_urls"][0]].summary[:500],
            } if post["source_urls"] else None}
            for post in accepted
        ]
        verdict = _batch_response(
            api_key, "founder_x_batch_review", review_schema,
            "Revise rigorosamente TODOS os posts para um fundador brasileiro. Aprove só se todos forem distintos, "
            "naturais, específicos e úteis, sem fatos inventados ou alegações pessoais. Se um post usar notícia, "
            "confirme que qualquer fato citado tem apoio no título ou resumo. Rejeite publicidade, repetição "
            "de tema ou estrutura e linguagem artificial. Na dúvida, rejeite. Explique o problema em poucas palavras.",
            review_data,
        )
        if verdict.get("approved") is True:
            return accepted
        issue = str(verdict.get("issue", "revisão rejeitou o lote"))[:300]
    raise ValueError(f"Lote de posts não passou na revisão automática: {issue}")
