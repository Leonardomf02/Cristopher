"""Reminders do Cristopher ↔ Reminders da Apple, nos dois sentidos.

O que ele escreve no iPhone aparece aqui e vice-versa. Cada lista do Cristopher
espelha uma lista da Apple com o mesmo nome; a ligação é feita uma vez e a partir
daí vive nos ids (`user_lists.apple_id`, `list_items.apple_id`), por isso mudar o
nome de um dos lados não desliga nada — mas também não se propaga.

Quem ganha um conflito: **a edição mais recente**. Compara-se o conteúdo dos dois
lados; se for igual não se toca em nada, e se for diferente ganha o lado com a
data de alteração mais tarde (`list_items.updated_at` contra a `modified` do
reminder).

Apagar propaga: o que desaparece da Apple é apagado aqui, e o que ele apaga aqui
deixa uma lápide (`reminder_tombstones`) que manda apagar o reminder na passagem
seguinte — sem isso, o item voltava a nascer, porque "não existe deste lado" é
exactamente o que também se parece com "acabou de ser criado do outro".

A conversa com a Apple é pelo EventKit (`tools/reminders`, Swift), não por
AppleScript: ler os 250 reminders dele leva 0,6s pelo EventKit e 37s por
AppleScript, onde cada propriedade é um Apple Event à parte.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models import ListItem, ReminderTombstone, UserList

logger = logging.getLogger(__name__)

BIN = os.path.join(os.path.dirname(__file__), "tools", "reminders")
FONTE = BIN + ".swift"

# Um reminder feito há muito tempo não vale a pena importar: a lista "Lembretes"
# dele tem 218 coisas feitas desde 2024 e despejá-las nas Listas era enterrar as
# que interessam. Isto só trava a **importação** — o que já está ligado continua
# a sincronizar para sempre.
DIAS_PARA_IMPORTAR_FEITOS = 30

# Cristopher: 0 nenhuma, 1 baixa, 2 média, 3 alta. Apple: 0, 9, 5, 1.
_PRIO_PARA_APPLE = {0: 0, 1: 9, 2: 5, 3: 1}

_lock = threading.Lock()


def _compila() -> bool:
    """O binário não vai para o repositório: compila-se à primeira utilização."""
    if os.access(BIN, os.X_OK):
        return True
    if not os.path.exists(FONTE) or not shutil.which("swiftc"):
        return False
    try:
        r = subprocess.run(["swiftc", "-O", "-o", BIN, FONTE],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            logger.info("ponte para os Reminders compilada")
            return True
        logger.warning("não consegui compilar a ponte dos Reminders: %s", r.stderr[:300])
    except Exception as ex:
        logger.warning("swiftc rebentou: %s", ex)
    return False


def disponivel() -> bool:
    return sys.platform == "darwin" and os.getenv("CLOUD") != "1" and _compila()


class SemAcesso(RuntimeError):
    """O macOS não deu acesso aos Reminders a quem está a correr isto."""


def _corre(comando: str, entrada: Optional[dict] = None, timeout: int = 120) -> dict:
    if not _compila():
        raise RuntimeError("ponte para os Reminders indisponível (falta o swiftc?)")
    r = subprocess.run(
        [BIN, comando],
        input=json.dumps(entrada) if entrada is not None else None,
        capture_output=True, text=True, timeout=timeout,
    )
    try:
        saida = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        raise RuntimeError(f"resposta ilegível ({r.returncode}): {(r.stderr or r.stdout)[:200]}")
    if not saida.get("ok"):
        erro = saida.get("error", "erro desconhecido")
        if r.returncode == 2:
            raise SemAcesso(erro)
        raise RuntimeError(erro)
    return saida


def estado() -> dict:
    """O que a página mostra antes de sincronizar seja o que for."""
    if sys.platform != "darwin":
        return {"disponivel": False, "motivo": "só no Mac"}
    if not _compila():
        return {"disponivel": False, "motivo": "falta o swiftc para compilar a ponte"}
    try:
        d = _corre("dump")
    except SemAcesso as ex:
        return {"disponivel": False, "acesso": False, "motivo": str(ex)}
    except Exception as ex:
        return {"disponivel": False, "motivo": str(ex)}
    return {
        "disponivel": True,
        "acesso": True,
        "listas": [l["name"] for l in d["lists"]],
        "reminders": len(d["reminders"]),
    }


# ── comparar os dois lados ───────────────────────────────────────

def _norm(nome: str) -> str:
    return (nome or "").strip().casefold()


def _prio_local(apple: int) -> int:
    if not apple:
        return 0
    if apple <= 4:
        return 3
    if apple == 5:
        return 2
    return 1


def _quando(texto: Optional[str], *, utc: bool = True) -> Optional[datetime]:
    """As datas vêm da Apple com fuso; as da base não têm nenhum e são UTC
    (`func.now()` do SQLite), tirando as que a app escreve à mão, que são locais.
    Daí as duas saídas."""
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if d.tzinfo is None:
        return d
    return (d.astimezone(timezone.utc) if utc else d.astimezone()).replace(tzinfo=None)


def _estado_local(item: ListItem, chave_lista: str) -> dict:
    return {
        "list": chave_lista,
        "title": (item.text or "").strip(),
        "notes": item.notes or "",
        "completed": bool(item.checked),
        "priority": _PRIO_PARA_APPLE.get(item.priority or 0, 0),
        "due_date": str(item.due_date) if item.due_date else None,
        "due_time": item.due_time or None,
    }


def _estado_apple(r: dict, chave_lista: str) -> dict:
    return {
        "list": chave_lista,
        "title": (r.get("title") or "").strip(),
        "notes": r.get("notes") or "",
        "completed": bool(r.get("completed")),
        "priority": int(r.get("priority") or 0),
        "due_date": r.get("due_date"),
        "due_time": r.get("due_time"),
    }


def _aplica_no_item(item: ListItem, r: dict, lista_local: UserList) -> None:
    from datetime import date as _date

    item.text = (r.get("title") or "").strip() or item.text
    item.notes = r.get("notes") or ""
    item.priority = _prio_local(int(r.get("priority") or 0))
    item.list_id = lista_local.id
    feito = bool(r.get("completed"))
    if feito != bool(item.checked):
        item.checked_at = (_quando(r.get("completed_at"), utc=False) or datetime.now()) if feito else None
    item.checked = feito
    if r.get("due_date"):
        try:
            item.due_date = _date.fromisoformat(r["due_date"])
        except ValueError:
            item.due_date = None
    else:
        item.due_date = None
    item.due_time = r.get("due_time")


# ── a passagem ───────────────────────────────────────────────────

def sincroniza(db: Session) -> dict:
    """Uma passagem completa. Devolve o que mudou, para o registo do trabalho."""
    if not _lock.acquire(blocking=False):
        return {"ignorado": "já estava a sincronizar"}
    try:
        return _sincroniza(db)
    finally:
        _lock.release()


def _sincroniza(db: Session) -> dict:
    d = le_apple()
    if repara_emblemas(d):
        d = le_apple()
    ops, conta = planeia(db, d)
    if not any(ops.values()):
        return conta
    conta.update(regista_aplicado(db, ops, aplica(ops)))
    return conta


# ── ícone e cor das listas ───────────────────────────────────────
# O EventKit não dá o ícone de uma lista nem diz se ela tem cor. Lêem-se da base
# da própria app Lembretes (só leitura, precisa do Full Disk Access que o agente
# já tem para o Screen Time) e escrevem-se por AppleScript (`emblem` e `color`).
# Ler por AppleScript abria a app Lembretes a cada passagem — fechá-la não
# servia de nada, voltava 25 segundos depois. Escrever abre-a, mas só quando há
# de facto um ícone ou uma cor a mudar. O ícone é um emoji, o mesmo que o iPhone
# mostra. A primeira escrita pede autorização ao macOS para controlar a app
# Lembretes; sem ela, o nome e os itens continuam a sincronizar.
_BASES_DOS_LEMBRETES = "~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/*.sqlite"


def _estilos_da_base() -> Optional[dict[str, tuple[Optional[str], Optional[str]]]]:
    """id da lista → (emblema, cor em #RRGGBB). None se a base não se deixa ler."""
    import glob
    import sqlite3
    out: dict = {}
    ficheiros = glob.glob(os.path.expanduser(_BASES_DOS_LEMBRETES))
    lidos = 0
    for f in ficheiros:
        try:
            con = sqlite3.connect(f"file:{f}?mode=ro", uri=True, timeout=5)
            try:
                linhas = con.execute(
                    "SELECT ZCKIDENTIFIER, ZBADGEEMBLEM, ZCOLOR FROM ZREMCDBASELIST "
                    "WHERE ZCKIDENTIFIER IS NOT NULL AND COALESCE(ZMARKEDFORDELETION, 0) = 0").fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        lidos += 1
        for ident, emblema, cor in linhas:
            out[ident] = (emblema, _hex_da_cor(cor))
    return out if lidos else None


# O ícone de uma lista é um `REMListBadge`: ou um símbolo ("cart"), guardado pelo
# nome, ou um emoji, guardado como `{"Emoji" : "🛒"}`. O AppleScript só conhece o
# primeiro — pôr lá "🛒" cru é pedir um símbolo chamado 🛒, que a app não tem, e
# ela desenha o ícone por omissão sem dar erro nenhum. Foi o que aconteceu às
# listas todas: a cor passava, o ícone ficava igual em todas.
def _emblema_para_apple(emoji: str) -> str:
    return json.dumps({"Emoji": emoji}, ensure_ascii=False).replace('":', '" :')


def _le_emblema(cru: Optional[str]) -> tuple[Optional[str], bool]:
    """(emoji ou nome do símbolo, escrito cru por engano). O segundo é o emoji
    que o AppleScript antigo gravou como se fosse um símbolo."""
    if not cru:
        return None, False
    if cru.lstrip().startswith("{"):
        try:
            return (json.loads(cru).get("Emoji") or None), False
        except (ValueError, AttributeError):
            return None, False
    return cru, not cru.isascii()


def _hex_da_cor(blob) -> Optional[str]:
    """O `REMColor` vem num NSKeyedArchiver; o que interessa é o `daHexString`
    ("#FF9500FF" — o alfa no fim sai)."""
    if not blob:
        return None
    try:
        import plistlib
        objs = plistlib.loads(blob).get("$objects") or []
        for o in objs:
            if isinstance(o, dict) and "daHexString" in o:
                valor = objs[o["daHexString"].data]
                return str(valor)[:7].upper() if isinstance(valor, str) else None
    except Exception:
        return None
    return None

# Pela procura (`whose`) e não por `byId`: uma lista acabada de criar pelo
# EventKit ainda não se encontra pelo id directo.
_JS_PINTA = """
function run(argv) {
  const ops = JSON.parse(argv[0]);
  const R = Application('Reminders');
  const ok = [], erros = [];
  for (const o of ops) {
    try {
      const achadas = R.lists.whose({id: o.id})();
      if (!achadas.length) throw new Error('lista não encontrada');
      if (o.icon) achadas[0].emblem = o.icon;
      if (o.color) achadas[0].color = o.color;
      ok.push(o.id);
    } catch (e) { erros.push('estilo ' + o.id + ': ' + e.message); }
  }
  return JSON.stringify({ok, erros});
}
"""


def _jxa(codigo: str, *args: str, timeout: int = 60) -> Optional[dict]:
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", codigo, *args],
                           capture_output=True, text=True, timeout=timeout)
    except Exception as ex:
        logger.warning("osascript rebentou: %s", ex)
        return None
    if r.returncode != 0:
        logger.warning("ícones das listas indisponíveis: %s", (r.stderr or "")[:200])
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def le_apple() -> dict:
    """O `dump` do EventKit, com o ícone e a cor de cada lista quando a app
    Lembretes os deixa ler (`estilo: True`)."""
    d = _corre("dump")
    por_id = _estilos_da_base()
    if por_id is not None:
        for l in d.get("lists") or []:
            if l["id"] in por_id:
                cru, l["as_color"] = por_id[l["id"]]
                l["emblem"], partido = _le_emblema(cru)
                l["estilo"] = True
                if partido:
                    l["emblem_partido"] = True
    return d


