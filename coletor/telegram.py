"""Envio de mensagens pelo bot do Telegram."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _api(token: str, metodo: str, body: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{metodo}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "description": e.read().decode()[:300]}


def enviar(texto: str, url: str | None = None, rotulo: str = "Abrir na loja") -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("[telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não configurados; mensagem:\n" + texto)
        return False
    body = {"chat_id": chat, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True}
    if url:
        body["reply_markup"] = {"inline_keyboard": [[{"text": rotulo, "url": url}]]}
    r = _api(token, "sendMessage", body)
    if not r.get("ok"):
        print(f"[telegram] falhou: {r.get('description')}", file=sys.stderr)
    return bool(r.get("ok"))


def descobrir_chat_id() -> None:
    """python -m coletor.telegram  → mostra os chats que falaram com o bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or input("Token do bot: ").strip()
    r = _api(token, "getUpdates")
    if not r.get("ok"):
        print("Erro:", r.get("description"))
        return
    vistos = {}
    for u in r.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat:
            vistos[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username")
    if not vistos:
        print("Nenhuma mensagem encontrada. Mande /start para o bot (ou no grupo) e rode de novo.")
    for cid, nome in vistos.items():
        print(f"TELEGRAM_CHAT_ID = {cid}   ({nome})")


if __name__ == "__main__":
    descobrir_chat_id()
