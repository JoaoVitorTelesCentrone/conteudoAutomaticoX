"""Radar editorial da Broto Space.

Busca assuntos em feeds públicos, filtra pela estratégia da marca, usa a
Responses API para transformar os assuntos em pautas e envia um briefing ao
Telegram. O script usa apenas a biblioteca padrão do Python.
"""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / ".content-radar"
STATE_FILE = STATE_DIR / "state.json"

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q=produtividade+OR+%22organiza%C3%A7%C3%A3o+pessoal%22+OR+%22clareza+mental%22&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://news.google.com/rss/search?q=h%C3%A1bitos+OR+reflex%C3%A3o+OR+procrastina%C3%A7%C3%A3o+OR+%22sa%C3%BAde+mental%22&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://news.google.com/rss/search?q=IA+produtividade+OR+foco+OR+rotina+OR+bem-estar&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://hnrss.org/newest?q=productivity",
]

POSITIVE_TERMS = {
    "clareza": 5,
    "organização pessoal": 5,
    "organizacao pessoal": 5,
    "sobrecarga": 5,
    "hábitos": 4,
    "habitos": 4,
    "reflexão": 4,
    "reflexao": 4,
    "procrastinação": 4,
    "procrastinacao": 4,
    "foco": 3,
    "rotina": 3,
    "objetivo": 3,
    "objetivos": 3,
    "intencional": 4,
    "bem-estar": 4,
    "bem estar": 4,
    "journaling": 4,
    "pausa": 3,
    "autocuidado": 4,
    "ação": 3,
    "acao": 3,
    "atenção": 3,
    "atencao": 3,
    "ansiedade": 2,
    "decisão": 3,
    "decisao": 3,
    "pequeno passo": 5,
    "produtividade": 2,
}

NEGATIVE_TERMS = {
    "alta performance": 7,
    "produtividade máxima": 7,
    "produtividade maxima": 7,
    "mindset vencedor": 7,
    "hack milagroso": 7,
    "cura": 5,
    "milagre": 5,
    "guru": 3,
    "agronegócio": 10,
    "agronegocio": 10,
    "agropecuária": 10,
    "agropecuaria": 10,
    "safra": 10,
    "soja": 10,
    "milho": 8,
    "pecuária": 8,
    "pecuaria": 8,
    "produtividade industrial": 10,
}

BRAND_BRIEF = """
Você é estrategista editorial da Broto Space, uma plataforma brasileira de
clareza mental e ação intencional.

A Broto ajuda pessoas que têm pensamentos, ideias, preocupações e objetivos
acumulados a tirar isso da cabeça, dar nome ao que importa e escolher pequenos
próximos passos. É um espaço privado, calmo e humano para reflexões, ideias,
desafios, hábitos, revisitas e comunidade com desafio semanal.

Público: pessoas mentalmente sobrecarregadas que sabem que algo precisa mudar,
mas têm dificuldade de transformar pensamentos em ação.

Tom: íntimo, direto, acolhedor, inteligente e sem clichês de autoajuda.
Escreva em português do Brasil.

Evite: alta performance, produtividade máxima, virar sua melhor versão,
mindset vencedor, promessas milagrosas, culpa, diagnóstico médico e conselhos
clínicos. Não transforme notícias de saúde mental em orientação médica.

Vocabulário: broto, cultivar, clareza, pausa, pequeno passo, revisitar, dar
nome, movimento, processo, pensar com os pés no chão.
""".strip()


@dataclass
class FeedItem:
    title: str
    link: str
    summary: str
    published: str
    source: str
    score: int = 0