def repara_emblemas(d: dict) -> list[str]:
    """Reescreve no formato certo os emojis que foram gravados crus.

    Do lado do Cristopher esses ícones já contam como enviados, por isso a
    decisão de sempre nunca os voltava a mandar — ficavam partidos para sempre.
    Corre uma vez por lista: depois de reescrito, deixa de estar partido."""
    pintar = [{"id": l["id"], "icon": _emblema_para_apple(l["emblem"])}
              for l in d.get("lists") or []
              if l.get("emblem_partido") and not l.get("readonly")]
    if not pintar:
        return []
    res = _jxa(_JS_PINTA, json.dumps(pintar, ensure_ascii=False))
    for erro in (res or {}).get("erros") or []:
        logger.warning("reparar ícone: %s", erro)
    return (res or {}).get("ok") or []


def aplica(ops: dict) -> dict:
    """Escreve na Apple o que `planeia` decidiu: o EventKit trata dos itens e
    das listas, o AppleScript do ícone e da cor."""
    r = _corre("apply", ops, timeout=300)
    def _estilo(aid: str, o: dict) -> dict:
        return {"id": aid, "icon": _emblema_para_apple(o["icon"]) if o.get("icon") else None,
                "color": o.get("color")}

    pintar = []
    for u in ops.get("update_lists") or []:
        if u.get("icon") or u.get("color"):
            pintar.append(_estilo(u["id"], u))
    for c in ops.get("create_lists") or []:
        aid = (r.get("lists") or {}).get(c.get("ref"))
        if aid and (c.get("icon") or c.get("color")):
            pintar.append(_estilo(aid, c))
    if pintar:
        res = _jxa(_JS_PINTA, json.dumps(pintar, ensure_ascii=False))
        r["styled_lists"] = (res or {}).get("ok") or []
        r["errors"] = list(r.get("errors") or []) + ((res or {}).get("erros") or
                                                       ([] if res else ["sem acesso à app Lembretes (ícones)"]))
    return r


