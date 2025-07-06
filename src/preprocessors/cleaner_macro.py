#!/usr/bin/env python3

import argparse
import logging
import sys
import re
from src.config import supabase, get_last_run_time, set_last_run_time  # import watermark helpers
from dateutil.parser import isoparse  # para parsing robusto
from datetime import datetime

def setup_logging(debug: bool = False):
    """Configura logging com nível DEBUG se solicitado."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def clean_html(text: str) -> str:
    """Remove tags HTML simples e normaliza whitespace."""
    if not text:
        return ""
    # Strip basic HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Normalize whitespace
    return " ".join(text.split())


def clean_text(text: str) -> str:
    """Pipeline de limpeza de texto para título e corpo."""
    return clean_html(text)


def run_cleaner(batch_size: int, debug: bool = False) -> int:
    """
    Busca até `batch_size` registros em raw_news_macro via Supabase,
    limpa e insere (upsert) em cleaned_news_macro usando watermark de published_at.
    Retorna número de itens processados.
    """
    # watermark filter
    # last_run = get_last_run_time("cleaner_macro")
    raw_last = get_last_run_time("cleaner_macro")
    last_run = raw_last if isinstance(raw_last, datetime) else isoparse(raw_last) 
    resp = (
        supabase.table("raw_news_macro")
                .select("guid, published_at, title, summary")
                # .gte("published_at", last_run)
                .gt("published_at", last_run)
                .order("published_at", desc=False)
                .limit(batch_size)
                .execute()
    )
    rows = resp.data or []
    if debug:
        logging.debug(f"Fetched {len(rows)} rows since {last_run}: {rows}")
    if not rows:
        logging.info("Nenhum raw_news_macro novo para processar.")
        return 0

    cleaned_batch = []
    for r in rows:
        cleaned_batch.append({
            "guid": r.get("guid"),
            "published_at": r.get("published_at"),
            "title_clean": clean_text(r.get("title", "")),
            "body_clean": clean_text(r.get("summary", ""))
        })

    insert_resp = (
        supabase.table("cleaned_news_macro")
                .upsert(cleaned_batch, on_conflict="guid")
                .execute()
    )
    err = getattr(insert_resp, 'error', None)
    status = getattr(insert_resp, 'status_code', None)
    if err or (status and status >= 300):
        logging.error(f"Erro ao inserir batch: {err or 'unknown error'}")
        sys.exit(1)

    processed = len(cleaned_batch)
    # update watermark
    max_ts_str = max(r["published_at"] for r in rows)
    max_ts: datetime = isoparse(max_ts_str)
    set_last_run_time("cleaner_macro", max_ts)

    logging.info(f"Processed {processed} items")
    return processed


def main():
    parser = argparse.ArgumentParser(
        description="Cleaner macro news batch job"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=100,
        help="Número máximo de itens a processar por vez"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Processa apenas um lote e encerra"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Habilita logging DEBUG e imprime detalhes do batch"
    )
    args = parser.parse_args()

    setup_logging(args.debug)
    if args.debug:
        logging.debug(f"Params: batch_size={args.batch_size}, once={args.once}, debug={args.debug}")

    try:
        total = 0
        logging.info("Iniciando cleaner_macro")
        if args.once:
            total = run_cleaner(args.batch_size, args.debug)
        else:
            while True:
                count = run_cleaner(args.batch_size, args.debug)
                total += count
                if count < args.batch_size:
                    break
        logging.info(f"batch_processed={total}")
        logging.info("Cleaner_macro finalizado com sucesso")
        sys.exit(0)
    except Exception:
        logging.exception("Erro na execução do cleaner_macro")
        sys.exit(1)
        
if __name__ == "__main__":
    main()