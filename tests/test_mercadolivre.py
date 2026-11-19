"""Testes da integração com a API do Mercado Livre (sem internet: HTTP falso)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from coletor.lojas import ler_preco
from coletor.mercadolivre import MercadoLivre, ids_ml
from coletor.parse import ErroColeta


def test_ids_ml():
    assert ids_ml("https://produto.mercadolivre.com.br/MLB-3456789012-geladeira-frost-free-_JM") == ("item", "MLB3456789012")
    assert ids_ml("https://www.mercadolivre.com.br/geladeira-brastemp/p/MLB19876543?pdp_filters=item_id%3AMLB4455667788") == ("item", "MLB4455667788")
    assert ids_ml("https://www.mercadolivre.com.br/geladeira/p/MLB19876543#polycard_client=search&wid=MLB5566778899") == ("item", "MLB5566778899")
    assert ids_ml("https://www.mercadolivre.com.br/geladeira-brastemp/p/MLB19876543") == ("produto", "MLB19876543")
    assert ids_ml("https://meli.la/2AbCdEf") is None


class FakeSB:
    def __init__(self, settings):
        self.s = dict(settings)

    def select(self, table, params):
        return [{"key": k, "value": v} for k, v in self.s.items()]

    def upsert(self, table, rows):
        for r in rows:
            self.s[r["key"]] = r["value"]

    def delete(self, table, match):
        self.s.pop(match["key"], None)


def fake_http(rotas, chamadas=None):
    def h(method, path, token=None, form=None):
        if chamadas is not None:
            chamadas.append((method, path, token, form))
        for chave, resp in rotas.items():
            if path.startswith(chave):
                return resp
        return 404, {"message": "not found"}
    return h


TOKENS = (200, {"access_token": "APP_USR-novo", "refresh_token": "TG-refresh-2", "expires_in": 21600})


def test_troca_codigo_pendente_e_avisa():
    sb = FakeSB({"ml_pending_code": json.dumps({"code": "TG-abc", "redirect_uri": "https://x.github.io/fareja-preco/"})})
    avisos, cham = [], []
    ml = MercadoLivre(sb, "123", "seg", avisar=avisos.append, http=fake_http({"/oauth/token": TOKENS}, cham))
    assert ml.preparar() and ml.access == "APP_USR-novo"
    assert "ml_pending_code" not in sb.s and sb.s["ml_refresh_token"] == "TG-refresh-2"
    assert cham[0][3]["grant_type"] == "authorization_code" and cham[0][3]["redirect_uri"].endswith("/fareja-preco/")
    assert json.loads(sb.s["ml_status"])["ok"] and "conectado" in avisos[0]


def test_usa_token_valido_sem_renovar():
    exp = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    cham = []
    ml = MercadoLivre(FakeSB({"ml_access_token": "A", "ml_access_expires": exp}), "1", "s", http=fake_http({}, cham))
    assert ml.preparar() and ml.access == "A" and cham == []


def test_renova_token_vencido_e_guarda_novo_refresh():
    exp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sb = FakeSB({"ml_access_token": "A", "ml_access_expires": exp, "ml_refresh_token": "TG-refresh-1",
                 "ml_status": json.dumps({"ok": True})})
    avisos = []
    ml = MercadoLivre(sb, "1", "s", avisar=avisos.append, http=fake_http({"/oauth/token": TOKENS}))
    assert ml.preparar() and sb.s["ml_refresh_token"] == "TG-refresh-2"
    assert avisos == []            # já estava conectado: não manda mensagem de novo


def test_refresh_invalido_avisa_uma_vez():
    sb = FakeSB({"ml_refresh_token": "TG-velho", "ml_status": json.dumps({"ok": True})})
    avisos = []
    ml = MercadoLivre(sb, "1", "s", avisar=avisos.append,
                      http=fake_http({"/oauth/token": (400, {"error": "invalid_grant"})}))
    assert not ml.preparar() and "expirou" in ml.erro and len(avisos) == 1
    ml2 = MercadoLivre(sb, "1", "s", avisar=avisos.append,
                       http=fake_http({"/oauth/token": (400, {"error": "invalid_grant"})}))
    assert not ml2.preparar() and len(avisos) == 1


def conectado(rotas):
    ml = MercadoLivre(FakeSB({}), "1", "s", http=fake_http(rotas))
    ml.access = "A"
    return ml


def test_ler_item_usa_sale_price():
    ml = conectado({
        "/items/MLB1111111111/sale_price": (200, {"amount": 1799.9, "regular_amount": 2199}),
        "/items/MLB1111111111": (200, {"id": "MLB1111111111", "title": "Geladeira Brastemp 375L", "price": 1899, "status": "active",
                                "available_quantity": 5}),
    })
    r = ml.ler("https://produto.mercadolivre.com.br/MLB-1111111111-geladeira-_JM")
    assert r.price == 1799.9 and r.title == "Geladeira Brastemp 375L" and r.in_stock


def test_ler_item_pausado_fica_sem_estoque():
    ml = conectado({"/items/MLB1111111111/sale_price": (404, {}),
                    "/items/MLB1111111111": (200, {"title": "X", "price": 100, "status": "paused"})})
    r = ml.ler("https://produto.mercadolivre.com.br/MLB-1111111111-x")
    assert r.price == 100 and r.in_stock is False


def test_ler_produto_catalogo_pelo_vencedor():
    ml = conectado({
        "/products/MLB99999999": (200, {"name": "Geladeira Brastemp Frost Free", "buy_box_winner": {"item_id": "MLB2222222222", "price": 2000}}),
        "/items/MLB2222222222/sale_price": (200, {"amount": 1950.0}),
        "/items/MLB2222222222": (200, {"title": "anúncio", "price": 2000, "status": "active"}),
    })
    r = ml.ler("https://www.mercadolivre.com.br/geladeira/p/MLB99999999")
    assert r.price == 1950.0 and r.title == "Geladeira Brastemp Frost Free"


def test_ler_produto_sem_vencedor_usa_menor_preco():
    ml = conectado({"/products/MLB99999999/items": (200, {"results": [{"price": 2100}, {"price": 1990.5}]}),
                    "/products/MLB99999999": (200, {"name": "G", "buy_box_winner": None})})
    assert ml.ler("https://www.mercadolivre.com.br/g/p/MLB99999999").price == 1990.5


def test_link_curto_e_resolvido():
    ml = conectado({"/items/MLB3333333333/sale_price": (200, {"amount": 50}), "/items/MLB3333333333": (200, {"title": "t", "status": "active"})})
    r = ml.ler("https://meli.la/abc", resolver=lambda u: "https://produto.mercadolivre.com.br/MLB-3333333333-x")
    assert r.price == 50


def test_sem_conexao_cai_para_html_e_explica():
    ml = MercadoLivre(FakeSB({}), "1", "s", http=fake_http({}))
    ml.erro = "ainda não conectado (clique em Conectar Mercado Livre no site)"

    class Nav:
        def get(self, url):
            class R:
                status, url_, text = 200, url, "<html>account-verification</html>"
            r = R()
            r.url = url
            return r

    with pytest.raises(ErroColeta, match="Conectar Mercado Livre"):
        ler_preco("https://produto.mercadolivre.com.br/MLB-1234567890-x", "mercadolivre", Nav(), ml)
