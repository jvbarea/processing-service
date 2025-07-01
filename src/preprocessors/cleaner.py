#!/usr/bin/env python3

import argparse
import logging
import sys
import re
from src.config import supabase  # supabase client configured in src/config.py


def setup_logging(debug: bool = False):
    """Configura logging com nível DEBUG se solicitado."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def clean_html(text: str) -> str:
    """Remove tags HTML simples."""
    return re.sub(r'<[^>]+>', '', text or '')


def normalize_whitespace(text: str) -> str:
    """Normaliza múltiplos espaços e quebras de linha."""
    return " ".join((text or '').split())


def clean_text(text: str) -> str:
    """Executa limpeza HTML + normalização de whitespace."""
    return normalize_whitespace(clean_html(text))


def run_cleaner(batch_size: int, debug: bool = False) -> int:
    """
    Busca até `batch_size` registros em raw_news via Supabase,
    limpa e insere em cleaned_news com upsert.
    Retorna número de itens processados.
    """
    # Seleção de registros não processados
    response = (
        supabase.table("raw_news")
                .select(
                    "guid, feed_id, title, summary, tickers, cnpjs, published_at"
                )
                .order("published_at", desc=False)
                .limit(batch_size)
                .execute()
    )

    rows = response.data or []
    if debug:
        logging.debug(f"Fetched {len(rows)} rows: {rows}")
    if not rows:
        logging.info("Nenhum raw_news para processar.")
        return 0

    # Preparar batch limpo conforme schema
    cleaned_batch = []
    for r in rows:
        cleaned_batch.append({
            "guid": r["guid"],
            "feed_id": r.get("feed_id"),
            "published_at": r.get("published_at"),
            "title_clean": clean_text(r.get("title", "")),
            "body_clean": clean_text(r.get("summary", "")),
            "tickers": r.get("tickers", []),
            "cnpjs": r.get("cnpjs", [])
        })

    # Upsert para cleaned_news (chave primária = guid)
    insert_resp = (
        supabase.table("cleaned_news")
                .upsert(cleaned_batch, on_conflict="guid")
                .execute()
    )

    # Verificação robusta de erro
    err = getattr(insert_resp, 'error', None)
    status = getattr(insert_resp, 'status_code', None)
    if err or (status and status >= 300):
        logging.error(f"Erro ao inserir batch: {err or 'unknown error'}")
        sys.exit(1)

    processed = len(cleaned_batch)
    logging.info(f"Processed {processed} items")
    return processed


def main():
    parser = argparse.ArgumentParser(
        description="Cleaner corporate news batch job"
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
        help="Roda apenas um lote de até --batch-size e encerra"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Habilita logging DEBUG e imprime detalhes do batch"
    )
    args = parser.parse_args()

    setup_logging(args.debug)
    if args.debug:
        logging.debug(f"Parameters: batch_size={args.batch_size}, once={args.once}, debug={args.debug}")

    try:
        total = 0
        if args.once:
            total = run_cleaner(args.batch_size, args.debug)
        else:
            while True:
                count = run_cleaner(args.batch_size, args.debug)
                total += count
                if count < args.batch_size:
                    break
        logging.info(f"batch_processed={total}")
        sys.exit(0)
    except Exception:
        logging.exception("Erro na execução do cleaner_corporate")
        sys.exit(1)


if __name__ == "__main__":
    main()
