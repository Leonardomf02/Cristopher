# Pôr o Cristopher na NAS — guia completo

O Cristopher a correr na NAS QNAP do Pedro (TS-431KX, ARM 32 bits), ao lado da
Gestão da PedroTec e do Cinespot. A receita é a mesma do Cinespot; o que muda vem
assinalado.

**Link final:** https://<NAS_HOST>:8443 — o `NAS_HOST` está no `.env.nas`, fora do git: o repositório é público e o endereço é uma porta aberta na casa do Pedro.
**Password:** a `CRISTOPHER_PASSWORD` do [`nas-compose.yml`](nas-compose.yml)

> Menus em **inglês**, como aparecem no painel.

**Estado (27/09/2026):** a app corre na NAS com a base verdadeira, o link abre
de fora, e o **agente do Mac está instalado** (Screen Time, tracker, champ select
e Reminders). O backend e o frontend do Mac foram desligados: a
`backend/cristopher.db` do Mac é uma cópia velha.

## Portas

| Porta | O quê |
|---|---|
| **8443** | HTTPS, aberta no router. É o reverse proxy da NAS que escuta aqui |
| **9011** | o contentor — só dentro da NAS |

**Porquê 8443 e não 90xx:** a rede da universidade bloqueia portas altas de saída.
Testado: 9006, 9010 e 5000 fechadas, 8443 aberta. Numa porta 90xx a app não abria
de lá — nem no browser, nem o agente do Mac.

## Antes de começar: a app deixa de viver no Mac

A partir do Passo 1 a base verdadeira é a da NAS. Dois backends a escrever em duas
bases é perder dados — por isso o backend do Mac pára **antes** de a base ser
copiada, e não volta a arrancar contra a `backend/cristopher.db`, que passa a ser
uma cópia velha.

---

## Passo 0 — construir e enviar a imagem

```bash
IMG=cristopher:v6 ./build-nas.sh /tmp/cristopher-nas-v6.tar
./deploy-nas.sh /tmp/cristopher-nas-v6.tar
```

Fica em `/Web/cristopher/cristopher-nas-v6.tar`. O `build-nas.sh` recusa-se a
exportar se alguma biblioteca que a app carrega estiver mal alinhada (ver o fim).

## Passo 1 — parar o Mac e enviar os dados

```bash
./scripts/launchd/uninstall.sh     # desliga o backend e o frontend do Mac
./deploy-nas.sh --dados
```

Vai tudo para `/Container/cristopher-dados`.

> **A pasta é essa e não a que a Container Station cria.** Ao montar o volume, ela
> cria `/Container/cristopher/data` como root e com permissões 755 — o File Station
> não consegue escrever lá dentro (o envio devolve `status 4`/`status 9` e o
> ficheiro nunca aparece), e copiar para lá também falha em silêncio. Uma pasta
> criada por nós na raiz da share fica nossa e aceita escrita; o contentor corre
> como root e escreve lá na mesma.

| Ficheiro | Para quê |
|---|---|
| `cristopher.db` | a base — fotografia consistente (`VACUUM INTO`) |
| `uploads/` | recibos |
| `garmin/garmin_tokens.json` | o relógio continua a sincronizar sem novo login (a Garmin bloqueia 48h a quem repete logins) |
| `enablebanking.pem` | a ligação ao banco continua válida |
| `push_keys.json`, `push_key.pem` | os avisos no telemóvel usam as mesmas chaves |

O `--dados` **recusa-se a pisar uma base que já esteja na NAS**. Para substituir
mesmo: parar a aplicação na Container Station e usar `--forcar`.

## Passo 2 — importar a imagem

**Container Station → Images → Import**
→ escolher `/Web/cristopher/cristopher-nas-v6.tar`
→ caixa **"create container" DESMARCADA**
→ esperar

Fica na lista como **`cristopher:v6`**.

> Desmarcada porque, se ela criar o contentor sozinha, cria-o sem a porta, sem a
> pasta de dados e sem as chaves — a app não arrancava (sem `JWT_SECRET` com
> password definida, recusa-se).

## Passo 3 — criar a aplicação

**Container Station → Applications → Create** → nome `cristopher` → colar o
conteúdo de **[`nas-compose.yml`](nas-compose.yml)** → **Validate** → **Create**.

O YAML já traz as chaves todas (as do `backend/.env`), a password da app, um
`JWT_SECRET` novo e o endereço de regresso do banco. Está fora do git de
propósito: o repositório é **público**.