def _emoji(emblema: Optional[str]) -> Optional[str]:
    """O ícone da Apple só se traz quando é um emoji. Os outros ("default", ou
    um símbolo escolhido no iPhone) não têm como ser mostrados aqui."""
    return emblema if emblema and not emblema.isascii() else None


def _decide(local, apple, base) -> str:
    """Quem mudou foi o lado que já não tem o último valor em comum. Se
    mudaram os dois, ganha o Cristopher — é onde ele está a mexer agora. Sem
    valor em comum guardado (listas ligadas antes disto), também: até aqui o
    nome, o ícone e a cor não passavam de um lado para o outro, por isso uma
    diferença é uma mudança dele que ficou por enviar."""
    if local == apple:
        return "igual"
    if base is not None and local == base:
        # o que a Apple tem agora não se consegue mostrar aqui: fica como está
        return "trazer" if apple is not None else "nada"
    return "enviar"


def _reconcilia_lista(lst: UserList, a: dict, ops: dict, conta: dict, so_leitura: bool) -> None:
    upd: dict = {}
    campos = [("name", "apple_name", (lst.name or "").strip(), (a.get("name") or "").strip() or None)]
    # Ícone e cor vêm por AppleScript (o EventKit não os dá); sem essa leitura
    # não se decide nada, senão a falta de resposta parecia "a Apple não tem".
    if a.get("estilo"):
        campos += [
            ("icon", "apple_icon", lst.icon or None, _emoji(a.get("emblem"))),
            ("color", "apple_color", (lst.color or "").upper() or None, (a.get("as_color") or "").upper() or None),
        ]
    for campo, coluna_base, local, apple in campos:
        decisao = _decide(local, apple, getattr(lst, coluna_base))
        if decisao == "igual":
            setattr(lst, coluna_base, local)
        elif decisao == "trazer":
            setattr(lst, campo, apple)
            setattr(lst, coluna_base, apple)
            conta["trazidos"] += 1
        elif decisao == "enviar" and not so_leitura and local is not None:
            upd[campo] = local
    if upd:
        ops["update_lists"].append({"id": a["id"], **upd})
        if "name" in upd:
            conta["listas_renomeadas"] += 1
        if "icon" in upd or "color" in upd:
            conta["listas_pintadas"] += 1


