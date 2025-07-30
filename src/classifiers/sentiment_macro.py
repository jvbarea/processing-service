#!/usr/bin/env python3

import argparse
import logging
import sys
import re
import json
from datetime import datetime, timezone
from openai import OpenAI
from src.config import supabase, settings, get_last_run_time, set_last_run_time

# Palavras-chave macroeconômicas
KEYWORDS = [
    'PIB', 'JUROS', 'TARIFA', 'INFLAÇÃO', 'CÂMBIO',
    'SELIC', 'IPCA', 'IPAD', 'IGP', 'DESEMPREGO',
    'DÓLAR', 'ECONOMIA', 'CRÉDITO', 'TAXA',
    'GDP', 'INTEREST', 'INFLATION', 'EXCHANGE', 'RATE',
    'FED', 'ECB', 'UNEMPLOYMENT', 'CPI', 'PPI',
    'YIELD', 'STIMULUS', 'RECESSION', 'MONETARY', 'FISCAL',
    'BOND', 'NOTES', 'PMI'
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
                "description": "Sentimento macroeconômico"
            },
            "score": {
                "type": "number",
                "description": "Score entre -1 e 1"
            }
        },
        "required": ["sentiment", "score"],
        "additionalProperties": False
    }
}]

def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def parse_args():
    parser = argparse.ArgumentParser(
        description="Classificador macroeconômico com Function Calling via OpenAI"
    )
    parser.add_argument(
        "-b", "--batch-size", type=int, default=100,
        help="Máximo de notícias por execução"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Executa apenas um lote e encerra"
    )
    parser.add_argument(
        "--backfill", action="store_true",
        help="Ignora watermark e processa histórico"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Habilita logs DEBUG"
    )
    return parser.parse_args()

def classify_sentiment(client: OpenAI, text: str) -> tuple[str, float]:
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role":"system","content":(
                "Você é um analista de sentimento macroeconômico. "
                "Use a função record_sentiment para retornar JSON com 'sentiment' e 'score'."
            )},
            {"role":"user","content":text}
        ],
        functions=SENTIMENT_TOOL, # type: ignore[arg-type]
        function_call={"name":"record_sentiment"},
        temperature=settings.OPENAI_TEMP,
        max_tokens=60,
        top_p=1
    )
    msg = resp.choices[0].message
    if msg.function_call and msg.function_call.arguments:
        try:
            data = json.loads(msg.function_call.arguments)
            return data.get("sentiment","neutro"), float(data.get("score",0.0))
        except json.JSONDecodeError:
            logging.warning("JSON inválido do function_call: %r", msg.function_call.arguments)
    return "neutro", 0.0

def run_filter(batch_size: int, debug: bool=False, backfill: bool=False) -> int:
    """
    Processa até `batch_size` notícias de cleaned_news_macro,
    usando watermark (se não backfill) e flush a cada 1.000 registros.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    # 1) GUIDs já processados
    proc = supabase.table("market_sentiment").select("news_guid").execute()
    processed = {r["news_guid"] for r in (proc.data or [])}
    if debug:
        logging.debug("GUIDs processados previamente: %d", len(processed))

    # 2) Watermark incremental
    last_run = None if backfill else get_last_run_time("sentiment_macro")

    # 3) Monta query inicial
    table = supabase.table("cleaned_news_macro")\
                    .select("guid,published_at,title_clean,body_clean")
    if last_run:
        table = table.gt("published_at", last_run)

    total = 0
    record_idx = 0
    all_records: list[dict] = []

    # Função interna de flush
    def flush_batch(records):
        if not records:
            return
        start = flush_batch.start_idx + 1
        end   = flush_batch.start_idx + len(records)
        logging.info("Inserindo batch %d–%d", start, end)
        resp_up = supabase.table("market_sentiment")\
                         .upsert(records, on_conflict="news_guid")\
                         .execute()
        err = getattr(resp_up, "error", None)
        st  = getattr(resp_up, "status_code", None)
        if err or (st and st >= 300):
            logging.error("Falha upsert %d–%d: %s", start, end, err or st)
            sys.exit(1)
        flush_batch.start_idx += len(records)
        records.clear()

    flush_batch.start_idx = 0

    # 4) Página única de até batch_size
    resp = table.order("published_at", desc=False)\
                .limit(batch_size).execute()
    rows = resp.data or []
    if debug:
        logging.debug("Recebidas %d linhas para classificação", len(rows))
    if not rows:
        logging.info("Nenhuma notícia nova para processar.")
        return 0

    for r in rows:
        guid = r["guid"]
        if guid in processed:
            continue

        text = f"{r.get('title_clean','')}\n\n{r.get('body_clean','')}"
        kws = extract_keywords(text)
        if not kws:
            if debug:
                logging.debug("Descartado %s sem keywords", guid)
            processed.add(guid)
            continue

        topic = kws[0].lower()
        label, score = classify_sentiment(client, text)

        # Consistência do label
        if score > 0.1:
            label = "positivo"
        elif score < -0.1:
            label = "negativo"
        else:
            label = "neutro"

        record_idx += 1
        if debug:
            logging.debug(
                "Record %d: topic=%s, score=%.3f, label=%s",
                record_idx, topic, score, label
            )

        all_records.append({
            "news_guid":       guid,
            "published_at":    r.get("published_at"),
            "topic":           topic,
            "sentiment":       score,
            "sentiment_label": label,
            "keywords":        kws
        })
        total += 1
        processed.add(guid)

        # Flush a cada 1000
        if len(all_records) >= 10:
            flush_batch(all_records)

    # 5) Flush final
    flush_batch(all_records)

    # 6) Atualiza watermark se não backfill
    if not backfill:
        set_last_run_time("sentiment_macro", datetime.now(timezone.utc))

    logging.info("Total market_sentiment processados: %d", total)
    return total

def main():
    args = parse_args()
    setup_logging(args.debug)
    try:
        total = 0
        if args.once:
            total = run_filter(args.batch_size, args.debug, args.backfill)
        else:
            while True:
                count = run_filter(args.batch_size, args.debug, args.backfill)
                total += count
                if count < args.batch_size:
                    break
        logging.info("batch_processed=%d", total)
        sys.exit(0)
    except Exception:
        logging.exception("Erro em sentiment_macro")
        sys.exit(1)

if __name__ == "__main__":
    main()
