"""Modelo de dados: tarefas, grupos, configurações, persistência em JSON e desfazer."""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .config import DEFAULT_SETTINGS, GROUP_COLORS, STATUSES, log_error
from .dates import split_due

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
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self._undo: list[tuple[list[Task], list[Group]]] = []
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
                self.tasks.append(t)
        s = raw.get("settings", {})
        if isinstance(s, dict):
            self.settings.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
        if self.settings["filter"] != "all" and self.settings["filter"] not in gids:
            self.settings["filter"] = "all"

    def save_now(self) -> None:
        self._save_timer.stop()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            data = {"version": 2, "tasks": [asdict(t) for t in self.tasks],
                    "groups": [asdict(g) for g in self.groups], "settings": self.settings}
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log_error(f"falha ao salvar: {e}")

    def schedule_save(self) -> None:
        self._save_timer.start()

    def _touch(self) -> None:
        self.changed.emit()
        self.schedule_save()

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
            due: str | None = None) -> Task | None:
        text = " ".join(text.split())
        if not text:
            return None
        t = Task(text=text, status=status, group=group if self.get_group(group) else None, due=due)
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
        self.tasks.remove(t)
        self._apply_status(t, status)
        self._insert_first_of_group(t)
        self._touch()

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
        self._undo.append((copy.deepcopy(self.tasks), copy.deepcopy(self.groups)))
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
            self._touch()
        return len(hit)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.tasks, self.groups = self._undo.pop()
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
        for t in self.tasks:
            if t.group == gid:
                t.group = None
        if self.settings["filter"] == gid:
            self.settings["filter"] = "all"
        self._touch()
        return True
