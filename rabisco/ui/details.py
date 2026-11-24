"""Página de detalhes da tarefa: título, descrição, prazo, grupo e status. Salva sozinha."""
from __future__ import annotations

import datetime as dt
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSizePolicy, QTimeEdit, QVBoxLayout, QWidget,
)

from ..config import G_BACK, G_DELETE, STATUS_LABEL, STATUSES
from ..dates import make_due, split_due
from .theme import dot_icon

if TYPE_CHECKING:
    from .panel import Panel

class DetailPage(QWidget):
    """Edição completa de uma tarefa. Tudo salva sozinho."""

    def __init__(self, panel: "Panel"):
        super().__init__()
        self.panel = panel
        self.store = panel.store
        self.tid: str | None = None
        self._loading = False
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(6)
        back = panel.icon_button(G_BACK, "Voltar (Esc)")
        back.clicked.connect(panel.close_details)
        top.addWidget(back)
        top.addStretch(1)
        segbox = QFrame()
        segbox.setObjectName("segbox")
        sl = QHBoxLayout(segbox)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.status_btns = {}
        for st in STATUSES:
            b = QPushButton(STATUS_LABEL[st])
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda *_, st=st: self._set_status(st))
            sl.addWidget(b)
            self.status_btns[st] = b
        top.addWidget(segbox)
        delete = panel.icon_button(G_DELETE, "Excluir tarefa")
        delete.clicked.connect(self._delete)
        top.addWidget(delete)
        lay.addLayout(top)

        self.title = QLineEdit()
        self.title.setObjectName("detailTitle")
        self.title.setPlaceholderText("Título")
        self.title.textEdited.connect(self._save_title)
        self.title.editingFinished.connect(self._restore_title_if_empty)
        self.title.returnPressed.connect(lambda: self.notes.setFocus())
        lay.addWidget(self.title)

        self.notes = QPlainTextEdit()
        self.notes.setObjectName("notes")
        self.notes.setPlaceholderText("Descrição (opcional)")
        self.notes.setTabChangesFocus(True)
        self.notes.textChanged.connect(self._save_notes)
        lay.addWidget(self.notes, 1)

        # prazo
        due_row = QHBoxLayout()
        due_row.setSpacing(6)
        self.due_on = QCheckBox("Prazo")
        self.due_on.toggled.connect(self._due_toggled)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd, dd/MM/yyyy")
        self.date.dateChanged.connect(self._save_due)
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        self.time.setSpecialValueText("sem hora")  # 00:00 = sem hora
        self.time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.time.setToolTip("Hora opcional (00:00 = sem hora). Use as setas ou digite.")
        self.time.timeChanged.connect(self._save_due)
        due_row.addWidget(self.due_on)
        due_row.addWidget(self.date, 1)
        due_row.addWidget(self.time)
        lay.addLayout(due_row)

        quick = QHBoxLayout()
        quick.setSpacing(2)
        quick.addSpacing(22)
        for label, days in (("Hoje", 0), ("Amanhã", 1), ("Próx. semana", 7), ("Sem prazo", None)):
            b = QPushButton(label)
            b.setObjectName("link")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda *_, d=days: self._quick_due(d))
            quick.addWidget(b)
        quick.addStretch(1)
        lay.addLayout(quick)

        # grupo
        grp_row = QHBoxLayout()
        grp_row.setSpacing(8)
        lbl = QLabel("Grupo")
        lbl.setObjectName("muted")
        self.group = QComboBox()
        self.group.activated.connect(self._group_chosen)
        grp_row.addWidget(lbl)
        grp_row.addWidget(self.group, 1)
        lay.addLayout(grp_row)

        self.meta = QLabel()
        self.meta.setObjectName("hint")
        lay.addWidget(self.meta)

    # carregar
    def load(self, tid: str) -> bool:
        t = self.store.get(tid)
        if not t:
            return False
        self.tid = tid
        self._loading = True
        self.title.setText(t.text)
        self.notes.setPlainText(t.notes)
        d, tm = split_due(t.due)
        self.due_on.setChecked(d is not None)
        self.date.setDate(QDate(d.year, d.month, d.day) if d else QDate.currentDate())
        self.time.setTime(QTime.fromString(tm, "HH:mm") if tm else QTime(0, 0))
        self.date.setEnabled(d is not None)
        self.time.setEnabled(d is not None)
        self.status_btns[t.status].setChecked(True)
        self.sync_groups()
        meta = f"Criada em {time.strftime('%d/%m/%Y %H:%M', time.localtime(t.created))}"
        if t.done_at:
            meta += f"  ·  feita em {time.strftime('%d/%m %H:%M', time.localtime(t.done_at))}"
        self.meta.setText(meta)
        self._loading = False
        return True

    def sync_groups(self) -> None:
        t = self.store.get(self.tid)
        if not t:
            return
        self.group.blockSignals(True)
        self.group.clear()
        self.group.addItem("Sem grupo", "")
        for g in self.store.groups:
            self.group.addItem(dot_icon(g.color), g.name, g.id)
        self.group.addItem("Novo grupo…", "__new__")
        idx = self.group.findData(t.group or "")
        self.group.setCurrentIndex(max(0, idx))
        self.group.blockSignals(False)
        self.status_btns[t.status].setChecked(True)

    # salvar
    def _save_title(self, text: str):
        if not self._loading and self.tid and text.strip():
            self.store.update_task(self.tid, text=text)

    def _restore_title_if_empty(self):
        t = self.store.get(self.tid)
        if t and not self.title.text().strip():
            self.title.setText(t.text)

    def _save_notes(self):
        if not self._loading and self.tid:
            self.store.update_task(self.tid, notes=self.notes.toPlainText())

    def _current_due(self) -> str | None:
        if not self.due_on.isChecked():
            return None
        q = self.date.date()
        tm = self.time.time()
        hhmm = None if (tm.hour() == 0 and tm.minute() == 0) else tm.toString("HH:mm")
        return make_due(dt.date(q.year(), q.month(), q.day()), hhmm)

    def _save_due(self, *_):
        if not self._loading and self.tid:
            self.store.update_task(self.tid, due=self._current_due())

    def _due_toggled(self, on: bool):
        self.date.setEnabled(on)
        self.time.setEnabled(on)
        self._save_due()

    def _quick_due(self, days):
        self._loading = True
        if days is None:
            self.due_on.setChecked(False)
        else:
            self.due_on.setChecked(True)
            self.date.setDate(QDate.currentDate().addDays(days))
        self.date.setEnabled(self.due_on.isChecked())
        self.time.setEnabled(self.due_on.isChecked())
        self._loading = False
        self._save_due()

    def _group_chosen(self, index: int):
        data = self.group.itemData(index)
        if data == "__new__":
            g = self.panel.ask_new_group()
            if g:
                self.store.update_task(self.tid, group=g.id)
            self.sync_groups()
            return
        self.store.update_task(self.tid, group=data or None)

    def _set_status(self, st: str):
        if self.tid:
            self.store.set_status(self.tid, st)

    def _delete(self):
        if self.tid:
            tid = self.tid
            self.panel.close_details()
            self.panel.delete_task(tid)
