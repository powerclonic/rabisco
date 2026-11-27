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
    APP_NAME, BOARD_WIDTH, C, DATA_DIR, EDGE, G_CLOSE, G_EXPAND, G_MORE, G_PIN, G_PINNED, G_SEARCH,
    GROUP_COLORS, INPUT_HELP, IS_WIN, LIST_WIDTH, MAX_HEIGHT, SLIDE, STATUS_LABEL, STATUSES,
)
from ..dates import due_display, is_overdue, make_due, next_weekday, parse_quick, split_due
from ..sections import build_sections, quick_first
from ..store import Group, Store, Task
from ..winapi import get_autostart, set_autostart
from .details import DetailPage
from .report import ReportPage
from .tasklist import TaskList
from .theme import dot_icon, glyph_icon
from .widgets import Column, GroupBar, ShortcutsOverlay

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
        self._searching = False
        self._note_tid: str | None = None
        self._note_back: TaskList | None = None
        self._reminder_tid: str | None = None

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)
        store.changed.connect(self._refresh_timer.start)

        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.setInterval(6000)

        # a cada 30 s: lembretes de prazo e repintura ("Hoje" / atrasada mudam com o relógio)
        self._clock = QTimer(self)
        self._clock.setInterval(30_000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

        self._build_ui()
        self._build_menu()
        self._build_tray()
        self._build_shortcuts()
        self._undo_timer.timeout.connect(self._hide_undo)

        self.refresh()
        self.set_view(store.settings["view"], animate=False)
        QTimer.singleShot(2000, self._check_reminders)

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
        self.input.setPlaceholderText("Anotar algo…   (F1: atalhos)")
        self.input.setToolTip(INPUT_HELP)
        self.input.returnPressed.connect(self._add_from_input)
        self.input.installEventFilter(self)
        act = self.input.addAction(glyph_icon(G_EXPAND, C["muted"]), QLineEdit.ActionPosition.TrailingPosition)
        act.setToolTip("Adicionar com detalhes (Ctrl+Enter)")
        act.triggered.connect(lambda *_: self._add_from_input(details=True))
        lay.addWidget(self.input)

        # busca (Ctrl+F)
        self.search = self._named(QLineEdit(), "search")
        self.search.setPlaceholderText("Buscar…   (Esc fecha)")
        self.search.addAction(glyph_icon(G_SEARCH, C["muted"]), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self._refresh_timer.start())
        self.search.installEventFilter(self)
        self.search.hide()
        lay.addWidget(self.search)

        # comentário ao concluir (Shift+Espaço / Shift+clique no círculo)
        self.note_bar = self._named(QFrame(), "noteBar")
        nl = QVBoxLayout(self.note_bar)
        nl.setContentsMargins(10, 7, 10, 8)
        nl.setSpacing(5)
        self.note_title = self._named(QLabel(), "noteTitle")
        self.note_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.note_edit = self._named(QLineEdit(), "noteEdit")
        self.note_edit.setPlaceholderText("Como ficou?   (Enter salva · Esc pula)")
        self.note_edit.returnPressed.connect(self._save_note)
        nl.addWidget(self.note_title)
        nl.addWidget(self.note_edit)
        self.note_bar.hide()
        lay.addWidget(self.note_bar)

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
        self.report = ReportPage(self)
        self.stack.addWidget(self.report)
        lay.addWidget(self.stack, 1)

        # rodapé
        foot = QHBoxLayout()
        foot.setSpacing(4)
        self.counter = self._named(QLabel(), "hint")
        self.counter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        foot.addWidget(self.counter, 1)
        self.undo_btn = self._named(QPushButton("Desfazer"), "undo")
        self.undo_btn.setToolTip("Desfazer (Ctrl+Z)")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.hide()
        self.clear_btn = self._named(QPushButton("Limpar feitas"), "link")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.clicked.connect(self.clear_done)
        self.clear_btn.setToolTip("Tira as feitas da lista (continuam no relatório, Ctrl+R)")
        foot.addWidget(self.undo_btn)
        foot.addWidget(self.clear_btn)
        lay.addLayout(foot)

        self.help = ShortcutsOverlay(card)

        self.btn_pin.blockSignals(True)
        self.btn_pin.setChecked(bool(self.store.settings["pinned"]))
        self.btn_pin.setText(G_PINNED if self.store.settings["pinned"] else G_PIN)
        self.btn_pin.blockSignals(False)

    def _wire(self, lst: TaskList):
        lst.dropped.connect(self._on_drop)
        lst.toggleRequested.connect(self.toggle_done)
        lst.typed.connect(self._type_into_input)
        lst.leaveTop.connect(self._leave_list)
        lst.neighborRequested.connect(lambda d, lst=lst: self._focus_neighbor(lst, d))
        lst.statusStep.connect(self._step_status)
        lst.noteRequested.connect(lambda tid, lst=lst: self.open_note(tid, lst))
        lst.postponeRequested.connect(self.postpone)
        lst.quickRequested.connect(self.store.toggle_quick)
        lst.delegateRequested.connect(self.store.toggle_delegated)
        lst.headerToggled.connect(self.store.toggle_collapsed)
        lst.deleteRequested.connect(self.delete_task)
        lst.detailsRequested.connect(self.open_details)
        lst.editedText.connect(lambda tid, text: self.store.update_task(tid, text=text))
        lst.menuRequested.connect(lambda tid, pos, lst=lst: self._task_menu(lst, tid, pos))

    def _on_drop(self, tid: str, status: str, before: str, section: str):
        if section:  # lista agrupada: a seção de destino define pra já / status
            self.store.drop_into_section(tid, section, before or None)
        else:
            self.store.move(tid, status or None, before or None)

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
        self.act_remind = m.addAction("Avisar na hora do prazo")
        self.act_remind.setCheckable(True)
        self.act_remind.toggled.connect(lambda on: self.store.set_setting("reminders", on))
        self.act_hide_done = m.addAction("Ocultar feitas na lista")
        self.act_hide_done.setCheckable(True)
        self.act_hide_done.toggled.connect(self._set_hide_done)
        self.act_smart = m.addAction("Agrupar lista em seções")
        self.act_smart.setCheckable(True)
        self.act_smart.toggled.connect(
            lambda on: (self.store.set_setting("sort", "smart" if on else "manual"), self.refresh()))

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
        m.addAction("Buscar…\tCtrl+F", self.open_search)
        m.addAction("Relatório de concluídas…\tCtrl+R", self.open_report)
        m.addAction("Novo grupo…", self._new_group_and_select)
        self.act_undo = m.addAction("Desfazer\tCtrl+Z", self.undo)
        m.addAction("Atalhos de teclado\tF1", self.show_help)
        m.addAction("Abrir pasta de dados", self._open_data_dir)
        self.act_help = m.addAction("")
        self.act_help.setEnabled(False)
        m.addSeparator()
        m.addAction("Sair", self.quit_app)
        m.aboutToShow.connect(self._sync_menu)

    def _sync_menu(self):
        s = self.store.settings
        for act, val in ((self.act_pin, s["pinned"]), (self.act_autohide, s["autohide"]),
                         (self.act_remind, s["reminders"]),
                         (self.act_hide_done, s["hide_done"]),
                         (self.act_smart, s["sort"] == "smart")):
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
        self.tray.messageClicked.connect(self._on_reminder_clicked)
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
        sc("Ctrl+Tab", lambda: self.set_view("board" if self.store.settings["view"] == "list" else "list"))
        sc("Ctrl+N", self._focus_input)
        sc("Ctrl+L", self._focus_input)
        sc("Ctrl+Z", self.undo)
        sc("Ctrl+H", lambda: self._set_hide_done(not self.store.settings["hide_done"]))
        sc("Ctrl+F", self.open_search)
        sc("Ctrl+R", self.open_report)
        sc("Ctrl+Return", self._ctrl_enter)
        sc("Ctrl+Enter", self._ctrl_enter)
        sc("F1", self.show_help)
        sc("Ctrl+Q", self.quit_app)
        sc("Alt+0", lambda: self.set_filter("all"))
        for n in range(1, 10):
            sc(f"Alt+{n}", lambda n=n: self._filter_nth(n))

    def set_hotkey_status(self, ok: bool):
        self.hotkey_ok = ok
        hk = self.store.settings["hotkey"]
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME} — {hk}" if ok else APP_NAME)

    # dados → tela
    def refresh(self):
        s = self.store
        vis = s.visible()
        query = self._query()
        shown = s.search(vis, query) if query else vis
        if not self.page_open():  # só reconstrói a página que está na tela
            groups = {g.id: g for g in s.groups}
            show_group = s.settings["filter"] == "all"
            if self.stack.currentIndex() == 0:
                self.list_view.empty_text = ("Nada encontrado." if query
                                             else "Tudo limpo por aqui.\nDigite acima e tecle Enter.")
                if s.settings["sort"] == "smart":
                    self.list_view.set_tasks([], groups, show_group,
                                             sections=build_sections(shown, s.settings["hide_done"]),
                                             collapsed=[] if query else s.settings["collapsed"])
                else:
                    pending = quick_first([t for t in shown if t.status != "done"])
                    done = [] if s.settings["hide_done"] else [t for t in shown if t.status == "done"]
                    self.list_view.set_tasks(pending + done, groups, show_group)
            else:
                for st, col in self.columns.items():
                    col.set_tasks(quick_first([t for t in shown if t.status == st]), groups, show_group)

        counts = {"all": sum(t.status != "done" for t in s.tasks)}
        for t in s.tasks:
            if t.group and t.status != "done":
                counts[t.group] = counts.get(t.group, 0) + 1
        self.groupbar.set_groups(s.groups, s.settings["filter"], counts)
        self.groupbar.setVisible(bool(s.groups) and not self.page_open())

        if query:
            n = len(shown)
            self.counter.setText(f"{n} resultado{'s' if n != 1 else ''}")
        else:
            self._update_counter(vis)
        self.clear_btn.setVisible(any(t.status == "done" for t in vis) and not self.page_open()
                                  and self.undo_btn.isHidden())

        if self.stack.currentWidget() is self.details:
            if s.get(self.details.tid) is None:
                self.close_page()
            else:
                self.details.sync_groups()
        elif self.stack.currentWidget() is self.report:
            self.report.reload()

    def _update_counter(self, vis: list[Task]):
        open_ = [t for t in vis if t.status != "done"]
        pending = [t for t in open_ if not t.delegated]  # o que está no seu prato
        delegated = len(open_) - len(pending)
        n = len(pending)
        late = sum(is_overdue(t) for t in pending)
        quick = sum(t.quick for t in pending)
        txt = "tudo em dia" if n == 0 else f"{n} pendente{'s' if n != 1 else ''}"
        if quick:
            txt += f"  ·  <span style='color:{C['accent']}'>{quick} pra já</span>"
        if late:
            txt += f"  ·  <span style='color:{C['danger']}'>{late} atrasada{'s' if late != 1 else ''}</span>"
        if delegated:
            txt += f"  ·  <span style='color:{C['delegated']}'>{delegated} delegada{'s' if delegated != 1 else ''}</span>"
        self.counter.setText(txt)

    def _tick(self):
        self._check_reminders()
        if self.isVisible():  # só repinta: não atrapalha uma edição em andamento
            if not self._query():
                self._update_counter(self.store.visible())
            for lst in (self.list_view, *(c.list for c in self.columns.values())):
                lst.viewport().update()

    # ações
    def _focus_input(self, select: bool = True):
        if self.page_open():
            self.close_page()
        self.input.setFocus()
        if select:
            self.input.selectAll()
        else:
            self.input.end(False)

    def _type_into_input(self, text: str):
        """Digitar com a lista em foco: o texto vai pro campo (ou pra busca, se estiver aberta)."""
        target = self.search if self._searching else self.input
        if not target.isVisible():
            return
        target.setFocus()
        target.end(False)
        target.insert(text)

    def _leave_list(self):
        if self._searching and self.search.isVisible():
            self.search.setFocus()
            self.search.end(False)
        elif self.input.isVisible():
            self._focus_input(select=False)

    # busca
    def _query(self) -> str:
        return self.search.text().strip() if self._searching else ""

    def open_search(self):
        if not self.isVisible():
            self.show_panel()
        if self.page_open():
            self.close_page()
        self._searching = True
        self.search.show()
        self.search.setFocus()
        self.search.selectAll()
        self.refresh()

    def close_search(self):
        self._searching = False
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.search.hide()
        self.refresh()
        self._focus_input()

    # comentário ao concluir
    def open_note(self, tid: str, back: TaskList | None = None):
        t = self.store.get(tid)
        if not t:
            return
        if self.page_open():
            self.close_page()
        self._note_tid, self._note_back = tid, back
        fm = self.note_title.fontMetrics()
        self.note_title.setText(fm.elidedText(f"✓  {t.text}", Qt.TextElideMode.ElideRight,
                                              max(80, self.width() - 60)))
        self.note_title.setToolTip(t.text)
        self.note_edit.clear()
        self.input.hide()
        self.note_bar.show()
        self.note_edit.setFocus()

    def _save_note(self):
        if self._note_tid:
            self.store.add_note(self._note_tid, self.note_edit.text())
        self.close_note()

    def close_note(self):
        if not self.note_bar.isVisible():
            return
        back = self._note_back
        self._note_tid = self._note_back = None
        self.note_bar.hide()
        if not self.page_open():
            self.input.show()
            if back is not None and back.isVisible() and back.has_tasks():
                back.setFocus()
            else:
                self.input.setFocus()

    # prazos
    def postpone(self, tid: str, days: int):
        """Ctrl+→ / Ctrl+←: prazo +1 / -1 dia, e a seleção acompanha a tarefa."""
        self.store.postpone(tid, days)
        self._follow(tid)

    def _set_due_date(self, tid: str, d: dt.date):
        t = self.store.get(tid)
        if t:
            self.store.update_task(tid, due=make_due(d, split_due(t.due)[1]))

    def _follow(self, tid: str):
        """Reconstrói já e mantém o foco/seleção na tarefa (que pode ter mudado de seção/coluna)."""
        self._refresh_timer.stop()
        self.refresh()
        t = self.store.get(tid)
        if not t or self.page_open():
            return
        lst = self.columns[t.status].list if self.store.settings["view"] == "board" else self.list_view
        if lst.select_id(tid):
            lst.setFocus()

    def _check_reminders(self):
        if not self.store.settings["reminders"] or not self.tray:
            return
        hits = self.store.due_reminders()
        if not hits:
            return
        if len(hits) == 1:
            t = hits[0]
            self._reminder_tid = t.id
            title, body = t.text, f"Prazo: {due_display(t.due, False)[0]}"
        else:
            self._reminder_tid = None
            title = f"{len(hits)} prazos chegaram"
            body = "\n".join(f"• {t.text}" for t in hits[:5]) + ("\n…" if len(hits) > 5 else "")
        self.tray.showMessage(title, body, self.icon, 15_000)

    def _on_reminder_clicked(self):
        tid, self._reminder_tid = self._reminder_tid, None
        self.show_panel()
        if tid and self.store.get(tid):
            self.open_details(tid)

    def _lists(self) -> list[TaskList]:
        if self.store.settings["view"] == "list":
            return [self.list_view]
        return [c.list for c in self.columns.values()]

    def _active_list(self) -> TaskList:
        lists = self._lists()
        return (next((lst for lst in lists if lst.current_id()), None)
                or next((lst for lst in lists if lst.has_tasks()), lists[0]))

    def _focus_list(self):
        lst = self._active_list()
        if lst.has_tasks():
            lst.setFocus()

    def _focus_neighbor(self, lst: TaskList, d: int):
        cols = [c.list for c in self.columns.values()]
        if lst not in cols:
            return
        i = cols.index(lst) + d
        while 0 <= i < len(cols):  # pula colunas vazias
            if cols[i].has_tasks():
                row = max(0, lst.currentRow())
                cols[i].setFocus()
                cols[i].select_near(row)
                return
            i += d

    def _ctrl_enter(self):
        if self.help.isVisible():
            self.help.close_overlay()
        if self.page_open():
            self.close_page()
        elif self.input.hasFocus():
            self._add_from_input(details=True)
        else:
            tid = next((lst.current_id() for lst in self._lists() if lst.hasFocus()), None)
            if tid:
                self.open_details(tid)

    def _filter_nth(self, n: int):
        if 0 < n <= len(self.store.groups):
            gid = self.store.groups[n - 1].id
            self.set_filter("all" if self.store.settings["filter"] == gid else gid)

    def show_help(self):
        if not self.isVisible():
            self.show_panel()
        if self.help.isVisible():
            self.help.close_overlay()
        else:
            self.help.open()

    def toggle_done(self, tid: str):
        t = self.store.get(tid)
        if not t:
            return
        self.store.toggle_done(tid)
        if t.status == "done":
            self._offer_undo("Concluída")

    def _step_status(self, tid: str, d: int):
        """Alt+setas: A fazer <-> Fazendo <-> Feito, e a seleção vai junto."""
        t = self.store.get(tid)
        if not t:
            return
        i = STATUSES.index(t.status) + d
        if not 0 <= i < len(STATUSES):
            return
        new = STATUSES[i]
        self.store.set_status(tid, new)
        if new == "done":
            self._offer_undo("Concluída")
        self._follow(tid)

    def _add_from_input(self, details: bool = False):
        mods = QApplication.keyboardModifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        details = details or bool(mods & Qt.KeyboardModifier.ControlModifier)
        title, due, gname, quick, delegate = parse_quick(self.input.text())
        if not title:
            self.input.setFocus()
            return
        gid = None
        if gname:
            g = self.store.group_by_name(gname) or self.store.add_group(gname)
            gid = g.id if g else None
        elif self.store.settings["filter"] != "all":
            gid = self.store.settings["filter"]
        t = self.store.add(title, "doing" if shift else "todo", group=gid, due=due, quick=quick,
                           delegate=delegate)
        if t:
            self.input.clear()
            if details:
                self.open_details(t.id, focus_notes=True)

    def delete_task(self, tid: str):
        if self.store.delete(tid):
            self._offer_undo("Excluída")

    def clear_done(self):
        f = self.store.settings["filter"]
        n = self.store.clear_done(None if f == "all" else f)
        if n:
            self._offer_undo(f"{n} feita{'s' if n != 1 else ''} arquivada{'s' if n != 1 else ''}")

    def _offer_undo(self, what: str = ""):
        self.undo_btn.setText(f"{what}  ·  Desfazer" if what else "Desfazer")
        self.undo_btn.show()
        self.clear_btn.hide()  # rodapé estreito: o desfazer tem prioridade
        self._undo_timer.start()

    def _hide_undo(self):
        self.undo_btn.hide()
        self.refresh()  # devolve o "Limpar feitas"

    def undo(self):
        if self.store.undo():
            self._undo_timer.stop()
            self.undo_btn.hide()

    def _task_menu(self, lst: TaskList, tid: str, gpos: QPoint):
        t = self.store.get(tid)
        if not t:
            return
        m = QMenu(self)
        m.addAction("Detalhes…\tEnter", lambda: self.open_details(tid))
        m.addAction("Concluir com comentário…\tShift+Espaço", lambda: lst.request_note(tid))
        a = m.addAction("Pra já\t!", lambda: self.store.toggle_quick(tid))
        a.setCheckable(True)
        a.setChecked(t.quick)
        a = m.addAction("Delegada\t>", lambda: self.store.toggle_delegated(tid))
        a.setCheckable(True)
        a.setChecked(t.delegated)
        m.addAction("Delegar para…", lambda: self.ask_delegate(tid))
        m.addAction("Renomear\tF2", lambda: lst.editItem(lst.currentItem()))
        mv = m.addMenu("Mover para")
        for st in STATUSES:
            a = mv.addAction(STATUS_LABEL[st], lambda *_, st=st: self.store.set_status(tid, st))
            a.setEnabled(st != t.status)

        dm = m.addMenu("Prazo")
        today = dt.date.today()
        for label, days in (("Hoje", 0), ("Amanhã", 1), ("Próxima semana", 7)):
            dm.addAction(label, lambda *_, d=days: self._set_due_date(tid, today + dt.timedelta(days=d)))
        dm.addSeparator()
        dm.addAction("Adiar 1 dia\tCtrl+→", lambda: self.postpone(tid, 1))
        dm.addAction("Adiar 1 semana", lambda: self.postpone(tid, 7))
        dm.addAction("Adiar pra segunda", lambda: self._set_due_date(tid, next_weekday(0, today)))
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
    def page_open(self) -> bool:
        """Uma página lateral (detalhes ou relatório) está no lugar da lista/quadro."""
        return self.stack.currentWidget() in (self.details, self.report)

    def _show_page(self, page: QWidget):
        if not self.isVisible():
            self.show_panel()
        self.close_note()
        if self.help.isVisible():
            self.help.close_overlay()
        self.stack.setCurrentWidget(page)
        self.input.hide()
        self.search.hide()
        self.groupbar.hide()
        self.clear_btn.hide()

    def open_report(self):
        if self.stack.currentWidget() is self.report:
            self.close_page()
            return
        self._show_page(self.report)
        self.report.open()
        self.report.setFocus()

    def open_details(self, tid: str, focus_notes: bool = False):
        if not self.details.load(tid):
            return
        self._show_page(self.details)
        if focus_notes:
            self.details.notes.setFocus()
        else:
            self.details.title.setFocus()
            self.details.title.end(False)

    def close_page(self):
        if not self.page_open():
            return
        if self.stack.currentWidget() is self.details:
            self.details.title.clearFocus()
            self.details.tid = None
        self.stack.setCurrentIndex(0 if self.store.settings["view"] == "list" else 1)
        self.input.show()
        self.search.setVisible(self._searching)
        self.refresh()
        self.input.setFocus()

    # grupos
    def ask_delegate(self, tid: str) -> None:
        """Pergunta pra quem (com as pessoas já usadas na lista); vazio = delegada sem nome."""
        t = self.store.get(tid)
        if not t:
            return
        names = self.store.delegate_names()
        current = t.delegated_to if t.delegated_to in names else ""
        items = [""] + names
        name, ok = QInputDialog.getItem(self, "Delegar", "Pra quem? (opcional)", items,
                                        items.index(current), True)
        if ok:
            self.store.set_delegated(tid, True, name)

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
            self._offer_undo("Grupo excluído")

    # preferências
    def _set_hide_done(self, on: bool):
        self.store.set_setting("hide_done", bool(on))
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
        if self.page_open():
            self.close_page()
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
        a.setDuration(160)
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
            if not self.page_open():
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
        pos.setDuration(170)
        pos.setStartValue(start.topLeft())
        pos.setEndValue(target.topLeft())
        pos.setEasingCurve(QEasingCurve.Type.OutCubic)
        op = QPropertyAnimation(self, b"windowOpacity", self)
        op.setDuration(120)
        op.setStartValue(0.0)
        op.setEndValue(1.0)
        grp.addAnimation(pos)
        grp.addAnimation(op)
        grp.finished.connect(self._snap_to_edge)
        grp.start()
        self._anim = grp
        if not self.page_open():
            self._focus_input()

    def hide_panel(self):
        if not self.isVisible() or self._hiding:
            return
        self._stop_anim()
        self._hiding = True
        grp = QParallelAnimationGroup(self)
        pos = QPropertyAnimation(self, b"pos", self)
        pos.setDuration(120)
        pos.setStartValue(self.pos())
        pos.setEndValue(self.pos() + QPoint(self._slide_dx(), 0))
        pos.setEasingCurve(QEasingCurve.Type.InCubic)
        op = QPropertyAnimation(self, b"windowOpacity", self)
        op.setDuration(110)
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
                if not self.page_open():
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

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.KeyPress and obj in (self.input, getattr(self, "search", None)):
            plain = not e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if e.key() == Qt.Key.Key_Down and plain:
                self._focus_list()
                return True
            if obj is self.search and plain and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._focus_list()
                return True
            if obj is self.search and e.key() == Qt.Key.Key_Escape:
                self.close_search()
                return True
        return super().eventFilter(obj, e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.help.isVisible():
            self.help.setGeometry(self.help.parentWidget().rect())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.note_bar.isVisible():
                self.close_note()
            elif self.page_open():
                self.close_page()
            elif self.input.hasFocus() and self.input.text():
                self.input.clear()
            elif self._searching:
                self.close_search()
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
