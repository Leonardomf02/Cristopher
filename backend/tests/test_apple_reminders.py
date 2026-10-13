"""A reconciliação com o Reminders da Apple, sem falar com a Apple.

O que estes testes prendem são as decisões que, quando falham, se pagam com
dados perdidos: quem ganha quando os dois lados mudaram, um item apagado que
volta a nascer, e uma lista da Apple que desapareceu levar consigo o que ele
tinha escrito aqui.

Corre sozinho:  python -m pytest tests/test_apple_reminders.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import apple_reminders as ar
from database import Base
from models import ListItem, ReminderTombstone, UserList

LISTA_APPLE = "cal-1"


@pytest.fixture(autouse=True)
def sem_applescript(monkeypatch):
    """Os testes nunca falam com a app Lembretes a sério."""
    monkeypatch.setattr(ar, "_jxa", lambda *a, **k: None)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


class AppleFalsa:
    """Guarda o dump que o binário devolveria e o que lhe mandaram fazer."""

    def __init__(self, listas=None, reminders=None):
        self.listas = listas if listas is not None else [{"id": LISTA_APPLE, "name": "todo", "color": "#111111"}]
        self.reminders = reminders or []
        self.ops = None

    def __call__(self, comando, entrada=None, timeout=120):
        if comando == "dump":
            return {"ok": True, "lists": self.listas, "reminders": self.reminders}
        self.ops = entrada
        return {
            "ok": True,
            "lists": {l["ref"]: f"nova-{l['ref']}" for l in entrada.get("create_lists", [])},
            "created": {c["ref"]: f"novo-{c['ref']}" for c in entrada.get("create", [])},
            "updated": len(entrada.get("update", [])),
            "deleted": len(entrada.get("delete", [])),
            "renamed_lists": [l["id"] for l in entrada.get("update_lists", [])],
            "deleted_lists": list(entrada.get("delete_lists", [])),
            "errors": [],
        }


def reminder(rid="r1", **kw):
    base = {"id": rid, "list": LISTA_APPLE, "title": "uma coisa", "notes": "",
            "completed": False, "priority": 0, "modified": "2026-08-19T12:00:00+01:00"}
    base.update(kw)
    return base


def corre(monkeypatch, db, apple):
    monkeypatch.setattr(ar, "_corre", apple)
    return ar.sincroniza(db)


def lista_local(db, **kw):
    l = UserList(name=kw.pop("name", "todo"), position=0, **kw)
    db.add(l)
    db.commit()
    return l


# ── importar ─────────────────────────────────────────────────────

def test_reminder_novo_entra_na_lista_espelho(monkeypatch, db):
    lista_local(db)
    apple = AppleFalsa(reminders=[reminder(title="comprar pão", priority=1, due_date="2026-09-01", due_time="08:30")])
    conta = corre(monkeypatch, db, apple)

    assert conta["importados"] == 1
    item = db.query(ListItem).one()
    assert item.text == "comprar pão"
    assert item.priority == 3          # a prioridade 1 da Apple é a alta
    assert str(item.due_date) == "2026-09-01" and item.due_time == "08:30"


def test_lista_da_apple_sem_par_nasce_aqui(monkeypatch, db):
    apple = AppleFalsa(listas=[{"id": "cal-x", "name": "Lembretes", "color": "#FF0000"}])
    corre(monkeypatch, db, apple)

    nova = db.query(UserList).one()
    assert nova.name == "Lembretes" and nova.apple_id == "cal-x" and nova.color == "#FF0000"


def test_a_lista_liga_se_pelo_nome_mesmo_com_espacos(monkeypatch, db):
    lista_local(db, name="Compras  ")
    apple = AppleFalsa(listas=[{"id": "cal-9", "name": "compras", "color": "#111111"}])
    corre(monkeypatch, db, apple)

    assert db.query(UserList).count() == 1
    assert db.query(UserList).one().apple_id == "cal-9"


def test_feito_ha_muito_tempo_nao_se_importa(monkeypatch, db):
    lista_local(db)
    velho = (datetime.now(timezone.utc) - timedelta(days=ar.DIAS_PARA_IMPORTAR_FEITOS + 5)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    apple = AppleFalsa(reminders=[reminder(completed=True, completed_at=velho)])
    conta = corre(monkeypatch, db, apple)

    assert conta["importados"] == 0
    assert db.query(ListItem).count() == 0


def test_feito_ontem_ainda_se_importa(monkeypatch, db):
    lista_local(db)
    ontem = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    apple = AppleFalsa(reminders=[reminder(completed=True, completed_at=ontem)])

    assert corre(monkeypatch, db, apple)["importados"] == 1
    assert db.query(ListItem).one().checked is True


# ── enviar ───────────────────────────────────────────────────────

def test_item_novo_daqui_vai_para_a_apple(monkeypatch, db):
    l = lista_local(db, apple_id=LISTA_APPLE)
    db.add(ListItem(list_id=l.id, text="pagar a renda", priority=2))
    db.commit()
    apple = AppleFalsa()
    corre(monkeypatch, db, apple)

    criado = apple.ops["create"][0]
    assert criado["title"] == "pagar a renda"
    assert criado["priority"] == 5                     # média, na escala da Apple
    assert criado["list"] == LISTA_APPLE
    assert db.query(ListItem).one().apple_id.startswith("novo-")


def test_lista_daqui_sem_par_e_criada_la(monkeypatch, db):
    lista_local(db, name="Uni")
    apple = AppleFalsa(listas=[])
    corre(monkeypatch, db, apple)

    assert [l["name"] for l in apple.ops["create_lists"]] == ["Uni"]
    assert db.query(UserList).one().apple_id == "nova-L1"


# ── conflitos ────────────────────────────────────────────────────

def _par(db, *, texto_local, texto_apple, mudou_aqui, mudou_na_apple):
    l = lista_local(db, apple_id=LISTA_APPLE)
    item = ListItem(list_id=l.id, text=texto_local, apple_id="r1", updated_at=mudou_aqui)
    db.add(item)
    db.commit()
    return AppleFalsa(reminders=[reminder(title=texto_apple, modified=mudou_na_apple)])


def test_ganha_quem_mexeu_por_ultimo_do_lado_da_apple(monkeypatch, db):
    apple = _par(db, texto_local="antigo", texto_apple="novo do iPhone",
                 mudou_aqui=datetime(2026, 8, 19, 10, 0),          # a base guarda em UTC
                 mudou_na_apple="2026-08-19T13:00:00+01:00")       # 12:00 UTC
    conta = corre(monkeypatch, db, apple)

    assert conta["trazidos"] == 1 and conta["empurrados"] == 0
    assert db.query(ListItem).one().text == "novo do iPhone"


def test_ganha_quem_mexeu_por_ultimo_deste_lado(monkeypatch, db):
    apple = _par(db, texto_local="novo daqui", texto_apple="antigo",
                 mudou_aqui=datetime(2026, 8, 19, 14, 0),
                 mudou_na_apple="2026-08-19T13:00:00+01:00")
    conta = corre(monkeypatch, db, apple)

    assert conta["empurrados"] == 1 and conta["trazidos"] == 0
    assert apple.ops["update"][0]["title"] == "novo daqui"


def test_o_fuso_horario_nao_decide_o_conflito(monkeypatch, db):
    """A hora da Apple é local e a da base é UTC. Sem converter, uma edição de
    há 20 minutos no Mac perdia para uma de há 40 na Apple."""
    apple = _par(db, texto_local="daqui", texto_apple="da apple",
                 mudou_aqui=datetime(2026, 8, 19, 12, 40),         # 13:40 em Lisboa
                 mudou_na_apple="2026-08-19T13:20:00+01:00")       # 20 min antes
    corre(monkeypatch, db, apple)

    assert db.query(ListItem).one().text == "daqui"


def test_conteudo_igual_nao_mexe_em_nada(monkeypatch, db):
    apple = _par(db, texto_local="a mesma coisa", texto_apple="a mesma coisa",
                 mudou_aqui=datetime(2026, 1, 1), mudou_na_apple="2026-08-19T13:00:00+01:00")
    conta = corre(monkeypatch, db, apple)

    assert conta["trazidos"] == 0 and conta["empurrados"] == 0
    assert apple.ops is None


# ── apagar ───────────────────────────────────────────────────────

def test_apagado_na_apple_desaparece_daqui(monkeypatch, db):
    l = lista_local(db, apple_id=LISTA_APPLE)
    db.add(ListItem(list_id=l.id, text="já não existe lá", apple_id="r1"))
    db.commit()
    conta = corre(monkeypatch, db, AppleFalsa(reminders=[]))

    assert conta["apagados_aqui"] == 1
    assert db.query(ListItem).count() == 0


def test_lapide_manda_apagar_do_outro_lado_e_desaparece(monkeypatch, db):
    lista_local(db, apple_id=LISTA_APPLE)
    db.add(ReminderTombstone(apple_id="r1"))
    db.commit()
    apple = AppleFalsa(reminders=[reminder()])
    conta = corre(monkeypatch, db, apple)

    assert conta["apagados_na_apple"] == 1
    assert apple.ops["delete"] == ["r1"]
    assert db.query(ReminderTombstone).count() == 0
    assert db.query(ListItem).count() == 0        # e não volta a ser importado


def test_lista_da_apple_apagada_nao_leva_os_itens_a_reboque(monkeypatch, db):
    """Uma lista que desapareceu do outro lado volta a ser criada. Apagar aqui
    seria perder o que ele escreveu por causa de um engano no iPhone."""
    l = lista_local(db, name="Uni", apple_id="cal-que-sumiu")
    db.add(ListItem(list_id=l.id, text="entregar o relatório", apple_id="r1"))
    db.commit()
    apple = AppleFalsa(listas=[])
    conta = corre(monkeypatch, db, apple)

    assert conta["apagados_aqui"] == 0
    assert db.query(ListItem).one().text == "entregar o relatório"
    assert [c["title"] for c in apple.ops["create"]] == ["entregar o relatório"]


# ── listas só de leitura ─────────────────────────────────────────

def test_lista_partilhada_so_de_leitura_nunca_recebe_escritas(monkeypatch, db):
    l = lista_local(db, apple_id=LISTA_APPLE)
    db.add(ListItem(list_id=l.id, text="escrito aqui"))
    db.commit()
    apple = AppleFalsa(listas=[{"id": LISTA_APPLE, "name": "todo", "color": "#111", "readonly": True}])
    conta = corre(monkeypatch, db, apple)

    assert conta["enviados"] == 0
    assert apple.ops is None


# ── na NAS: decidir aqui, escrever no Mac ────────────────────────

def test_plano_e_aplicado_em_dois_pedidos(monkeypatch, db):
    """Na NAS o plano e a escrita na Apple são pedidos diferentes: o que foi
    criado tem de ficar ligado pelo ref, sem objectos em memória pelo meio."""
    lista = lista_local(db, apple_id=LISTA_APPLE)
    db.add(ListItem(list_id=lista.id, text="nova", position=0))
    db.commit()
    apple = AppleFalsa()
    ops, conta = ar.planeia(db, apple("dump"))
    assert conta["enviados"] == 1
    ar.regista_aplicado(db, ops, apple("apply", ops))
    item = db.query(ListItem).one()
    assert item.apple_id == f"novo-I{item.id}"


def test_apagado_entre_o_plano_e_a_escrita_nao_volta(monkeypatch, db):
    """Ele apaga o item enquanto o Mac o está a criar na Apple. Sem lápide, o
    reminder acabado de criar voltava a entrar como se viesse do iPhone."""
    lista = lista_local(db, apple_id=LISTA_APPLE)
    db.add(ListItem(list_id=lista.id, text="efémero", position=0))
    db.commit()
    apple = AppleFalsa()
    ops, _ = ar.planeia(db, apple("dump"))
    db.query(ListItem).delete()
    db.commit()
    resposta = apple("apply", ops)
    ar.regista_aplicado(db, ops, resposta)
    rid = next(iter(resposta["created"].values()))
    assert db.query(ReminderTombstone).filter_by(apple_id=rid).count() == 1


def test_a_impressao_muda_quando_ele_mexe_nas_listas(db):
    lista = lista_local(db)
    antes = ar.impressao(db)
    item = ListItem(list_id=lista.id, text="x", position=0)
    db.add(item)
    db.commit()
    depois = ar.impressao(db)
    assert antes != depois
    item.checked = True
    db.commit()
    assert ar.impressao(db) != depois



# ── listas: nome e apagar ────────────────────────────────────────

def test_nome_mudado_aqui_vai_para_a_apple(monkeypatch, db):
    lista = lista_local(db, name="todo", apple_id=LISTA_APPLE, apple_name="todo")
    lista.name = "Someday"
    db.commit()
    apple = AppleFalsa()
    conta = corre(monkeypatch, db, apple)
    assert apple.ops["update_lists"] == [{"id": LISTA_APPLE, "name": "Someday"}]
    assert conta["listas_renomeadas"] == 1
    assert db.get(UserList, lista.id).apple_name == "Someday"


def test_nome_mudado_no_iphone_chega_aqui(monkeypatch, db):
    lista = lista_local(db, name="todo", apple_id=LISTA_APPLE, apple_name="todo")
    apple = AppleFalsa(listas=[{"id": LISTA_APPLE, "name": "Casa"}])
    corre(monkeypatch, db, apple)
    assert apple.ops is None
    assert db.get(UserList, lista.id).name == "Casa"


def test_lista_ligada_antes_disto_manda_o_nome_daqui(monkeypatch, db):
    """Até agora o nome não passava: uma diferença é uma renomeação dele que
    ficou por enviar, não uma do iPhone."""
    lista_local(db, name="Someday", apple_id=LISTA_APPLE)
    apple = AppleFalsa()
    corre(monkeypatch, db, apple)
    assert apple.ops["update_lists"] == [{"id": LISTA_APPLE, "name": "Someday"}]


def test_renomeacao_que_falha_volta_a_tentar(monkeypatch, db):
    lista = lista_local(db, name="todo", apple_id=LISTA_APPLE, apple_name="todo")
    lista.name = "Someday"
    db.commit()
    apple = AppleFalsa()
    ops, _ = ar.planeia(db, apple("dump"))
    ar.regista_aplicado(db, ops, {"ok": True, "renamed_lists": [], "errors": ["não deu"]})
    ops, _ = ar.planeia(db, apple("dump"))
    assert ops["update_lists"] == [{"id": LISTA_APPLE, "name": "Someday"}]
    assert db.get(UserList, lista.id).name == "Someday"


def test_lista_apagada_aqui_e_apagada_na_apple_e_nao_volta(monkeypatch, db):
    """Voltava na passagem seguinte, vazia, como se viesse do iPhone."""
    lista = lista_local(db, apple_id=LISTA_APPLE)
    ar.marca_apagado(db, lista.apple_id)
    db.delete(lista)
    db.commit()
    apple = AppleFalsa(reminders=[reminder("r1")])
    conta = corre(monkeypatch, db, apple)
    assert apple.ops["delete_lists"] == [LISTA_APPLE]
    assert conta["listas_apagadas"] == 1
    assert db.query(UserList).count() == 0
    assert db.query(ReminderTombstone).count() == 0


def test_mudar_de_lista_move_na_apple(monkeypatch, db):
    a = lista_local(db, name="todo", apple_id=LISTA_APPLE, apple_name="todo")
    b = lista_local(db, name="Compras", apple_id="cal-2", apple_name="Compras")
    item = ListItem(list_id=a.id, text="uma coisa", position=0, apple_id="r1")
    db.add(item)
    db.commit()
    item.list_id = b.id
    item.updated_at = datetime(2030, 1, 1)
    db.commit()
    apple = AppleFalsa(listas=[{"id": LISTA_APPLE, "name": "todo"}, {"id": "cal-2", "name": "Compras"}],
                       reminders=[reminder("r1")])
    corre(monkeypatch, db, apple)
    assert [u["list"] for u in apple.ops["update"]] == ["cal-2"]



# ── ícone e cor das listas ───────────────────────────────────────

def _com_estilo(listas, estilos):
    """O que `le_apple` junta ao dump quando o AppleScript responde."""
    for l in listas:
        emblema, cor = estilos.get(l["id"], (None, None))
        l.update(emblem=emblema, as_color=cor, estilo=True)
    return listas


def test_o_icone_e_a_cor_daqui_vao_para_a_apple(monkeypatch, db):
    """Do lado da Apple as listas não tinham ícone nenhum: nasciam pelo EventKit,
    que não sabe pôr um."""
    lista_local(db, name="todo", icon="🏋️", color="#8b5cf6", apple_id=LISTA_APPLE, apple_name="todo")
    apple = AppleFalsa(listas=_com_estilo([{"id": LISTA_APPLE, "name": "todo"}], {}))
    ops, conta = ar.planeia(db, apple("dump"))
    assert ops["update_lists"] == [{"id": LISTA_APPLE, "icon": "🏋️", "color": "#8B5CF6"}]
    ar.regista_aplicado(db, ops, {"ok": True, "styled_lists": [LISTA_APPLE]})
    lst = db.query(UserList).one()
    assert (lst.apple_icon, lst.apple_color) == ("🏋️", "#8B5CF6")


def test_icone_mudado_no_iphone_chega_aqui(monkeypatch, db):
    lista_local(db, name="todo", icon="📝", color="#3B82F6", apple_id=LISTA_APPLE,
                apple_name="todo", apple_icon="📝", apple_color="#3B82F6")
    apple = AppleFalsa(listas=_com_estilo([{"id": LISTA_APPLE, "name": "todo"}],
                                          {LISTA_APPLE: ("🛒", "#FF9500")}))
    ops, _ = ar.planeia(db, apple("dump"))
    assert ops["update_lists"] == []
    lst = db.query(UserList).one()
    assert (lst.icon, lst.color) == ("🛒", "#FF9500")


def test_simbolo_da_apple_que_nao_e_emoji_nao_apaga_o_icone_daqui(monkeypatch, db):
    lista_local(db, name="todo", icon="📝", apple_id=LISTA_APPLE, apple_name="todo", apple_icon="📝")
    apple = AppleFalsa(listas=_com_estilo([{"id": LISTA_APPLE, "name": "todo"}], {LISTA_APPLE: ("house.fill", None)}))
    ar.planeia(db, apple("dump"))
    assert db.query(UserList).one().icon == "📝"


def test_sem_applescript_o_icone_nao_se_decide(monkeypatch, db):
    """Sem a leitura do AppleScript, "não sei" não pode parecer "a Apple não tem"."""
    lista_local(db, name="todo", icon="🏋️", apple_id=LISTA_APPLE, apple_name="todo")
    ops, _ = ar.planeia(db, AppleFalsa()("dump"))
    assert ops["update_lists"] == []


def test_lista_importada_traz_o_emoji_da_apple(monkeypatch, db):
    apple = AppleFalsa(listas=_com_estilo([{"id": "cal-9", "name": "Casa"}], {"cal-9": ("🏠", "#34C759")}))
    ar.planeia(db, apple("dump"))
    lst = db.query(UserList).one()
    assert (lst.name, lst.icon, lst.color) == ("Casa", "🏠", "#34C759")


# ── o formato do ícone na Apple ──────────────────────────────────
# Um emoji guarda-se como `{"Emoji" : "🛒"}`; cru ("🛒") é o nome de um símbolo
# que não existe e a app desenha o ícone por omissão.

def test_emoji_vai_para_a_apple_no_formato_que_ela_desenha(monkeypatch):
    pedidos = []
    monkeypatch.setattr(ar, "_jxa", lambda codigo, arg, **k: pedidos.append(arg) or {"ok": [], "erros": []})
    apple = AppleFalsa()
    monkeypatch.setattr(ar, "_corre", apple)
    ar.aplica({"update_lists": [{"id": LISTA_APPLE, "icon": "🛒", "color": "#10B981"}]})
    import json
    assert json.loads(pedidos[0]) == [{"id": LISTA_APPLE, "icon": '{"Emoji" : "🛒"}', "color": "#10B981"}]


def _dump_com_base(monkeypatch, crus):
    monkeypatch.setattr(ar, "_corre", AppleFalsa(listas=[{"id": k, "name": k} for k in crus]))
    monkeypatch.setattr(ar, "_estilos_da_base", lambda: {k: (v, None) for k, v in crus.items()})
    return ar.le_apple()


def test_le_o_emoji_escrito_pela_apple(monkeypatch):
    d = _dump_com_base(monkeypatch, {"a": '{"Emoji" : "🛒"}', "b": "house.fill", "c": None})
    por_id = {l["id"]: l for l in d["lists"]}
    assert por_id["a"]["emblem"] == "🛒" and not por_id["a"].get("emblem_partido")
    assert por_id["b"]["emblem"] == "house.fill" and not por_id["b"].get("emblem_partido")
    assert por_id["c"]["emblem"] is None


def test_emoji_gravado_cru_e_reescrito_no_formato_certo(monkeypatch):
    d = _dump_com_base(monkeypatch, {"a": "📝", "b": '{"Emoji" : "✈️"}'})
    assert [l["id"] for l in d["lists"] if l.get("emblem_partido")] == ["a"]
    # do lado do Cristopher continua a ser o mesmo emoji: nada muda na NAS
    assert d["lists"][0]["emblem"] == "📝"
    pedidos = []
    monkeypatch.setattr(ar, "_jxa", lambda codigo, arg, **k: pedidos.append(arg) or {"ok": ["a"], "erros": []})
    assert ar.repara_emblemas(d) == ["a"]
    import json
    assert json.loads(pedidos[0]) == [{"id": "a", "icon": '{"Emoji" : "📝"}'}]


def test_sem_nada_partido_nao_abre_a_app_lembretes(monkeypatch):
    d = _dump_com_base(monkeypatch, {"a": '{"Emoji" : "🛒"}'})
    monkeypatch.setattr(ar, "_jxa", lambda *a, **k: pytest.fail("abriu a app Lembretes"))
    assert ar.repara_emblemas(d) == []
