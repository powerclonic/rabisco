"""Permite rodar com `python -m rabisco` (ou `pythonw -m rabisco`)."""
import sys

from .app import main

sys.exit(main())
