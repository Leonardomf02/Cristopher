"""A mesma loja escrita de duas maneiras é a mesma loja.

A Caixa prefixa cada linha com o tipo de operação e corta o resultado aos 21
caracteres: `COMPRAS C.DEB INTER F` e `Inter Figueira Da Foz` são a mesma bomba
de combustível. Enquanto foram duas identidades, uma correcção dele numa delas
não chegava à outra — e ele teve de corrigir a mesma loja duas vezes.

Corre sozinho:  python tests/test_lojas_do_banco.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bank_categories as bc


class RegraFalsa:
    def __init__(self, key, category, source="ia"):
        self.key, self.category, self.source, self.hits = key, category, source, 0


class DbFalsa:
    """Só o que o `_regra` usa: procurar por chave e listar tudo."""
    def __init__(self, regras):
        self.regras = regras

    def query(self, _modelo):
        return self

    def filter(self, criterio):
        # a única filtragem feita é por igualdade da chave
        alvo = criterio.right.value
        self._encontradas = [r for r in self.regras if r.key == alvo]
        return self

    def first(self):
        return self._encontradas[0] if self._encontradas else None

    def all(self):
        return self.regras


def test_o_prefixo_da_caixa_nao_faz_parte_do_nome_da_loja():
    assert bc.limpa("COMPRAS C.DEB AUCHAN") == "AUCHAN"
    assert bc.limpa("COMPRA WORTEN-EQUIPAM") == "WORTEN-EQUIPAM"
    assert bc.chave("COMPRAS C.DEB INTER F") == "inter f"


def test_comissao_nao_e_uma_compra():
    """O prefixo só sai quando é mesmo o prefixo — "COMISSAO COMPRAS FORA" é
    uma comissão, não uma compra no "FORA"."""
    assert bc.limpa("COMISSAO COMPRAS FORA") == "COMISSAO COMPRAS FORA"


def test_o_carregamento_para_o_revolut_nao_e_tocado():
    """O tipo do movimento lê-se da descrição inteira; mexer nela aqui fazia o
    carregamento voltar a contar como gasto."""
    assert bc.limpa("CAR WAL CRT DEB REVOL") == "CAR WAL CRT DEB REVOL"


def test_o_nome_cortado_encontra_a_loja_inteira():
    db = DbFalsa([RegraFalsa("inter figueira da foz", "transport", "manual")])
    assert bc._por_prefixo("inter f", db).category == "transport"
    assert bc._por_prefixo("mcdonal", DbFalsa([RegraFalsa("mcdonalds figueira f", "food")])).category == "food"


def test_lojas_diferentes_com_o_mesmo_princípio_nao_se_misturam():
    """"INTERSP" é o Intersport e "INTER F" é o Intermarché: nenhuma é prefixo
    da outra, e o corte da Caixa não pode inventar uma ligação."""
    db = DbFalsa([RegraFalsa("inter figueira da foz", "transport", "manual")])
    assert bc._por_prefixo("intersp", db) is None
    assert bc._por_prefixo("pkp intercity", db) is None


def test_prefixos_curtos_nao_identificam_ninguem():
    db = DbFalsa([RegraFalsa("continente covilha", "groceries")])
    assert bc._por_prefixo("cont", db) is None


def test_a_correcao_dele_ganha_a_uma_regra_da_ia_com_o_mesmo_prefixo():
    db = DbFalsa([
        RegraFalsa("inter fig", "groceries", "ia"),
        RegraFalsa("inter figueira da foz", "transport", "manual"),
    ])
    assert bc._por_prefixo("inter f", db).category == "transport"


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {nome}")
            except AssertionError as ex:
                falhas += 1
                print(f"  FALHA {nome}: {ex}")
    print(f"\n{falhas} falhas")
    sys.exit(1 if falhas else 0)


# ── MB Way: o número é a loja ────────────────────────────────────

def test_no_mbway_cada_numero_e_uma_loja():
    """Sem o número, o ginásio e os amigos eram a mesma "loja": corrigir a
    transferência para o ginásio mudava as dos amigos todos."""
    assert bc.chave("TRF MBWAY 963XXX836") == "mbway 963xxx836"
    assert bc.chave("Trf Mbway 927XXX207") == "mbway 927xxx207"


def test_o_mesmo_numero_escrito_de_outra_maneira_e_o_mesmo():
    assert bc.chave("MB WAY para 963123836") == "mbway 963xxx836"
    assert bc.chave("Transfer to MBWAY +351 963 123 836") == "mbway 963xxx836"


def test_mbway_sem_numero_fica_como_estava():
    assert bc.chave("TRF MBWAY") == "trf mbway"


def test_a_regra_do_ginasio_nao_apanha_os_amigos():
    db = DbFalsa([RegraFalsa("mbway 963xxx836", "subscriptions", "manual")])
    assert bc.categoria_com_memoria("TRF MBWAY 963XXX836", db) == "subscriptions"
    assert bc.categoria_com_memoria("Trf Mbway 927XXX207", db) == "other"
