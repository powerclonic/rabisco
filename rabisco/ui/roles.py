"""Papéis de dados dos itens das listas e tipo MIME do arrastar e soltar."""
from PySide6.QtCore import Qt

ROLE_ID = int(Qt.ItemDataRole.UserRole)
ROLE_STATUS = ROLE_ID + 1
ROLE_NOTES = ROLE_ID + 2
ROLE_DUE = ROLE_ID + 3
ROLE_GNAME = ROLE_ID + 4
ROLE_GCOLOR = ROLE_ID + 5
ROLE_QUICK_SINCE = ROLE_ID + 6   # float (0 = não é "pra já")
ROLE_KIND = ROLE_ID + 7          # "task" | "header"
ROLE_SECTION = ROLE_ID + 8       # chave da seção (lista agrupada) ou ""
ROLE_COUNT = ROLE_ID + 9         # cabeçalho: nº de tarefas
ROLE_COLLAPSED = ROLE_ID + 10    # cabeçalho: recolhido?
ROLE_DELEG_SINCE = ROLE_ID + 11  # float (0 = não delegada)
ROLE_DELEG_TO = ROLE_ID + 12     # pra quem foi delegada ("" = não informado)
MIME = "application/x-rabisco-task"
