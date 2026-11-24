import datetime as dt

import pytest

from rabisco.config import C
from rabisco.dates import age_display, due_display, due_sort_key, parse_quick

NOW = dt.datetime(2026, 11, 24, 9, 30)  # terça-feira


@pytest.mark.parametrize("text, expected", [
    ("comprar café", ("comprar café", None, None, False)),
    ("ligar banco #casa @amanhã 14h", ("ligar banco", "2026-11-25 14:00", "casa", False)),
    ("relatório @sex", ("relatório", "2026-11-27", None, False)),
    ("reunião @ter", ("reunião", "2026-12-01", None, False)),          # mesmo dia da semana -> próxima
    ("deploy @hoje 18:30 #trabalho", ("deploy", "2026-11-24 18:30", "trabalho", False)),
    ("pagar boleto @10/12", ("pagar boleto", "2026-12-10", None, False)),
    ("aniversário @05/01", ("aniversário", "2027-01-05", None, False)),  # data passada -> ano que vem
    ("tarefa @3d", ("tarefa", "2026-11-27", None, False)),
    ("café @15h", ("café", "2026-11-24 15:00", None, False)),
    ("café @8h", ("café", "2026-11-25 08:00", None, False)),            # hora já passou -> amanhã
    ("y @25/12/27", ("y", "2027-12-25", None, False)),
    # não confunde com outras coisas
    ("issue #123 @fulano mail a@b.com", ("issue #123 @fulano mail a@b.com", None, None, False)),
    ("x @31/02", ("x @31/02", None, None, False)),
    # pra já
    ("!analisar email do Fulano", ("analisar email do Fulano", None, None, True)),
    ("  ! investigar erro #trabalho", ("investigar erro", None, "trabalho", True)),
    ("!!responder @hoje 16h", ("responder", "2026-11-24 16:00", None, True)),
    ("ver isso!", ("ver isso!", None, None, False)),
])
def test_parse_quick(text, expected):
    assert parse_quick(text, NOW) == expected


@pytest.mark.parametrize("due, done, expected", [
    ("2026-11-24", False, ("Hoje", C["accent"])),
    ("2026-11-24 09:00", False, ("Hoje 09:00", C["danger"])),
    ("2026-11-23", False, ("Ontem", C["danger"])),
    ("2026-11-25", False, ("Amanhã", C["soft"])),
    ("2026-11-27 14:00", False, ("Sex 14:00", C["soft"])),
    ("2026-12-10", False, ("10/12", C["soft"])),
    ("2027-01-05", False, ("05/01/27", C["soft"])),
    ("2026-11-20", True, ("20/11", C["muted"])),
    (None, False, ("", C["muted"])),
])
def test_due_display(due, done, expected):
    assert due_display(due, done, NOW) == expected


@pytest.mark.parametrize("ago_secs, expected", [
    (20, ("agora", C["soft"])),
    (40 * 60, ("há 40 min", C["soft"])),
    (3 * 3600, ("há 3h", C["soft"])),
    (5 * 3600, ("há 5h", C["accent"])),
    (26 * 3600, ("há 1d", C["danger"])),
])
def test_age_display(ago_secs, expected):
    assert age_display(NOW.timestamp() - ago_secs, NOW) == expected


def test_age_display_sem_data():
    assert age_display(None, NOW) == ("", C["muted"])


def test_due_sort_key_sem_hora_depois_das_com_hora():
    dues = ["2026-11-25", "2026-11-24", "2026-11-24 15:00", "2026-11-24 09:00", None]
    assert sorted(dues, key=due_sort_key) == [
        "2026-11-24 09:00", "2026-11-24 15:00", "2026-11-24", "2026-11-25", None]
