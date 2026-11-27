"""Página do relatório: o que foi concluído num período (Hoje, Ontem, Semana, Mês ou datas livres)."""
from __future__ import annotations

import datetime as dt
import html
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextBrowser, QVBoxLayout,
    QWidget,
)

from ..config import C, G_BACK
from ..report import PERIODS, by_day, completion_notes, day_label, period_range, range_label, report_text
from .theme import dot_icon

if TYPE_CHECKING:
    from .panel import Panel


class ReportPage(QWidget):
    def __init__(self, panel: "Panel"):
        super().__init__()
        self.panel = panel
        self.store = panel.store
        self._text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(6)
        back = panel.icon_button(G_BACK, "Voltar (Esc)")
        back.clicked.connect(panel.close_page)
        title = QLabel("Concluídas")
        title.setObjectName("title")
        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.setObjectName("link")
        self.copy_btn.setToolTip("Copia o relatório como texto (Ctrl+C)")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_btn.clicked.connect(self.copy)
        top.addWidget(back)
        top.addWidget(title, 1)
        top.addWidget(self.copy_btn)
        lay.addLayout(top)

        segbox = QFrame()
        segbox.setObjectName("segbox")
        sl = QHBoxLayout(segbox)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.period_btns: dict[str, QPushButton] = {}
        for key, label in PERIODS:
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda *_, k=key: self.set_period(k))
            sl.addWidget(b, 1)
            self.period_btns[key] = b
        lay.addWidget(segbox)

        # datas livres (só no "Período")
        self.custom = QWidget()
        cl = QHBoxLayout(self.custom)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        self.date_from, self.date_to = QDateEdit(), QDateEdit()
        for de in (self.date_from, self.date_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd/MM/yyyy")
            de.setDate(QDate.currentDate())
            de.dateChanged.connect(self.reload)
        self.date_from.setDate(QDate.currentDate().addDays(-6))
        lbl_from, lbl_to = QLabel("de"), QLabel("até")
        lbl_from.setObjectName("muted")
        lbl_to.setObjectName("muted")
        cl.addWidget(lbl_from)
        cl.addWidget(self.date_from, 1)
        cl.addWidget(lbl_to)
        cl.addWidget(self.date_to, 1)
        lay.addWidget(self.custom)

        info = QHBoxLayout()
        info.setSpacing(8)
        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.group = QComboBox()
        self.group.activated.connect(self.reload)
        info.addWidget(self.summary, 1)
        info.addWidget(self.group)
        lay.addLayout(info)

        self.body = QTextBrowser()
        self.body.setObjectName("report")
        self.body.setOpenLinks(False)
        self.body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.body, 1)

    # abrir / período
    def open(self) -> None:
        cur = self.group.currentData()
        self.group.clear()
        self.group.addItem("Todos os grupos", "")
        for g in self.store.groups:
            self.group.addItem(dot_icon(g.color), g.name, g.id)
        f = self.store.settings["filter"]
        want = cur if cur is not None else ("" if f == "all" else f)
        self.group.setCurrentIndex(max(0, self.group.findData(want)))
        self.group.setVisible(bool(self.store.groups))
        self.set_period(self.store.settings["report_period"])

    def set_period(self, key: str) -> None:
        if key not in self.period_btns:
            key = "week"
        self.store.set_setting("report_period", key)
        self.period_btns[key].setChecked(True)
        self.custom.setVisible(key == "custom")
        self.reload()

    def _range(self) -> tuple[dt.date, dt.date]:
        key = self.store.settings["report_period"]
        if key != "custom":
            return period_range(key)
        a, b = self.date_from.date().toPython(), self.date_to.date().toPython()
        return (a, b) if a <= b else (b, a)

    # conteúdo
    def reload(self, *_) -> None:
        if self.panel.stack.currentWidget() is not self:  # só calcula com a página na tela
            return
        start, end = self._range()
        gid = self.group.currentData() or None
        tasks = self.store.completed(start, end, gid)
        groups = {g.id: g for g in self.store.groups}
        n = len(tasks)
        days = len(by_day(tasks))
        summary = f"{range_label(start, end)}  ·  {n} concluída{'s' if n != 1 else ''}"
        if n and start != end:
            summary += f" em {days} dia{'s' if days != 1 else ''}"
        self.summary.setText(summary)
        self._text = report_text(tasks, start, end, {g.id: g.name for g in groups.values()})
        self.body.setHtml(self._html(tasks, groups))

    def _html(self, tasks, groups) -> str:
        if not tasks:
            return (f"<p style='color:{C['muted']}; margin-top:24px' align=center>"
                    "Nada concluído nesse período.</p>")
        esc = html.escape
        out = []
        for d, items in by_day(tasks):
            out.append(f"<p style='margin:14px 0 4px 0'><b style='color:{C['soft']}'>{esc(day_label(d))}</b>"
                       f"<span style='color:{C['muted']}'>&nbsp;&nbsp;{len(items)}</span></p>")
            for t in items:
                meta = [time.strftime("%H:%M", time.localtime(t.done_at))]
                g = groups.get(t.group)
                if g:
                    meta.append(f"<span style='color:{g.color}'>●</span> {esc(g.name)}")
                if t.delegated_to:
                    meta.append(f"com {esc(t.delegated_to)}")
                out.append(
                    f"<table width='100%' cellspacing=0 cellpadding=0 style='margin:3px 0'><tr>"
                    f"<td width=18 valign=top style='color:{C['done']}'>✓</td>"
                    f"<td>{esc(t.text)}<br><span style='color:{C['muted']}; font-size:8.5pt'>"
                    f"{' · '.join(meta)}</span>"
                    + "".join(f"<br><span style='color:{C['soft']}'>“{esc(note)}”</span>"
                              for note in completion_notes(t.notes))
                    + "</td></tr></table>")
        return "".join(out)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self._text)
        self.copy_btn.setText("Copiado ✓")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copiar"))

    # teclado: ← → troca o período, ↑ ↓ PgUp PgDn rolam, Ctrl+C copia
    def keyPressEvent(self, e):
        keys = [k for k, _ in PERIODS if k != "custom"]
        cur = self.store.settings["report_period"]
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not e.modifiers():
            i = keys.index(cur) if cur in keys else len(keys)
            i = max(0, min(len(keys) - 1, i + (-1 if k == Qt.Key.Key_Left else 1)))
            self.set_period(keys[i])
            return
        if e.matches(QKeySequence.StandardKey.Copy):
            if self.body.textCursor().hasSelection():
                self.body.copy()
            else:
                self.copy()
            return
        sb = self.body.verticalScrollBar()
        step = {Qt.Key.Key_Up: -sb.singleStep() * 3, Qt.Key.Key_Down: sb.singleStep() * 3,
                Qt.Key.Key_PageUp: -sb.pageStep(), Qt.Key.Key_PageDown: sb.pageStep()}.get(k)
        if step is not None:
            sb.setValue(sb.value() + step)
            return
        super().keyPressEvent(e)
