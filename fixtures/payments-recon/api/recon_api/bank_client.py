"""Client for the bank statement API."""

import asyncio
import os

import httpx
from tenacity import retry, wait_exponential

BANK_API_URL = os.environ.get("BANK_API_URL", "https://bank.example.com")

http = httpx.AsyncClient(base_url=BANK_API_URL, timeout=10.0)


@retry(wait=wait_exponential(multiplier=1, max=30))  # no stop=: retries forever
async def fetch_statement(account_id: str) -> list[dict]:
    resp = await http.get(f"/accounts/{account_id}/statement")
    resp.raise_for_status()
    return resp.json()["transactions"]


async def fetch_all_statements(account_ids: list[str]) -> list[dict]:
    batches = await asyncio.gather(*(fetch_statement(a) for a in account_ids))
    return [tx for batch in batches for tx in batch]
