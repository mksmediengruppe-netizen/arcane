# ARCANE — Полный список багов (Phase 5 — Финальная версия)

Дата: 30 марта 2026
Основание: Аудит кода по спецификации `ARCANE_SPEC.md` + перекрёстная проверка с документом `ARCANE_practical_audit_2026-03-30.docx` + ручная верификация кода на сервере + внешний аудит + платформенный анализ.

---

## КРИТИЧЕСКИЕ (Блокируют работу или безопасность)

| ID | Проблема | Статус | Что сделано |
|---|---|---|---|
| **BUG-001** | Несовпадение контракта авторизации (Frontend vs Backend) | **P3 ИСПРАВЛЕН** | `resolved_login_id` -> `login_id` в `LoginRequest`. |
| **BUG-004** | Отсутствие авторизации на SSE subscribe endpoint | **P3 ИСПРАВЛЕН** | `_require_user_id()` + `_check_chat_ownership()` в `api/sse.py`. |
| **BUG-005** | Рассинхронизация файловых путей и URL контракта | **P4 ИСПРАВЛЕН** | Унифицированы ВСЕ URL на `/workspace/{chat_id}/`. Удалены `/home/ubuntu/projects` и `/projects/images/`. |
| **BUG-006** | Несовместимость API скачивания файлов | **P3 ИСПРАВЛЕН** | ID-based маршруты: `/api/files/{id}/download`, `/api/files/{id}/preview`. |
| **BUG-007** | Потеря сессий при перезапуске сервиса | **P3 ИСПРАВЛЕН** | Сессии сохраняются в `/root/arcane/data/sessions.json`. |
| **BUG-008** | Конфликт механизмов SSE (POST vs EventSource) | **P3 ИСПРАВЛЕН** | Обработчик `agent_status` в `useChatsAPI.ts`. |
| **BUG-017** | Отсутствие проверки ownership на критических маршрутах | **P4.5 ИСПРАВЛЕН** | `_require_user_id()` + `_check_chat_ownership()` на `update_chat_model`, `submit_feedback`, `get_chat_status`. Исправлен краш `submit_feedback` (неверный import `store_get_chat` -> `get_chat`). |

---

## СЕРЬЁЗНЫЕ (Влияют на архитектуру и UX)

| ID | Проблема | Статус | Что сделано |
|---|---|---|---|
| **BUG-009** | Пустое сообщение-обёртка при старте задачи | **P3 ИСПРАВЛЕН** | `isStreaming: true` к placeholder-сообщению. |
| **BUG-010** | Проблемы с инициализацией Memory v9 | **P3 ИСПРАВЛЕН** | Установлен `qdrant-client`. Адаптер корректно делегирует в v9. |
| **BUG-012** | Неполный маппинг статусов агента | **P3 ИСПРАВЛЕН** | Маппинг `coding/browsing/deploying/researching` в `useChatsAPI.ts`. |
| **BUG-013** | Отсутствие SSE события для обновления заголовка чата | **P3 ИСПРАВЛЕН** | `emit_to_chat(chat_id, "title", ...)` после `_generate_chat_title()`. |
| **BUG-018** | Смешанный пайплайн генерации (Landing default path) | **P4+P5 ИСПРАВЛЕН** | Retry: 2 попытки с задержкой 2с. Legacy path за `FEATURE_FLAG_LEGACY_CODER=false`. |
| **BUG-019** | Нестрогая персистентность чатов (fire-and-forget) | **P3 ИСПРАВЛЕН** | `_safe_db_write` теперь `async def` с `await`. |
| **BUG-020** | Зависимость тестов от живого сервера | **P4 ИСПРАВЛЕН** | TestClient (in-process) по умолчанию, httpx при наличии `ARCANE_TEST_URL`. |

---

## МИНОРНЫЕ (Косметические проблемы и техдолг)

| ID | Проблема | Статус | Что сделано |
|---|---|---|---|
| **BUG-003** | Testimonials без аватаров | **P3 ИСПРАВЛЕН** | Цветные круги с инициалами авторов. |
| **BUG-011** | Rate limiter in-memory без cleanup | **P3 ИСПРАВЛЕН** | `_cleanup_expired()` с периодической очисткой. |
| **BUG-014** | Двойное хранение данных чатов (JSON + PostgreSQL) | **ЗАДОКУМЕНТИРОВАН** | TODO: полный переход на PostgreSQL. |
| **BUG-015** | Отсутствие реальной очереди задач для агента | **ЗАДОКУМЕНТИРОВАН** | TODO: message queue per chat. |
| **BUG-016** | События `tool_executing` игнорируются фронтендом | **P3 ИСПРАВЛЕН** | Обработчик `tool_executing`/`tool_progress`. |
| **BUG-021** | Слишком "тонкие" шаблоны сцен | **P4.5 ИСПРАВЛЕН** | ВСЕ шаблоны расширены: trust (53-80 строк), features_editorial_cards (71), features_process_timeline (82), testimonials_quote_wall (87). Ноль шаблонов менее 20 строк. |
| **BUG-022** | Хардкод ключевых слов в `classify_task` | **P3 ИСПРАВЛЕН** | Сужены до точных фраз. |

