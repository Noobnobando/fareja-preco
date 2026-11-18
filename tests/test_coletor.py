"""Testes offline: HTML de exemplo no formato de cada loja + regras de alerta.

Rode com:  python -m pytest -q
"""
from datetime import datetime, timedelta, timezone

import pytest

from coletor.alertas import Novo, Registro, avaliar_item, brl
from coletor.lojas import (checar_bloqueio, detectar_loja, ids_shopee, ler_amazon, ler_casasbahia,
                           ler_magalu, ler_mercadolivre, url_amazon)
from coletor.parse import ErroColeta, generic, parse_brl


# ------------------------------------------------------------------ preços
@pytest.mark.parametrize("txt,esperado", [
    ("R$ 1.299,90", 1299.90), ("1299,90", 1299.90), ("1299.90", 1299.90), ("440,91", 440.91),
    ("R$\xa060,79", 60.79), ("1.299", 1299.0), ("2.499.000,00", 2499000.0), (529.9, 529.9),
    ("1,299.90", 1299.90), ("", None), ("grátis", None), (None, None),
])
def test_parse_brl(txt, esperado):
    assert parse_brl(txt) == esperado


def test_brl():
    assert brl(1299.9) == "R$ 1.299,90"


# ------------------------------------------------------------------ lojas
def test_detectar_loja():
    assert detectar_loja("https://www.amazon.com.br/dp/B0ABCDEFGH") == "amazon"
    assert detectar_loja("https://amzn.to/3xyz") == "amazon"
    assert detectar_loja("https://produto.mercadolivre.com.br/MLB-123") == "mercadolivre"
    assert detectar_loja("https://www.magazineluiza.com.br/x/p/abc/") == "magalu"
    assert detectar_loja("https://www.casasbahia.com.br/x/p/123") == "casasbahia"
    assert detectar_loja("https://shopee.com.br/Panela-i.123.456") == "shopee"
    assert detectar_loja("https://www.tokstok.com.br/x") == "outra"


def test_url_amazon_limpa():
    u = "https://www.amazon.com.br/Panela-Tramontina/dp/B07XYZ1234/ref=sr_1_3?keywords=panela"
    assert url_amazon(u) == "https://www.amazon.com.br/dp/B07XYZ1234"


def test_ids_shopee():
    assert ids_shopee("https://shopee.com.br/Jogo-de-Panelas-i.112233.445566?sp_atk=x") == (112233, 445566)
    assert ids_shopee("https://shopee.com.br/product/112233/445566") == (112233, 445566)


AMAZON = """
<html><head><title>Amazon.com.br</title></head><body>
<span id="productTitle">  Jogo de Panelas Tramontina Sicília 5 Peças  </span>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-price a-text-price"><span class="a-offscreen">R$ 699,90</span></span>
  <span class="a-price"><span class="a-offscreen">R$ 440,91</span>
    <span class="a-price-whole">440,</span><span class="a-price-fraction">91</span></span>
</div></body></html>"""


def test_amazon():
    r = ler_amazon(AMAZON)
    assert r.price == 440.91 and r.in_stock
    assert r.title.startswith("Jogo de Panelas")


def test_amazon_so_whole_fraction():
    html = ('<div id="corePrice_feature_div"><span class="a-price"><span class="a-price-whole">1.299<span>,</span></span>'
            '<span class="a-price-fraction">90</span></span></div>')
    assert ler_amazon(html).price == 1299.90


def test_amazon_captcha():
    html = "<html><form action='/errors/validateCaptcha'>Digite os caracteres</form></html>"
    with pytest.raises(ErroColeta, match="captcha"):
        try:
            ler_amazon(html)
        except ErroColeta:
            checar_bloqueio(200, html)


MERCADOLIVRE_JSONLD = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Taças de Vidro 6 un",
 "offers":{"@type":"Offer","price":60.79,"priceCurrency":"BRL","availability":"https://schema.org/InStock"}}
</script></head><body></body></html>"""

MERCADOLIVRE_HTML = """
<html><head><meta property="og:title" content="Taças de Vidro"></head><body>
<div class="ui-pdp-price">
 <s class="andes-money-amount"><span class="andes-money-amount__fraction">89</span></s>
 <div class="ui-pdp-price__second-line"><span class="andes-money-amount">
   <span class="andes-money-amount__fraction">1.060</span><span class="andes-money-amount__cents">79</span></span></div>
