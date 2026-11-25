"""Lista de cartões (com ou sem seções) e arrastar e soltar entre listas/colunas."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QDrag, QPainter, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QListView, QListWidget, QListWidgetItem, QSizePolicy,
)

from ..config import C
from ..sections import SectionInfo
from ..store import Group, Task
from .delegate import CardDelegate
from .roles import (
    MIME, ROLE_COLLAPSED, ROLE_COUNT, ROLE_DELEG_SINCE, ROLE_DELEG_TO, ROLE_DUE, ROLE_GCOLOR,
    ROLE_GNAME, ROLE_ID, ROLE_KIND, ROLE_NOTES, ROLE_QUICK_SINCE, ROLE_SECTION, ROLE_STATUS,
)

Sections = list[tuple[SectionInfo, list[Task]]]


class TaskList(QListWidget):
    """Lista de cartões com arrastar e soltar próprio (o modelo é a fonte da verdade)."""

    # task_id, status ('' = mantém), before_id ('' = fim), seção de destino ('' = lista sem seções)
    dropped = Signal(str, str, str, str)
    toggleRequested = Signal(str)
    quickRequested = Signal(str)
    delegateRequested = Signal(str)
    headerToggled = Signal(str)
    deleteRequested = Signal(str)
    detailsRequested = Signal(str)
    editedText = Signal(str, str)
    menuRequested = Signal(str, QPoint)

    def __init__(self, status: str | None = None, show_check: bool = False, empty_text: str = ""):
        super().__init__()
        self.status = status
        self.empty_text = empty_text
        self._drop_y: int | None = None
        self._drag_over = False
        self._last_width = -1
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(0)
        self._relayout.timeout.connect(self.doItemsLayout)

        self.delegate = CardDelegate(self, show_check)
        self.delegate.toggled.connect(self.toggleRequested)
        self.delegate.headerToggled.connect(self.headerToggled)
        self.setItemDelegate(self.delegate)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.customContextMenuRequested.connect(self._on_menu)
        self.itemChanged.connect(self._on_item_changed)

    # dados
    def set_tasks(self, tasks: list[Task], groups: dict[str, Group], show_group: bool,
                  sections: Sections | None = None, collapsed: list[str] | None = None) -> None:
        """Lista plana (`tasks`) ou agrupada (`sections`, que tem precedência)."""
        cur = self.currentItem()
        cur_id = cur.data(ROLE_ID) if cur else None
        scroll = self.verticalScrollBar().value()
        self.blockSignals(True)
        self.clear()
        if sections is None:
            for t in tasks:
                if self._add_task(t, groups, show_group, "") == cur_id:
                    self.setCurrentItem(self.item(self.count() - 1))
        else:
            collapsed = collapsed or []
            for sec, items in sections:
                self._add_header(sec, len(items), sec.key in collapsed)
                if sec.key in collapsed:
                    continue
                for t in items:
                    if self._add_task(t, groups, show_group, sec.key) == cur_id:
                        self.setCurrentItem(self.item(self.count() - 1))
        self.blockSignals(False)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))
        self.viewport().update()

    def _add_task(self, t: Task, groups: dict[str, Group], show_group: bool, section: str) -> str:
        it = QListWidgetItem(t.text)
        it.setData(ROLE_KIND, "task")
        it.setData(ROLE_SECTION, section)
        it.setData(ROLE_ID, t.id)
        it.setData(ROLE_STATUS, t.status)
        it.setData(ROLE_NOTES, t.notes)
        it.setData(ROLE_DUE, t.due or "")
        it.setData(ROLE_QUICK_SINCE, float(t.quick_since or 0) if t.quick else 0.0)
        it.setData(ROLE_DELEG_SINCE, float(t.delegated_since or 0) if t.delegated else 0.0)
        it.setData(ROLE_DELEG_TO, t.delegated_to if t.delegated else "")
        g = groups.get(t.group) if show_group and t.group else None
        it.setData(ROLE_GNAME, g.name if g else "")
        it.setData(ROLE_GCOLOR, g.color if g else "")
        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
        tip = f"Criada em {time.strftime('%d/%m %H:%M', time.localtime(t.created))}"
        if t.delegated and t.delegated_since:
            who = f" para {t.delegated_to}" if t.delegated_to else ""
            tip += f"\nDelegada{who} em {time.strftime('%d/%m %H:%M', time.localtime(t.delegated_since))}"
        if t.quick and t.quick_since:
            tip += f"\nPra já desde {time.strftime('%d/%m %H:%M', time.localtime(t.quick_since))}"
        if t.done_at:
            tip += f"\nFeita em {time.strftime('%d/%m %H:%M', time.localtime(t.done_at))}"
        it.setToolTip(tip + "\nDuplo clique: detalhes  ·  !: pra já  ·  >: delegada")
        self.addItem(it)
        return t.id

    def _add_header(self, sec: SectionInfo, count: int, collapsed: bool) -> None:
        it = QListWidgetItem(sec.label)
        it.setData(ROLE_KIND, "header")
        it.setData(ROLE_SECTION, sec.key)
        it.setData(ROLE_COUNT, count)
        it.setData(ROLE_COLLAPSED, collapsed)
        it.setFlags(Qt.ItemFlag.ItemIsEnabled)  # não seleciona, não arrasta, não edita
        it.setToolTip("Clique para " + ("expandir" if collapsed else "recolher"))
        self.addItem(it)

    @staticmethod
    def _is_task(it: QListWidgetItem | None) -> bool:
        return it is not None and it.data(ROLE_KIND) == "task"

    def current_id(self) -> str | None:
        it = self.currentItem()
        return it.data(ROLE_ID) if self._is_task(it) else None

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._is_task(item):
            self.editedText.emit(item.data(ROLE_ID), item.text())

    def _on_menu(self, pos: QPoint) -> None:
        it = self.itemAt(pos)
        if self._is_task(it):
            self.setCurrentItem(it)
            self.menuRequested.emit(it.data(ROLE_ID), self.viewport().mapToGlobal(pos))

    def viewportEvent(self, e):
        # largura mudou (janela ou barra de rolagem) -> recalcula a quebra de linha
        if e.type() == QEvent.Type.Resize and self.viewport().width() != self._last_width:
            self._last_width = self.viewport().width()
            self._relayout.start()
        return super().viewportEvent(e)

    def mouseDoubleClickEvent(self, e):
        pos = e.position()
        it = self.itemAt(pos.toPoint())
        if it is not None and not self._is_task(it):
            e.accept()  # cabeçalho: o clique simples já recolhe/expande
            return
        if it is not None and e.button() == Qt.MouseButton.LeftButton:
            idx = self.indexFromItem(it)
            if not self.delegate.hits_check(self.visualItemRect(it), idx, pos):
                self.detailsRequested.emit(it.data(ROLE_ID))
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        tid = self.current_id()
        k = e.key()
        if k == Qt.Key.Key_Escape:
            e.ignore()  # sobe para o painel
            return
        if tid and k == Qt.Key.Key_Delete:
            self.deleteRequested.emit(tid)
            return
        if tid and k == Qt.Key.Key_Space:
            self.toggleRequested.emit(tid)
            return
        if tid and k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.detailsRequested.emit(tid)
            return
        if tid and e.text() == "!":
            self.quickRequested.emit(tid)
            return
        if tid and e.text() == ">":
            self.delegateRequested.emit(tid)
            return
        super().keyPressEvent(e)

    # arrastar
    def startDrag(self, actions):
        it = self.currentItem()
        if not self._is_task(it):
            return
        rect = self.visualItemRect(it)
        mime = QMimeData()
        mime.setData(MIME, it.data(ROLE_ID).encode())
        grab = self.viewport().grab(rect)
        pm = QPixmap(grab.size())
        pm.setDevicePixelRatio(grab.devicePixelRatio())
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setOpacity(0.85)
        painter.drawPixmap(0, 0, grab)
        painter.end()
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pm)
        drag.setHotSpot(self.viewport().mapFromGlobal(QCursor.pos()) - rect.topLeft())
        drag.exec(Qt.DropAction.MoveAction)

    def _next_in_section(self, it: QListWidgetItem, section: str) -> str | None:
        nxt = self.item(self.row(it) + 1)
        if self._is_task(nxt) and (nxt.data(ROLE_SECTION) or "") == section:
            return nxt.data(ROLE_ID)
        return None

    def _drop_target(self, pos: QPoint):
        """-> (before_id | None, y da linha indicadora, seção de destino ou '')"""
        if self.count() == 0:
            return None, 4, ""
        it = self.itemAt(pos)
        if it is None:
            first = self.item(0)
            if pos.y() >= self.visualItemRect(first).top():  # abaixo do último item
                last = self.item(self.count() - 1)
                return None, self.visualItemRect(last).bottom(), last.data(ROLE_SECTION) or ""
            it = first
        rect = self.visualItemRect(it)
        section = it.data(ROLE_SECTION) or ""
        if not self._is_task(it):  # em cima de um cabeçalho: vai para o topo daquela seção
            return self._next_in_section(it, section), rect.bottom(), section
        if pos.y() < rect.center().y():
            return it.data(ROLE_ID), rect.top() + 1, section
        return self._next_in_section(it, section), rect.bottom(), section

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            self._drag_over = True
            e.setDropAction(Qt.DropAction.MoveAction)
            e.accept()
            self.viewport().update()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(MIME):
            e.ignore()
            return
        pos = e.position().toPoint()
        _, self._drop_y, _ = self._drop_target(pos)
        sb = self.verticalScrollBar()  # auto-scroll nas bordas
        if pos.y() < 28:
            sb.setValue(sb.value() - 12)
        elif pos.y() > self.viewport().height() - 28:
            sb.setValue(sb.value() + 12)
        e.setDropAction(Qt.DropAction.MoveAction)
        e.accept()
        self.viewport().update()

    def dragLeaveEvent(self, e):
        self._clear_drag()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME):
            e.ignore()
            return
        tid = e.mimeData().data(MIME).data().decode()
        before, _, section = self._drop_target(e.position().toPoint())
        self._clear_drag()
        e.setDropAction(Qt.DropAction.MoveAction)
        e.accept()
        self.dropped.emit(tid, self.status or "", before or "", section)

    def _clear_drag(self):
        self._drop_y = None
        self._drag_over = False
        self.viewport().update()

    def paintEvent(self, e):
        if self._drag_over:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = QColor(C["accent"])
            col.setAlpha(18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(self.viewport().rect()).adjusted(1, 1, -1, -1), 8, 8)
            p.end()
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.count() == 0 and self.empty_text and not self._drag_over:
            p.setPen(QColor(C["muted"]))
            opt = QTextOption(Qt.AlignmentFlag.AlignHCenter)
            opt.setWrapMode(QTextOption.WrapMode.WordWrap)
            p.drawText(QRectF(self.viewport().rect()).adjusted(12, 24, -12, 0), self.empty_text, opt)
        if self._drop_y is not None:
            y = max(2, min(self._drop_y, self.viewport().height() - 2))
            p.setPen(QPen(QColor(C["accent"]), 2))
            p.drawLine(12, y, self.viewport().width() - 8, y)
            p.setBrush(QColor(C["accent"]))
            p.drawEllipse(QPointF(8, y), 3, 3)
        p.end()
