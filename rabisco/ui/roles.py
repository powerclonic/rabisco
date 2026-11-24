"""Papéis de dados dos itens das listas e tipo MIME do arrastar e soltar."""
from PySide6.QtCore import Qt

ROLE_ID = int(Qt.ItemDataRole.UserRole)
ROLE_STATUS = ROLE_ID + 1
ROLE_NOTES = ROLE_ID + 2
ROLE_DUE = ROLE_ID + 3
ROLE_GNAME = ROLE_ID + 4
ROLE_GCOLOR = ROLE_ID + 5
MIME = "application/x-rabisco-task"