---

## Дополнительные исправления Phase 3–5

| Проблема | Статус | Что сделано |
|---|---|---|
| HTML: Дублированные section IDs | **P4 ИСПРАВЛЕН** | `_inject_section_id` отслеживает `used_ids` и добавляет суффикс. |
| HTML: Текстовые иконки вместо SVG | **P4 ИСПРАВЛЕН** | Нормализация: CamelCase -> kebab-case -> Lucide валидация -> fallback `star`. |
| HTML: Нерезолвленные плейсхолдеры `{{BG}}` | **P4 ИСПРАВЛЕН** | Sweep `re.sub(r'{{[A-Z_]+}}', '', result)` в `render_scene`. |
| Мусор: 14 patch-скриптов в корне | **P4 УДАЛЕНО** | Все удалены. |
| Мусор: 59 .bak файлов + 7 tracked в git | **P4.5 УДАЛЕНО** | FS: 0, Git: 0. Добавлено `*.bak*` в `.gitignore`. |
| Мусор: dist_backup директории | **P4 УДАЛЕНО** | Удалены. |
| Мусор: Дубль scene_assembler.py (1501 строка) | **P4 УДАЛЕНО** | Удалён из `shared/design/premium_scenes/`. |
| golden_paths: путь `/home/ubuntu/projects` | **P4 ИСПРАВЛЕН** | Заменён на `/root/workspace`. |
| Документация: README.md устарел | **P4.5 ИСПРАВЛЕН** | Обновлён: текущая архитектура, deprecated компоненты, правильный порт. |
| Документация: нет ARCHITECTURE_STATUS.md | **P4.5 СОЗДАН** | `docs/ARCHITECTURE_STATUS.md` — source of truth по всем компонентам. |
| submit_feedback: краш 500 вместо 401 | **P4.5 ИСПРАВЛЕН** | Неверный import `store_get_chat` -> `get_chat`. |
| **ComponentRetriever: статический словарь** | **P5 ИСПРАВЛЕН** | Полный каталог 19 шаблонов с метаданными (niches, styles, themes, complexity, slots). Scoring engine: niche 45%, style 30%, theme 25%. `retrieve_best()` + `retrieve_templates()` API. |
| **Legacy path: активный fallback** | **P5 ИСПРАВЛЕН** | `FEATURE_FLAG_LEGACY_CODER=false` в `.env` + gate в `agent_loop.py`. Legacy MultiConcept/Director path отключен по умолчанию. |
| **requirements.txt: неполный** | **P5 ИСПРАВЛЕН** | Добавлены: `bcrypt>=4.1.0`, `aiohttp>=3.9.0`, `openai>=1.12.0`. |

---

## Итоги Phase 5

| Категория | Количество | Исправлено | Задокументировано |
|---|---|---|---|
| КРИТИЧЕСКИЕ | 7 | 7 | 0 |
| СЕРЬЁЗНЫЕ | 7 | 7 | 0 |
| МИНОРНЫЕ | 7 | 5 | 2 |
| Доп. находки | 14 | 14 | 0 |
| **ВСЕГО** | **35** | **33** | **2** |

Тесты: **58 пройдено**, 2 пропущено.

Верификация Phase 5:
| Проверка | Результат |
|---|---|
| Health endpoint | `healthy` (degraded — только OpenAI key) |
| Login (неверный пароль) | 401 ✅ |
| SSE без auth | 401 ✅ |
| /model без auth | 401 ✅ |
| /feedback без auth | 401 ✅ |
| /status без auth | 401 ✅ |
| .bak файлов | 0 ✅ |
| Шаблонов < 20 строк | 0 ✅ |
| Patch-скриптов в корне | 0 ✅ |
| Дубль scene_assembler | 0 ✅ |
| /home/ubuntu в golden_paths | 0 ✅ |
| ComponentRetriever: fitness→hero | cinematic_fullbleed ✅ |
| ComponentRetriever: legal→features | process_timeline ✅ |
| ComponentRetriever: restaurant→testimonials | marquee ✅ |
| Feature flag legacy path | FEATURE_FLAG_LEGACY_CODER=false ✅ |
| Pytest | 58 passed, 2 skipped ✅ |

Git commits:
- `Phase 3: Fix all 20 audit bugs`
- `Phase 4: Fix all audit findings` (+381 -8819 lines)
- `Phase 4.5: Cleanup .bak files, expand templates, docs` (+313 -1649 lines)
- `Phase 5: ComponentRetriever v2, feature flag, requirements.txt` (+437 -52 lines)

Репозиторий: https://github.com/mksmediengruppe-netizen/arcane
