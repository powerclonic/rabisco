import json

import pytest

from rabisco.store import Store


@pytest.fixture(scope="session", autouse=True)
def qcore():
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "dados.json")


def texts(s, status):
    return [t.text for t in s.tasks if t.status == status]


def test_add_normaliza_e_entra_no_topo(store):
    store.add("  comprar   café ")
    store.add("ligar pro banco")
    assert texts(store, "todo") == ["ligar pro banco", "comprar café"]
    assert store.add("   ") is None


def test_toggle_done(store):
    t = store.add("x")
    store.toggle_done(t.id)
    assert store.get(t.id).status == "done" and store.get(t.id).done_at
    store.toggle_done(t.id)
    assert store.get(t.id).status == "todo" and store.get(t.id).done_at is None


def test_move_entre_colunas_e_reordenar(store):
    a, b, c = store.add("a"), store.add("b"), store.add("c", "doing")
    store.move(b.id, "doing", c.id)
    assert texts(store, "doing") == ["b", "c"]
    store.move(a.id, "doing", None)
    assert texts(store, "doing") == ["b", "c", "a"]
    store.move(a.id, None, b.id)
    assert texts(store, "doing") == ["a", "b", "c"]


def test_delete_clear_e_undo(store):
    a, b = store.add("a"), store.add("b")
    store.set_status(b.id, "done")
    assert store.clear_done() == 1 and not texts(store, "done")
    store.undo()
    assert texts(store, "done") == ["b"]
    store.delete(a.id)
    assert store.get(a.id) is None
    store.undo()
    assert store.get(a.id)


def test_update_task(store):
    t = store.add("x")
    store.update_task(t.id, notes="linha1\nlinha2  ", text="  novo  título ")
    assert t.notes == "linha1\nlinha2" and t.text == "novo título"
    store.update_task(t.id, text="   ")
    assert t.text == "novo título"
    store.update_task(t.id, group="inexistente")
    assert t.group is None


def test_grupos_filtro_e_exclusao(store):
    g = store.add_group("Trabalho")
    g2 = store.add_group("  casa ")
    assert store.add_group("trabalho") is g and g2.name == "casa" and g.color != g2.color
    x = store.add("x", group=g.id)
    store.add("y")
    store.set_setting("filter", g.id)
    assert [t.id for t in store.visible()] == [x.id]
    assert store.delete_group(g.id)
    assert store.get(x.id).group is None and store.settings["filter"] == "all"
    store.undo()
    assert store.get_group(g.id) and store.get(x.id).group == g.id


def test_persistencia_e_compat_v1(tmp_path):
    f = tmp_path / "dados.json"
    f.write_text(json.dumps({"version": 1, "settings": {"view": "board"}, "tasks": [
        {"text": "antiga", "status": "doing", "id": "a1", "created": 1.0, "done_at": None}]}))
    s = Store(f)
    t = s.get("a1")
    assert t.notes == "" and t.due is None and t.group is None and s.settings["view"] == "board"
    g = s.add_group("G")
    s.update_task("a1", group=g.id, due="2026-12-01 10:00", notes="n")
    s.save_now()
    s2 = Store(f)
    t2 = s2.get("a1")
    assert (t2.group, t2.due, t2.notes) == (g.id, "2026-12-01 10:00", "n")


def test_arquivo_corrompido_vira_backup(tmp_path, monkeypatch):
    monkeypatch.setattr("rabisco.store.log_error", lambda *_: None)
    f = tmp_path / "dados.json"
    f.write_text("{lixo")
    s = Store(f)
    assert s.tasks == []
    assert any(p.name.startswith("dados.corrompido-") for p in tmp_path.iterdir())


def test_pra_ja(store):
    a, b = store.add("a"), store.add("b")
    q = store.add("rápida", quick=True)
    assert q.quick and q.quick_since
    store.set_quick(a.id, True)
    assert store.get(a.id).quick and store.tasks[0].id == a.id  # sobe pro topo
    store.toggle_quick(a.id)
    assert not store.get(a.id).quick and store.get(a.id).quick_since is None
    store.set_status(b.id, "done")
    store.set_quick(b.id, True)  # marcar pra já reabre a tarefa
    assert store.get(b.id).status == "todo"


def test_drop_into_section(store):
    a, b = store.add("a"), store.add("b", "doing")
    store.drop_into_section(a.id, "quick", None)
    assert store.get(a.id).quick
    store.drop_into_section(a.id, "doing", b.id)
    t = store.get(a.id)
    assert not t.quick and t.status == "doing" and texts(store, "doing") == ["a", "b"]
    store.drop_into_section(b.id, "nodue", b.id)  # mesmo lugar: só atributos
    assert store.get(b.id).status == "todo"
    store.drop_into_section(b.id, "done", None)
    assert store.get(b.id).status == "done"


