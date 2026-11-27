"""Relatório de concluídas: períodos, agrupamento por dia e versão em texto. Sem dependência de Qt."""
from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING

from .dates import WEEKDAY_SHORT

if TYPE_CHECKING:
    from .store import Task

PERIODS = [("today", "Hoje"), ("yesterday", "Ontem"), ("week", "Semana"), ("month", "Mês"),
           ("custom", "Período")]
NOTE_PREFIX = "✓ "  # linhas da descrição escritas pelo "concluir com comentário"


def period_range(key: str, today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """-> (início, fim) inclusive. Semana = de segunda até hoje; mês = do dia 1 até hoje."""
    today = today or dt.date.today()
    if key == "yesterday":
        y = today - dt.timedelta(days=1)
        return y, y
    if key == "week":
        return today - dt.timedelta(days=today.weekday()), today
    if key == "month":
        return today.replace(day=1), today
    return today, today


def day_label(d: dt.date, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    if d == today:
        return "Hoje"
    if d == today - dt.timedelta(days=1):
        return "Ontem"
    label = f"{WEEKDAY_SHORT[d.weekday()]}, {d:%d/%m}"
    return label + (f"/{d:%y}" if d.year != today.year else "")


def range_label(start: dt.date, end: dt.date, today: dt.date | None = None) -> str:
    if start == end:
        return day_label(start, today)
    fmt = (lambda d: f"{d:%d/%m}") if start.year == end.year else (lambda d: f"{d:%d/%m/%y}")
    return f"{fmt(start)} a {fmt(end)}"


def by_day(tasks: list["Task"]) -> list[tuple[dt.date, list["Task"]]]:
    """Agrupa pelo dia em que foi concluída, mais recente primeiro (mantém a ordem de entrada)."""
    days: dict[dt.date, list] = {}
    for t in sorted(tasks, key=lambda t: t.done_at or 0, reverse=True):
        days.setdefault(dt.date.fromtimestamp(t.done_at or 0), []).append(t)
    return list(days.items())


def completion_notes(notes: str) -> list[str]:
    """Os comentários de conclusão (linhas '✓ 27/11: ...'), sem o prefixo nem a data."""
    out = []
    for ln in notes.splitlines():
        ln = ln.strip()
        if ln.startswith(NOTE_PREFIX):
            out.append(re.sub(r"^\d{2}/\d{2}: ", "", ln[len(NOTE_PREFIX):]))
    return out


def report_text(tasks: list["Task"], start: dt.date, end: dt.date, group_names: dict[str, str],
                today: dt.date | None = None) -> str:
    """Versão pra colar (daily, e-mail, chat): Markdown simples."""
    n = len(tasks)
    lines = [f"Concluídas — {range_label(start, end, today)} ({n})"]
    for d, items in by_day(tasks):
        lines += ["", f"{day_label(d, today)}"]
        for t in items:
            extra = []
            if t.group and t.group in group_names:
                extra.append(group_names[t.group])
            if t.delegated_to:
                extra.append(f"com {t.delegated_to}")
            lines.append(f"- {t.text}" + (f" [{', '.join(extra)}]" if extra else ""))
            lines += [f"  - {note}" for note in completion_notes(t.notes)]
    if not tasks:
        lines += ["", "Nada concluído nesse período."]
    return "\n".join(lines)
