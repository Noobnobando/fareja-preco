"""Coletor de preços.

Uso:
  python -m coletor                       # verifica todas as ofertas e manda alertas
  python -m coletor --teste URL [URL...]  # só testa a leitura de preço, sem banco de dados
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .alertas import Novo, Registro, avaliar_item, brl, mensagem_falha
from .http import Navegador, pausa
from .lojas import LOJAS, detectar_loja, ler_preco
from .parse import ErroColeta
from .supa import Supabase
from . import telegram

FALHAS_PARA_AVISAR = 3          # avisa no Telegram na 3ª falha seguida de uma oferta
REGISTRAR_IGUAL_APOS_HORAS = 20  # grava um ponto mesmo sem mudança, 1x por dia, para o gráfico


def env(nome: str, obrigatorio: bool = True) -> str:
    v = os.environ.get(nome, "").strip()
    if obrigatorio and not v:
        sys.exit(f"Faltou configurar a variável {nome} (veja o README).")
    return v


def testar(urls: list[str]) -> int:
    nav = Navegador()
    erros = 0
    for i, url in enumerate(urls):
        if i:
            pausa(1, 3)
        loja = detectar_loja(url)
        try:
            r = ler_preco(url, loja, nav)
            estoque = "" if r.in_stock else "  (sem estoque)"
            print(f"OK   {LOJAS[loja]:<14} {brl(r.price):>14}{estoque}  {r.title or ''}")
        except ErroColeta as e:
            erros += 1
            print(f"ERRO {LOJAS[loja]:<14} {e}")
        except Exception as e:  # noqa: BLE001
            erros += 1
            print(f"ERRO {LOJAS[loja]:<14} {type(e).__name__}: {e}")
    return 1 if erros else 0


def rodar() -> int:
    sb = Supabase(env("SUPABASE_URL"), env("SUPABASE_SERVICE_KEY"))
    min_queda = float(os.environ.get("MIN_QUEDA_PCT", "3") or 3)
    agora = datetime.now(timezone.utc)

    run = sb.insert("runs", {"started_at": agora.isoformat()}, returning=True)[0]

    itens = {i["id"]: i for i in sb.select("items", {"select": "*", "status": "neq.comprado"})}
    ofertas_todas = [o for o in sb.select("offers", {"select": "*"}) if o["item_id"] in itens]
    desde = (agora - timedelta(days=200)).isoformat()
    precos = sb.select("prices", {
        "select": "offer_id,price,shipping,in_stock,captured_at",
        "captured_at": f"gte.{desde}",
        "order": "captured_at.asc",
    })

    historico: dict[str, list[Registro]] = defaultdict(list)
    for p in precos:
        historico[p["offer_id"]].append(
            Registro(p["captured_at"], float(p["price"]),
                     None if p["shipping"] is None else float(p["shipping"]), bool(p["in_stock"])))

    a_verificar = [o for o in ofertas_todas if o.get("active") and (o.get("url") or "").strip()]
    random.shuffle(a_verificar)
    print(f"{len(itens)} itens pendentes, {len(a_verificar)} ofertas para verificar")

    nav = Navegador()
    novos: dict[str, Novo] = {}
    ok = falhas = 0
    for n, o in enumerate(a_verificar):
        if n:
            pausa()
        item = itens[o["item_id"]]
        loja = o.get("store") or detectar_loja(o["url"])
        rotulo = f"{item['name'][:40]:<40} {LOJAS.get(loja, loja):<14}"
        try:
            r = ler_preco(o["url"], loja, nav)
        except Exception as e:  # noqa: BLE001
            falhas += 1
            erro = str(e) if isinstance(e, ErroColeta) else f"erro inesperado ({type(e).__name__})"
            if not isinstance(e, ErroColeta):
                traceback.print_exc()
            fc = int(o.get("fail_count") or 0) + 1
            print(f"ERRO {rotulo} {erro}")
            sb.update("offers", {"id": o["id"]}, {
                "fail_count": fc, "last_error": erro[:300], "last_checked_at": agora.isoformat()})
            if fc == FALHAS_PARA_AVISAR:
                telegram.enviar(mensagem_falha(item, o, erro), o.get("url"))
            continue

        ok += 1
        novos[o["id"]] = Novo(r.price, r.in_stock)
        print(f"OK   {rotulo} {brl(r.price):>14}{'' if r.in_stock else ' (sem estoque)'}")

        ultimo = historico[o["id"]][-1] if historico[o["id"]] else None
        mudou = (ultimo is None or abs(ultimo.price - r.price) >= 0.01 or ultimo.in_stock != r.in_stock
                 or ultimo.shipping is not None)
        velho = ultimo is None or (agora - datetime.fromisoformat(ultimo.quando.replace("Z", "+00:00"))
                                   >= timedelta(hours=REGISTRAR_IGUAL_APOS_HORAS))
        if mudou or velho:
            sb.insert("prices", {"offer_id": o["id"], "price": r.price, "in_stock": r.in_stock,
                                 "source": "auto", "captured_at": agora.isoformat()})
        upd = {"fail_count": 0, "last_error": None, "last_checked_at": agora.isoformat()}
        if r.title and not o.get("title"):
            upd["title"] = r.title[:200]
        sb.update("offers", {"id": o["id"]}, upd)

    # alertas por item
    por_item: dict[str, list[dict]] = defaultdict(list)
    for o in ofertas_todas:
        por_item[o["item_id"]].append(o)
    enviados = 0
    for item_id, ofs in por_item.items():
        if not any(o["id"] in novos for o in ofs):
            continue
        alerta = avaliar_item(itens[item_id], ofs, historico, novos, min_queda, agora)
        if not alerta:
            continue
        if alerta.texto and telegram.enviar(alerta.texto, alerta.url):
            enviados += 1
        if alerta.mudou_last_alert:
            sb.update("items", {"id": item_id}, {"last_alert_price": alerta.novo_last_alert_price})

    sb.update("runs", {"id": run["id"]}, {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "checked": len(a_verificar), "ok": ok, "failed": falhas, "alerts": enviados})
    print(f"Fim: {ok} ok, {falhas} com erro, {enviados} alertas enviados")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="coletor", description="Coletor de preços do Caderno de Compras")
    ap.add_argument("--teste", nargs="+", metavar="URL", help="só testa a leitura destes links")
    a = ap.parse_args()
    sys.exit(testar(a.teste) if a.teste else rodar())


if __name__ == "__main__":
    main()
