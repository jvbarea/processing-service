# File: data-harvester/src/utils/extract_tickers.py
#!/usr/bin/env python3
"""
Utility to extract tickers mentioned in a text using the company_map table.
Assumes a Supabase table 'company_map(name_canonical, ticker)'.
"""
import re
from typing import List
from src.config import supabase

# Load mapping once
def load_company_map() -> dict[str, str]:
    resp = supabase.table('company_map').select('name_canonical, ticker').execute()
    rows = resp.data or []
    # build regex patterns for tickers and names
    return {r['name_canonical'].upper(): r['ticker'].upper() for r in rows}

_COMPANY_MAP = load_company_map()
# build a combined regex to match tickers or company names
_PATTERN = re.compile(r"\b(" + "|".join(re.escape(k) for k in _COMPANY_MAP) + r")\b", flags=re.IGNORECASE)


def extract_tickers(text: str) -> List[str]:
    """
    Extracts tickers referenced in `company_map` from the given text.
    Returns a list of unique tickers (upper-case).
    """
    found = {match.group(0).upper() for match in _PATTERN.finditer(text or '')}
    # map canonical to ticker
    return [ _COMPANY_MAP.get(key, key) for key in found ]