def planeia(db: Session, d: dict) -> tuple[dict, dict]:
    """Compara o que a Apple tem (`d`, a saída do `dump`) com a base, aplica aqui
    o que vem de lá e devolve o que falta fazer do lado da Apple.

    Está separado da escrita na Apple porque na NAS são duas máquinas: a NAS
    decide (a base é dela) e o agente do Mac lê e escreve nos Reminders. Os
    `ref` são `L<id>`/`I<id>` para a resposta poder voltar noutro pedido."""
    apple_listas = {l["id"]: l for l in d["lists"]}
    apple_rem = {r["id"]: r for r in d["reminders"]}

    ops: dict = {"create_lists": [], "update_lists": [], "delete_lists": [],
                 "create": [], "update": [], "delete": []}
    conta = {"importados": 0, "enviados": 0, "trazidos": 0, "empurrados": 0,
             "apagados_aqui": 0, "apagados_na_apple": 0, "listas_novas": 0,
             "listas_renomeadas": 0, "listas_pintadas": 0, "listas_apagadas": 0}
    lapides = {t.apple_id for t in db.query(ReminderTombstone).all()}
    so_leitura = {aid for aid, a in apple_listas.items() if a.get("readonly")}

    # ── listas ───────────────────────────────────────────────────
    # Uma lista que ele apagou aqui deixa lápide com o id da lista da Apple: a
    # lista vai-se de lá também. Sem isto voltava na passagem seguinte, vazia,
    # como se tivesse sido criada no iPhone.
    for aid in list(apple_listas):
        if aid in lapides:
            if aid not in so_leitura:
                ops["delete_lists"].append(aid)
                conta["listas_apagadas"] += 1
            del apple_listas[aid]

    locais = db.query(UserList).all()
    lista_de_apple: dict[str, UserList] = {}     # id da lista Apple → lista local
    chave_da_lista: dict[int, str] = {}          # lista local → id Apple ou "ref:…"
    usadas: set[str] = set()

    for lst in locais:
        if lst.apple_id and lst.apple_id in apple_listas:
            lista_de_apple[lst.apple_id] = lst
            chave_da_lista[lst.id] = lst.apple_id
            usadas.add(lst.apple_id)
            _reconcilia_lista(lst, apple_listas[lst.apple_id], ops, conta,
                              lst.apple_id in so_leitura)

    for lst in locais:
        if lst.id in chave_da_lista:
            continue
        par = next((a for aid, a in apple_listas.items()
                    if aid not in usadas and _norm(a["name"]) == _norm(lst.name)), None)
        if par:
            lst.apple_id = par["id"]
            lst.apple_name = par["name"]
            lista_de_apple[par["id"]] = lst
            chave_da_lista[lst.id] = par["id"]
            usadas.add(par["id"])
        else:
            # Inclui o caso de uma lista Apple apagada à mão: recria-se e os
            # itens voltam a ser enviados, em vez de se apagarem daqui.
            ref = f"L{lst.id}"
            ops["create_lists"].append({"ref": ref, "name": (lst.name or "Cristopher").strip(),
                                        "icon": lst.icon or None, "color": (lst.color or "").upper() or None})
            chave_da_lista[lst.id] = f"ref:{ref}"
            lst.apple_id = None
            conta["listas_novas"] += 1

    for aid, a in apple_listas.items():
        if aid in usadas:
            continue
        from sqlalchemy import func as _f
        maior = db.query(_f.max(UserList.position)).scalar() or 0
        icone, cor = _emoji(a.get("emblem")), (a.get("as_color") or "").upper() or None
        nova = UserList(name=a["name"], icon=icone or "📝", color=cor or a.get("color") or "#3B82F6",
                        position=maior + 1, apple_id=aid, apple_name=a["name"],
                        apple_icon=icone, apple_color=cor)
        db.add(nova)
        db.flush()
        lista_de_apple[aid] = nova
        chave_da_lista[nova.id] = aid
        conta["listas_novas"] += 1

    # ── itens ────────────────────────────────────────────────────
    itens = db.query(ListItem).all()
    por_apple_id = {i.apple_id: i for i in itens if i.apple_id}
    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    limite_feitos = agora_utc - timedelta(days=DIAS_PARA_IMPORTAR_FEITOS)

    for rid, r in apple_rem.items():
        if rid in lapides:
            ops["delete"].append(rid)
            conta["apagados_na_apple"] += 1
            continue

        lista_local = lista_de_apple.get(r.get("list") or "")
        if not lista_local:
            continue

        item = por_apple_id.get(rid)
        if item is None:
            if r.get("completed"):
                feito_em = _quando(r.get("completed_at"))
                if feito_em is None or feito_em < limite_feitos:
                    continue
            from sqlalchemy import func as _f
            maior = (db.query(_f.max(ListItem.position))
                     .filter(ListItem.list_id == lista_local.id).scalar() or 0)
            item = ListItem(list_id=lista_local.id, text=(r.get("title") or "").strip() or "(sem título)",
                            position=maior + 1, apple_id=rid)
            _aplica_no_item(item, r, lista_local)
            db.add(item)
            conta["importados"] += 1
            continue

        chave = chave_da_lista.get(item.list_id)
        if not chave:
            continue
        local = _estado_local(item, chave)
        remoto = _estado_apple(r, r.get("list") or "")
        if local == remoto:
            continue

        mudou_apple = _quando(r.get("modified")) or datetime.min
        mudou_aqui = item.updated_at or item.created_at or datetime.min
        if mudou_apple > mudou_aqui or (r.get("list") or "") in so_leitura:
            _aplica_no_item(item, r, lista_de_apple[r["list"]])
            conta["trazidos"] += 1
        else:
            ops["update"].append({"id": rid, **local})
            conta["empurrados"] += 1

    for item in itens:
        if item.apple_id:
            if item.apple_id in apple_rem or item.apple_id in lapides:
                continue
            # Sumiu do lado da Apple. Só conta como apagado se a lista onde ele
            # vivia continua lá — uma lista inteira que desapareceu volta a ser
            # criada, e apagar aqui seria perder o que ele tem.
            lst = next((l for l in locais if l.id == item.list_id), None)
            if lst is not None and lst.apple_id:
                db.delete(item)
                conta["apagados_aqui"] += 1
                continue
            # A lista sumiu do outro lado e está a ser recriada nesta mesma
            # passagem: o item volta a ser enviado, sem esperar pela próxima.
            item.apple_id = None

        chave = chave_da_lista.get(item.list_id)
        if not chave:
            continue
        if chave in so_leitura:
            continue
        ref = f"I{item.id}"
        ops["create"].append({"ref": ref, **_estado_local(item, chave)})
        conta["enviados"] += 1

    db.commit()
    return ops, conta