def load_env(path: Path = ROOT / ".env") -> None:
    """Carrega um .env simples sem substituir variáveis já existentes."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def clean_text(value: str | None, limit: int = 700) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", html.unescape(value))
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text.strip()
        found = element.find(f"{{*}}{name}")
        if found is not None and found.text:
            return found.text.strip()
    return ""


def link_from_element(element: ET.Element) -> str:
    link = child_text(element, ("link",))
    if link:
        return link
    for candidate in element.findall("{*}link"):
        href = candidate.attrib.get("href")
        if href:
            return href
    return ""


def parse_feed(xml_bytes: bytes, feed_url: str) -> list[FeedItem]:
    root = ET.fromstring(xml_bytes)
    entries = root.findall(".//item") or root.findall(".//{*}entry")
    items: list[FeedItem] = []
    for entry in entries:
        title = clean_text(child_text(entry, ("title",)), 300)
        link = link_from_element(entry)
        summary = clean_text(
            child_text(entry, ("description", "summary", "content")), 700
        )
        published = child_text(entry, ("pubDate", "published", "updated"))
        source = clean_text(child_text(entry, ("source",)), 120)
        if not source:
            source = urllib.parse.urlparse(feed_url).netloc
        if title and link:
            items.append(FeedItem(title, link, summary, published, source))
    return items


def fetch_feed(feed_url: str) -> list[FeedItem]:
    request = urllib.request.Request(
        feed_url,
        headers={
            "User-Agent": "BrotoSpaceContentRadar/1.0 (+https://www.brotospace.com/)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return parse_feed(response.read(), feed_url)


def published_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def score_item(item: FeedItem) -> int:
    text = f"{item.title} {item.summary}".lower()
    score = 0
    for term, weight in POSITIVE_TERMS.items():
        if term in text:
            score += weight
    for term, weight in NEGATIVE_TERMS.items():
        if term in text:
            score -= weight
    published = published_datetime(item.published)
    if published:
        age_hours = max(
            0, (datetime.now(timezone.utc) - published).total_seconds() / 3600
        )
        if age_hours <= 24:
            score += 4
        elif age_hours <= 72:
            score += 2
    if item.summary:
        score += 1
    return score


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"seen": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"seen": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def mark_items_seen(items: list[FeedItem]) -> None:
    state = load_state()
    seen = state.setdefault("seen", {})
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        key = item.link or item.title.lower()
        seen[key] = now
    save_state(state)


def discover_items() -> list[FeedItem]:
    feeds = [
        feed.strip()
        for feed in os.getenv("RSS_FEEDS", "").split("|")
        if feed.strip()
    ] or DEFAULT_FEEDS
    state = load_state()
    seen = state.setdefault("seen", {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    seen = {
        key: value
        for key, value in seen.items()
        if value and value > cutoff.isoformat()
    }
    state["seen"] = seen

    collected: list[FeedItem] = []
    for feed in feeds:
        try:
            collected.extend(fetch_feed(feed))
        except Exception as exc:  # noqa: BLE001 - uma fonte não deve parar o radar
            print(f"[aviso] não foi possível ler {feed}: {exc}", file=sys.stderr)

    unique: dict[str, FeedItem] = {}
    for item in collected:
        key = item.link or item.title.lower()
        if key in seen or key in unique:
            continue
        item.score = score_item(item)
        unique[key] = item

    relevance_threshold = int(os.getenv("RELEVANCE_THRESHOLD", "4"))
    ranked = sorted(
        (item for item in unique.values() if item.score >= relevance_threshold),
        key=lambda item: item.score,
        reverse=True,
    )
    selected = ranked[: int(os.getenv("MAX_RESEARCH_ITEMS", "12"))]
    save_state(state)
    return selected


def context_for_model(items: list[FeedItem]) -> str:
    payload = [
        {
            "title": item.title,
            "summary": item.summary,
            "source": item.source,
            "published": item.published,
            "url": item.link,
            "relevance_score": item.score,
        }
        for item in items
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def response_schema() -> dict[str, Any]:
    post = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "post_text": {"type": "string"},
            "source_urls": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "post_text",
            "source_urls",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "posts": {"type": "array", "minItems": 5, "maxItems": 5, "items": post},
        },
        "required": ["posts"],
    }


def extract_output_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    chunks: list[str] = []
    for output in data.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks)


def generate_recommendations(items: list[FeedItem]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "editor_note": "OPENAI_API_KEY não configurada; este é o ranking bruto para revisão manual.",
            "topics": [
                {
                    "title": item.title,
                    "why_now": f"Assunto encontrado em {item.source}.",
                    "broto_angle": "Conectar o assunto a clareza, pausa, pequeno passo ou revisita sem usar pressão.",
                    "format": "carrossel ou texto curto",
                    "draft_post": f"{item.title}. O que esse assunto faz você perceber sobre o seu próprio processo?",
                    "cta": "Convide a pessoa a compartilhar uma experiência real.",
                    "source_urls": [item.link],
                }
                for item in items[:5]
            ],
        }

    model = os.getenv("OPENAI_MODEL", "gpt-5.2")
    instructions = f"""{BRAND_BRIEF}

Sua tarefa é transformar as fontes abaixo em uma pauta editorial diária.
Escolha de 3 a 5 assuntos realmente úteis. Não copie títulos de notícia como
se fossem posts. Faça uma leitura e crie um ângulo original para a Broto.

