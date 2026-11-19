"""Cliente mínimo da API REST do Supabase (PostgREST), só com a biblioteca padrão."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class Supabase:
    def __init__(self, url: str, service_key: str) -> None:
        self.base = url.rstrip("/") + "/rest/v1/"
        self.h = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _req(self, method: str, path: str, params: dict | None = None, body: Any = None,
             prefer: str | None = None, extra: dict | None = None) -> Any:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="(),.*:")
        h = dict(self.h)
        if prefer:
            h["Prefer"] = prefer
        if extra:
            h.update(extra)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                txt = r.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Supabase {method} {path}: HTTP {e.code} {e.read().decode()[:300]}") from e
        return json.loads(txt) if txt else None

    def select(self, table: str, params: dict) -> list[dict]:
        """SELECT com paginação automática (o Supabase devolve no máximo 1000 linhas por vez)."""
        out: list[dict] = []
        start = 0
        while True:
            page = self._req("GET", table, params, extra={"Range": f"{start}-{start + 999}"})
            out.extend(page or [])
            if not page or len(page) < 1000:
                return out
            start += 1000

    def insert(self, table: str, rows: dict | list[dict], returning: bool = False) -> Any:
        return self._req("POST", table, body=rows,
                         prefer="return=representation" if returning else "return=minimal")

    def update(self, table: str, match: dict, values: dict) -> None:
        params = {k: f"eq.{v}" for k, v in match.items()}
        self._req("PATCH", table, params, body=values, prefer="return=minimal")

    def upsert(self, table: str, rows: dict | list[dict]) -> None:
        self._req("POST", table, body=rows, prefer="resolution=merge-duplicates,return=minimal")

    def delete(self, table: str, match: dict) -> None:
        params = {k: f"eq.{v}" for k, v in match.items()}
        self._req("DELETE", table, params, prefer="return=minimal")