def _guarda_estilo(lst: UserList, op: dict) -> None:
    if op.get("icon") is not None:
        lst.apple_icon = op["icon"]
    if op.get("color") is not None:
        lst.apple_color = op["color"].upper()


def _id_do_ref(ref: str, letra: str) -> Optional[int]:
    if not ref or ref[0] != letra:
        return None
    try:
        return int(ref[1:])
    except ValueError:
        return None


def regista_aplicado(db: Session, ops: dict, r: dict) -> dict:
    """Guarda os ids que a Apple deu ao que foi criado e arruma as lápides
    gastas. `ops` é o que `planeia` devolveu; `r` a resposta do `apply`."""
    for ref, aid in (r.get("lists") or {}).items():
        lid = _id_do_ref(ref, "L")
        lst = db.get(UserList, lid) if lid is not None else None
        if lst is not None:
            lst.apple_id = aid
            lst.apple_name = lst.name
    # Só depois de a Apple confirmar: se a renomeação falhar, o nome em comum
    # fica o antigo e a próxima passagem volta a tentar em vez de trazer o
    # nome velho de volta.
    nomes = {l["id"]: l["name"] for l in ops.get("update_lists") or [] if "name" in l}
    for aid in r.get("renamed_lists") or []:
        for lst in db.query(UserList).filter(UserList.apple_id == aid).all():
            lst.apple_name = nomes.get(aid, lst.name)
    pintadas = set(r.get("styled_lists") or [])
    for u in ops.get("update_lists") or []:
        if u["id"] in pintadas:
            for lst in db.query(UserList).filter(UserList.apple_id == u["id"]).all():
                _guarda_estilo(lst, u)
    for c in ops.get("create_lists") or []:
        aid = (r.get("lists") or {}).get(c.get("ref"))
        lid = _id_do_ref(c.get("ref") or "", "L")
        lst = db.get(UserList, lid) if lid is not None else None
        if aid in pintadas and lst is not None:
            _guarda_estilo(lst, c)
    for ref, rid in (r.get("created") or {}).items():
        iid = _id_do_ref(ref, "I")
        item = db.get(ListItem, iid) if iid is not None else None
        if item is not None:
            item.apple_id = rid
        else:
            # Apagado aqui entre o plano e a escrita na Apple (na NAS são dois
            # pedidos). Sem lápide, o reminder acabado de criar voltava a entrar
            # como se ele o tivesse escrito no iPhone.
            marca_apagado(db, rid)
    apagados = list(ops.get("delete") or []) + list(r.get("deleted_lists") or [])
    if apagados:
        (db.query(ReminderTombstone)
           .filter(ReminderTombstone.apple_id.in_(apagados))
           .delete(synchronize_session=False))

    db.commit()
    extra: dict = {}
    if r.get("errors"):
        logger.warning("sincronização dos Reminders com queixas: %s", r["errors"][:5])
        extra["erros"] = r["errors"][:5]
    return extra


