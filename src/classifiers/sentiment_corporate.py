#!/usr/bin/env python3

import argparse
import logging
import sys
import json
from datetime import datetime, timezone
from openai import OpenAI
from src.config import supabase, settings, get_last_run_time, set_last_run_time
from src.utils.extract_tickers import extract_tickers

# Função para LLM Function Calling
FUNCTION_DEF = [{
    "type": "function",
    "name": "record_corp_sentiments",
    "description": "Registra sentimento para cada ticker em uma notícia",
    "parameters": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": { "type": "string" },
                        "sentiment": {
                            "type": "string",
                            "enum": ["positivo", "neutro", "negativo"]
                        },
                        "score": { "type": "number" }
                    },
                    "required": ["ticker", "sentiment", "score"]
                }
            }
        },
        "required": ["results"]
    }
}]

# Limites do Supabase e batch
MAX_PAGE_SIZE = 1000  # Máximo retornado por chamada REST

def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def classify_corporate(client: OpenAI, text: str) -> list[dict]:
    """
    Classifica sentimento por ticker via OpenAI Function Calling.
    """
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um analista de notícias corporativas. "
                    "Para cada ticker mencionado no texto, retorne um JSON com ticker, sentiment e score."
                )
            },
            { "role": "user", "content": text }
        ],
        functions=FUNCTION_DEF, # type: ignore[arg-type]
        function_call={ "name": "record_corp_sentiments" },
        temperature=settings.OPENAI_TEMP,
        max_tokens=200,
        top_p=1
    )
    msg = resp.choices[0].message
    if msg.function_call:
        try:
            data = json.loads(msg.function_call.arguments)
            return data.get('results', [])
        except json.JSONDecodeError:
            logging.error("Falha ao parsear JSON: %s", msg.function_call.arguments)
    return []
def run_classifier(batch_size: int, debug: bool = False, backfill: bool = False) -> int:
    """
    Processa até `batch_size` notícias, em páginas de MAX_PAGE_SIZE,
    aplicando watermark (exceto em backfill) e fazendo upsert incremental
    a cada 1 000 registros para economizar memória e tokens.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    # 1) GUIDs já processados
    proc = supabase.table('corporate_sentiment').select('raw_id').execute()
    processed = {r['raw_id'] for r in (proc.data or [])}
    if debug:
        logging.debug('GUIDs já processados: %d', len(processed))

    # 2) Watermark incremental (None se backfill)
    last_run = None if backfill else get_last_run_time('sentiment_corporate')

    total = 0
    offset = 0
    all_records = []
    record_idx = 0

    # Função auxiliar para upsert e limpeza de buffer
    def flush_batch(records):
        if not records:
            return
        start = flush_batch.start_idx + 1
        end   = flush_batch.start_idx + len(records)
        logging.info('Inserindo batch de registros %d a %d', start, end)
        resp = supabase.table('corporate_sentiment') \
                       .upsert(records, on_conflict='raw_id,ticker') \
                       .execute()
        err = getattr(resp, 'error', None)
        status = getattr(resp, 'status_code', None)
        if err or (status and status >= 300):
            logging.error("Erro ao upsert batch %d-%d: %s", start, end, err or "unknown error")
            sys.exit(1)
        flush_batch.start_idx += len(records)
        records.clear()

    flush_batch.start_idx = 0

    # 3) Loop de leitura paginada
    while True:
        to_fetch = min(MAX_PAGE_SIZE, batch_size - offset)
        if to_fetch <= 0:
            break

        qry = supabase.table('cleaned_news')\
                      .select('guid,title_clean,body_clean,published_at')
        if last_run:
            qry = qry.gt('published_at', last_run)

        resp = (qry.order('published_at', desc=False)
                   .range(offset, offset + to_fetch - 1)
                   .execute())
        rows = resp.data or []
        if not rows:
            break

        for r in rows:
            guid = r['guid']
            if guid in processed:
                continue

            text = f"{r['title_clean']}\n\n{r['body_clean']}"
            tickers = extract_tickers(text)
            if not tickers:
                if debug:
                    logging.debug('GUID %s: sem tickers', guid)
                processed.add(guid)
                continue

            results = classify_corporate(client, text)
            for res in results:
                record_idx += 1
                if debug:
                    logging.debug(
                        'Record %d: ticker=%s, sentiment=%.3f, label=%s',
                        record_idx, res['ticker'], res['score'], res['sentiment']
                    )
                all_records.append({
                    'raw_id':          guid,
                    'ticker':          res['ticker'],
                    'sentiment':       float(res['score']),
                    'sentiment_label': res['sentiment'],
                    'created_at':      datetime.now(timezone.utc).isoformat()
                })
                total += 1

                # flush a cada 1000 registros
                if len(all_records) >= 10:
                    flush_batch(all_records)

            processed.add(guid)

        offset += len(rows)
        if len(rows) < to_fetch:
            break

    # 4) Flush final do que sobrou (< 1000)
    flush_batch(all_records)

    # 5) Atualiza watermark se não for backfill
    if not backfill:
        set_last_run_time('sentiment_corporate', datetime.now(timezone.utc))

    logging.info('Total records processed and upserted: %d', total)
    return total

def parse_args():
    p = argparse.ArgumentParser('Classificador Sentimento Corporate')
    p.add_argument(
        '-b', '--batch-size', '--batch', type=int,
        dest='batch_size', default=50,
        help='Total de linhas a processar (paginado)'
    )
    p.add_argument('--debug', action='store_true')
    p.add_argument(
        '--once', action='store_true',
        help='Para após uma execução paginada'
    )
    p.add_argument(
        '--backfill', action='store_true',
        help='Ignora watermark (processa histórico)'
    )
    return p.parse_args()

def main():
    args = parse_args()
    setup_logging(args.debug)
    count = run_classifier(args.batch_size, args.debug, args.backfill)
    logging.info('Processed total: %d', count)

if __name__ == '__main__':
    main()
