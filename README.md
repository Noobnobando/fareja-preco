# Caderno de Compras 

Lista de compras da casa com **monitoramento automático de preços** em Amazon, Mercado Livre, Magalu, Casas Bahia e Shopee, **histórico em gráfico** e **alertas no Telegram**.

```
 ┌──────────────┐   lê/edita    ┌──────────────┐   grava preços   ┌──────────────────────┐
 │  Site (docs) │ ────────────▶ │   Supabase   │ ◀─────────────── │ Coletor (GitHub      │
 │ GitHub Pages │               │ (banco grátis)│                  │ Actions, 4x por dia) │
 └──────────────┘               └──────────────┘                  └──────────┬───────────┘
                                                                              │ alertas
                                                                              ▼
                                                                       Bot do Telegram
```

- **Site**: vocês cadastram os itens e colam o link do produto em cada loja.
- **Coletor**: 4 vezes por dia (6h, 12h, 18h e 21h) abre cada link, lê o preço e grava no banco.
- **Bot**: manda mensagem quando:
  -  o preço cai 3% ou mais numa loja;
  -  o menor preço chega no **preço-alvo** que você definiu;
  -  é o menor preço desde que começaram a acompanhar (depois de 7 dias de histórico);
  -  uma loja falha 3 vezes seguidas (aí você pode registrar o preço na mão).

Tudo roda **de graça**. Leva uns 30–40 minutos para colocar no ar na primeira vez.

---

## Passo 1: GitHub (onde o código fica e o robô roda)

1. Crie uma conta em <https://github.com> (se ainda não tiver).
2. Clique em **New repository**. Nome: `caderno-compras`. Marque **Public** (precisa ser público para o site no GitHub Pages ser grátis; os dados ficam protegidos no Supabase, e as senhas ficam nos *Secrets*, que ninguém vê).
3. Na página do repositório: **Add file → Upload files** e arraste **todo o conteúdo** desta pasta (incluindo a pasta `.github`. Se o seu sistema esconder pastas que começam com ponto, veja a dica no fim).
4. Clique em **Commit changes**.

## Passo 2: Supabase (o banco de dados)

1. Crie uma conta em <https://supabase.com> e clique em **New project**. Região: **South America (São Paulo)**. Guarde a senha do banco.
2. No menu da esquerda, abra **SQL Editor**, cole o conteúdo de `supabase/schema.sql` e clique em **Run**.
3. Ainda no SQL Editor, libere os e-mails de vocês dois (troque pelos reais) e rode:
   ```sql
   insert into public.allowed_users (email) values ('voce@gmail.com'), ('ela@gmail.com');
   ```
4. Vá em **Project Settings → API** (ou **Data API / API Keys**) e anote:
   - **Project URL** (algo como `https://abcdxyz.supabase.co`)
   - **anon public** key → vai no site
   - **service_role** key → vai no robô (**é secreta**, nunca coloque no site)
5. Vá em **Authentication → URL Configuration** e em **Site URL** coloque o endereço do site do passo 4:
   `https://SEU-USUARIO.github.io/caderno-compras/`

> O plano grátis do Supabase pausa projetos sem uso por 7 dias. O robô acessa o banco 4x por dia, então isso não deve acontecer.

## Passo 3: Bot do Telegram

1. No Telegram, abra o **@BotFather**, mande `/newbot` e escolha um nome (ex.: *Preços da Casa*). Ele te dá um **token** parecido com `123456:ABC-xyz`.
2. Para os dois receberem os alertas: crie um **grupo** com você e ela, adicione o bot e mande no grupo `/start@NomeDoSeuBot`.
   (Se preferir só você: abra a conversa com o bot e mande `/start`.)
3. Descubra o **chat id** abrindo no navegador (troque o TOKEN):
   `https://api.telegram.org/botTOKEN/getUpdates`
   Procure `"chat":{"id": -1001234567890 ...`. Esse número (grupos começam com `-`) é o `TELEGRAM_CHAT_ID`.

## Passo 4: ligar tudo no GitHub

**Senhas do robô:** no repositório, **Settings → Secrets and variables → Actions → New repository secret**. Crie um por um:

| Nome | Valor |
|---|---|
| `SUPABASE_URL` | Project URL do Supabase |
| `SUPABASE_SERVICE_KEY` | chave **service_role** |
| `TELEGRAM_BOT_TOKEN` | token do BotFather |
| `TELEGRAM_CHAT_ID` | o número do chat |
| `SHOPEE_APP_ID` / `SHOPEE_APP_SECRET` | opcional, veja "Shopee" abaixo |

**Site:**
1. Edite o arquivo `docs/config.js` (clique nele no GitHub e depois no lápis ✏️) e coloque a **Project URL** e a **anon public key**. Commit.
2. **Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main`, pasta = `/docs`. Salve.
3. Em 1–2 minutos o site estará em `https://SEU-USUARIO.github.io/caderno-compras/`. Entre com seu e-mail e clique no link que chegar.