def impressao(db: Session) -> str:
    """Muda sempre que muda alguma coisa que vá para a Apple. É o que o agente
    do Mac espera para sincronizar logo, em vez de à hora."""
    import hashlib
    from sqlalchemy import text
    h = hashlib.sha1()
    for consulta in (
        "SELECT id, list_id, text, notes, checked, priority, due_date, due_time, apple_id "
        "FROM list_items ORDER BY id",
        "SELECT id, name, icon, color, apple_id FROM user_lists ORDER BY id",
        "SELECT apple_id FROM reminder_tombstones ORDER BY apple_id",
    ):
        for linha in db.execute(text(consulta)):
            h.update(repr(tuple(linha)).encode())
    return h.hexdigest()[:16]


# ── o agente do Mac (quando a app vive na NAS) ───────────────────
# Em memória: o que a página mostra é "quando foi a última passagem", e um
# reinício do backend só apaga isso até à passagem seguinte, um minuto depois.
_agente: dict = {"quando": None, "ok": True, "detalhe": ""}
_pedidos = 0


def regista_passagem_do_agente(ok: bool, detalhe: str) -> None:
    _agente.update(quando=datetime.now(), ok=ok, detalhe=detalhe)


def estado_do_agente() -> dict:
    return dict(_agente)


def pede_passagem() -> None:
    """O botão da página: acorda o agente sem esperar que algo mude."""
    global _pedidos
    _pedidos += 1


def pedidos() -> int:
    return _pedidos


def marca_apagado(db: Session, apple_id: Optional[str]) -> None:
    """Lápide para o apagar propagar. Chamado de quem apaga itens ou listas."""
    if not apple_id:
        return
    if db.query(ReminderTombstone).filter(ReminderTombstone.apple_id == apple_id).first():
        return
    db.add(ReminderTombstone(apple_id=apple_id))


def resumo(conta: dict) -> str:
    partes = []
    for chave, texto in (("importados", "importados"), ("enviados", "enviados"),
                         ("trazidos", "trazidos"), ("empurrados", "empurrados"),
                         ("apagados_aqui", "apagados aqui"),
                         ("apagados_na_apple", "apagados na Apple"),
                         ("listas_novas", "listas novas"),
                         ("listas_renomeadas", "listas renomeadas"),
                         ("listas_pintadas", "listas com ícone ou cor novos"),
                         ("listas_apagadas", "listas apagadas")):
        if conta.get(chave):
            partes.append(f"{conta[chave]} {texto}")
    return ", ".join(partes) or "nada a fazer"
