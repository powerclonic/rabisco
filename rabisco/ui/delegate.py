"""Desenho dos cartões de tarefa (título, descrição, pra já, prazo, grupo e check) e dos cabeçalhos de seção."""
from __future__ import annotations

import math
from types import SimpleNamespace

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QLineEdit, QListWidget, QStyle, QStyledItemDelegate

from ..config import C, G_BOLT, G_CAL, G_CHEVRON_DOWN, G_CHEVRON_RIGHT
from ..dates import age_display, due_display
from ..sections import SECTION_BY_KEY
from .roles import (
    ROLE_COLLAPSED, ROLE_COUNT, ROLE_DUE, ROLE_GCOLOR, ROLE_GNAME, ROLE_ID, ROLE_KIND, ROLE_NOTES,
    ROLE_QUICK_SINCE, ROLE_SECTION, ROLE_STATUS,
)
from .theme import icon_font, small_font

HEADER_HEIGHT = 30


def is_header(index) -> bool:
    return index.data(ROLE_KIND) == "header"


def build_text_layout(text: str, font: QFont, width: float):
    layout = QTextLayout(text.replace("\n", "\u2028"), font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(opt)
    layout.beginLayout()
    y = 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        line.setPosition(QPointF(0, y))
        y += line.height()
    layout.endLayout()
    return layout, y


class CardDelegate(QStyledItemDelegate):
    """Desenha cada tarefa como um cartão: título, 1ª linha da descrição e linha de prazo/grupo."""

    toggled = Signal(str)
    headerToggled = Signal(str)

    MX, MY = 4, 3        # margem externa do cartão
    PX, PY = 12, 9       # padding interno
    CHECK, GAP = 18, 10

    def __init__(self, view: QListWidget, show_check: bool):
        super().__init__(view)
        self.view = view
        self.show_check = show_check

    def _text_width(self, total: int) -> float:
        w = total - 2 * self.MX - 2 * self.PX
        w -= (self.CHECK + self.GAP) if self.show_check else 4
        return max(40.0, float(w))

    def _info(self, font: QFont, index, width: int):
        title = index.data() or ""
        notes = (index.data(ROLE_NOTES) or "").strip()
        due = index.data(ROLE_DUE) or ""
        gname = index.data(ROLE_GNAME) or ""
        done = index.data(ROLE_STATUS) == "done"
        quick_since = 0.0 if done else float(index.data(ROLE_QUICK_SINCE) or 0)
        tw = self._text_width(width)
        layout, th = build_text_layout(title, font, tw)
        lh = QFontMetricsF(font).height()
        sf = small_font(font)
        sf.setStrikeOut(False)
        sh = QFontMetricsF(sf).height()
        if self.show_check:
            first = max(float(self.CHECK), lh)
            text_dy, check_dy = (first - lh) / 2, (first - self.CHECK) / 2
            y = max(th + text_dy, first)
        else:
            text_dy = check_dy = 0.0
            y = max(th, lh)
        notes_y = meta_y = None
        if notes:
            notes_y = y + 2
            y = notes_y + sh
        if due or gname or quick_since:
            meta_y = y + 4
            y = meta_y + sh
        return SimpleNamespace(layout=layout, text_dy=text_dy, check_dy=check_dy, content=y,
                               tw=tw, notes=notes, notes_y=notes_y, due=due, gname=gname,
                               quick_since=quick_since,
                               gcolor=index.data(ROLE_GCOLOR) or C["muted"], meta_y=meta_y, sf=sf)

    def _check_rect(self, card: QRectF, check_dy: float) -> QRectF:
        return QRectF(card.left() + self.PX, card.top() + self.PY + check_dy, self.CHECK, self.CHECK)

    def hits_check(self, rect: QRect, index, pos: QPointF) -> bool:
        if not self.show_check or is_header(index):
            return False
        card = QRectF(rect).adjusted(self.MX, self.MY, -self.MX, -self.MY)
        info = self._info(self.view.font(), index, rect.width())
        return self._check_rect(card, info.check_dy).adjusted(-6, -6, 6, 6).contains(pos)

    def sizeHint(self, option, index):
        # a largura real do item é a do viewport (QListView estica no ListMode)
        if is_header(index):
            return QSize(10, HEADER_HEIGHT)
        width = max(self.view.viewport().width(), 120)
        info = self._info(option.font, index, width)
        return QSize(10, int(math.ceil(info.content + 2 * self.PY + 2 * self.MY)))

    def paint(self, p: QPainter, option, index):
        if is_header(index):
            self._paint_header(p, option, index)
            return
        status = index.data(ROLE_STATUS) or "todo"
        done = status == "done"
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        font = QFont(option.font)
        font.setStrikeOut(done)
        info = self._info(font, index, option.rect.width())

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(self.MX + 0.5, self.MY + 0.5, -self.MX - 0.5, -self.MY - 0.5)
        p.setBrush(QColor(C["card_hover"] if hovered else C["card"]))
        p.setPen(QPen(QColor(C["accent"]), 1.2) if selected else Qt.PenStyle.NoPen)
        p.drawRoundedRect(card, 8, 8)
        p.setClipRect(card)

        x = card.left() + self.PX
        quick = bool(info.quick_since)
        if self.show_check:
            if quick:  # faixa amarela das "pra já"
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(C["accent"]))
                p.drawRoundedRect(QRectF(card.left() + 3, card.top() + 8, 3, card.height() - 16), 1.5, 1.5)
            self._paint_check(p, self._check_rect(card, info.check_dy), status, hovered)
            x += self.CHECK + self.GAP
        else:
            bar = QRectF(card.left() + 5, card.top() + 8, 3, card.height() - 16)
            p.setPen(Qt.PenStyle.NoPen)
            col = QColor(C["accent"] if quick else C[status])
            col.setAlpha(200 if (quick or status != "todo") else 90)
            p.setBrush(col)
            p.drawRoundedRect(bar, 1.5, 1.5)
            x += 4

        top = card.top() + self.PY
        p.setPen(QColor(C["muted"] if done else C["text"]))
        info.layout.draw(p, QPointF(x, top + info.text_dy))

        sfm = QFontMetricsF(info.sf)
        if info.notes_y is not None:
            line = next((ln for ln in info.notes.splitlines() if ln.strip()), "")
            p.setFont(info.sf)
            p.setPen(QColor(C["muted"]))
            p.drawText(QPointF(x, top + info.notes_y + sfm.ascent()),
                       sfm.elidedText(line, Qt.TextElideMode.ElideRight, info.tw))
        if info.meta_y is not None:
            base = top + info.meta_y + sfm.ascent()
            cx = x
            icf = icon_font(sfm.height() * 0.68)
            icm = QFontMetricsF(icf)

            def chip(glyph: str, label: str, color: str) -> None:
                nonlocal cx
                p.setFont(icf)
                p.setPen(QColor(color))
                p.drawText(QPointF(cx, base - 0.5), glyph)
                cx += icm.horizontalAdvance(glyph) + 4
                p.setFont(info.sf)
                p.drawText(QPointF(cx, base), label)
                cx += sfm.horizontalAdvance(label) + 12

            if quick:
                chip(G_BOLT, *age_display(info.quick_since))
            if info.due:
                chip(G_CAL, *due_display(info.due, done))
            if info.gname:
                cy = top + info.meta_y + sfm.height() / 2
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(info.gcolor))
                p.drawEllipse(QPointF(cx + 3, cy), 3, 3)
                cx += 10
                p.setFont(info.sf)
                p.setPen(QColor(C["muted"]))
                room = card.right() - self.PX - cx
                p.drawText(QPointF(cx, base), sfm.elidedText(info.gname, Qt.TextElideMode.ElideRight, room))
        p.restore()

    def _paint_header(self, p: QPainter, option, index):
        sec = SECTION_BY_KEY.get(index.data(ROLE_SECTION))
        if sec is None:
            return
        collapsed = bool(index.data(ROLE_COLLAPSED))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        r = QRectF(option.rect).adjusted(self.MX + 4, 0, -self.MX - 4, 0)
        sf = small_font(option.font)
        sf.setBold(True)
        sf.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106)
        sfm = QFontMetricsF(sf)
        icf = icon_font(sfm.height() * 0.72)
        icm = QFontMetricsF(icf)
        base = r.top() + (r.height() + sfm.ascent() - sfm.descent()) / 2 + 2

        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = r.left()
        p.setFont(icf)
        p.setPen(QColor(C[sec.color]))
        p.drawText(QPointF(x, base), sec.glyph)
        x += icm.horizontalAdvance(sec.glyph) + 7
        p.setFont(sf)
        p.setPen(QColor(C["text"] if hovered else C["soft"]))
        label = sec.label.upper()
        p.drawText(QPointF(x, base), label)
        x += sfm.horizontalAdvance(label) + 7
        p.setPen(QColor(C["muted"]))
        p.drawText(QPointF(x, base), str(index.data(ROLE_COUNT) or 0))
        chevron = G_CHEVRON_RIGHT if collapsed else G_CHEVRON_DOWN
        p.setFont(icf)
        p.drawText(QPointF(r.right() - icm.horizontalAdvance(chevron), base), chevron)
        p.restore()

    def _paint_check(self, p: QPainter, r: QRectF, status: str, hovered: bool):
        color = QColor(C[status])
        if status == "done":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(r)
            path = QPainterPath()
            path.moveTo(r.x() + r.width() * 0.28, r.y() + r.height() * 0.52)
            path.lineTo(r.x() + r.width() * 0.44, r.y() + r.height() * 0.67)
            path.lineTo(r.x() + r.width() * 0.73, r.y() + r.height() * 0.36)
            p.setPen(QPen(QColor(C["bg"]), 2.0, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            return
        if hovered and status == "todo":
            color = QColor(C["text"])
        p.setPen(QPen(color, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
        if status == "doing":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(r.adjusted(5, 5, -5, -5))

    def editorEvent(self, event, model, option, index):
        if is_header(index):
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                                QEvent.Type.MouseButtonDblClick):
                if (event.type() == QEvent.Type.MouseButtonRelease
                        and event.button() == Qt.MouseButton.LeftButton):
                    self.headerToggled.emit(index.data(ROLE_SECTION))
                return True  # cabeçalho: só recolhe/expande
            return False
        if self.show_check and event.type() in (QEvent.Type.MouseButtonPress,
                                                QEvent.Type.MouseButtonRelease,
                                                QEvent.Type.MouseButtonDblClick):
            if self.hits_check(option.rect, index, event.position()):
                if (event.type() == QEvent.Type.MouseButtonRelease
                        and event.button() == Qt.MouseButton.LeftButton):
                    self.toggled.emit(index.data(ROLE_ID))
                return True  # não seleciona / não arrasta / não abre detalhes
        return super().editorEvent(event, model, option, index)

    # renomear inline (F2)
    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setObjectName("cardEditor")
        ed.setFrame(False)
        return ed

    def setEditorData(self, editor, index):
        editor.setText(index.data() or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect.adjusted(self.MX, self.MY, -self.MX, -self.MY)
        r.setHeight(min(r.height(), 40))
        editor.setGeometry(r)
