#!/usr/bin/env python3

import argparse
import logging
import sys
import re
import json
from openai import OpenAI
from src.config import supabase, settings  # supabase client and settings


def setup_logging(debug: bool = False):
    """Configura logging com nível DEBUG se solicitado."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Classificador macroeconômico com Function Calling via Chat API"
    )
    parser.add_argument(
        "-b", "--batch-size", type=int, default=100,
        help="Número máximo de itens a processar por vez"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Roda apenas um lote e encerra"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Habilita logging DEBUG"
    )
    return parser.parse_args()

# Palavras-chave macroeconômicas
KEYWORDS = [
    'PIB', 'JUROS', 'TARIFA', 'INFLAÇÃO', 'CÂMBIO',
    'SELIC', 'IPCA', 'IPAD', 'IGP', 'DESEMPREGO',
    'DÓLAR', 'ECONOMIA', 'CRÉDITO', 'TAXA',
    'GDP', 'INTEREST', 'INFLATION', 'EXCHANGE', 'RATE',
    'FED', 'ECB', 'UNEMPLOYMENT', 'CPI', 'PPI',
    'YIELD', 'STIMULUS', 'RECESSION', 'MONETARY', 'FISCAL', 'BOND', 'NOTES', 'PMI'
]
KW_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in KEYWORDS) + r")\b",
    flags=re.IGNORECASE
)

def extract_keywords(text: str) -> list[str]:
    return list({m.group(0).upper() for m in KW_PATTERN.finditer(text or "")})

# Definição da função para Function Calling
SENTIMENT_TOOL = [{
    "type": "function",
    "name": "record_sentiment",
    "description": "Registra sentimento macroeconômico e score",
    "parameters": {
        "type": "object",
        "properties": {
            "sentiment": {
                "type": "string",
                "enum": ["positivo", "neutro", "negativo"],
                "description": "Sentimento macroeconômico registrado"
            },
            "score": {
                "type": "number",
                "description": "Score associado ao sentimento"
            }
        },
        "additionalProperties": False
    },
}]

def classify_sentiment(client: OpenAI, text: str) -> tuple[str, float]:
    """
    Classifica sentimento com Function Calling.
    """
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
        {"role": "system", "content": (
            "Você é um analista de sentimento macroeconômico. "
            "Use a função record_sentiment para retornar apenas JSON com 'sentiment' e 'score'."
        )},
        {"role": "user", "content": text}
    ],
        functions=SENTIMENT_TOOL,  # type: ignore[arg-type]
        function_call={"name": "record_sentiment"},
        temperature=settings.OPENAI_TEMP,
        max_tokens=60,
        top_p=1,
    )

    message = response.choices[0].message
    if message.function_call and message.function_call.arguments:
        try:
            data = json.loads(message.function_call.arguments)
            return data.get("sentiment", "neutro"), float(data.get("score", 0.0))
        except json.JSONDecodeError:
            logging.warning(
                "Falha ao parsear argumentos da função: %r",
                message.function_call.arguments
            )
    return "neutro", 0.0

def run_filter(batch_size: int, debug: bool = False) -> int:
    """
    Executa o filtro macroeconômico e persiste em market_sentiment.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    # 1) Busca GUIDs já processados
    proc = supabase.table("market_sentiment").select("news_guid").execute()
    processed = {r["news_guid"] for r in (proc.data or [])}

    # 2) Prepara a consulta à cleaned_news_macro
    table = supabase.table("cleaned_news_macro").select(
        "guid, published_at, title_clean, body_clean"
    )
    #  — filtra todos os já processados, se existir ao menos um
    if processed:
        table = table.not_.in_("guid", list(processed))

    # 3) Puxa o batch
    resp = (
        table.order("published_at", desc=False)
             .limit(batch_size)
             .execute()
    )
    rows = resp.data or []
    if debug:
        logging.debug("Fetched %d rows: %s", len(rows), rows)
    if not rows:
        logging.info("Nenhum cleaned_news_macro para processar.")
        return 0

    # restante do laço de classificação…
    total = 0
    for r in rows:
        guid = r["guid"]
        text = f"{r.get('title_clean','')}\n\n{r.get('body_clean','')}"
        kws = extract_keywords(text)
        if not kws:
            if debug:
                logging.debug("Descartado %s sem keywords macro", guid)
            continue
        topic = kws[0].lower()
        label, score = classify_sentiment(client, text)
        if debug:
            logging.debug(
                "GUID %s → topic=%s → sentiment=%s score=%.2f",
                guid, topic, label, score
            )
        record = {
            "news_guid": guid,
            "published_at": r.get("published_at"),
            "topic": topic,
            "sentiment": score,
            "sentiment_label": label,
            "keywords": kws
        }
        up = supabase.table("market_sentiment").upsert(
            record, on_conflict="news_guid"
        ).execute()
        err = getattr(up, 'error', None)
        status = getattr(up, 'status_code', None)
        if err or (status and status >= 300):
            logging.error("Erro ao upsert market_sentiment: %s", err or "unknown error")
            sys.exit(1)
        total += 1

    logging.info("market_sentiment: %d itens processados", total)
    return total



def main():
    args = parse_args()
    setup_logging(args.debug)
    try:
        total = 0
        if args.once:
            total = run_filter(args.batch_size, args.debug)
        else:
            while True:
                count = run_filter(args.batch_size, args.debug)
                total += count
                if count < args.batch_size:
                    break
        logging.info("batch_processed=%d", total)
        sys.exit(0)
    except Exception:
        logging.exception("Erro na execução do sentiment_macro")
        sys.exit(1)

if __name__ == "__main__":
    main()
