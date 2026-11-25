"""Constantes, cores, caminhos e log de erros. Sem dependência de Qt."""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

IS_WIN = sys.platform == "win32"

APP_NAME = "Rabisco"
APP_ID = "dresch.rabisco.1"
PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent
ICON_PATH = PACKAGE_DIR / "assets" / "rabisco.ico"
ENTRY_SCRIPT = ROOT_DIR / "rabisco.pyw"
DATA_DIR = Path(os.environ.get("APPDATA") or (Path.home() / ".config")) / APP_NAME
DATA_FILE = DATA_DIR / "dados.json"
LOG_FILE = DATA_DIR / "erro.log"
SERVER_NAME = f"{APP_NAME}-{os.environ.get('USERNAME') or os.environ.get('USER') or 'user'}"

# geometria do painel (px lógicos)
LIST_WIDTH = 370
BOARD_WIDTH = 820
MAX_HEIGHT = 740
EDGE = 10          # distância da borda da tela
SLIDE = 28         # deslocamento da animação de entrada

STATUSES = ("todo", "doing", "done")
STATUS_LABEL = {"todo": "A fazer", "doing": "Fazendo", "done": "Feito"}

C = {
    "bg": "#1B1B20",
    "surface": "#232329",
    "card": "#2C2C34",
    "card_hover": "#35353E",
    "border": "#3A3A44",
    "text": "#ECECF1",
    "soft": "#B4B4C0",
    "muted": "#8D8D99",
    "accent": "#F5C84C",
    "danger": "#F06A6A",
    "todo": "#8D8D99",
    "doing": "#F5C84C",
    "done": "#5EC27A",
    "delegated": "#8AA9FF",
}

GROUP_COLORS = [("Azul", "#6CA0FF"), ("Verde", "#5EC27A"), ("Rosa", "#F07AB5"), ("Roxo", "#A78BFA"),
                ("Laranja", "#F5A15C"), ("Ciano", "#4FD1C5"), ("Vermelho", "#F06A6A"), ("Oliva", "#C9C96B")]

DEFAULT_SETTINGS = {
    "view": "list",        # list | board
    "pinned": True,        # sempre no topo
    "hide_done": False,    # esconder feitas na lista
    "autohide": False,     # esconder ao perder o foco
    "side": "right",       # right | left
    "filter": "all",       # all | id do grupo
    "sort": "smart",       # smart (seções) | manual (lista plana)
    "collapsed": ["done"], # seções recolhidas na lista
    "hotkey": "Ctrl+Alt+K",
}

# Glifos da fonte Segoe Fluent Icons (Win11) / Segoe MDL2 Assets (Win10)
ICON_FONTS = ["Segoe Fluent Icons", "Segoe MDL2 Assets"]
G_PIN, G_PINNED, G_MORE, G_CLOSE = "\uE718", "\uE840", "\uE712", "\uE8BB"
G_BACK, G_DELETE, G_CAL, G_EXPAND = "\uE72B", "\uE74D", "\uE787", "\uE70F"
G_BOLT, G_PLAY, G_CLOCK, G_LIST, G_CHECK = "\uE945", "\uE768", "\uE823", "\uE8FD", "\uE73E"
G_CHEVRON_DOWN, G_CHEVRON_RIGHT = "\uE70D", "\uE76C"
G_DELEGATE = "\uE72D"  # Share

INPUT_HELP = ("Enter: adiciona  ·  Shift+Enter: em Fazendo  ·  Ctrl+Enter: abre detalhes\n"
              "!  no começo: pra já (rápida, fazer o quanto antes)\n"
              ">Fulano  delegada pra Fulano   ·   >  sozinho no começo/fim: delegada sem dizer pra quem\n"
              "#grupo  coloca num grupo (cria se não existir)\n"
              "@hoje  @amanhã  @sex  @25/12  @3d  define prazo — pode seguir hora: 14h, 14:30")


def log_error(text: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{text}\n")
    except OSError:
        pass


def _excepthook(etype, value, tb):
    log_error("".join(traceback.format_exception(etype, value, tb)))


def install_excepthook() -> None:
    """Num .pyw não há console: exceções vão para o erro.log."""
    sys.excepthook = _excepthook
