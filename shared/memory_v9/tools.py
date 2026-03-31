"""
Tool definitions для agent_loop — scratchpad, memory, recall.
Добавить в TOOLS_SCHEMA.
"""

SCRATCHPAD_TOOL = {
    "type": "function",
    "function": {
        "name": "update_scratchpad",
        "description": "Обновить блокнот агента. Записывай ТЗ, планы, чек-листы, промежуточные результаты. Содержимое ВСЕГДА видно в начале каждой итерации.",
        "parameters": {"type": "object", "properties": {"content": {"type": "string", "description": "Полный текст блокнота (Markdown)"}}, "required": ["content"]}
    }
}

STORE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "store_memory",
        "description": "Сохранить факт в долгосрочную память. Используй для: предпочтений пользователя, конфигов серверов, решений, навыков.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string", "description": "Ключ (user_name, server_config, tech_stack...)"},
            "value": {"type": "string", "description": "Значение"},
            "category": {"type": "string", "description": "Категория: preference, fact, project, decision", "default": "fact"}
        }, "required": ["key", "value"]}
    }
}

RECALL_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": "Вспомнить из долгосрочной памяти. Поиск по ключу или тексту.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Что вспомнить"},
            "category": {"type": "string", "description": "Фильтр по категории (опционально)"}
        }, "required": ["query"]}
    }
}

SNAPSHOT_SERVER_TOOL = {
    "type": "function",
    "function": {
        "name": "snapshot_server",
        "description": "Сделать снимок состояния сервера (uptime, диски, сервисы, docker). Для сравнения 'что изменилось'.",
        "parameters": {"type": "object", "properties": {
            "host": {"type": "string", "description": "IP или hostname сервера"}
        }, "required": ["host"]}
    }
}

DIFF_SERVER_TOOL = {
    "type": "function",
    "function": {
        "name": "diff_server",
        "description": "Сравнить текущее состояние сервера с предыдущим снимком. Показывает что изменилось.",
        "parameters": {"type": "object", "properties": {
            "host": {"type": "string", "description": "IP или hostname сервера"}
        }, "required": ["host"]}
    }
}

ALL_MEMORY_TOOLS = [
    SCRATCHPAD_TOOL,
    STORE_MEMORY_TOOL,
    RECALL_MEMORY_TOOL,
    SNAPSHOT_SERVER_TOOL,
    DIFF_SERVER_TOOL,
]