Para cada pauta, escreva um rascunho curto e publicável, sem inventar dados,
sem afirmar que uma notícia prova uma tese e sem fazer aconselhamento clínico.
Se a fonte for ruim, sensacionalista ou desconectada da marca, descarte-a.
Priorize assuntos que geram a reação: “isso aconteceu comigo hoje”.
"""
    body = {
        "model": model,
        "instructions": instructions,
        "input": context_for_model(items),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "broto_content_radar",
                "strict": True,
                "schema": response_schema(),
            },
            "verbosity": "low",
        },
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        text = extract_output_text(data)
        return json.loads(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API retornou HTTP {exc.code}: {detail[:600]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"falha ao gerar pautas: {exc}") from exc


def generate_posts(items: list[FeedItem]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return generate_posts_without_ai(items)

    model = os.getenv("OPENAI_MODEL", "gpt-5.2")
    instructions = f"""{BRAND_BRIEF}

Você escreve para o perfil pessoal @joaocentrone, fundador da Broto Space.
A voz é de uma pessoa construindo um produto e compartilhando o que percebe no
dia a dia. Casual, direta, honesta e um pouco crua. Não escreva como marca,
copywriter, coach, assessoria de imprensa ou agência de social media.

Transforme as fontes em exatamente 5 posts prontos para X/Twitter. Use as
notícias só como faísca. O leitor não precisa perceber que o texto nasceu de
uma notícia. Entregue somente o texto final de cada post e as fontes usadas.

O que deixa o texto humano:
- uma ideia por post, escrita com palavras comuns e detalhes concretos;
- ritmo de conversa: frases curtas misturadas com frases mais longas;
- "pra", "tô" e fragmentos são permitidos quando soarem naturais;
- pode existir hesitação, incômodo, humor seco ou uma opinião de verdade;
- o post pode terminar sem lição, pergunta ou conclusão perfeita;
- no máximo 2 dos 5 posts terminam em pergunta;
- pelo menos 3 dos 5 conectam naturalmente com a Broto, uma funcionalidade ou
  uma decisão de produto, sem parecer anúncio;
- os demais constroem a visão de mundo do fundador sem vender nada;
- cada post deve ter entre 100 e 280 caracteres.

Evite completamente:
- "Talvez isso esteja acontecendo com você hoje";
- "Às vezes, o primeiro passo...";
- "Você não precisa...";
- "O problema não é X, é Y";
- "Ninguém fala sobre isso";
- "em um mundo cada vez mais";
- "comente abaixo", "o que você acha?" e pedidos artificiais de engajamento;
- sequência de frases com a mesma estrutura;
- hashtags, emojis decorativos, tom professoral e vocabulário corporativo;
- repetir clareza, processo, movimento e pequeno passo em todos os textos;
- inventar experiências pessoais, números ou fatos que não estejam nas fontes.
- usar notícia de agricultura, indústria, mercado financeiro ou desempenho de
  empresas só porque o título contém a palavra "produtividade";
- criar metáfora forçada para aproveitar uma fonte que não tem relação humana
  direta com sobrecarga mental, ideias, hábitos, reflexão ou ação intencional.

Primeira pessoa pode aparecer em opiniões reais como "eu acho", "pra mim" ou
"isso me incomoda". Não invente cliente, conversa, teste, resultado ou episódio
da vida do João. Se uma fonte não render um texto excelente, ignore-a e use um
ângulo melhor de outra fonte. Qualidade vale mais que cobrir todas as notícias.

Referências de voz. Capture a naturalidade, não copie as frases:
1. "abri minhas notas pra organizar uma ideia e encontrei outras 47 me cobrando atenção. chega uma hora em que anotar tudo só muda a bagunça de lugar."
2. "eu comecei a Broto por um motivo bem menos grandioso do que parece: precisava parar de usar a cabeça como caixa de entrada."
3. "tem pensamento que ocupa a semana inteira só porque a gente ainda não conseguiu dar um nome pra ele."
4. "qual foi a última ideia que você anotou e realmente revisitou?"

