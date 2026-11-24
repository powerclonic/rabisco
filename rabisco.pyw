"""Rabisco — duplo clique neste arquivo (ou `pythonw rabisco.pyw`) para abrir."""
import sys
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # sem console no .pyw: avisa com uma caixa nativa
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, "PySide6 não encontrado.\n\nInstale com:\n\n    pip install PySide6",
            "Rabisco", 0x10)
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rabisco.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
