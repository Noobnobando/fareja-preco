"""Funções genéricas para achar preço e título em páginas de produto."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from bs4 import BeautifulSoup


@dataclass
class Leitura:
    """Resultado da leitura de uma página de produto."""
    price: float
    title: str | None = None
    in_stock: bool = True


class ErroColeta(Exception):
    """Não foi possível ler o preço (bloqueio, página mudou, produto removido...)."""


def parse_brl(valor: Any) -> float | None:
    """Converte '1.299,90', 'R$ 1299,90', '1299.90' ou 1299.9 em float."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return round(float(valor), 2) if valor >= 0 else None
    s = str(valor)
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        # o separador que aparece por último é o decimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s and len(s.split(".")[1]) == 3:
        # '1.299' no padrão brasileiro é milhar, não decimal
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return round(v, 2) if v > 0 else None


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _walk(obj: Any) -> Iterable[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _is_type(node: dict, name: str) -> bool:
    t = node.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == name.lower() for x in t)
    return str(t).lower() == name.lower()


def from_jsonld(page: BeautifulSoup) -> Leitura | None:
    """Lê o bloco <script type="application/ld+json"> com @type Product (padrão do Google)."""
    for tag in page.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _walk(data):
            if not _is_type(node, "Product"):
                continue
            offers = node.get("offers")
            candidatos: list[dict] = []
            for o in _walk(offers) if offers else []:
                if _is_type(o, "Offer") or _is_type(o, "AggregateOffer") or "price" in o or "lowPrice" in o:
                    candidatos.append(o)
            precos = []
            em_estoque = None
            for o in candidatos:
                p = parse_brl(o.get("price")) or parse_brl(o.get("lowPrice"))
                if p:
                    precos.append(p)
                av = str(o.get("availability", ""))
                if av:
                    disponivel = not re.search(r"OutOfStock|SoldOut|Discontinued", av, re.I)
                    em_estoque = disponivel if em_estoque is None else (em_estoque or disponivel)
            if precos:
                return Leitura(price=min(precos), title=_clean(node.get("name")),
                               in_stock=True if em_estoque is None else em_estoque)
    return None


def from_meta(page: BeautifulSoup) -> Leitura | None:
    """Lê <meta property="product:price:amount"> ou itemprop="price"."""
    for attrs in ({"property": "product:price:amount"}, {"itemprop": "price"},
                  {"property": "og:price:amount"}, {"name": "twitter:data1"}):
        tag = page.find(attrs=attrs)
        if tag is not None:
            p = parse_brl(tag.get("content") or tag.get_text())
            if p:
                return Leitura(price=p, title=title_of(page))
    return None


def title_of(page: BeautifulSoup) -> str | None:
    og = page.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return _clean(og["content"])
    h1 = page.find("h1")
    if h1:
        return _clean(h1.get_text())
    if page.title:
        return _clean(page.title.get_text())
    return None


def _clean(s: Any) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s[:200] or None


def generic(html: str) -> Leitura | None:
    page = soup(html)
    return from_jsonld(page) or from_meta(page)