Antes de responder, releia os 5 posts e reescreva qualquer um que pareça frase
motivacional, anúncio, legenda genérica ou texto produzido por IA.
"""
    body = {
        "model": model,
        "instructions": instructions,
        "input": context_for_model(items),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "broto_ready_posts",
                "strict": True,
                "schema": response_schema(),
            },
            "verbosity": "low",
        },
        "reasoning": {"effort": "low"},
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        return json.loads(extract_output_text(data))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API retornou HTTP {exc.code}: {detail[:600]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"falha ao gerar posts: {exc}") from exc


def generate_posts_without_ai(items: list[FeedItem]) -> dict[str, Any]:
    return {
        "posts": [
            {
                "post_text": (
                    f"li sobre {item.title.lower()} e fiquei com isso na cabeça. "
                    "tem coisa que a gente não resolve fazendo mais. primeiro precisa "
                    "entender o que está pedindo atenção."
                ),
                "source_urls": [item.link],
            }
            for item in items[:5]
        ]
    }


def render_ready_posts(recommendations: dict[str, Any], items: list[FeedItem]) -> str:
    date = datetime.now().astimezone().strftime("%d/%m/%Y")
    posts = recommendations.get("posts", [])
    lines = [
        f"🌱 POSTS DE HOJE — {date}",
        "",
        "prontos pra copiar e postar:",
        "",
    ]
    for index, post in enumerate(posts, start=1):
        lines.extend(
            [
                f"{index}.\n{post.get('post_text', '').strip()}",
            ]
        )
        lines.append("")
    if not posts:
        lines.extend(
            [
                "Nenhum post passou pelo filtro hoje.",
                "Fontes consultadas: " + str(len(items)),
            ]
        )
    return "\n".join(lines).strip()


def render_digest(recommendations: dict[str, Any], items: list[FeedItem]) -> str:
    return render_ready_posts(recommendations, items)


def render_digest_legacy(recommendations: dict[str, Any], items: list[FeedItem]) -> str:
    date = datetime.now().astimezone().strftime("%d/%m/%Y")
    lines = [
        f"🌱 RADAR DA BROTO — {date}",
        "",
        recommendations.get("editor_note", ""),
        "",
    ]
    for index, topic in enumerate(recommendations.get("topics", []), start=1):
        lines.extend(
            [
                f"{index}. {topic.get('title', '').strip()}",
                f"Por que agora: {topic.get('why_now', '').strip()}",
                f"Ângulo Broto: {topic.get('broto_angle', '').strip()}",
                f"Formato: {topic.get('format', '').strip()}",
                f"Rascunho:\n{topic.get('draft_post', '').strip()}",
                f"CTA: {topic.get('cta', '').strip()}",
            ]
        )
        sources = topic.get("source_urls", [])
        if sources:
            lines.append("Fontes: " + " | ".join(sources[:3]))
        lines.append("")
    if not recommendations.get("topics"):
        lines.extend(
            [
                "Nenhuma pauta passou pelo filtro hoje.",
                "Fontes consultadas: " + str(len(items)),
            ]
        )
    return "\n".join(lines).strip()


def telegram_send(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID precisam estar configurados")

    chunks: list[str] = []
    remaining = message
    while len(remaining) > 3900:
        cut = remaining.rfind("\n\n", 0, 3900)
        cut = cut if cut > 0 else remaining.rfind("\n", 0, 3900)
        cut = cut if cut > 0 else 3900
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in chunks:
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": chunk}).encode("utf-8")
        request = urllib.request.Request(endpoint, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not data.get("ok"):
                raise RuntimeError(str(data))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram API retornou HTTP {exc.code}: {detail[:500]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Envia o radar editorial da Broto ao Telegram")
    parser.add_argument("--dry-run", action="store_true", help="não envia; imprime o briefing")
    parser.add_argument("--no-ai", action="store_true", help="não chama a IA; usa o ranking bruto")
    args = parser.parse_args()
    load_env()

    items = discover_items()
    if not items:
        print("Nenhum assunto relevante encontrado hoje.")
        return 0

    recommendations = (
        generate_posts(items)
        if not args.no_ai
        else generate_posts_without_ai(items)
    )
    digest = render_digest(recommendations, items)
    if args.dry_run:
        print(digest)
        return 0
    telegram_send(digest)
    mark_items_seen(items)
    print(f"Posts enviados ao Telegram: {len(recommendations.get('posts', []))}.")
    return 0


def generate_recommendations_without_ai(items: list[FeedItem]) -> dict[str, Any]:
    return {
        "editor_note": "Ranking de fontes sem geração automática. Use como fila de pesquisa.",
        "topics": [
            {
                "title": item.title,
                "why_now": "Assunto recente encontrado no radar.",
                "broto_angle": "Perguntar o que isso revela sobre clareza, pausa, hábito ou pequeno passo.",
                "format": "carrossel ou texto para LinkedIn",
                "draft_post": f"{item.title}. Isso aparece de que forma na sua rotina?",
                "cta": "Convide uma resposta com uma experiência concreta.",
                "source_urls": [item.link],
            }
            for item in items[:5]
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
