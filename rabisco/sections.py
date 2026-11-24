"""Agrupamento da lista em seções (Pra já, Fazendo, Hoje e atrasadas, ...). Sem dependência de Qt.

Cada tarefa cai na primeira seção cuja regra ela satisfaz, nesta ordem:
  quick  — marcada como "pra já" (e não concluída)
  doing  — em andamento
  due    — prazo hoje ou vencido
  soon   — prazo nos próximos dias
  nodue  — sem prazo (ordem manual, arrastando)
  done   — concluídas
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import G_BOLT, G_CAL, G_CHECK, G_CLOCK, G_LIST, G_PLAY
from .dates import due_sort_key, is_due_today_or_late

if TYPE_CHECKING:
    from .store import Task


@dataclass(frozen=True)
class SectionInfo:
    key: str
    label: str
    glyph: str
    color: str      # chave em config.C
    by_due: bool    # ordena por prazo (senão, ordem manual)


SECTIONS = [
    SectionInfo("quick", "Pra já", G_BOLT, "accent", False),
    SectionInfo("doing", "Fazendo", G_PLAY, "doing", False),
    SectionInfo("due", "Hoje e atrasadas", G_CLOCK, "danger", True),
    SectionInfo("soon", "Próximos dias", G_CAL, "soft", True),
    SectionInfo("nodue", "Sem prazo", G_LIST, "muted", False),
    SectionInfo("done", "Feitas", G_CHECK, "done", False),
]
SECTION_BY_KEY = {s.key: s for s in SECTIONS}


def section_of(t: "Task", now: dt.datetime | None = None) -> str:
    if t.status == "done":
        return "done"
    if t.quick:
        return "quick"
    if t.status == "doing":
        return "doing"
    if t.due:
        return "due" if is_due_today_or_late(t, now) else "soon"
    return "nodue"


def build_sections(tasks: list["Task"], hide_done: bool = False,
                   now: dt.datetime | None = None) -> list[tuple[SectionInfo, list["Task"]]]:
    """-> [(seção, tarefas)] só com as seções que têm tarefas, na ordem de SECTIONS."""
    buckets: dict[str, list] = {s.key: [] for s in SECTIONS}
    for t in tasks:  # mantém a ordem manual (global) dentro de cada seção
        buckets[section_of(t, now)].append(t)
    out = []
    for s in SECTIONS:
        items = buckets[s.key]
        if not items or (hide_done and s.key == "done"):
            continue
        if s.by_due:
            items = sorted(items, key=lambda t: due_sort_key(t.due))
        out.append((s, items))
    return out


def quick_first(tasks: list["Task"]) -> list["Task"]:
    """Ordenação estável que sobe as "pra já" (usada no quadro e na lista manual)."""
    return sorted(tasks, key=lambda t: not (t.quick and t.status != "done"))
