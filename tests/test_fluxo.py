"""Simula uma execução completa do coletor com banco e lojas falsos."""
from datetime import datetime, timedelta, timezone

import coletor.__main__ as m
from coletor.parse import ErroColeta, Leitura


class FakeSB:
    def __init__(self, *a):
        dez = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self.t = {
            "items": [{"id": "i1", "name": "Panela", "qty": 1, "status": "pesquisando",
                       "target_price": 450, "last_alert_price": None}],
            "offers": [
                {"id": "a", "item_id": "i1", "store": "amazon", "url": "https://www.amazon.com.br/dp/B000000001",
                 "active": True, "fail_count": 0, "frete": None, "title": None},
                {"id": "c", "item_id": "i1", "store": "casasbahia", "url": "https://www.casasbahia.com.br/p/1",
                 "active": True, "fail_count": 2, "frete": None, "title": "x"},
            ],
            "prices": [{"offer_id": "a", "price": 529.9, "shipping": None, "in_stock": True, "captured_at": dez}],
            "runs": [],
        }
        self.updates = []

    def select(self, table, params):
        rows = self.t[table]
        if table == "items":
            rows = [r for r in rows if r["status"] != "comprado"]
        return list(rows)

    def insert(self, table, row, returning=False):
        row = dict(row, id=len(self.t[table]) + 1)
        self.t[table].append(row)
        return [row]

    def update(self, table, match, values):
        self.updates.append((table, match, values))


def test_execucao_completa(monkeypatch):
    sb = FakeSB()
    enviados = []
    monkeypatch.setenv("SUPABASE_URL", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "y")
    monkeypatch.setattr(m, "Supabase", lambda *a: sb)
    monkeypatch.setattr(m, "pausa", lambda *a: None)
    monkeypatch.setattr(m.telegram, "enviar", lambda txt, url=None: enviados.append((txt, url)) or True)

    def fake_ler(url, loja, nav, ml=None):
        if loja == "casasbahia":
            raise ErroColeta("a loja bloqueou o robô")
        return Leitura(price=440.91, title="Jogo de Panelas")
    monkeypatch.setattr(m, "ler_preco", fake_ler)

    assert m.rodar() == 0
    novos = [p for p in sb.t["prices"] if p.get("source") == "auto"]
    assert len(novos) == 1 and novos[0]["price"] == 440.91
    textos = "\n".join(t for t, _ in enviados)
    assert "📉 Amazon" in textos and "🎯" in textos and "🏆" in textos
    assert "Não estou conseguindo ler" in textos          # 3ª falha da Casas Bahia
    assert ("items", {"id": "i1"}, {"last_alert_price": 440.91}) in sb.updates
    run_upd = [u for u in sb.updates if u[0] == "runs"][0][2]
    assert run_upd["ok"] == 1 and run_upd["failed"] == 1 and run_upd["alerts"] == 1  # falhas não contam
