"""Prazos: leitura da digitação rápida (@amanhã 14h) e rótulos dos cartões. Sem dependência de Qt.

Prazo guardado como texto: "AAAA-MM-DD" ou "AAAA-MM-DD HH:MM".
"""
from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, NamedTuple

from .config import C

if TYPE_CHECKING:
    from .store import Task

WEEKDAYS = {"seg": 0, "segunda": 0, "ter": 1, "terca": 1, "terça": 1, "qua": 2, "quarta": 2,
            "qui": 3, "quinta": 3, "sex": 4, "sexta": 4, "sab": 5, "sáb": 5, "sabado": 5,
            "sábado": 5, "dom": 6, "domingo": 6}
WEEKDAY_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
TIME_RE = re.compile(r"^([01]?\d|2[0-3])(?:h([0-5]\d)?|:([0-5]\d))$")
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?$")


def split_due(due: str | None):
    """-> (date | None, 'HH:MM' | None)"""
    if not due:
        return None, None
    try:
        d = dt.date.fromisoformat(due[:10])
    except ValueError:
        return None, None
    tm = due[11:16] if len(due) >= 16 else None
    return d, tm


def make_due(d: dt.date | None, tm: str | None) -> str | None:
    if d is None:
        return None
    return d.isoformat() + (f" {tm}" if tm else "")


def _parse_time(tok: str) -> str | None:
    m = TIME_RE.match(tok.lower())
    if not m:
        return None
    return f"{int(m[1]):02d}:{int(m[2] or m[3] or 0):02d}"


def _parse_date(tok: str, today: dt.date) -> dt.date | None:
    t = tok.lower()
    if t == "hoje":
        return today
    if t in ("amanha", "amanhã"):
        return today + dt.timedelta(days=1)
    if t in WEEKDAYS:
        return today + dt.timedelta(days=(WEEKDAYS[t] - today.weekday()) % 7 or 7)
    m = re.match(r"^(\d{1,3})d$", t)
    if m:
        return today + dt.timedelta(days=int(m[1]))
    m = DATE_RE.match(t)
    if m:
        day, month = int(m[1]), int(m[2])
        year = int(m[3]) if m[3] else today.year
        if m[3] and len(m[3]) == 2:
            year += 2000
        try:
            d = dt.date(year, month, day)
        except ValueError:
            return None
        if not m[3] and d < today:
            try:
                d = d.replace(year=year + 1)
            except ValueError:
                return None
        return d
    return None


class QuickInput(NamedTuple):
    title: str
    due: str | None
    group: str | None
    quick: bool
    delegate: str | None  # None = não delegada; "" = delegada sem dizer pra quem


def parse_quick(text: str, now: dt.datetime | None = None) -> QuickInput:
    """Lê a digitação rápida.

    '!ligar pro banco #casa @amanhã 14h' -> ('ligar pro banco', '2026-11-25 14:00', 'casa', True, None)
      !         no começo: "pra já"
      >Fulano   delegada para Fulano;  > sozinho (no começo ou no fim): delegada sem dizer pra quem
    Pra já e delegada são excludentes (delegada vence).
    """
    now = now or dt.datetime.now()
    today = now.date()
    text = text.strip()
    quick = text.startswith("!")
    if quick:
        text = text.lstrip("! ")
    toks = text.split()
    out, due, group, delegate = [], None, None, None
    i = 0
    while i < len(toks):
        tok = toks[i]
        lone = tok == ">" and i in (0, len(toks) - 1)  # ">" solto só no começo ou no fim
        if delegate is None and (lone or (tok.startswith(">") and tok[1:2].isalpha())):
            delegate = tok[1:]
            i += 1
            continue
        if group is None and tok.startswith("#") and tok[1:2].isalpha():
            group = tok[1:]
            i += 1
            continue
        if due is None and tok.startswith("@") and len(tok) > 1:
            body = tok[1:]
            d, tm = _parse_date(body, today), None
            if d is None:
                tm = _parse_time(body)
                if tm:
                    d = today if tm > now.strftime("%H:%M") else today + dt.timedelta(days=1)
            if d is not None:
                if tm is None and i + 1 < len(toks):
                    tm = _parse_time(toks[i + 1])
                    if tm:
                        i += 1
                due = make_due(d, tm)
                i += 1
                continue
        out.append(tok)
        i += 1
    if delegate is not None:
        quick = False
    return QuickInput(" ".join(out), due, group, quick, delegate)


def due_display(due: str | None, done: bool, now: dt.datetime | None = None):
    """-> (rótulo, cor) para mostrar no cartão."""
    d, tm = split_due(due)
    if d is None:
        return "", C["muted"]
    now = now or dt.datetime.now()
    today = now.date()
    delta = (d - today).days
    if delta == 0:
        label = "Hoje"
    elif delta == 1:
        label = "Amanhã"
    elif delta == -1:
        label = "Ontem"
    elif 1 < delta < 7:
        label = WEEKDAY_SHORT[d.weekday()]
    else:
        label = d.strftime("%d/%m") + (d.strftime("/%y") if d.year != today.year else "")
    if tm:
        label += f" {tm}"
    if done:
        return label, C["muted"]
    overdue = delta < 0 or (delta == 0 and tm is not None and tm < now.strftime("%H:%M"))
    if overdue:
        return label, C["danger"]
    if delta == 0:
        return label, C["accent"]
    return label, C["soft"]


def is_overdue(t: "Task", now: dt.datetime | None = None) -> bool:
    return t.status != "done" and due_display(t.due, False, now)[1] == C["danger"]


def is_due_today_or_late(t: "Task", now: dt.datetime | None = None) -> bool:
    d, _ = split_due(t.due)
    return d is not None and d <= (now or dt.datetime.now()).date()


def due_sort_key(due: str | None):
    """Ordena por data; sem hora conta como 'qualquer hora do dia' (depois das com hora)."""
    d, tm = split_due(due)
    return (d or dt.date.max, tm or "24:00")


QUICK_WARN_SECS = 4 * 3600         # "pra já" esperando há 4h: amarelo
QUICK_LATE_SECS = 24 * 3600        # há 1 dia: vermelho (não era tão rápida assim)
DELEGATE_WARN_SECS = 3 * 86400     # delegada há 3 dias: amarelo (hora de cobrar?)
DELEGATE_LATE_SECS = 7 * 86400     # há 1 semana: vermelho


def age_display(since: float | None, now: dt.datetime | None = None,
                warn: float = QUICK_WARN_SECS, late: float = QUICK_LATE_SECS):
    """Há quanto tempo algo está esperando -> (rótulo, cor). Limiares padrão: "pra já"."""
    if not since:
        return "", C["muted"]
    secs = max(0.0, (now or dt.datetime.now()).timestamp() - since)
    mins = int(secs // 60)
    if mins < 1:
        label = "agora"
    elif mins < 60:
        label = f"há {mins} min"
    elif mins < 60 * 24:
        label = f"há {mins // 60}h"
    else:
        label = f"há {mins // (60 * 24)}d"
    if secs >= late:
        return label, C["danger"]
    if secs >= warn:
        return label, C["accent"]
    return label, C["soft"]


def delegate_display(to: str, since: float | None, now: dt.datetime | None = None):
    """'Fulano · há 2d' (ou só 'há 2d') -> (rótulo, cor); cobra depois de 3 e 7 dias."""
    age, color = age_display(since, now, DELEGATE_WARN_SECS, DELEGATE_LATE_SECS)
    if not age:
        return to or "delegada", C["soft"]
    return (f"{to} · {age}" if to else age), color
