"""Leitura de preço pelo API oficial do Mercado Livre (com login OAuth).

Fluxo de conexão:
  1. No site, "Conectar Mercado Livre" leva à página de autorização do ML.
  2. O ML volta para o site com ?code=TG-...; o site grava esse código em app_settings.
  3. Na próxima execução, o coletor troca o código por tokens e passa a renová-los sozinho.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .parse import ErroColeta, Leitura

API = "https://api.mercadolibre.com"
UA = "FarejaPreco/1.0 (+uso pessoal)"


# ----------------------------------------------------------------- links
def ids_ml(url: str) -> tuple[str, str] | None:
    """Descobre o que o link aponta: ('item', 'MLB123...') ou ('produto', 'MLB123...')."""
    u = urllib.parse.unquote(url)
    m = re.search(r"(?:item_id[:=]|wid=)(MLB\d{6,})", u, re.I)
    if m:
        return ("item", m.group(1).upper())
    m = re.search(r"/p/(MLB\d{5,})", u, re.I)
    if m:
        return ("produto", m.group(1).upper())
    caminho = urllib.parse.urlparse(u).path
    m = re.search(r"(MLB)-?(\d{6,})", caminho, re.I)
    if m:
        return ("item", "MLB" + m.group(2))
    return None


# ----------------------------------------------------------------- HTTP
def _http(method: str, path: str, token: str | None = None, form: dict | None = None) -> tuple[int, Any]:
    url = path if path.startswith("http") else API + path
    h = {"Accept": "application/json", "User-Agent": UA}
    data = None
    if token:
        h["Authorization"] = f"Bearer {token}"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, {"message": txt[:200]}


# ----------------------------------------------------------------- cliente
class MercadoLivre:
    """Guarda/renova os tokens na tabela app_settings (só o coletor lê os tokens)."""

    def __init__(self, sb, client_id: str, client_secret: str,
                 avisar: Callable[[str], Any] | None = None, http=_http) -> None:
        self.sb, self.cid, self.secret = sb, client_id, client_secret
        self.avisar = avisar or (lambda _t: None)
        self.http = http
        self.access: str | None = None
        self.erro: str | None = None

    # -- app_settings
    def _get(self) -> dict[str, str]:
        rows = self.sb.select("app_settings", {"select": "key,value", "key": "like.ml_*"})
        return {r["key"]: r["value"] for r in rows}

    def _set(self, **vals: str) -> None:
        agora = datetime.now(timezone.utc).isoformat()
        self.sb.upsert("app_settings", [{"key": k, "value": v, "updated_at": agora} for k, v in vals.items()])

    def _status(self, ok: bool, msg: str, anterior: str | None) -> None:
        novo = json.dumps({"ok": ok, "msg": msg, "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
        self._set(ml_status=novo)
        try:
            antes_ok = json.loads(anterior)["ok"] if anterior else None
        except (ValueError, KeyError, TypeError):
            antes_ok = None
        if ok and antes_ok is not True:
            self.avisar("✅ Mercado Livre conectado! Os preços de lá agora são lidos pela API oficial.")
        if not ok and antes_ok is not False:
            self.avisar(f"⚠️ Mercado Livre: {msg}\nAbra o site e clique em <b>Conectar Mercado Livre</b> de novo.")

    def _salvar_tokens(self, resp: dict) -> None:
        expira = datetime.now(timezone.utc) + timedelta(seconds=int(resp.get("expires_in") or 21600))
        vals = {"ml_access_token": resp["access_token"], "ml_access_expires": expira.isoformat()}
        if resp.get("refresh_token"):
            vals["ml_refresh_token"] = resp["refresh_token"]
        self._set(**vals)
        self.access = resp["access_token"]

    def preparar(self) -> bool:
        """Deixa um access token válido em self.access. Retorna False se não der."""
        cfg = self._get()
        status_antes = cfg.get("ml_status")

        pend = cfg.get("ml_pending_code")
        if pend:
            try:
                p = json.loads(pend)
            except ValueError:
                p = {"code": pend}
            self.sb.delete("app_settings", {"key": "ml_pending_code"})
            st, r = self.http("POST", "/oauth/token", form={
                "grant_type": "authorization_code", "client_id": self.cid, "client_secret": self.secret,
                "code": p.get("code", ""), "redirect_uri": p.get("redirect_uri", "")})
            if st == 200 and r and r.get("access_token"):
                self._salvar_tokens(r)
                if not r.get("refresh_token"):
                    self._status(True, "conectado, mas sem renovação automática: ative 'offline_access' no app do ML",
                                 status_antes)
                else:
                    self._status(True, "conectado", status_antes)
                return True
            msg = (r or {}).get("message") or (r or {}).get("error") or f"HTTP {st}"
            self.erro = f"não consegui concluir a conexão ({msg}). O código vale poucos minutos: conecte de novo e rode o robô logo em seguida"
            self._status(False, self.erro, status_antes)
            return False

        tok, exp = cfg.get("ml_access_token"), cfg.get("ml_access_expires")
        if tok and exp:
            try:
                if datetime.fromisoformat(exp) - datetime.now(timezone.utc) > timedelta(minutes=10):
                    self.access = tok
                    return True
            except ValueError:
                pass

        ref = cfg.get("ml_refresh_token")
        if not ref:
            self.erro = "ainda não conectado (clique em Conectar Mercado Livre no site)"
            return False
        st, r = self.http("POST", "/oauth/token", form={
            "grant_type": "refresh_token", "client_id": self.cid, "client_secret": self.secret, "refresh_token": ref})
        if st == 200 and r and r.get("access_token"):
            self._salvar_tokens(r)
            self._status(True, "conectado", status_antes)
            return True
        msg = (r or {}).get("message") or (r or {}).get("error") or f"HTTP {st}"
        self.erro = f"a conexão expirou ({msg})"
        self._status(False, self.erro, status_antes)
        return False

    # -- preços
    def _api(self, path: str) -> tuple[int, Any]:
        return self.http("GET", path, token=self.access)

    def ler(self, url: str, resolver: Callable[[str], str] | None = None) -> Leitura:
        if not self.access:
            raise ErroColeta(f"API do Mercado Livre: {self.erro or 'não conectada'}")
        alvo = ids_ml(url)
        if not alvo and resolver:
            alvo = ids_ml(resolver(url))      # link curto (meli.la) → link completo
        if not alvo:
            raise ErroColeta("não reconheci o código do anúncio neste link do Mercado Livre; "
                             "abra o produto no navegador e copie o link da barra de endereço")
        tipo, mid = alvo
        if tipo == "produto":
            return self._produto(mid)
        return self._item(mid)

    def _item(self, mid: str, titulo: str | None = None) -> Leitura:
        st, it = self._api(f"/items/{mid}?attributes=id,title,price,status,available_quantity")
        if st == 404:
            raise ErroColeta("anúncio não encontrado no Mercado Livre (pode ter sido removido)")
        if st != 200 or not it:
            raise ErroColeta(f"API do Mercado Livre respondeu HTTP {st}: {(it or {}).get('message', '')}"[:200])
        preco = None
        st2, sp = self._api(f"/items/{mid}/sale_price?context=channel_marketplace")
        if st2 == 200 and sp and sp.get("amount"):
            preco = float(sp["amount"])
        if not preco and it.get("price"):
            preco = float(it["price"])
        if not preco:
            raise ErroColeta("o Mercado Livre não informou preço para este anúncio")
        status = it.get("status")
        qtd = it.get("available_quantity")
        em_estoque = status == "active" and (qtd is None or qtd > 0)
        return Leitura(price=round(preco, 2), title=titulo or it.get("title"), in_stock=em_estoque)

    def _produto(self, pid: str) -> Leitura:
        st, p = self._api(f"/products/{pid}")
        if st != 200 or not p:
            raise ErroColeta(f"API do Mercado Livre (produto) respondeu HTTP {st}")
        nome = p.get("name")
        win = p.get("buy_box_winner") or {}
        if win.get("item_id"):
            try:
                return self._item(win["item_id"], titulo=nome)
            except ErroColeta:
                if win.get("price"):
                    return Leitura(price=round(float(win["price"]), 2), title=nome)
                raise
        st, lst = self._api(f"/products/{pid}/items")
        precos = [float(x["price"]) for x in (lst or {}).get("results", []) if x.get("price")]
        if precos:
            return Leitura(price=round(min(precos), 2), title=nome)
        raise ErroColeta("nenhum vendedor com este produto disponível no Mercado Livre agora")
