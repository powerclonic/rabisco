"""Modelo de dados: tarefas, grupos, configurações, persistência em JSON e desfazer."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .config import DEFAULT_SETTINGS, GROUP_COLORS, STATUSES, log_error
from .dates import due_datetime, shift_due, split_due

REMIND_WINDOW = dt.timedelta(hours=24)  # prazo que passou há mais que isso não gera aviso


def fold(text: str) -> str:
    """Minúsculas e sem acento: 'Café' e 'cafe' batem na busca."""
    nfd = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in nfd if not unicodedata.combining(c))


@dataclass
class Task:
    text: str                       # título
    status: str = "todo"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.time)
    done_at: float | None = None
    notes: str = ""                 # descrição (opcional)
    due: str | None = None          # prazo (opcional)
    group: str | None = None        # id do grupo (opcional)
    quick: bool = False             # "pra já": rápida, fazer o quanto antes
    quick_since: float | None = None  # desde quando está marcada como pra já
    delegated: bool = False         # delegada: está com outra pessoa
    delegated_to: str = ""          # pra quem (opcional)
    delegated_since: float | None = None
    reminded: str | None = None     # prazo que já foi avisado (muda o prazo -> avisa de novo)


@dataclass
class Group:
    name: str
    color: str = GROUP_COLORS[0][1]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


class Store(QObject):
    """Lista ordenada de tarefas (a ordem de cada coluna é a ordem global filtrada)."""

    changed = Signal()

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.tasks: list[Task] = []
        self.groups: list[Group] = []
        self.archive: list[Task] = []   # feitas que saíram da lista ("Limpar feitas"): só pro relatório
        self.settings: dict = copy.deepcopy(DEFAULT_SETTINGS)
        self._undo: list[tuple[list[Task], list[Group], list[Task]]] = []
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_now)
        self.load()

    # persistência
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            # não perde nada: guarda o arquivo ruim e começa limpo
            log_error(f"dados corrompidos: {e}")
            try:
                self.path.replace(self.path.with_suffix(f".corrompido-{int(time.time())}.json"))
            except OSError:
                pass
            return
        gnames = {f.name for f in fields(Group)}
        for d in raw.get("groups", []):
            if isinstance(d, dict) and d.get("name"):
                self.groups.append(Group(**{k: v for k, v in d.items() if k in gnames}))
        gids = {g.id for g in self.groups}
        tnames = {f.name for f in fields(Task)}
        for d in raw.get("archive", []):
            if isinstance(d, dict) and d.get("text") and d.get("done_at"):
                t = Task(**{k: v for k, v in d.items() if k in tnames})
                t.status = "done"
                if t.group not in gids:
                    t.group = None
                t.notes = t.notes or ""
                self.archive.append(t)
        for d in raw.get("tasks", []):
            if isinstance(d, dict) and d.get("text"):
                t = Task(**{k: v for k, v in d.items() if k in tnames})
                if t.status not in STATUSES:
                    t.status = "todo"
                if t.group not in gids:
                    t.group = None
                if split_due(t.due)[0] is None:
                    t.due = None
                t.notes = t.notes or ""
                t.quick = bool(t.quick)
                t.quick_since = (t.quick_since or t.created) if t.quick else None
                t.delegated = bool(t.delegated)
                t.delegated_to = " ".join(str(t.delegated_to or "").split()) if t.delegated else ""
                t.delegated_since = (t.delegated_since or t.created) if t.delegated else None
                if t.delegated:
                    t.quick, t.quick_since = False, None
                self.tasks.append(t)
        s = raw.get("settings", {})
        if isinstance(s, dict):
            self.settings.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
        if self.settings["filter"] != "all" and self.settings["filter"] not in gids:
            self.settings["filter"] = "all"
        if self.settings["sort"] not in ("smart", "manual"):
            self.settings["sort"] = "smart"
        if not isinstance(self.settings["collapsed"], list):
            self.settings["collapsed"] = list(DEFAULT_SETTINGS["collapsed"])
        if self.settings["report_period"] not in ("today", "yesterday", "week", "month", "custom"):
            self.settings["report_period"] = DEFAULT_SETTINGS["report_period"]

    def save_now(self) -> None:
        self._save_timer.stop()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            data = {"version": 2, "tasks": [asdict(t) for t in self.tasks],
                    "groups": [asdict(g) for g in self.groups],
                    "archive": [asdict(t) for t in self.archive], "settings": self.settings}
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log_error(f"falha ao salvar: {e}")

    def schedule_save(self) -> None:
        self._save_timer.start()

    def _touch(self) -> None:
        self.changed.emit()
        self.schedule_save()

    def toggle_collapsed(self, section: str) -> None:
        col = self.settings["collapsed"]
        if section in col:
            col.remove(section)
        else:
            col.append(section)
        self.schedule_save()
        self.changed.emit()

    def set_setting(self, key: str, value) -> None:
        self.settings[key] = value
        self.schedule_save()

    # consultas
    def get(self, tid: str | None) -> Task | None:
        return next((t for t in self.tasks if t.id == tid), None)

    def get_group(self, gid: str | None) -> Group | None:
        return next((g for g in self.groups if g.id == gid), None)

    def group_by_name(self, name: str) -> Group | None:
        key = " ".join(name.split()).casefold()
        return next((g for g in self.groups if g.name.casefold() == key), None)

    def visible(self) -> list[Task]:
        f = self.settings["filter"]
        return self.tasks if f == "all" else [t for t in self.tasks if t.group == f]

    def search(self, tasks: list[Task], query: str) -> list[Task]:
        """Todas as palavras precisam aparecer no título, descrição, pessoa ou grupo."""
        words = fold(query).split()
        if not words:
            return tasks
        gnames = {g.id: g.name for g in self.groups}
        out = []
        for t in tasks:
            hay = fold(" ".join((t.text, t.notes, t.delegated_to, gnames.get(t.group, ""))))
            if all(w in hay for w in words):
                out.append(t)
        return out

    def completed(self, start: dt.date, end: dt.date, group: str | None = None) -> list[Task]:
        """Concluídas entre start e end (inclusive, pelo dia local), da mais recente pra mais antiga.

        Inclui as arquivadas por "Limpar feitas".
        """
        out = []
        for t in (*self.tasks, *self.archive):
            if t.status != "done" or not t.done_at or (group and t.group != group):
                continue
            if start <= dt.date.fromtimestamp(t.done_at) <= end:
                out.append(t)
        return sorted(out, key=lambda t: t.done_at, reverse=True)

    def due_reminders(self, now: dt.datetime | None = None) -> list[Task]:
        """Tarefas abertas cujo prazo com hora chegou e ainda não foram avisadas (marca como avisadas)."""
        now = now or dt.datetime.now()
        hits = []
        for t in self.tasks:
            when = due_datetime(t.due)
            if (t.status != "done" and when is not None and t.reminded != t.due
                    and when <= now and now - when <= REMIND_WINDOW):
                t.reminded = t.due
                hits.append(t)
        if hits:
            self.schedule_save()
        return hits

    # tarefas
    @staticmethod
    def _apply_status(t: Task, status: str) -> None:
        if status == t.status:
            return
        t.status = status
        t.done_at = time.time() if status == "done" else None

    def _insert_first_of_group(self, t: Task) -> None:
        idx = next((i for i, x in enumerate(self.tasks) if x.status == t.status), len(self.tasks))
        self.tasks.insert(idx, t)

    def add(self, text: str, status: str = "todo", group: str | None = None,
            due: str | None = None, quick: bool = False, delegate: str | None = None) -> Task | None:
        """`delegate`: None = não delegada; "" = delegada sem nome; "Fulano" = delegada pra Fulano."""
        text = " ".join(text.split())
        if not text:
            return None
        t = Task(text=text, status=status, group=group if self.get_group(group) else None, due=due)
        if delegate is not None:
            self._delegate_fields(t, True, delegate)
        elif quick:
            self._quick_fields(t, True)
        self._insert_first_of_group(t)
        self._touch()
        return t

    def update_task(self, tid: str, **kw) -> None:
        t = self.get(tid)
        if not t:
            return
        changed = False
        for k, v in kw.items():
            if k == "text":
                v = " ".join((v or "").split())
                if not v:
                    continue
            elif k == "notes":
                v = (v or "").rstrip()
            elif k == "group" and not self.get_group(v):
                v = None
            elif k == "delegated_to":
                v = " ".join((v or "").split())
            if getattr(t, k) != v:
                setattr(t, k, v)
                changed = True
        if changed:
            self._touch()
        else:
            self.changed.emit()  # força redesenho (ex.: desfaz título vazio)

    def set_status(self, tid: str, status: str) -> None:
        """Muda de coluna e coloca no topo dela."""
        t = self.get(tid)
        if not t or t.status == status:
            return
        if status == "done":
            self._snapshot()  # concluir sem querer é comum: dá pra desfazer
        self.tasks.remove(t)
        self._apply_status(t, status)
        self._insert_first_of_group(t)
        self._touch()

    # pra já e delegada são excludentes: marcar uma desmarca a outra
    @staticmethod
    def _quick_fields(t: Task, on: bool) -> None:
        if on and not t.quick:
            t.quick_since = time.time()
        t.quick = on
        if not on:
            t.quick_since = None
        if on:
            Store._delegate_fields(t, False)

    @staticmethod
    def _delegate_fields(t: Task, on: bool, to: str | None = None) -> None:
        if on and not t.delegated:
            t.delegated_since = time.time()
        t.delegated = on
        if to is not None:
            t.delegated_to = " ".join(to.split())
        if not on:
            t.delegated_to, t.delegated_since = "", None
        else:
            t.quick, t.quick_since = False, None

    def set_quick(self, tid: str, on: bool) -> None:
        """Marca/desmarca como "pra já". Ao marcar, sobe para o topo da sua coluna."""
        t = self.get(tid)
        if not t or t.quick == on:
            return
        self._quick_fields(t, on)
        if on:
            self.tasks.remove(t)
            if t.status == "done":
                self._apply_status(t, "todo")
            self._insert_first_of_group(t)
        self._touch()

    def toggle_quick(self, tid: str) -> None:
        t = self.get(tid)
        if t:
            self.set_quick(tid, not t.quick)

    def set_delegated(self, tid: str, on: bool, to: str | None = None) -> None:
        """Marca/desmarca como delegada. `to` None mantém o nome que já existia."""
        t = self.get(tid)
        if not t:
            return
        before = (t.delegated, t.delegated_to)
        self._delegate_fields(t, on, to)
        if on and t.status == "done":
            self._apply_status(t, "todo")
        if (t.delegated, t.delegated_to) != before:
            self._touch()

    def toggle_delegated(self, tid: str) -> None:
        t = self.get(tid)
        if t:
            self.set_delegated(tid, not t.delegated)

    def delegate_names(self) -> list[str]:
        """Pessoas para quem você já delegou (para autocompletar)."""
        names = {t.delegated_to for t in self.tasks if t.delegated_to}
        return sorted(names, key=str.casefold)

    def drop_into_section(self, tid: str, section: str, before_id: str | None) -> None:
        """Arrastar para uma seção da lista agrupada ajusta o que define a seção e reposiciona."""
        t = self.get(tid)
        if not t:
            return
        if section == "quick":
            self._quick_fields(t, True)
            if t.status == "done":
                self._apply_status(t, "todo")
        elif section == "delegated":
            self._delegate_fields(t, True)
            if t.status == "done":
                self._apply_status(t, "todo")
        elif section == "doing":
            self._quick_fields(t, False)
            self._delegate_fields(t, False)
            self._apply_status(t, "doing")
        elif section == "done":
            self._apply_status(t, "done")
        else:  # due / soon / nodue: é o prazo que decide onde ela aparece
            self._quick_fields(t, False)
            self._delegate_fields(t, False)
            if t.status != "todo":
                self._apply_status(t, "todo")
        if before_id == tid:  # soltou no mesmo lugar: só os atributos mudaram
            self._touch()
        else:
            self.move(tid, None, before_id)

    def postpone(self, tid: str, days: int, today: dt.date | None = None) -> None:
        """Empurra o prazo `days` dias (a partir de hoje se já venceu; sem prazo vira hoje + days)."""
        t = self.get(tid)
        if t:
            self.update_task(tid, due=shift_due(t.due, days, today))

    def add_note(self, tid: str, note: str, when: float | None = None) -> None:
        """Comentário de conclusão: entra no fim da descrição, com a data."""
        t = self.get(tid)
        note = " ".join(note.split())
        if not t or not note:
            return
        stamp = time.strftime("%d/%m", time.localtime(when or time.time()))
        line = f"✓ {stamp}: {note}"
        self.update_task(tid, notes=f"{t.notes.rstrip()}\n\n{line}" if t.notes.strip() else line)

    def toggle_done(self, tid: str) -> None:
        t = self.get(tid)
        if t:
            self.set_status(tid, "todo" if t.status == "done" else "done")

    def move(self, tid: str, status: str | None, before_id: str | None) -> None:
        """Arrastar e soltar: muda status (opcional) e posiciona antes de `before_id`."""
        t = self.get(tid)
        if not t or before_id == tid:
            return
        self.tasks.remove(t)
        if status:
            self._apply_status(t, status)
        before = self.get(before_id) if before_id else None
        if before is not None:
            idx = self.tasks.index(before)
        else:
            idx = len(self.tasks)
            if status:
                last = max((i for i, x in enumerate(self.tasks) if x.status == status), default=None)
                if last is not None:
                    idx = last + 1
        self.tasks.insert(idx, t)
        self._touch()

    def _snapshot(self) -> None:
        self._undo.append((copy.deepcopy(self.tasks), copy.deepcopy(self.groups), copy.deepcopy(self.archive)))
        del self._undo[:-20]

    def delete(self, tid: str) -> bool:
        t = self.get(tid)
        if not t:
            return False
        self._snapshot()
        self.tasks.remove(t)
        self._touch()
        return True

    def clear_done(self, group: str | None = None) -> int:
        hit = [t for t in self.tasks if t.status == "done" and (group is None or t.group == group)]
        if hit:
            self._snapshot()
            ids = {t.id for t in hit}
            self.tasks = [t for t in self.tasks if t.id not in ids]
            self.archive.extend(hit)  # some da lista, mas continua no relatório
            self._touch()
        return len(hit)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.tasks, self.groups, self.archive = self._undo.pop()
        if self.settings["filter"] != "all" and not self.get_group(self.settings["filter"]):
            self.settings["filter"] = "all"
        self._touch()
        return True

    # grupos
    def add_group(self, name: str) -> Group | None:
        name = " ".join(name.split())
        if not name:
            return None
        existing = self.group_by_name(name)
        if existing:
            return existing
        used = {g.color for g in self.groups}
        color = next((c for _, c in GROUP_COLORS if c not in used),
                     GROUP_COLORS[len(self.groups) % len(GROUP_COLORS)][1])
        g = Group(name=name, color=color)
        self.groups.append(g)
        self._touch()
        return g

    def rename_group(self, gid: str, name: str) -> None:
        g = self.get_group(gid)
        name = " ".join(name.split())
        if g and name and name != g.name:
            g.name = name
            self._touch()

    def set_group_color(self, gid: str, color: str) -> None:
        g = self.get_group(gid)
        if g and g.color != color:
            g.color = color
            self._touch()

    def delete_group(self, gid: str) -> bool:
        """Remove o grupo; as tarefas dele ficam sem grupo."""
        g = self.get_group(gid)
        if not g:
            return False
        self._snapshot()
        self.groups.remove(g)
        for t in (*self.tasks, *self.archive):
            if t.group == gid:
                t.group = None
        if self.settings["filter"] == gid:
            self.settings["filter"] = "all"
        self._touch()
        return True
