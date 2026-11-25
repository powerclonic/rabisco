import datetime as dt

from rabisco.sections import build_sections, quick_first, section_of
from rabisco.store import Task

NOW = dt.datetime(2026, 11, 24, 9, 30)


def T(text, **kw):
    return Task(text=text, **kw)


def keys(sections):
    return [(s.key, [t.text for t in items]) for s, items in sections]


def test_section_of_precedencia():
    assert section_of(T("a", quick=True, status="doing", due="2026-11-20"), NOW) == "quick"
    assert section_of(T("b", status="doing", due="2026-11-20"), NOW) == "doing"
    assert section_of(T("c", due="2026-11-20"), NOW) == "due"       # atrasada
    assert section_of(T("d", due="2026-11-24 18:00"), NOW) == "due"  # hoje
    assert section_of(T("e", due="2026-11-25"), NOW) == "soon"
    assert section_of(T("f"), NOW) == "nodue"
    assert section_of(T("g", quick=True, status="done"), NOW) == "done"
    assert section_of(T("h", delegated=True, status="doing", due="2026-11-20"), NOW) == "delegated"


def test_build_sections_ordem_e_vazias():
    tasks = [
        T("sem prazo 1"),
        T("amanhã", due="2026-11-25"),
        T("rápida", quick=True),
        T("hoje 15h", due="2026-11-24 15:00"),
        T("atrasada", due="2026-11-20"),
        T("sem prazo 2"),
        T("com a Ana", delegated=True, delegated_to="Ana"),
        T("feita", status="done"),
    ]
    assert keys(build_sections(tasks, now=NOW)) == [
        ("quick", ["rápida"]),
        ("due", ["atrasada", "hoje 15h"]),        # ordenado por prazo
        ("soon", ["amanhã"]),
        ("nodue", ["sem prazo 1", "sem prazo 2"]),  # ordem manual preservada
        ("delegated", ["com a Ana"]),
        ("done", ["feita"]),
    ]
    assert "done" not in [k for k, _ in keys(build_sections(tasks, hide_done=True, now=NOW))]


def test_quick_first_estavel():
    tasks = [T("a"), T("b", quick=True), T("del", delegated=True), T("c"), T("d", quick=True),
             T("e", quick=True, status="done")]
    assert [t.text for t in quick_first(tasks)] == ["b", "d", "a", "c", "e", "del"]
