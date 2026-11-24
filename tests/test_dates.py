import datetime as dt

import pytest

from rabisco.config import C
from rabisco.dates import due_display, parse_quick

NOW = dt.datetime(2026, 11, 24, 9, 30)  # terça-feira


@pytest.mark.parametrize("text, expected", [
    ("comprar café", ("comprar café", None, None)),
    ("ligar banco #casa @amanhã 14h", ("ligar banco", "2026-11-25 14:00", "casa")),
    ("relatório @sex", ("relatório", "2026-11-27", None)),
    ("reunião @ter", ("reunião", "2026-12-01", None)),          # mesmo dia da semana -> próxima
    ("deploy @hoje 18:30 #trabalho", ("deploy", "2026-11-24 18:30", "trabalho")),
    ("pagar boleto @10/12", ("pagar boleto", "2026-12-10", None)),
    ("aniversário @05/01", ("aniversário", "2027-01-05", None)),  # data passada -> ano que vem
    ("tarefa @3d", ("tarefa", "2026-11-27", None)),
    ("café @15h", ("café", "2026-11-24 15:00", None)),
    ("café @8h", ("café", "2026-11-25 08:00", None)),            # hora já passou -> amanhã
    ("y @25/12/27", ("y", "2027-12-25", None)),
    # não confunde com outras coisas
    ("issue #123 @fulano mail a@b.com", ("issue #123 @fulano mail a@b.com", None, None)),
    ("x @31/02", ("x @31/02", None, None)),
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
