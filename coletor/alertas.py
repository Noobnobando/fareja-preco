"""Decide quando mandar mensagem no Telegram. Funções puras, fáceis de testar."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape

from .lojas import LOJAS


def brl(v: float) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class Registro:
    quando: str          # ISO 8601
    price: float
    shipping: float | None
    in_stock: bool = True


@dataclass
class Novo:
    price: float
    in_stock: bool = True


@dataclass
class Alerta:
    texto: str
    url: str | None
    novo_last_alert_price: float | None
    mudou_last_alert: bool
    linhas: list[str] = field(default_factory=list)


def na(loja: str) -> str:
    return ("no " if loja == "Mercado Livre" else "na ") + loja


def custo(oferta: dict, price: float, shipping: float | None) -> float:
    frete = shipping if shipping is not None else (oferta.get("frete") or 0)
    return round(float(price) + float(frete), 2)


def avaliar_item(item: dict, ofertas: list[dict], historico: dict[str, list[Registro]],
                 novos: dict[str, Novo], min_queda_pct: float = 3.0,
                 agora: datetime | None = None) -> Alerta | None:
    agora = agora or datetime.now(timezone.utc)
    nome_loja = lambda o: LOJAS.get(o.get("store"), o.get("store") or "Loja")  # noqa: E731

    antes: dict[str, float] = {}
    for o in ofertas:
        regs = [r for r in historico.get(o["id"], []) if r.in_stock]
        if regs:
            r = regs[-1]
            antes[o["id"]] = custo(o, r.price, r.shipping)

    agora_custo: dict[str, float | None] = {}
    for o in ofertas:
        n = novos.get(o["id"])
        if n is not None:
            agora_custo[o["id"]] = custo(o, n.price, None) if n.in_stock else None
        else:
            agora_custo[o["id"]] = antes.get(o["id"])

    linhas: list[str] = []

    # 1) queda de preço numa loja
    for o in ofertas:
        n = novos.get(o["id"])
        if n is None or not n.in_stock or o["id"] not in antes:
            continue
        a, d = antes[o["id"]], agora_custo[o["id"]]
        if d is not None and a > 0 and d <= a * (1 - min_queda_pct / 100):
            pct = (a - d) / a * 100
            linhas.append(f"📉 {escape(nome_loja(o))}: {brl(a)} → <b>{brl(d)}</b> (−{pct:.0f}%)")

    validos = [(c, o) for o in ofertas if (c := agora_custo.get(o["id"])) is not None]
    if not validos:
        return None
    melhor, melhor_oferta = min(validos, key=lambda x: x[0])
    melhor_e_novo = melhor_oferta["id"] in novos

    # 2) preço-alvo
    alvo = item.get("target_price")
    last = item.get("last_alert_price")
    novo_last, mudou = last, False
    if alvo is not None:
        alvo = float(alvo)
        if melhor <= alvo and (last is None or melhor < float(last) - 0.005):
            linhas.append(f"🎯 Chegou no seu preço-alvo de {brl(alvo)}")
            novo_last, mudou = melhor, True
        elif melhor > alvo and last is not None:
            novo_last, mudou = None, True   # rearma: avisa de novo se voltar a cair

    # 3) menor preço já registrado (só depois de 7 dias de histórico)
    todos = [(r, o) for o in ofertas for r in historico.get(o["id"], []) if r.in_stock]
    if todos and melhor_e_novo:
        primeiro = min(datetime.fromisoformat(r.quando.replace("Z", "+00:00")) for r, _ in todos)
        if agora - primeiro >= timedelta(days=7):
            minimo = min(custo(o, r.price, r.shipping) for r, o in todos)
            # recorde precisa ser pelo menos metade do limite de queda abaixo do mínimo anterior
            if melhor <= minimo * (1 - min_queda_pct / 200) - 0.005:
                linhas.append(f"🏆 Menor preço desde que começamos a acompanhar (antes: {brl(minimo)})")

    if not linhas:
        if mudou:
            return Alerta("", None, novo_last, True)
        return None

    qtd = int(item.get("qty") or 1)
    texto = "\n".join([
        f"🛒 <b>{escape(item.get('name') or 'Item')}</b>",
        *linhas,
        f"Melhor agora: <b>{brl(melhor)}</b> {escape(na(nome_loja(melhor_oferta)))}"
        + (f" ({qtd} un. = {brl(melhor * qtd)})" if qtd > 1 else ""),
    ])
    return Alerta(texto, melhor_oferta.get("url"), novo_last, mudou, linhas)


def mensagem_falha(item: dict, oferta: dict, erro: str) -> str:
    loja = LOJAS.get(oferta.get("store"), oferta.get("store") or "Loja")
    return (f"⚠️ Não estou conseguindo ler o preço de <b>{escape(item.get('name') or 'Item')}</b> "
            f"{escape(na(loja))}: {escape(erro)}.\n"
            f"Você pode registrar o preço manualmente no site enquanto isso.")