def test_collapsed_e_settings_isolados(tmp_path):
    s1, s2 = Store(tmp_path / "a.json"), Store(tmp_path / "b.json")
    s1.toggle_collapsed("nodue")
    assert "nodue" in s1.settings["collapsed"] and "nodue" not in s2.settings["collapsed"]
    s1.toggle_collapsed("done")
    assert s1.settings["collapsed"] == ["nodue"]
    s1.save_now()
    assert Store(tmp_path / "a.json").settings["collapsed"] == ["nodue"]


def test_delegar(store):
    a = store.add("a")
    store.set_delegated(a.id, True)
    t = store.get(a.id)
    assert t.delegated and t.delegated_to == "" and t.delegated_since
    store.set_delegated(a.id, True, "  Ana  Paula ")
    assert t.delegated_to == "Ana Paula"
    store.set_quick(a.id, True)  # pra já e delegada são excludentes
    assert t.quick and not t.delegated and t.delegated_to == ""
    store.toggle_delegated(a.id)
    assert t.delegated and not t.quick


def test_add_delegada_e_nomes(store):
    store.add("x", delegate="Bruno")
    store.add("y", delegate="")
    store.add("z", delegate="ana", quick=True)
    assert [(t.text, t.delegated, t.delegated_to, t.quick) for t in store.tasks] == [
        ("z", True, "ana", False), ("y", True, "", False), ("x", True, "Bruno", False)]
    assert store.delegate_names() == ["ana", "Bruno"]


def test_drop_em_delegadas_e_de_volta(store):
    a = store.add("a", quick=True)
    store.drop_into_section(a.id, "delegated", None)
    t = store.get(a.id)
    assert t.delegated and not t.quick
    store.drop_into_section(a.id, "nodue", None)
    assert not t.delegated and t.delegated_since is None


def test_concluir_pode_ser_desfeito(store):
    a = store.add("a")
    store.toggle_done(a.id)
    assert store.get(a.id).status == "done" and store.can_undo()
    assert store.undo()
    assert store.get(a.id).status == "todo"
    store.toggle_done(a.id)
    store.toggle_done(a.id)  # reabrir não empilha outro desfazer
    store.undo()
    assert store.get(a.id).status == "todo" and not store.can_undo()


def test_busca_ignora_acento_e_olha_descricao_pessoa_e_grupo(store):
    g = store.add_group("Trabalho")
    a = store.add("Comprar café", group=g.id)
    b = store.add("revisar contrato", delegate="Ana")
    store.update_task(b.id, notes="cláusula de multa")
    store.add("outra coisa")
    find = lambda q: {t.text for t in store.search(store.tasks, q)}
    assert find("cafe") == {"Comprar café"}
    assert find("CLAUSULA") == {"revisar contrato"}
    assert find("ana") == {"revisar contrato"}
    assert find("trab compr") == {a.text}
    assert find("   ") == {t.text for t in store.tasks}


def test_lembretes_avisam_uma_vez_e_de_novo_se_o_prazo_mudar(store):
    import datetime as dt
    now = dt.datetime(2026, 11, 27, 14, 0)
    a = store.add("ligar", due="2026-11-27 13:59")
    store.add("sem hora", due="2026-11-27")
    store.add("futura", due="2026-11-27 15:00")
    store.add("antiga", due="2026-11-20 10:00")  # passou há mais de 24h: não avisa
    feita = store.add("feita", due="2026-11-27 13:00")
    store.toggle_done(feita.id)
    assert [t.text for t in store.due_reminders(now)] == ["ligar"]
    assert store.due_reminders(now) == []
    store.update_task(a.id, due="2026-11-27 14:00")
    assert [t.text for t in store.due_reminders(now)] == ["ligar"]


def test_adiar_conta_de_hoje_se_venceu_e_mantem_hora(store):
    import datetime as dt
    hoje = dt.date(2026, 11, 27)
    a = store.add("a", due="2026-11-20 09:30")
    store.postpone(a.id, 1, hoje)
    assert store.get(a.id).due == "2026-11-28 09:30"
    store.postpone(a.id, 1, hoje)
    assert store.get(a.id).due == "2026-11-29 09:30"
    store.postpone(a.id, -5, hoje)
    assert store.get(a.id).due == "2026-11-27 09:30"  # nunca antes de hoje
    b = store.add("b")
    store.postpone(b.id, 1, hoje)
    assert store.get(b.id).due == "2026-11-28"


def test_comentario_de_conclusao_vai_pro_fim_da_descricao(store):
    a = store.add("a")
    store.add_note(a.id, "  mandei   pro cliente ", when=0)
    first = store.get(a.id).notes
    assert first.startswith("✓ ") and first.endswith(": mandei pro cliente")
    store.add_note(a.id, "e cobrei", when=0)
    assert store.get(a.id).notes.count("\n\n✓ ") == 1
    store.add_note(a.id, "   ")
    assert store.get(a.id).notes.count("✓") == 2
