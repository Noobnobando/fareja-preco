"""Leitura de preço específica de cada loja."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from urllib.parse import urlparse

from .http import Navegador
from .parse import ErroColeta, Leitura, from_jsonld, from_meta, generic, parse_brl, soup, title_of

LOJAS = {
    "amazon": "Amazon",
    "mercadolivre": "Mercado Livre",
    "magalu": "Magalu",
    "casasbahia": "Casas Bahia",
    "shopee": "Shopee",
    "outra": "Outra loja",
}


def detectar_loja(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "amazon." in host or host.endswith("amzn.to") or host.endswith("a.co"):
        return "amazon"
    if "mercadolivre" in host or "mercadolibre" in host or host.endswith("meli.la"):
        return "mercadolivre"
    if "magazineluiza" in host or "magalu" in host:
        return "magalu"
    if "casasbahia" in host:
        return "casasbahia"
    if "shopee" in host or host.endswith("shp.ee"):
        return "shopee"
    return "outra"


# ----------------------------------------------------------------- bloqueios
SINAIS_BLOQUEIO = [
    (r"validateCaptcha|Digite os caracteres|Type the characters you see", "a Amazon pediu captcha (bloqueou o robô)"),
    (r"account-verification|Para continuar, acesse sua conta|suspicious-traffic", "o Mercado Livre pediu login/verificação"),
    (r"Access Denied|Request blocked|_Incapsula_Resource|cf-chl-|Just a moment\.\.\.|px-captcha|Pardon Our Interruption",
     "a loja bloqueou o robô"),
]


def checar_bloqueio(status: int, html: str) -> None:
    trecho = html[:200_000]
    for padrao, msg in SINAIS_BLOQUEIO:
        if re.search(padrao, trecho, re.I):
            raise ErroColeta(msg)
    if status == 404 or status == 410:
        raise ErroColeta("página não encontrada (o anúncio pode ter saído do ar)")
    if status in (403, 429, 503):
        raise ErroColeta(f"a loja recusou o acesso (HTTP {status})")
    if status >= 400:
        raise ErroColeta(f"erro HTTP {status}")


# ----------------------------------------------------------------- Amazon
def url_amazon(url: str) -> str:
    m = re.search(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})", url, re.I)
    return f"https://www.amazon.com.br/dp/{m.group(1).upper()}" if m else url


def ler_amazon(html: str) -> Leitura:
    page = soup(html)
    titulo_tag = page.find(id="productTitle")
    titulo = titulo_tag.get_text(strip=True) if titulo_tag else title_of(page)
    indisponivel = bool(page.find(id="outOfStock")) or bool(
        re.search(r"Não disponível\.|Currently unavailable", html[:400_000]))

    preco = None
    for bloco_id in ("corePriceDisplay_desktop_feature_div", "corePrice_feature_div",
                     "corePrice_desktop", "apex_desktop", "apex_offerDisplay_desktop"):
        bloco = page.find(id=bloco_id)
        if not bloco:
            continue
        span = bloco.select_one("span.a-price:not(.a-text-price) span.a-offscreen") or bloco.select_one("span.a-offscreen")
        if span:
            preco = parse_brl(span.get_text())
            if preco:
                break
        inteiro = bloco.select_one("span.a-price-whole")
        if inteiro:
            frac = bloco.select_one("span.a-price-fraction")
            preco = parse_brl(inteiro.get_text(strip=True).rstrip(",.") + "," + (frac.get_text(strip=True) if frac else "00"))
            if preco:
                break
    if not preco:
        m = re.search(r'"priceAmount"\s*:\s*([\d.]+)', html)
        if m:
            preco = parse_brl(float(m.group(1)))
    if not preco:
        g = generic(html)
        if g:
            return g
        if indisponivel:
            raise ErroColeta("produto indisponível na Amazon no momento")
        raise ErroColeta("não achei o preço na página da Amazon")
    return Leitura(price=preco, title=titulo, in_stock=not indisponivel)


# ----------------------------------------------------------------- Mercado Livre
def ler_mercadolivre(html: str) -> Leitura:
    page = soup(html)
    leitura = from_jsonld(page)
    if leitura:
        return leitura
    # preço principal (não o riscado): segunda linha do bloco de preço
    bloco = page.select_one(".ui-pdp-price__second-line") or page.select_one(".ui-pdp-price")
    if bloco:
        fr = bloco.select_one(".andes-money-amount__fraction")
        ct = bloco.select_one(".andes-money-amount__cents")
        if fr:
            p = parse_brl(fr.get_text(strip=True) + "," + (ct.get_text(strip=True) if ct else "00"))
            if p:
                return Leitura(price=p, title=title_of(page),
                               in_stock="Anúncio pausado" not in html and "Publicação finalizada" not in html)
    leitura = from_meta(page)
    if leitura:
        return leitura
    raise ErroColeta("não achei o preço na página do Mercado Livre")


# ----------------------------------------------------------------- Magalu
def ler_magalu(html: str) -> Leitura:
    page = soup(html)
    leitura = from_jsonld(page)
    if leitura:
        return leitura
    tag = page.select_one('[data-testid="price-value"]')
    if tag:
        p = parse_brl(tag.get_text())
        if p:
            return Leitura(price=p, title=title_of(page))
    m = re.search(r'"bestPrice"\s*:\s*"?([\d.]+)', html)
    if m:
        return Leitura(price=parse_brl(float(m.group(1))), title=title_of(page))
    leitura = from_meta(page)
    if leitura:
        return leitura
    raise ErroColeta("não achei o preço na página da Magalu")


# ----------------------------------------------------------------- Casas Bahia
def ler_casasbahia(html: str) -> Leitura:
    page = soup(html)
    leitura = from_jsonld(page)
    if leitura:
        return leitura
    for sel in ('[data-testid="product-price-value"]', '[data-testid="price-value"]', "#product-price"):
        tag = page.select_one(sel)
        if tag:
            p = parse_brl(tag.get_text())
            if p:
                return Leitura(price=p, title=title_of(page))
    m = re.search(r'"sellPrice"\s*:\s*"?([\d.]+)', html)
    if m:
        return Leitura(price=parse_brl(float(m.group(1))), title=title_of(page))
    leitura = from_meta(page)
    if leitura:
        return leitura
    raise ErroColeta("não achei o preço na página da Casas Bahia")


# ----------------------------------------------------------------- Shopee
def ids_shopee(url: str) -> tuple[int, int] | None:
    """shopee.com.br/Nome-i.SHOP.ITEM  ou  shopee.com.br/product/SHOP/ITEM"""
    m = re.search(r"-i\.(\d+)\.(\d+)", url) or re.search(r"/product/(\d+)/(\d+)", url)
    return (int(m.group(1)), int(m.group(2))) if m else None


SHOPEE_API = "https://open-api.affiliate.shopee.com.br/graphql"


def ler_shopee(url: str, nav: Navegador) -> Leitura:
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_APP_SECRET", "").strip()
    if not (app_id and secret):
        raise ErroColeta("a Shopee bloqueia robôs; configure a API de afiliados (veja o README) "
                         "ou registre o preço manualmente")
    ids = ids_shopee(url)
    if not ids:
        raise ErroColeta("não reconheci o link da Shopee; use o link completo da página do produto")
    shop_id, item_id = ids
    query = ("{ productOfferV2(itemId: %d, shopId: %d) { nodes { itemId productName priceMin priceMax } } }"
             % (item_id, shop_id))
    body = json.dumps({"query": query}, separators=(",", ":"))
    ts = str(int(time.time()))
    assinatura = hashlib.sha256((app_id + ts + body + secret).encode()).hexdigest()
    status, txt = nav.post_json(SHOPEE_API, body, {
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}"})
    if status != 200:
        raise ErroColeta(f"API da Shopee respondeu HTTP {status}")
    data = json.loads(txt)
    if data.get("errors"):
        raise ErroColeta("API da Shopee: " + str(data["errors"][0].get("message", "erro"))[:150])
    nodes = (((data.get("data") or {}).get("productOfferV2") or {}).get("nodes")) or []
    if not nodes:
        raise ErroColeta("a API da Shopee não encontrou este produto")
    n = nodes[0]
    preco = parse_brl(n.get("priceMin")) or parse_brl(n.get("priceMax"))
    if not preco:
        raise ErroColeta("a API da Shopee não informou preço")
    return Leitura(price=preco, title=n.get("productName"))


# ----------------------------------------------------------------- entrada única
LEITORES = {
    "amazon": ler_amazon,
    "mercadolivre": ler_mercadolivre,
    "magalu": ler_magalu,
    "casasbahia": ler_casasbahia,
}


def ler_preco(url: str, loja: str | None, nav: Navegador, ml=None) -> Leitura:
    loja = loja or detectar_loja(url)
    if loja == "shopee":
        return ler_shopee(url, nav)
    if loja == "mercadolivre" and ml is not None and ml.access:
        # API oficial (o site do ML bloqueia robôs em servidores)
        return ml.ler(url, resolver=lambda u: nav.get(u).url)
    if loja == "mercadolivre" and ml is not None:
        try:
            return ler_preco(url, loja, nav, None)
        except ErroColeta as e:
            raise ErroColeta(f"{e}. API do Mercado Livre: {ml.erro or 'não conectada'}") from e
    alvo = url_amazon(url) if loja == "amazon" else url
    resp = nav.get(alvo)
    if loja == "amazon" and resp.url != alvo:
        # link curto (amzn.to) redireciona para a página do produto
        alvo2 = url_amazon(resp.url)
        if alvo2 != resp.url:
            resp = nav.get(alvo2)
    if resp.status >= 400:
        checar_bloqueio(resp.status, resp.text)
    try:
        leitor = LEITORES.get(loja)
        if leitor:
            return leitor(resp.text)
        leitura = generic(resp.text)
        if not leitura:
            raise ErroColeta("não achei o preço nesta página (loja sem suporte específico)")
        return leitura
    except ErroColeta:
        # se a página era uma tela de bloqueio, a mensagem fica mais clara
        checar_bloqueio(resp.status, resp.text)
        raise