</div></body></html>"""


def test_mercadolivre_jsonld():
    r = ler_mercadolivre(MERCADOLIVRE_JSONLD)
    assert r.price == 60.79 and r.title == "Taças de Vidro 6 un"


def test_mercadolivre_html():
    r = ler_mercadolivre(MERCADOLIVRE_HTML)
    assert r.price == 1060.79


MAGALU = """
<html><head><script type="application/ld+json">[{"@type":"BreadcrumbList"},
{"@type":"Product","name":"Panela de Pressão","offers":{"@type":"AggregateOffer","lowPrice":"199.90","highPrice":"249.90",
"availability":"http://schema.org/OutOfStock"}}]</script></head></html>"""


def test_magalu_aggregate_sem_estoque():
    r = ler_magalu(MAGALU)
    assert r.price == 199.90 and r.in_stock is False


def test_magalu_testid():
    html = '<h1>Cafeteira</h1><p data-testid="price-value">R$&nbsp;349,00</p>'
    assert ler_magalu(html).price == 349.0


def test_casasbahia_next_data():
    html = '<h1>Geladeira</h1><script id="__NEXT_DATA__">{"sku":{"sellPrice":3499.0}}</script>'
    assert ler_casasbahia(html).price == 3499.0


def test_generico_meta():
    html = '<meta property="product:price:amount" content="129.90"><meta property="og:title" content="Tapete">'
    r = generic(html)
    assert r.price == 129.90 and r.title == "Tapete"


def test_sem_preco():
    with pytest.raises(ErroColeta):
        ler_casasbahia("<html><body>nada aqui</body></html>")


# ------------------------------------------------------------------ alertas
AGORA = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def dias(n):
    return (AGORA - timedelta(days=n)).isoformat()


ITEM = {"id": "i1", "name": "Panela Tramontina", "qty": 1, "target_price": None, "last_alert_price": None}
OFS = [{"id": "a", "store": "amazon", "url": "https://amazon/x", "frete": None},
       {"id": "m", "store": "magalu", "url": "https://magalu/x", "frete": 20}]


def test_queda_dispara():
    hist = {"a": [Registro(dias(10), 529.9, None)], "m": [Registro(dias(10), 499.0, None)]}
    al = avaliar_item(ITEM, OFS, hist, {"a": Novo(440.91)}, agora=AGORA)
    assert al and "📉 Amazon" in al.texto and "−17%" in al.texto
    assert "🏆" in al.texto              # 440,91 < menor histórico (519,00 com frete)
    assert "na Amazon" in al.texto and al.url == "https://amazon/x"


def test_queda_pequena_nao_dispara():
    hist = {"a": [Registro(dias(10), 500.0, None)]}
    assert avaliar_item(ITEM, OFS[:1], hist, {"a": Novo(495.0)}, agora=AGORA) is None


def test_recorde_exige_7_dias():
    hist = {"a": [Registro(dias(2), 500.0, None)]}
    al = avaliar_item(ITEM, OFS[:1], hist, {"a": Novo(490.0)}, min_queda_pct=50, agora=AGORA)
    assert al is None


def test_preco_alvo_uma_vez_e_rearma():
    item = dict(ITEM, target_price=450)
    hist = {"a": [Registro(dias(1), 460.0, None)]}
    al = avaliar_item(item, OFS[:1], hist, {"a": Novo(449.0)}, min_queda_pct=50, agora=AGORA)
    assert "🎯" in al.texto and al.novo_last_alert_price == 449.0

    item2 = dict(item, last_alert_price=449.0)
    hist2 = {"a": hist["a"] + [Registro(AGORA.isoformat(), 449.0, None)]}
    assert avaliar_item(item2, OFS[:1], hist2, {"a": Novo(449.0)}, min_queda_pct=50, agora=AGORA) is None

    al3 = avaliar_item(item2, OFS[:1], hist2, {"a": Novo(470.0)}, min_queda_pct=50, agora=AGORA)
    assert al3.texto == "" and al3.mudou_last_alert and al3.novo_last_alert_price is None


def test_frete_da_oferta_entra_no_custo():
    hist = {"m": [Registro(dias(10), 500.0, None)]}
    al = avaliar_item(ITEM, OFS[1:], hist, {"m": Novo(450.0)}, agora=AGORA)
    assert "R$ 520,00 → <b>R$ 470,00</b>" in al.texto


def test_sem_estoque_nao_e_melhor():
    hist = {"a": [Registro(dias(10), 300.0, None)], "m": [Registro(dias(10), 500.0, None)]}
    al = avaliar_item(ITEM, OFS, hist, {"a": Novo(100.0, in_stock=False), "m": Novo(400.0)}, agora=AGORA)
    assert "na Magalu" in al.texto and "R$ 100" not in al.texto
