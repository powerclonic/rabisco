"""Janela principal: painel docado na lateral, tray, menus, animações e atalhos."""
from __future__ import annotations

import datetime as dt
import time

from PySide6.QtCore import QEasingCurve, QEvent, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QActionGroup, QCursor, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton,
    QSizePolicy, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ..config import (
    APP_NAME, BOARD_WIDTH, C, DATA_DIR, EDGE, G_CLOSE, G_EXPAND, G_MORE, G_PIN, G_PINNED,
    GROUP_COLORS, INPUT_HELP, IS_WIN, LIST_WIDTH, MAX_HEIGHT, SLIDE, STATUS_LABEL, STATUSES,
)
from ..dates import is_overdue, make_due, parse_quick, split_due
from ..store import Group, Store, Task
from ..winapi import get_autostart, set_autostart
from .details import DetailPage
from .tasklist import TaskList
from .theme import dot_icon, glyph_icon
from .widgets import Column, GroupBar

if IS_WIN:
    from ..winapi import user32, win_set_topmost, win_style_window

class Panel(QWidget):
    def __init__(self, store: Store, icon: QIcon):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if not IS_WIN and store.settings["pinned"]:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.store = store
        self.icon = icon
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon)
        self._anim = None
        self._hiding = False
        self._quitting = False
        self._autohidden_at = 0.0
        self._styled_hwnd = None
        self.hotkey_ok = False

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)
        store.changed.connect(self._refresh_timer.start)

        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.setInterval(6000)

        # repinta de minuto em minuto: "Hoje" / atrasada mudam com o relógio
        self._clock = QTimer(self)
        self._clock.setInterval(60_000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

        self._build_ui()
        self._build_menu()
        self._build_tray()
        self._build_shortcuts()
        self._undo_timer.timeout.connect(lambda: self.undo_btn.hide())

        self.refresh()
        self.set_view(store.settings["view"], animate=False)

    # construção
    @staticmethod
    def _named(w, name):
        w.setObjectName(name)
        return w

    def icon_button(self, glyph: str, tip: str, checkable=False) -> QPushButton:
        b = self._named(QPushButton(glyph), "icon")
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = self._named(QFrame(), "card")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(8)

        # cabeçalho
        head = QHBoxLayout()
        head.setSpacing(4)
        title = self._named(QLabel(APP_NAME), "title")
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(title, 1)

        segbox = self._named(QFrame(), "segbox")
        sl = QHBoxLayout(segbox)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.btn_list = self._named(QPushButton("Lista"), "seg")
        self.btn_board = self._named(QPushButton("Quadro"), "seg")
        for b, v, tip in ((self.btn_list, "list", "Lista (Ctrl+1)"), (self.btn_board, "board", "Quadro (Ctrl+2)")):
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda *_, v=v: self.set_view(v))
            sl.addWidget(b)
        head.addWidget(segbox)
        head.addSpacing(4)

        self.btn_pin = self.icon_button(G_PIN, "Sempre no topo", checkable=True)
        self.btn_pin.toggled.connect(self.set_pinned)
        self.btn_menu = self.icon_button(G_MORE, "Opções")
        self.btn_menu.clicked.connect(self._show_menu_from_button)
        btn_close = self.icon_button(G_CLOSE, "Esconder (Esc)")
        btn_close.clicked.connect(self.hide_panel)
        head.addWidget(self.btn_pin)
        head.addWidget(self.btn_menu)
        head.addWidget(btn_close)
        lay.addLayout(head)

        # entrada rápida
        self.input = self._named(QLineEdit(), "input")
        self.input.setPlaceholderText("Anotar algo…  (Enter)")
        self.input.setToolTip(INPUT_HELP)
        self.input.returnPressed.connect(self._add_from_input)
        act = self.input.addAction(glyph_icon(G_EXPAND, C["muted"]), QLineEdit.ActionPosition.TrailingPosition)
        act.setToolTip("Adicionar com detalhes (Ctrl+Enter)")
        act.triggered.connect(lambda *_: self._add_from_input(details=True))
        lay.addWidget(self.input)

        # grupos (só aparece se existir algum)
        self.groupbar = GroupBar()
        self.groupbar.selected.connect(self.set_filter)
        self.groupbar.createRequested.connect(self._new_group_and_select)
        self.groupbar.menuRequested.connect(self._group_menu)
        lay.addWidget(self.groupbar)

        # páginas
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.list_view = TaskList(status=None, show_check=True,
                                  empty_text="Tudo limpo por aqui.\nDigite acima e tecle Enter.")
        self._wire(self.list_view)
        self.stack.addWidget(self.list_view)

        board = QWidget()
        board.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        bl = QHBoxLayout(board)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        self.columns: dict[str, Column] = {}
        for s in STATUSES:
            col = Column(s)
            self._wire(col.list)
            self.columns[s] = col
            bl.addWidget(col, 1)
        self.board = board
        self.stack.addWidget(board)

        self.details = DetailPage(self)
        self.stack.addWidget(self.details)
        lay.addWidget(self.stack, 1)

        # rodapé
        foot = QHBoxLayout()
        foot.setSpacing(4)
        self.counter = self._named(QLabel(), "hint")
        self.counter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        foot.addWidget(self.counter, 1)
        self.undo_btn = self._named(QPushButton("Desfazer"), "link")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.hide()
        self.clear_btn = self._named(QPushButton("Limpar feitas"), "link")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.clicked.connect(self.clear_done)
        foot.addWidget(self.undo_btn)
        foot.addWidget(self.clear_btn)
        lay.addLayout(foot)

        self.btn_pin.blockSignals(True)
        self.btn_pin.setChecked(bool(self.store.settings["pinned"]))
        self.btn_pin.setText(G_PINNED if self.store.settings["pinned"] else G_PIN)
        self.btn_pin.blockSignals(False)

    def _wire(self, lst: TaskList):
        lst.dropped.connect(lambda tid, st, before: self.store.move(tid, st or None, before or None))
        lst.toggleRequested.connect(self.store.toggle_done)
        lst.deleteRequested.connect(self.delete_task)
        lst.detailsRequested.connect(self.open_details)
        lst.editedText.connect(lambda tid, text: self.store.update_task(tid, text=text))
        lst.menuRequested.connect(lambda tid, pos, lst=lst: self._task_menu(lst, tid, pos))

    def _build_menu(self):
        m = self.menu = QMenu(self)
        self.act_toggle = m.addAction("Mostrar / esconder", self.toggle_from_tray)
        m.addSeparator()
        self.act_pin = m.addAction("Sempre no topo")
        self.act_pin.setCheckable(True)
        self.act_pin.toggled.connect(self.set_pinned)
        self.act_autohide = m.addAction("Esconder ao perder o foco")
        self.act_autohide.setCheckable(True)
        self.act_autohide.toggled.connect(lambda on: self.store.set_setting("autohide", on))
        self.act_hide_done = m.addAction("Ocultar feitas na lista")
        self.act_hide_done.setCheckable(True)
        self.act_hide_done.toggled.connect(self._set_hide_done)

        side = m.addMenu("Lado da tela")
        grp = QActionGroup(self)
        self.act_side = {}
        for key, label in (("right", "Direita"), ("left", "Esquerda")):
            a = side.addAction(label)
            a.setCheckable(True)
            grp.addAction(a)
            a.triggered.connect(lambda *_, k=key: self.set_side(k))
            self.act_side[key] = a

        self.act_autostart = None
        if IS_WIN:
            self.act_autostart = m.addAction("Iniciar com o Windows")
            self.act_autostart.setCheckable(True)
            self.act_autostart.toggled.connect(set_autostart)
        m.addSeparator()
        m.addAction("Novo grupo…", self._new_group_and_select)
        self.act_undo = m.addAction("Desfazer exclusão", self.undo)
        m.addAction("Abrir pasta de dados", self._open_data_dir)
        self.act_help = m.addAction("")
        self.act_help.setEnabled(False)
        m.addSeparator()
        m.addAction("Sair", self.quit_app)
        m.aboutToShow.connect(self._sync_menu)

    def _sync_menu(self):
        s = self.store.settings
        for act, val in ((self.act_pin, s["pinned"]), (self.act_autohide, s["autohide"]),
                         (self.act_hide_done, s["hide_done"])):
            act.blockSignals(True)
            act.setChecked(bool(val))
            act.blockSignals(False)
        self.act_side.get(s["side"], self.act_side["right"]).setChecked(True)
        if self.act_autostart:
            self.act_autostart.blockSignals(True)
            self.act_autostart.setChecked(get_autostart())
            self.act_autostart.blockSignals(False)
        self.act_undo.setEnabled(self.store.can_undo())
        self.act_toggle.setText("Esconder" if self.isVisible() and not self._hiding else "Mostrar")
        self.act_help.setText(f"Atalho global: {s['hotkey']}" if self.hotkey_ok
                              else "Atalho global indisponível")

    def _open_data_dir(self):
        self.store.save_now()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))

    def _show_menu_from_button(self):
        self.menu.popup(self.btn_menu.mapToGlobal(QPoint(0, self.btn_menu.height() + 2)))

    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray)
        self.tray.show()

    def _on_tray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_from_tray()

    def _build_shortcuts(self):
        def sc(seq, fn):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.activated.connect(fn)
        sc("Ctrl+1", lambda: self.set_view("list"))
        sc("Ctrl+2", lambda: self.set_view("board"))
        sc("Ctrl+N", self._focus_input)
        sc("Ctrl+L", self._focus_input)
        sc("Ctrl+Z", self.undo)
        sc("Ctrl+Q", self.quit_app)

    def set_hotkey_status(self, ok: bool):
        self.hotkey_ok = ok
        hk = self.store.settings["hotkey"]
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME} — {hk}" if ok else APP_NAME)

    # dados → tela
    def refresh(self):
        s = self.store
        vis = s.visible()
        if not self.details_open():  # só reconstrói a página que está na tela
            groups = {g.id: g for g in s.groups}
            show_group = s.settings["filter"] == "all"
            if self.stack.currentIndex() == 0:
                pending = [t for t in vis if t.status != "done"]
                done = [] if s.settings["hide_done"] else [t for t in vis if t.status == "done"]
                self.list_view.set_tasks(pending + done, groups, show_group)
            else:
                for st, col in self.columns.items():
                    col.set_tasks([t for t in vis if t.status == st], groups, show_group)

        counts = {"all": sum(t.status != "done" for t in s.tasks)}
        for t in s.tasks:
            if t.group and t.status != "done":
                counts[t.group] = counts.get(t.group, 0) + 1
        self.groupbar.set_groups(s.groups, s.settings["filter"], counts)
        self.groupbar.setVisible(bool(s.groups) and not self.details_open())

        self._update_counter(vis)
        self.clear_btn.setVisible(any(t.status == "done" for t in vis) and not self.details_open())

        if self.details_open():
            if s.get(self.details.tid) is None:
                self.close_details()
            else:
                self.details.sync_groups()

    def _update_counter(self, vis: list[Task]):
        pending = [t for t in vis if t.status != "done"]
        n = len(pending)
        late = sum(is_overdue(t) for t in pending)
        txt = "tudo em dia" if n == 0 else f"{n} pendente{'s' if n != 1 else ''}"
        if late:
            txt += f"  ·  <span style='color:{C['danger']}'>{late} atrasada{'s' if late != 1 else ''}</span>"
        self.counter.setText(txt)

    def _tick(self):
        if self.isVisible():  # só repinta: não atrapalha uma edição em andamento
            self._update_counter(self.store.visible())
            for lst in (self.list_view, *(c.list for c in self.columns.values())):
                lst.viewport().update()

    # ações
    def _focus_input(self):
        if self.details_open():
            self.close_details()
        self.input.setFocus()
        self.input.selectAll()

    def _add_from_input(self, details: bool = False):
        mods = QApplication.keyboardModifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        details = details or bool(mods & Qt.KeyboardModifier.ControlModifier)
        title, due, gname = parse_quick(self.input.text())
        if not title:
            self.input.setFocus()
            return
        gid = None
        if gname:
            g = self.store.group_by_name(gname) or self.store.add_group(gname)
            gid = g.id if g else None
        elif self.store.settings["filter"] != "all":
            gid = self.store.settings["filter"]
        t = self.store.add(title, "doing" if shift else "todo", group=gid, due=due)
        if t:
            self.input.clear()
            if details:
                self.open_details(t.id, focus_notes=True)

    def delete_task(self, tid: str):
        if self.store.delete(tid):
            self._offer_undo()

    def clear_done(self):
        f = self.store.settings["filter"]
        if self.store.clear_done(None if f == "all" else f):
            self._offer_undo()

    def _offer_undo(self):
        self.undo_btn.show()
        self._undo_timer.start()

    def undo(self):
        self.store.undo()
        self.undo_btn.setVisible(False)

    def _task_menu(self, lst: TaskList, tid: str, gpos: QPoint):
        t = self.store.get(tid)
        if not t:
            return
        m = QMenu(self)
        m.addAction("Detalhes…\tEnter", lambda: self.open_details(tid))
        m.addAction("Renomear\tF2", lambda: lst.editItem(lst.currentItem()))
        mv = m.addMenu("Mover para")
        for st in STATUSES:
            a = mv.addAction(STATUS_LABEL[st], lambda *_, st=st: self.store.set_status(tid, st))
            a.setEnabled(st != t.status)

        dm = m.addMenu("Prazo")
        today = dt.date.today()
        for label, days in (("Hoje", 0), ("Amanhã", 1), ("Próxima semana", 7)):
            dm.addAction(label, lambda *_, d=days: self.store.update_task(
                tid, due=make_due(today + dt.timedelta(days=d), split_due(t.due)[1])))
        if t.due:
            dm.addSeparator()
            dm.addAction("Remover prazo", lambda: self.store.update_task(tid, due=None))

        gm = m.addMenu("Grupo")
        a = gm.addAction("Sem grupo", lambda: self.store.update_task(tid, group=None))
        a.setEnabled(t.group is not None)
        for g in self.store.groups:
            a = gm.addAction(dot_icon(g.color), g.name,
                             lambda *_, gid=g.id: self.store.update_task(tid, group=gid))
            a.setEnabled(g.id != t.group)
        gm.addSeparator()
        gm.addAction("Novo grupo…", lambda: self._new_group_for_task(tid))

        m.addAction("Copiar texto", lambda: QGuiApplication.clipboard().setText(
            t.text + (f"\n\n{t.notes}" if t.notes else "")))
        m.addSeparator()
        m.addAction("Excluir\tDel", lambda: self.delete_task(tid))
        m.exec(gpos)

    # detalhes
    def details_open(self) -> bool:
        return self.stack.currentWidget() is self.details

    def open_details(self, tid: str, focus_notes: bool = False):
        if not self.details.load(tid):
            return
        if not self.isVisible():
            self.show_panel()
        self.stack.setCurrentWidget(self.details)
        self.input.hide()
        self.groupbar.hide()
        self.clear_btn.hide()
        if focus_notes:
            self.details.notes.setFocus()
        else:
            self.details.title.setFocus()
            self.details.title.end(False)

    def close_details(self):
        if not self.details_open():
            return
        self.details.title.clearFocus()
        self.details.tid = None
        self.stack.setCurrentIndex(0 if self.store.settings["view"] == "list" else 1)
        self.input.show()
        self.refresh()
        self.input.setFocus()

    # grupos
    def ask_group_name(self, title: str, text: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, "Nome do grupo:", QLineEdit.EchoMode.Normal, text)
        name = " ".join(name.split()) if ok else ""
        return name or None

    def ask_new_group(self) -> Group | None:
        name = self.ask_group_name("Novo grupo")
        return self.store.add_group(name) if name else None

    def _new_group_and_select(self):
        if not self.isVisible():
            self.show_panel()
        g = self.ask_new_group()
        if g:
            self.set_filter(g.id)

    def _new_group_for_task(self, tid: str):
        g = self.ask_new_group()
        if g:
            self.store.update_task(tid, group=g.id)

    def set_filter(self, fid: str):
        if fid != "all" and not self.store.get_group(fid):
            fid = "all"
        self.store.set_setting("filter", fid)
        self.refresh()

    def _group_menu(self, gid: str, gpos: QPoint):
        g = self.store.get_group(gid)
        if not g:
            return
        m = QMenu(self)
        m.addAction("Renomear…", lambda: self._rename_group(gid))
        cm = m.addMenu("Cor")
        for name, col in GROUP_COLORS:
            a = cm.addAction(dot_icon(col), name, lambda *_, c=col: self.store.set_group_color(gid, c))
            a.setEnabled(col != g.color)
        m.addSeparator()
        m.addAction("Excluir grupo (mantém as tarefas)", lambda: self._delete_group(gid))
        m.exec(gpos)

    def _rename_group(self, gid: str):
        g = self.store.get_group(gid)
        if g:
            name = self.ask_group_name("Renomear grupo", g.name)
            if name:
                self.store.rename_group(gid, name)

    def _delete_group(self, gid: str):
        if self.store.delete_group(gid):
            self._offer_undo()

    # preferências
    def _set_hide_done(self, on: bool):
        self.store.set_setting("hide_done", on)
        self.refresh()

    def set_pinned(self, on: bool):
        self.store.set_setting("pinned", bool(on))
        for w in (self.btn_pin, self.act_pin):
            w.blockSignals(True)
            w.setChecked(bool(on))
            w.blockSignals(False)
        self.btn_pin.setText(G_PINNED if on else G_PIN)
        self._apply_topmost()

    def set_side(self, side: str):
        self.store.set_setting("side", side)
        if self.isVisible():
            self._animate_geometry(self._target_rect(self.screen()))

    def set_view(self, view: str, animate: bool = True):
        if view not in ("list", "board"):
            view = "list"
        if self.details_open():
            self.close_details()
        self.store.set_setting("view", view)
        self.btn_list.setChecked(view == "list")
        self.btn_board.setChecked(view == "board")
        self.stack.setCurrentIndex(0 if view == "list" else 1)
        self.refresh()
        if self.isVisible() and not self._hiding:
            target = self._target_rect(self.screen())
            if animate:
                self._animate_geometry(target)
            else:
                self.setGeometry(target)

    # geometria / animação
    def _target_rect(self, screen) -> QRect:
        ag = screen.availableGeometry()
        w = BOARD_WIDTH if self.store.settings["view"] == "board" else LIST_WIDTH
        # nunca menor que o mínimo do layout (senão o Qt alarga pra direita e sai da tela)
        w = max(w, self.minimumSizeHint().width(), self.minimumWidth())
        w = min(w, ag.width() - 2 * EDGE)
        h = min(MAX_HEIGHT, ag.height() - 2 * EDGE)
        h = max(h, min(self.minimumSizeHint().height(), ag.height() - 2 * EDGE))
        y = ag.top() + (ag.height() - h) // 2
        if self.store.settings["side"] == "left":
            x = ag.left() + EDGE
        else:
            x = ag.left() + ag.width() - EDGE - w
        return QRect(x, y, w, h)

    def _slide_dx(self) -> int:
        return -SLIDE if self.store.settings["side"] == "left" else SLIDE

    def _stop_anim(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def _animate_geometry(self, target: QRect):
        self._stop_anim()
        a = QPropertyAnimation(self, b"geometry", self)
        a.setDuration(180)
        a.setStartValue(self.geometry())
        a.setEndValue(target)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(self._snap_to_edge)
        a.start()
        self._anim = a

    def _snap_to_edge(self):
        """Garante que a janela termina encostada na borda certa, com o mesmo respiro dos dois lados."""
        if not self.isVisible() or self._hiding:
            return
        ag = self.screen().availableGeometry()
        g = self.frameGeometry()
        if self.store.settings["side"] == "left":
            x = ag.left() + EDGE
        else:
            x = ag.left() + ag.width() - EDGE - g.width()
        if g.x() != x:
            self.move(self.x() + (x - g.x()), self.y())

    def show_panel(self):
        if self.isVisible() and not self._hiding:
            self._activate()
            if not self.details_open():
                self._focus_input()
            return
        self._stop_anim()
        self._hiding = False
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        target = self._target_rect(screen)
        start = target.translated(self._slide_dx(), 0)
        self.setWindowOpacity(0.0)
        self.setGeometry(start)
        self.show()
        self._activate()

        grp = QParallelAnimationGroup(self)
        pos = QPropertyAnimation(self, b"pos", self)
        pos.setDuration(190)
        pos.setStartValue(start.topLeft())
        pos.setEndValue(target.topLeft())
        pos.setEasingCurve(QEasingCurve.Type.OutCubic)
        op = QPropertyAnimation(self, b"windowOpacity", self)
        op.setDuration(150)
        op.setStartValue(0.0)
        op.setEndValue(1.0)
        grp.addAnimation(pos)
        grp.addAnimation(op)
        grp.finished.connect(self._snap_to_edge)
        grp.start()
        self._anim = grp
        if not self.details_open():
            self._focus_input()

    def hide_panel(self):
        if not self.isVisible() or self._hiding:
            return
        self._stop_anim()
        self._hiding = True
        grp = QParallelAnimationGroup(self)
        pos = QPropertyAnimation(self, b"pos", self)
        pos.setDuration(140)
        pos.setStartValue(self.pos())
        pos.setEndValue(self.pos() + QPoint(self._slide_dx(), 0))
        pos.setEasingCurve(QEasingCurve.Type.InCubic)
        op = QPropertyAnimation(self, b"windowOpacity", self)
        op.setDuration(140)
        op.setStartValue(self.windowOpacity())
        op.setEndValue(0.0)
        grp.addAnimation(pos)
        grp.addAnimation(op)
        grp.finished.connect(self._finish_hide)
        grp.start()
        self._anim = grp

    def _finish_hide(self):
        self._anim = None
        self.hide()
        self.setWindowOpacity(1.0)
        self._hiding = False
        self.store.save_now()

    def toggle_from_hotkey(self):
        if self.isVisible() and not self._hiding:
            if self.isActiveWindow():
                self.hide_panel()
            else:
                self._activate()
                if not self.details_open():
                    self._focus_input()
        else:
            self.show_panel()

    def toggle_from_tray(self):
        if time.monotonic() - self._autohidden_at < 0.5:
            return  # o clique no tray acabou de esconder por perda de foco
        if self.isVisible() and not self._hiding:
            self.hide_panel()
        else:
            self.show_panel()

    def _activate(self):
        self.raise_()
        self.activateWindow()
        self._apply_topmost()
        if IS_WIN:
            user32.SetForegroundWindow(int(self.winId()))

    def _apply_topmost(self):
        pinned = bool(self.store.settings["pinned"])
        if IS_WIN:
            win_set_topmost(int(self.winId()), pinned)
        elif bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != pinned:
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
            if visible:
                self.show()

    def quit_app(self):
        self._quitting = True
        self.store.save_now()
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    # eventos
    def showEvent(self, e):
        super().showEvent(e)
        if IS_WIN:
            hwnd = int(self.winId())
            if hwnd != self._styled_hwnd:
                win_style_window(hwnd)
                self._styled_hwnd = hwnd

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.details_open():
                self.close_details()
            elif self.input.hasFocus() and self.input.text():
                self.input.clear()
            else:
                self.hide_panel()
            return
        super().keyPressEvent(e)

    def changeEvent(self, e):
        if (e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow()
                and self.store.settings["autohide"] and self.isVisible() and not self._hiding):
            QTimer.singleShot(120, self._maybe_autohide)
        super().changeEvent(e)

    def _maybe_autohide(self):
        if (self.isActiveWindow() or QApplication.activePopupWidget()
                or QApplication.activeModalWidget() or not self.isVisible()):
            return
        self._autohidden_at = time.monotonic()
        self.hide_panel()

    def closeEvent(self, e):
        if self._quitting or not self.tray:
            self.store.save_now()
            e.accept()
            if not self.tray:
                QApplication.quit()
        else:
            e.ignore()
            self.hide_panel()