- **Limites de CPU não vão no YAML**: a Container Station recusa-o ("Resources:
  Configure resource limitations in Advanced Settings"). Se a app estiver a abafar
  a Gestão do Pedro, limitar depois, nas *Advanced Settings* do contentor.
- **`JWT_SECRET` tem de ser sempre o mesmo**: se mudar, a sessão cai em todos os
  dispositivos (a password mantém-se).

### Se não existir "Applications"

**Images → linha do `cristopher:v6` → Create Container**, e em **Advanced Settings**:

| Definição | Valor |
|---|---|
| Container name | `cristopher` |
| Network → Port Forwarding | Host **9011** → Container **8001** (TCP) |
| Shared Folder / Volume | `/Container/cristopher-dados` → `/data` |
| Environment | todas as linhas do `environment:` do `nas-compose.yml` |
| Restart policy | `unless-stopped` |

Não mexer no *Command* nem no *Entrypoint* — já vêm na imagem.

## Passo 4 — confirmar que arrancou

Em **Containers** fica *Running*, e nos **logs** aparece:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001
```

Mensagens `[migrate] …` no arranque são normais. Os trabalhos que não correram
hoje recuperam logo a seguir (banco, Garmin, jogos de LoL, preços).

## Passo 5 — HTTPS (reverse proxy)

**Fazer antes de pedir a porta ao Pedro**: a app nunca deve estar aberta à
internet em `http://` — a password viajava sem cifra, e no telemóvel nem abre
(`ERR_SSL_PROTOCOL_ERROR`).

```
Control Panel → Network & File Services → Network Access → separador "Reverse Proxy"
→ Add / Criar
```

| Campo | Valor |
|---|---|
| Source — Protocol | **HTTPS** |
| Source — Hostname | `<NAS_HOST>` |
| Source — Port | **8443** |
| Destination — Protocol | **HTTP** |
| Destination — Hostname | `127.0.0.1` |
| Destination — Port | **9011** |
| Certificate | o certificado da NAS (myQNAPcloud) |

→ Apply

Se a NAS disser que a 8443 já está em uso por outro serviço, usar outra porta
aqui, no pedido ao Pedro, no `BANK_REDIRECT_URL` do YAML e no Passo 7.

## Passo 6 — pedido ao Pedro

**Sem isto o link nunca abre de fora.**

```
Preciso de duas coisas para o Cristopher abrir de fora:

1) No router, abrir a porta 8443 para a NAS:
   Port Forwarding -> porta externa 8443 -> IP da NAS, porta 8443, TCP

2) Na app QuFirewall da NAS, criar uma regra:
   Permission: Allow | Interface: All | Source: Any | Protocol: TCP | Port: 8443
   Tem de ficar ACIMA da última linha ("Any Any Any Deny"), senão não faz efeito.
```

Para testar de fora da rede dele:

```bash
nc -z -G 8 <NAS_HOST> 8443 && echo aberta || echo fechada
```

## Passo 7 — ligar o resto

1. **Entrar** em https://<NAS_HOST>:8443 com a password.
2. **Telemóvel**: abrir o link novo → *Adicionar ao ecrã principal* → activar os
   avisos na app. A app instalada do endereço antigo não passa sozinha para o novo.
3. **Banco** — no painel do Enable Banking, na aplicação → *Redirect URLs* →
   acrescentar `https://<NAS_HOST>:8443/expenses`. Sem isto, ligar
   outro banco ou renovar o consentimento falha no regresso.
4. **Atalho iOS da captura rápida** — mudar o URL para
   `https://<NAS_HOST>:8443/api/ingest/capture` (o
   `X-Ingest-Token` é o mesmo).
5. **Agente do Mac** (tracker de apps, Screen Time, o **champ select** do LoL,
   que só o Mac vê — ver `lol_live.py` — e a ponte para os **Reminders da
   Apple**), no Mac:
   ```bash
   CRISTOPHER_CLOUD_URL=https://<NAS_HOST>:8443 \
   INGEST_TOKEN=<o INGEST_TOKEN do nas-compose.yml> \
   ./agent/install.sh
   ```
   E dar **Full Disk Access** ao Python que o script indicar. Com o Mac desligado a
   app continua online; ao ligar, o agente envia o que faltou. **Instalado a
   27/09/2026**, e com ele o backend e o frontend do Mac foram desligados
   (`scripts/launchd/uninstall.sh`).

---

## O que não funciona na NAS

Precisam do macOS e ficam desligados (`CLOUD=1`) ou respondem "só no Mac":

| O quê | Porquê |
|---|---|
| LoL: jogo ao vivo, treinador, previsões | lêem o cliente do LoL no Mac. Os **jogos** continuam a entrar (API da Riot), e o **champ select** também, empurrado pelo agente |
| Calendário da Apple (importar/exportar) | AppleScript — responde 501 |
| Actividade de código do VS Code | histórico local do editor. O **WakaTime** funciona |
| Importar PDF e OCR de recibos | o `pdftotext` e o `tesseract` não carregam na NAS (ver o fim) |
| Ícones das apps no Screen Time | vêm dos `.app` do Mac |
| Avisos do macOS (manhã, orçamento, fim da tarde, eventos) | balão do macOS; os avisos por Web Push continuam |
| Paragens do Mac para o sono | o sono vem do Garmin |
| Modelo local (Ollama) | ver abaixo |

## Modelo local: desligado

`LOCAL_AI=0`. O Ollama não tem versão para ARM de 32 bits, um processo de 32 bits
não chega aos ~9 GB que o `qwen3.5:9b` ocupa, e a NAS tem 8 GB partilhados com as
apps do Pedro. O que muda:

- a **cor pela foto** nos Deals deixa de existir (a cor fica "o anúncio não diz");
- a categorização de CSV importado vai ao agente (tecto `lojas_banco`, 6/dia);
- com os dois agentes em baixo, a IA diz "indisponível" em vez de cair no local.

---

## Se falhar

Ver os *logs* do contentor.

| Sintoma | Causa |
|---|---|
| Link a carregar e **nada nos logs** | Os pedidos não chegam à NAS → falta o Passo 6 |
| `ERR_SSL_PROTOCOL_ERROR` | Falta o reverse proxy (Passo 5) ou abriu em `http://` |
| `CRISTOPHER_PASSWORD definida sem JWT_SECRET` | O YAML não foi colado inteiro (Passo 3) |
| `ELF load command ... not page-aligned` | Biblioteca por corrigir → ver o fim |
| App abre mas vazia | A base não foi para `/share/Container/cristopher-dados` (Passo 1) |
| "Demasiadas tentativas" no login | 10 passwords erradas em 15 minutos — esperar |
| Toda a gente desligada de repente | `JWT_SECRET` mudou entre versões |
| Banco falha ao voltar | Falta o URL nas Redirect URLs (Passo 7) |
| Relógio sem dados novos | Token do Garmin em falta ou caducado → correr `backend/scripts/garmin_login.py` no Mac e enviar o `~/.garminconnect/garmin_tokens.json` pelo File Station para `/Container/cristopher-dados/garmin` |
| Dados desaparecem ao recriar | Volume `/data` não montado (Passo 3) |

---

## Manutenção

### Actualizar depois de mudar código

```bash
IMG=cristopher:v6 ./build-nas.sh /tmp/cristopher-nas-v6.tar
./deploy-nas.sh /tmp/cristopher-nas-v6.tar          # sem --dados: a base fica na NAS
```

Importar e mudar a etiqueta no YAML. **Usar sempre etiqueta nova** (`v2`, `v3`, …):
reutilizar a mesma faz a Container Station ficar com a versão antiga em cache.

### Cópias de segurança

A app faz a cópia dela às 5h, dentro do volume:

```
/share/Container/cristopher-dados/backups     (14 dias)
```

A base em si é `/share/Container/cristopher-dados/cristopher.db` — com os ficheiros
`-wal` e `-shm` ao lado enquanto a app corre (modo WAL). Para a trazer para o Mac,
usar a cópia das 5h, não o ficheiro com a app a correr.

---

## Porque é que a imagem tem de ser feita à medida

**1. Páginas de memória de 32K.** Como no Cinespot e na Gestão: quase todo o
software Linux vem alinhado a 4K e o kernel da NAS recusa-o. Das bibliotecas que
esta app carrega, só a **`libz`** e a **`libbz2`** vêm mal — o
[`Dockerfile.nas`](Dockerfile.nas) recompila-as a 64K.

A verificação é mais apertada do que a do Cinespot, que procurava por nomes: o
[`scripts/verifica-alinhamento.py`](scripts/verifica-alinhamento.py) corre dentro
da imagem, carrega a app e os módulos que ela só importa a meio do caminho
(Garmin, avisos, curl_cffi, PDFs…) e confere **tudo o que ficou carregado** — uma
dependência nova mal alinhada não passa despercebida.

O `pdftotext` e o `tesseract` do Debian ficaram de fora por isto: carregam **10** e
**9** bibliotecas a 4K (NSS, gmp, rtmp, psl, leptonica…). Para os ter era preciso
compilá-los de raiz.

**2. Dependências sem versão ARM de 32 bits.** O `cffi` (do `curl_cffi`) e o
`pillow` (do `reportlab`) compilam-se na imagem; o `uvloop` e o `httptools` não
fazem falta e ficam de fora (`uvicorn` simples).

**3. Formato do ficheiro.** A Container Station só lê o formato Docker clássico —
o [`scripts/para-formato-classico.py`](scripts/para-formato-classico.py) converte.

**4. Uma imagem só.** O FastAPI serve também o build do React: uma porta, sem CORS,
e o HTTPS resolve-se de uma vez no reverse proxy.

Não verificável fora da NAS: o Mac emula ARM com páginas de 4K. A confirmação final
é o `Application startup complete` na própria NAS.
