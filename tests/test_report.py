import datetime as dt

import pytest

from rabisco.report import by_day, completion_notes, day_label, period_range, range_label, report_text
from rabisco.store import Store


@pytest.fixture(scope="session", autouse=True)
def qcore():
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "dados.json")


def ts(y, m, d, h=12):
    return dt.datetime(y, m, d, h).timestamp()


def done(store, text, when, **kw):
    t = store.add(text, **kw)
    store.toggle_done(t.id)
    store.get(t.id).done_at = when
    return t


SEX = dt.date(2026, 11, 27)  # uma sexta-feira


def test_periodos():
    assert period_range("today", SEX) == (SEX, SEX)
    assert period_range("yesterday", SEX) == (dt.date(2026, 11, 26),) * 2
    assert period_range("week", SEX) == (dt.date(2026, 11, 23), SEX)  # segunda
    assert period_range("month", SEX) == (dt.date(2026, 11, 1), SEX)


def test_rotulos():
    assert day_label(SEX, SEX) == "Hoje"
    assert day_label(dt.date(2026, 11, 26), SEX) == "Ontem"
    assert day_label(dt.date(2026, 11, 24), SEX) == "Ter, 24/11"
    assert day_label(dt.date(2025, 12, 30), SEX) == "Ter, 30/12/25"
    assert range_label(dt.date(2026, 11, 23), SEX, SEX) == "23/11 a 27/11"


def test_concluidas_no_periodo_inclui_arquivadas_e_filtra_grupo(store):
    g = store.add_group("Trab")
    done(store, "seg", ts(2026, 11, 23), group=g.id)
    done(store, "sex", ts(2026, 11, 27, 9))
    done(store, "semana passada", ts(2026, 11, 20))
    store.add("aberta")
    assert store.clear_done() == 3  # arquiva: some da lista...
    assert not [t for t in store.tasks if t.status == "done"]
    week = store.completed(dt.date(2026, 11, 23), SEX)  # ...mas segue no relatório
    assert [t.text for t in week] == ["sex", "seg"]
    assert [t.text for t in store.completed(dt.date(2026, 11, 23), SEX, g.id)] == ["seg"]


def test_arquivo_persiste_e_desfazer_limpar_volta_pra_lista(store, tmp_path):
    done(store, "a", ts(2026, 11, 27))
    store.clear_done()
    store.save_now()
    again = Store(tmp_path / "dados.json")
    assert [t.text for t in again.archive] == ["a"] and not again.tasks
    store.undo()
    assert [t.text for t in store.tasks] == ["a"] and not store.archive


def test_excluir_grupo_limpa_grupo_do_arquivo(store):
    g = store.add_group("X")
    done(store, "a", ts(2026, 11, 27), group=g.id)
    store.clear_done()
    store.delete_group(g.id)
    assert store.archive[0].group is None


def test_texto_do_relatorio(store):
    g = store.add_group("Trab")
    a = done(store, "deploy", ts(2026, 11, 27, 15), group=g.id)
    store.add_note(a.id, "subiu sem erro", when=ts(2026, 11, 27))
    done(store, "contrato", ts(2026, 11, 26), delegate="Ana")
    tasks = store.completed(dt.date(2026, 11, 26), SEX)
    assert [d for d, _ in by_day(tasks)] == [SEX, dt.date(2026, 11, 26)]
    assert completion_notes(store.get(a.id).notes) == ["subiu sem erro"]
    txt = report_text(tasks, dt.date(2026, 11, 26), SEX, {g.id: "Trab"}, today=SEX)
    assert txt == ("Concluídas — 26/11 a 27/11 (2)\n\nHoje\n- deploy [Trab]\n  - subiu sem erro\n"
                   "\nOntem\n- contrato [com Ana]")
    assert "Nada concluído" in report_text([], SEX, SEX, {}, today=SEX)
