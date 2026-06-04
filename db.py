"""Postgres connection + schema bootstrap + searches/shortlist CRUD (infra).

Engine modules accept a `conn` parameter — they don't open connections themselves.
The caller (CLI runner or Streamlit) owns the connection lifecycle.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(database_url: str):
    """Open a psycopg3 connection with dict_row factory."""
    return psycopg.connect(database_url, row_factory=dict_row)


def init_schema(database_url: str) -> None:
    """Run schema.sql against the target DB. Idempotent."""
    sql = SCHEMA_PATH.read_text()
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


# ---------- searches ----------

def save_search(
    conn,
    *,
    label: Optional[str],
    tab: str,
    input_count: int,
    filters: dict,
    input_data: dict,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO searches (label, tab, input_count, filters, input_data)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (label, tab, input_count, json.dumps(filters), json.dumps(input_data)),
        )
        sid = cur.fetchone()["id"]
    conn.commit()
    return sid


def list_searches(conn, tab: Optional[str] = None) -> list[dict]:
    with conn.cursor() as cur:
        if tab:
            cur.execute(
                "SELECT id, created_at, label, tab, input_count, filters, input_data "
                "FROM searches WHERE tab = %s ORDER BY created_at DESC",
                (tab,),
            )
        else:
            cur.execute(
                "SELECT id, created_at, label, tab, input_count, filters, input_data "
                "FROM searches ORDER BY created_at DESC"
            )
        return list(cur.fetchall())


def load_search(conn, search_id: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM searches WHERE id = %s", (search_id,))
        return cur.fetchone()


def delete_search(conn, search_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM searches WHERE id = %s", (search_id,))
    conn.commit()


def update_search_label(conn, search_id: int, label: Optional[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE searches SET label = %s WHERE id = %s",
            (label or None, search_id),
        )
    conn.commit()


def display_label(search: dict) -> str:
    """Render label or synthesize one from the input data."""
    if search.get("label"):
        return search["label"]
    data = search.get("input_data") or {}
    kws = data.get("keywords") or []
    if kws:
        head = kws[0]
        if len(kws) > 1:
            return f"{head} +{len(kws)-1}"
        return head
    if data.get("url"):
        url = data["url"]
        return url if len(url) <= 50 else url[:47] + "…"
    return "Untitled"


# ---------- shortlist ----------

def add_to_shortlist(
    conn,
    *,
    keyword: str,
    source_tab: Optional[str],
    source_search_id: Optional[int],
    metrics_snapshot: dict,
) -> None:
    """Upsert by keyword (spec §3: shortlist deduped by keyword)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO shortlist (keyword, source_tab, source_search_id, metrics_snapshot)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (keyword) DO UPDATE SET
                source_tab       = EXCLUDED.source_tab,
                source_search_id = EXCLUDED.source_search_id,
                metrics_snapshot = EXCLUDED.metrics_snapshot
            """,
            (keyword, source_tab, source_search_id, json.dumps(metrics_snapshot)),
        )
    conn.commit()


def remove_from_shortlist(conn, keyword: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shortlist WHERE keyword = %s", (keyword,))
    conn.commit()


def list_shortlist(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, keyword, added_at, source_tab, source_search_id, metrics_snapshot "
            "FROM shortlist ORDER BY added_at DESC"
        )
        return list(cur.fetchall())


def shortlist_keywords(conn) -> set[str]:
    """Just the set of keywords currently in the shortlist."""
    with conn.cursor() as cur:
        cur.execute("SELECT keyword FROM shortlist")
        return {r["keyword"] for r in cur.fetchall()}


def clear_shortlist(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shortlist")
        n = cur.rowcount
    conn.commit()
    return n
