# ContextTree MCP 🌳

**Глубокий семантический и гибридный поиск по коду для ИИ-ассистентов на базе AST-парсинга и локальных эмбеддингов. 100% офлайн.**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-Model%20Context%20Protocol-purple.svg)](https://modelcontextprotocol.io)

ContextTree MCP — это локальный сервер [Model Context Protocol](https://modelcontextprotocol.io), предоставляющий ИИ-ассистентам **структурное понимание** кодовой базы.

- **tree-sitter** разбирает код на логические блоки — функции, методы, структуры и сигнатуры классов с документацией.
- **Гибридный поиск (BM25 + Векторы + RRF)** — сочетает точный поиск по идентификаторам (`camelCase`, `snake_case`) и семантический поиск по смыслу через `all-MiniLM-L6-v2` в ChromaDB.
- **Watch Mode и инкрементальность** — отслеживание хэшей SHA-256 и мгновенная переиндексация на лету при сохранении файлов.

> 🔒 **100% приватность.** Парсинг, векторизация и база хранятся только на локальной машине. Никаких внешних API-запросов и телеметрии.

---

## Поддерживаемые языки

| Язык | Расширения | Индексируемые AST-узлы |
|---|---|---|
| **Python** | `.py` | функции, декорированные функции, методы, сигнатуры классов, docstring |
| **TypeScript / TSX** | `.ts`, `.tsx`, `.mts`, `.cts` | функции, методы, сигнатуры классов, JSDoc |
| **JavaScript / JSX** | `.js`, `.jsx`, `.mjs`, `.cjs` | функции, методы, сигнатуры классов, JSDoc |
| **Go** | `.go` | функции, методы ресиверов, структуры, интерфейсы, комментарии |
| **Rust** | `.rs` | функции, impl-методы, структуры, трейты, `///` документация |
| **C#** | `.cs` | методы, конструкторы, классы, интерфейсы, `/// <summary>` XML-doc |
| **Java** | `.java` | методы, конструкторы, классы, интерфейсы, рекорды, Javadoc |

---

## Установка и запуск

Требуется Python **3.12+**. Рекомендуется [`uv`](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/chelslava/mcp-context-tree.git
cd mcp-context-tree
uv sync
```

### Запуск

```bash
# Режим MCP-сервера (stdio)
uv run context-tree

# Режим наблюдения (автоматическая переиндексация при изменении файлов)
uv run context-tree --watch /путь/к/проекту
```

### Подключение к клиентам (Claude Desktop, Cursor, Antigravity)

```json
{
  "mcpServers": {
    "context-tree": {
      "command": "uv",
      "args": ["run", "--directory", "D:/Repo/mcp-context-tree", "context-tree"]
    }
  }
}
```

---

## Инструменты MCP

| Инструмент | Параметры | Описание |
|---|---|---|
| `index_workspace` | `(directory_path: str = ".")` | Сканирование и инкрементальная индексация изменённых файлов. |
| `semantic_search` | `(query: str, limit: int = 5, mode: str = "hybrid")` | Гибридный (BM25 + vectors), семантический или ключевой поиск со сниппетами с диска. |
| `find_ast_usages` | `(symbol_name: str, limit: int = 50)` | Поиск реальных вызовов символа через AST (без ложных срабатываний в строках). |

---

## Лицензия

MIT — см. [LICENSE](LICENSE).