**Primeiro teste do robô:** aba **Actions → Coletor de preços → Run workflow**. Abra a execução para ver o log: cada linha mostra `OK` com o preço ou `ERRO` com o motivo. Se o GitHub perguntar se quer habilitar os workflows, confirme.

---

## Como usar no dia a dia

1. **Novo item** → nome, cômodo, quantidade e, se quiser, um **preço-alvo**.
2. Dentro do item, **+ Adicionar link de loja** → cole o link da página do produto. A loja é reconhecida sozinha.
   - Em **Frete para vocês**, coloque o frete que aparece para o seu CEP (o robô não consegue saber o frete). Ele entra na conta do "menor custo".
   - Se quiser, informe o preço que está vendo agora. Senão, o robô busca na próxima rodada.
3. Repita para cada loja. O card mostra sempre o **menor custo** e onde está.
4. Quando comprar, mude o status para **Comprado**. O valor pago entra no total "Já comprado" e o robô para de verificar o item.

Dá para registrar preços manualmente a qualquer momento (inclusive com data antiga) e apagar registros errados em "Todos os registros de preço".

---

## Sobre cada loja (seja realista 🙂)

| Loja | Como o robô lê | Chance de funcionar no GitHub Actions |
|---|---|---|
| **Mercado Livre** | dados estruturados da página do produto | boa |
| **Magalu** | dados estruturados da página | boa |
| **Amazon** | bloco de preço da página | média: às vezes pede captcha para servidores |
| **Casas Bahia** | dados estruturados da página | média/baixa: usa proteção anti-robô forte |
| **Shopee** | API oficial de afiliados | só com a API configurada |

Quando uma loja bloquear, o site mostra o aviso na oferta e o bot avisa na 3ª falha seguida. Você continua podendo registrar o preço na mão.

### Shopee
A Shopee bloqueia praticamente todo robô. O caminho confiável é a **API do programa de afiliados** (gratuita):
1. Cadastre-se em <https://affiliate.shopee.com.br> (a aprovação é manual e pode levar alguns dias).
2. No painel, abra **Open API** e copie o **App ID** e o **App Secret**.
3. Crie os secrets `SHOPEE_APP_ID` e `SHOPEE_APP_SECRET` no GitHub.
Use o link completo do produto (o que tem `-i.NUMERO.NUMERO` no final).

### Se a Amazon/Casas Bahia bloquearem muito: rodar no seu computador
Os servidores do GitHub são mais visados. Rodar o mesmo robô no seu PC (internet de casa) costuma funcionar bem melhor.

```bash
# uma vez
python -m venv .venv
.venv\Scripts\activate          # Windows   (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt

# testar links sem mexer no banco
python -m coletor --teste "https://www.amazon.com.br/dp/XXXXXXXXXX" "https://www.magazineluiza.com.br/..."

# rodar de verdade (defina as mesmas variáveis dos secrets antes)
set SUPABASE_URL=...            # Linux/Mac: export SUPABASE_URL=...
set SUPABASE_SERVICE_KEY=...
set TELEGRAM_BOT_TOKEN=...
set TELEGRAM_CHAT_ID=...
python -m coletor
```
No Windows, agende com o **Agendador de Tarefas**; no Linux/Raspberry Pi, com `cron`. Você pode deixar os dois (GitHub + PC) rodando; não tem problema.

---

## Ajustes

- **Horários**: em `.github/workflows/coletor.yml`, linha `cron` (horário UTC = Brasília + 3h).
- **Sensibilidade do alerta de queda**: crie em *Settings → Secrets and variables → Actions → Variables* a variável `MIN_QUEDA_PCT` (padrão `3`).
- **Pausar a verificação de uma loja**: no site, *Editar* a oferta e desmarcar "Verificar preço automaticamente".

## Problemas comuns

- **"Seu e-mail ainda não está liberado"**: faltou o passo 2.3 (inserir em `allowed_users`) ou o e-mail está diferente.
- **O link de login abre uma página de erro**: confira o *Site URL* do passo 2.5 (precisa terminar com `/`).
- **O robô não roda sozinho**: veja a aba *Actions*. O GitHub pode atrasar alguns minutos, e desliga agendamentos de repositórios sem commits há 60 dias. O workflow tenta se manter ativo sozinho; se mesmo assim aparecer como desativado, é só clicar em **Enable workflow**.
- **Pasta `.github` não subiu**: no GitHub, *Add file → Create new file*, digite o nome `.github/workflows/coletor.yml` e cole o conteúdo do arquivo.

## Estrutura

```
coletor/          robô em Python (lojas, alertas, Telegram, banco)
tests/            testes automáticos (python -m pytest -q)
docs/             site (GitHub Pages)
supabase/         script do banco de dados
.github/workflows agendamento do robô
```
