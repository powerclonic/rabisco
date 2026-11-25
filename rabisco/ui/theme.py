"""Tema escuro: folha de estilo, paleta, fontes e ícones desenhados em tempo de execução."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap

from ..config import C, ICON_FONTS, IS_WIN

if IS_WIN:
    from ..winapi import is_win11

def icon_font(px: float) -> QFont:
    f = QFont()
    f.setFamilies(ICON_FONTS)
    f.setPixelSize(max(6, round(px)))
    return f


def small_font(base: QFont) -> QFont:
    f = QFont(base)
    if base.pointSizeF() > 0:
        f.setPointSizeF(base.pointSizeF() * 0.86)
    elif base.pixelSize() > 0:
        f.setPixelSize(max(8, round(base.pixelSize() * 0.86)))
    return f


def dot_icon(color: str, px: int = 10) -> QIcon:
    pm = QPixmap(px * 2, px * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(1, 1, px - 2, px - 2))
    p.end()
    return QIcon(pm)


def glyph_icon(glyph: str, color: str, px: int = 16) -> QIcon:
    pm = QPixmap(px * 2, px * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(icon_font(px * 0.72))
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


def make_fallback_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C["accent"]))
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)
    path = QPainterPath()
    path.moveTo(18, 33)
    path.lineTo(28, 43)
    path.lineTo(47, 23)
    p.setPen(QPen(QColor("#262016"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def stylesheet() -> str:
    win10_border = "" if (not IS_WIN or is_win11()) else f"border:1px solid {C['border']};"
    icon_fonts = ",".join(f'"{f}"' for f in ICON_FONTS)
    return f"""
    QWidget {{ color:{C['text']}; }}
    QFrame#card {{ background:{C['bg']}; {win10_border} }}
    QLabel#title {{ font-size:12pt; font-weight:600; }}
    QLabel#muted, QLabel#hint {{ color:{C['muted']}; }}
    QLabel#hint {{ font-size:8.5pt; }}
    QLabel#colTitle {{ font-weight:600; }}
    QLineEdit#input {{
        background:{C['surface']}; border:1px solid {C['border']}; border-radius:8px;
        padding:8px 6px 8px 10px; selection-background-color:{C['accent']}; selection-color:{C['bg']};
    }}
    QLineEdit#input:focus {{ border-color:{C['accent']}; }}
    QLineEdit#cardEditor {{
        background:{C['card_hover']}; border:1px solid {C['accent']}; border-radius:8px;
        padding:0 10px; selection-background-color:{C['accent']}; selection-color:{C['bg']};
    }}
    QLineEdit#detailTitle {{
        background:transparent; border:none; border-bottom:1px solid {C['border']};
        font-size:12.5pt; font-weight:600; padding:4px 2px 6px 2px;
        selection-background-color:{C['accent']}; selection-color:{C['bg']};
    }}
    QLineEdit#detailTitle:focus {{ border-bottom-color:{C['accent']}; }}
    QPlainTextEdit#notes {{
        background:{C['surface']}; border:1px solid {C['border']}; border-radius:8px; padding:6px 8px;
        selection-background-color:{C['accent']}; selection-color:{C['bg']};
    }}
    QPlainTextEdit#notes:focus {{ border-color:{C['accent']}; }}
    QLineEdit#field {{
        background:{C['surface']}; border:1px solid {C['border']}; border-radius:6px; padding:4px 8px;
        min-height:22px; selection-background-color:{C['accent']}; selection-color:{C['bg']};
    }}
    QLineEdit#field:focus {{ border-color:{C['accent']}; }}
    QLineEdit#field:disabled {{ color:{C['muted']}; background:{C['bg']}; }}
    QDateEdit, QTimeEdit, QComboBox {{
        background:{C['surface']}; border:1px solid {C['border']}; border-radius:6px;
        padding:4px 8px; min-height:22px;
    }}
    QDateEdit:focus, QTimeEdit:focus, QComboBox:focus {{ border-color:{C['accent']}; }}
    QDateEdit:disabled, QTimeEdit:disabled {{ color:{C['muted']}; background:{C['bg']}; }}
    QComboBox QAbstractItemView {{
        background:{C['surface']}; border:1px solid {C['border']};
        selection-background-color:{C['card_hover']}; outline:0;
    }}
    QCheckBox {{ spacing:6px; }}
    QCheckBox::indicator {{
        width:14px; height:14px; border:1px solid {C['border']}; border-radius:4px; background:{C['surface']};
    }}
    QCheckBox::indicator:checked {{ background:{C['accent']}; border-color:{C['accent']}; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background:{C['surface']}; }}
    QCalendarWidget QToolButton {{ color:{C['text']}; background:transparent; border:none; padding:4px 8px; }}
    QCalendarWidget QToolButton:hover {{ background:{C['card_hover']}; border-radius:4px; }}
    QCalendarWidget QAbstractItemView:enabled {{
        background:{C['surface']}; color:{C['text']};
        selection-background-color:{C['accent']}; selection-color:{C['bg']}; outline:0;
    }}
    QFrame#segbox {{ background:{C['surface']}; border-radius:8px; }}
    QPushButton#seg {{
        background:transparent; border:none; border-radius:6px; padding:4px 10px; color:{C['muted']};
    }}
    QPushButton#seg:hover {{ color:{C['text']}; }}
    QPushButton#seg:checked {{ background:{C['card_hover']}; color:{C['text']}; }}
    QPushButton#icon {{
        font-family:{icon_fonts}; font-size:10pt;
        background:transparent; border:none; border-radius:6px;
        min-width:28px; max-width:28px; min-height:28px; max-height:28px; color:{C['muted']};
    }}
    QPushButton#icon:hover {{ background:{C['card_hover']}; color:{C['text']}; }}
    QPushButton#icon:checked {{ color:{C['accent']}; }}
    QPushButton#link {{
        background:transparent; border:none; color:{C['muted']}; padding:2px 5px; font-size:8.5pt;
    }}
    QPushButton#link:hover {{ color:{C['accent']}; }}
    QWidget#chipRow {{ background:transparent; }}
    QPushButton#chip {{
        background:{C['surface']}; border:1px solid transparent; border-radius:11px;
        padding:3px 10px; color:{C['muted']}; font-size:9pt;
    }}
    QPushButton#chip:hover {{ color:{C['text']}; }}
    QPushButton#chip:checked {{ background:{C['card_hover']}; color:{C['text']}; border-color:{C['border']}; }}
    QPushButton#chipAdd {{
        background:transparent; border:1px dashed {C['border']}; border-radius:11px;
        padding:2px 9px; color:{C['muted']}; font-size:9pt;
    }}
    QPushButton#chipAdd:hover {{ color:{C['accent']}; border-color:{C['accent']}; }}
    QFrame#column {{ background:{C['surface']}; border-radius:10px; }}
    QListWidget, QScrollArea {{ background:transparent; border:none; outline:0; }}
    QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}
    QScrollBar::handle:vertical {{ background:#45454F; border-radius:2px; min-height:30px; }}
    QScrollBar::handle:vertical:hover {{ background:#5B5B67; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:none; }}
    QMenu {{ background:{C['surface']}; border:1px solid {C['border']}; padding:4px; }}
    QMenu::item {{ padding:6px 22px 6px 22px; border-radius:4px; }}
    QMenu::item:selected {{ background:{C['card_hover']}; }}
    QMenu::item:disabled {{ color:{C['muted']}; }}
    QMenu::separator {{ height:1px; background:{C['border']}; margin:4px 8px; }}
    QToolTip {{ background:{C['surface']}; color:{C['text']}; border:1px solid {C['border']}; padding:4px 6px; }}
    """


def dark_palette() -> QPalette:
    pal = QPalette()
    roles = QPalette.ColorRole
    for role, key in ((roles.Window, "bg"), (roles.WindowText, "text"), (roles.Base, "surface"),
                      (roles.AlternateBase, "card"), (roles.Text, "text"), (roles.Button, "card"),
                      (roles.ButtonText, "text"), (roles.ToolTipBase, "surface"),
                      (roles.ToolTipText, "text"), (roles.PlaceholderText, "muted"),
                      (roles.Highlight, "accent"), (roles.HighlightedText, "bg")):
        pal.setColor(role, QColor(C[key]))
    return pal
