"""Acesso às páginas das lojas.

Usa curl_cffi para imitar o Chrome de verdade (inclusive a "impressão digital" TLS),
o que reduz muito os bloqueios. Se curl_cffi não estiver instalado, cai para urllib.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

try:
    from curl_cffi import requests as _cr  # type: ignore
except ImportError:  # pragma: no cover
    _cr = None

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.6,en;q=0.5",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


@dataclass
class Resposta:
    url: str
    status: int
    text: str


class Navegador:
    def __init__(self) -> None:
        self._s = _cr.Session(impersonate="chrome") if _cr else None

    def get(self, url: str, timeout: int = 30) -> Resposta:
        if self._s is not None:
            r = self._s.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            return Resposta(str(r.url), r.status_code, r.text)
        import urllib.request  # fallback simples
        req = urllib.request.Request(url, headers={**HEADERS, "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return Resposta(r.geturl(), r.status, r.read().decode("utf-8", "replace"))

    def post_json(self, url: str, body: str, headers: dict, timeout: int = 30) -> tuple[int, str]:
        h = {"Content-Type": "application/json", **headers}
        if self._s is not None:
            r = self._s.post(url, data=body, headers=h, timeout=timeout)
            return r.status_code, r.text
        import urllib.request
        req = urllib.request.Request(url, data=body.encode(), headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")


def pausa(minimo: float = 2.0, maximo: float = 6.0) -> None:
    """Espera um pouco entre páginas para não parecer robô apressado."""
    time.sleep(random.uniform(minimo, maximo))
