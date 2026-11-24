"""Coluna do quadro e barra de grupos (chips de filtro)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..config import C, STATUS_LABEL
from ..store import Group, Task
from .tasklist import TaskList
from .theme import dot_icon

class Column(QFrame):
    def __init__(self, status: str):
        super().__init__()
        self.setObjectName("column")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 10, 6, 6)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 8, 0)
        head.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background:{C[status]}; border-radius:4px;")
        name = QLabel(STATUS_LABEL[status])
        name.setObjectName("colTitle")
        self.count = QLabel("0")
        self.count.setObjectName("muted")
        head.addWidget(dot)
        head.addWidget(name)
        head.addWidget(self.count)
        head.addStretch(1)
        lay.addLayout(head)
        empty = {"todo": "Nada a fazer", "doing": "Arraste algo pra cá", "done": "Nada feito ainda"}[status]
        self.list = TaskList(status=status, show_check=False, empty_text=empty)
        lay.addWidget(self.list, 1)

    def set_tasks(self, tasks: list[Task], groups: dict[str, Group], show_group: bool) -> None:
        self.list.set_tasks(tasks, groups, show_group)
        self.count.setText(str(len(tasks)))


class GroupBar(QScrollArea):
    """Chips de filtro: Tudo · Grupo A · Grupo B · +"""

    selected = Signal(str)            # "all" | id do grupo
    createRequested = Signal()
    menuRequested = Signal(str, QPoint)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        inner = QWidget()
        inner.setObjectName("chipRow")
        self.row = QHBoxLayout(inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.setWidget(inner)
        self._sig = None

    def set_groups(self, groups: list[Group], current: str, counts: dict) -> None:
        sig = (tuple((g.id, g.name, g.color) for g in groups), current, tuple(sorted(counts.items())))
        if sig == self._sig:
            return
        self._sig = sig
        while self.row.count():
            w = self.row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._chip("Tudo", "all", None, counts.get("all", 0), current)
        for g in groups:
            self._chip(g.name, g.id, g.color, counts.get(g.id, 0), current)
        add = QPushButton("+")
        add.setObjectName("chipAdd")
        add.setToolTip("Novo grupo")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add.clicked.connect(self.createRequested)
        self.row.addWidget(add)
        self.row.addStretch(1)

    def _chip(self, name, gid, color, count, current):
        b = QPushButton(f"{name}  {count}" if count else name)
        b.setObjectName("chip")
        b.setCheckable(True)
        b.setAutoExclusive(True)
        b.setChecked(gid == current)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if color:
            b.setIcon(dot_icon(color))
            b.setIconSize(QSize(8, 8))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, b=b, gid=gid: self.menuRequested.emit(gid, b.mapToGlobal(pos)))
            b.setToolTip("Botão direito: renomear, cor, excluir")
        b.clicked.connect(lambda *_, gid=gid: self.selected.emit(gid))
        self.row.addWidget(b)

    def wheelEvent(self, e):
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() - e.angleDelta().y() // 2)
        e.accept()
