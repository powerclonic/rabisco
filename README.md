<p align="center"><img src="docs/icon.png" width="96" alt="Rabisco"></p>

# Rabisco

Lista de tarefas + kanban de canto de tela para Windows 11, em Python com **PySide6** (e nada além da biblioteca padrão).

Abre docado na lateral da tela, você escreve, dá Enter e fecha. Quando quiser mais, cada tarefa pode ter descrição, prazo e grupo — mas nada disso é obrigatório.

## Rodando

```bash
pip install -r requirements.txt
```

Depois é só dar duplo clique em `rabisco.pyw` (ou `pythonw rabisco.pyw`; `python -m rabisco` também funciona).

O app fica no tray. Para abrir junto com o Windows: menu **⋯ → Iniciar com o Windows**.

## Uso

| Ação | Como |
| --- | --- |
| Mostrar / esconder de qualquer lugar | `Ctrl+Alt+K` (ou clique no ícone do tray) |
| Adicionar | digitar + `Enter` |
| Adicionar já em "Fazendo" | `Shift+Enter` |
| Adicionar e abrir detalhes | `Ctrl+Enter` ou o ícone de lápis no campo |
| Fechar | `Esc` |
| Lista / Quadro | `Ctrl+1` / `Ctrl+2` |
| Concluir | clique no círculo ou `Espaço` |
| Detalhes (descrição, prazo, grupo) | duplo clique ou `Enter` na tarefa |
| Renomear rápido | `F2` |
| Excluir / desfazer | `Del` / `Ctrl+Z` (ou o botão "Desfazer" no rodapé) |
| Mover entre colunas ou reordenar | arrastar e soltar |

### Digitação rápida

Dá para definir grupo e prazo direto no campo:

```
pagar boleto @10/12
ligar pro banco #casa @amanhã 14h
deploy @hoje 18:30 #trabalho
```

- `#grupo` — coloca no grupo (cria se não existir)
- `@hoje`, `@amanhã`, `@seg`…`@dom`, `@25/12`, `@25/12/27`, `@3d` (daqui a 3 dias), `@15h`
- depois da data pode vir uma hora: `14h`, `14h30`, `14:30`

Prazos aparecem nos cartões como "Hoje", "Amanhã", "Sex 14:00"… em amarelo quando é hoje e em vermelho quando estão atrasados.

### Grupos

Ao criar o primeiro grupo aparece uma barra de filtros (Tudo · Trabalho · Casa · +). Com um grupo selecionado, as tarefas novas entram nele. Botão direito no grupo: renomear, mudar cor ou excluir (as tarefas são mantidas).

## Dados

Tudo fica em `%APPDATA%\Rabisco\dados.json` (salvo de forma atômica). Se o arquivo estiver corrompido ele é guardado como `dados.corrompido-<timestamp>.json` e o app começa limpo. Erros vão para `%APPDATA%\Rabisco\erro.log`, já que um `.pyw` não tem console.

O atalho global pode ser trocado editando `"hotkey"` em `dados.json` (ex.: `"Ctrl+Shift+Space"`, `"Win+Alt+N"`).

## Estrutura

```
rabisco.pyw            entrada (duplo clique)
rabisco/
  app.py               instância única, tema, tray, atalho global, loop do Qt
  config.py            constantes, cores, caminhos, log de erros
  dates.py             prazos: digitação rápida e rótulos (sem Qt)
  store.py             tarefas, grupos, persistência, desfazer
  winapi.py            Win32: hotkey global, sempre no topo, cantos arredondados, autostart
  ui/
    panel.py           janela principal (painel lateral, menus, animações)
    details.py         página de detalhes da tarefa
    tasklist.py        lista de cartões com arrastar e soltar
    delegate.py        desenho dos cartões
    widgets.py         coluna do quadro e barra de grupos
    theme.py           folha de estilo, paleta e ícones
    roles.py           papéis de dados dos itens
  assets/rabisco.ico
tools/make_icon.py     gera o .ico (precisa de Pillow)
tests/                 pytest
```

## Testes

```bash
pip install pytest
pytest
```
