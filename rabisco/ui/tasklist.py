"""Lista de cartões com arrastar e soltar entre listas/colunas."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QDrag, QPainter, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QListView, QListWidget, QListWidgetItem, QSizePolicy,
)

from ..config import C
from ..store import Group, Task
from .delegate import CardDelegate
from .roles import MIME, ROLE_DUE, ROLE_GCOLOR, ROLE_GNAME, ROLE_ID, ROLE_NOTES, ROLE_STATUS

class TaskList(QListWidget):
    """Lista de cartões com arrastar e soltar próprio (o modelo é a fonte da verdade)."""

    dropped = Signal(str, str, str)   # task_id, status ('' = mantém), before_id ('' = fim)
    toggleRequested = Signal(str)
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
    def set_tasks(self, tasks: list[Task], groups: dict[str, Group], show_group: bool) -> None:
        cur = self.currentItem()
        cur_id = cur.data(ROLE_ID) if cur else None
        scroll = self.verticalScrollBar().value()
        self.blockSignals(True)
        self.clear()
        flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                 | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
        for t in tasks:
            it = QListWidgetItem(t.text)
            it.setData(ROLE_ID, t.id)
            it.setData(ROLE_STATUS, t.status)
            it.setData(ROLE_NOTES, t.notes)
            it.setData(ROLE_DUE, t.due or "")
            g = groups.get(t.group) if show_group and t.group else None
            it.setData(ROLE_GNAME, g.name if g else "")
            it.setData(ROLE_GCOLOR, g.color if g else "")
            it.setFlags(flags)
            tip = f"Criada em {time.strftime('%d/%m %H:%M', time.localtime(t.created))}"
            if t.done_at:
                tip += f"\nFeita em {time.strftime('%d/%m %H:%M', time.localtime(t.done_at))}"
            it.setToolTip(tip + "\nDuplo clique: detalhes")
            self.addItem(it)
            if t.id == cur_id:
                self.setCurrentItem(it)
        self.blockSignals(False)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))
        self.viewport().update()

    def current_id(self) -> str | None:
        it = self.currentItem()
        return it.data(ROLE_ID) if it else None

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        self.editedText.emit(item.data(ROLE_ID), item.text())

    def _on_menu(self, pos: QPoint) -> None:
        it = self.itemAt(pos)
        if it:
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
        super().keyPressEvent(e)

    # arrastar
    def startDrag(self, actions):
        it = self.currentItem()
        if not it:
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

    def _drop_target(self, pos: QPoint):
        """-> (before_id | None, y da linha indicadora)"""
        it = self.itemAt(pos)
        if it is None:
            if self.count():
                first = self.visualItemRect(self.item(0))
                if pos.y() < first.top():
                    return self.item(0).data(ROLE_ID), first.top() + 1
                return None, self.visualItemRect(self.item(self.count() - 1)).bottom()
            return None, 4
        rect = self.visualItemRect(it)
        if pos.y() < rect.center().y():
            return it.data(ROLE_ID), rect.top() + 1
        nxt = self.item(self.row(it) + 1)
        return (nxt.data(ROLE_ID) if nxt else None), rect.bottom()

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
        _, self._drop_y = self._drop_target(pos)
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
        before, _ = self._drop_target(e.position().toPoint())
        self._clear_drag()
        e.setDropAction(Qt.DropAction.MoveAction)
        e.accept()
        self.dropped.emit(tid, self.status or "", before or "")

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
