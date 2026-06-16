# PLAN UPGRADE 01

# План доработки: DOCX Translation MVP → Production-ready service

## 1. Цель upgrade

Преобразовать текущий рабочий MVP DOCX-переводчика в production-ready сервис обработки документов.

Новая целевая система должна:

- обрабатывать DOCX асинхронно через фоновые задачи;
- сохранять форматирование DOCX на уровне `runs`;
- поддерживать очередь задач и независимые worker-процессы;
- отдавать статус и прогресс выполнения;
- использовать Redis cache между worker-ами;
- поддерживать persistent translation memory;
- поддерживать пакетную обработку нескольких документов;
- не ломать текущий корректно работающий pipeline перевода DOCX.

## 2. Главный принцип доработки

Не переписывать рабочий MVP целиком.

Текущий синхронный pipeline уже работает:

```text
upload DOCX → parse → segment → translate → build DOCX → save output
```

Его нужно постепенно обернуть в job-систему, cache layer и progress layer.

Правило:

- сначала добавить новые слои рядом с текущими сервисами;
- затем перевести API на async job behavior;
- старую бизнес-логику использовать повторно;
- менять внутренние сервисы только там, где это нужно для нового поведения;
- сохранять unit-тесты текущего MVP зелеными после каждого этапа.

## 3. Экономия токенов при реализации

Общие правила:

- Не отправлять DOCX, XML, стили, изображения и бинарные данные в AI.
- Не отправлять повторяющиеся строки в AI.
- Использовать Redis cache до вызова AI.
- Использовать translation memory до вызова AI.
- Делить документ на batch-запросы по лимитам.
- Не повторять успешно переведенные batch при retry.
- Не логировать полный текст документа, prompt или AI response.
- В progress events хранить только stage, progress и короткое сообщение.
- В job state хранить метаданные, а не содержимое документа.
- Для тестов использовать mock AI.
- Для ручной проверки использовать маленькие DOCX-файлы.

## 4. Целевая архитектура

```text
Client
  |
  v
FastAPI API
  |
  |-- POST /translate/          → create job
  |-- GET /status/{job_id}      → read job status
  |-- GET /stream/{job_id}      → live progress via SSE
  |-- POST /translate/batch     → create batch job
  |
  v
Redis
  |
  |-- queue broker
  |-- job state storage
  |-- progress events
  |-- translation cache
  |
  v
Celery workers
  |
  v
DOCX pipeline
  |
  |-- parse
  |-- estimate
  |-- cache lookup
  |-- translation memory lookup
  |-- AI translate
  |-- build DOCX
  |
  v
outputs/
```

## 5. Новая структура проекта

Планируемая структура после upgrade:

```text
Translator_MVP/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── translate.py
│   │   ├── status.py
│   │   ├── stream.py
│   │   └── batch.py
│   ├── core/
│   │   ├── ai_client.py
│   │   ├── cache.py
│   │   ├── celery_app.py
│   │   ├── config.py
│   │   ├── job_store.py
│   │   └── logging.py
│   ├── models/
│   │   ├── schemas.py
│   │   └── jobs.py
│   └── services/
│       ├── builder.py
│       ├── cost_estimator.py
│       ├── docx_parser.py
│       ├── run_preserver.py
│       ├── segmenter.py
│       ├── translation_cache.py
│       ├── translation_memory.py
│       └── translator.py
├── workers/
│   ├── __init__.py
│   └── translation_worker.py
├── tests/
├── uploads/
├── outputs/
├── tmp/
├── requirements.txt
├── MANUAL_TESTS.md
├── app_structure.md
└── plan_upgrade01.md
```

## 6. Этап P0 — Async Job System

Приоритет: критически важно.

### 6.1 Цель

Перевести `POST /translate/` из синхронного выполнения в постановку фоновой задачи.

Текущее поведение:

```text
POST /translate/ → долго ждет → возвращает готовый файл
```

Новое поведение:

```text
POST /translate/ → быстро возвращает job_id
GET /status/{job_id} → показывает статус и результат
```

### 6.2 Новые зависимости

Добавить:

- `redis`
- `celery`

Опционально для локальной разработки:

- `flower`

### 6.3 Новые настройки `.env`

```text
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
JOB_TTL_SECONDS=86400
```

### 6.4 Новые компоненты

#### `app/core/celery_app.py`

Создает Celery app.

Требования:

- читать broker/backend из `Settings`;
- не импортировать FastAPI app;
- регистрировать worker task;
- иметь безопасные retry-настройки.

#### `app/core/job_store.py`

Обертка над Redis для хранения job state.

Хранит:

- `job_id`;
- `status`;
- `progress`;
- `source_lang`;
- `target_lang`;
- `original_filename`;
- `upload_path`;
- `result_file`;
- `error`;
- `created_at`;
- `updated_at`.

#### `workers/translation_worker.py`

Worker task для полного pipeline:

```text
parse → estimate → translate → build
```

Worker должен переиспользовать текущий `translate_docx_file` или его выделенную pipeline-функцию.

### 6.5 API

#### `POST /translate/`

Request:

- `file`;
- `source_lang`;
- `target_lang`.

Response:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

Поведение:

- валидирует файл и языки;
- сохраняет DOCX в `uploads/`;
- создает job в Redis;
- ставит Celery task в очередь;
- не вызывает AI внутри HTTP request.

#### `GET /status/{job_id}`

Response:

```json
{
  "job_id": "uuid",
  "status": "parsing",
  "progress": 10,
  "result_file": null,
  "error": null
}
```

### 6.6 Статусы

```text
queued
parsing
estimating
translating
building
completed
failed
```

### 6.7 Progress mapping

```text
queued       → 0
parsing      → 10
estimating   → 20
translating  → 30-80
building     → 90
completed    → 100
failed       → текущий progress или 100
```

### 6.8 Совместимость с текущим MVP

На этом этапе нельзя ломать:

- парсинг DOCX;
- сегментацию;
- AI-клиент;
- mock AI;
- сборку DOCX;
- текущие unit-тесты.

Рекомендуемый подход:

- выделить reusable pipeline-функцию;
- синхронный старый endpoint можно временно сохранить как `/translate/sync` для отладки;
- новый `/translate/` сделать async job endpoint.

### 6.9 Тесты P0

Добавить тесты:

- `POST /translate/` возвращает `job_id`;
- job создается со статусом `queued`;
- `GET /status/{job_id}` возвращает состояние;
- worker task меняет статусы;
- failed task сохраняет ошибку без stack trace;
- mock AI pipeline работает внутри worker.

### 6.10 Экономия токенов P0

- В job state не хранить полный текст документа.
- В Redis job metadata не класть prompt/response.
- Worker должен использовать существующий cache/dedup до AI.
- Retry task не должен повторно переводить уже успешные batch, если их можно восстановить из cache.

## 7. Этап P1 — Preservation of DOCX formatting

Приоритет: высокий.

### 7.1 Цель

Сохранять форматирование DOCX при замене текста.

Нужно сохранить:

- bold;
- italic;
- underline;
- hyperlinks;
- mixed formatting runs;
- таблицы;
- списки;
- стили абзацев.

### 7.2 Проблема текущего подхода

Текущая замена очищает дополнительные runs:

```text
paragraph.runs[0].text = translated_text
остальные runs = ""
```

Это сохраняет базовую структуру, но может потерять mixed formatting внутри абзаца.

### 7.3 Рекомендуемый подход

Сначала реализовать run-aware replacement.

Новый компонент:

```text
app/services/run_preserver.py
```

Задачи:

- читать исходные `paragraph.runs`;
- сохранять run properties;
- распределять переведенный текст по существующим runs;
- не трогать paragraph style;
- не трогать numbering/list properties;
- не удалять hyperlink containers.

### 7.4 Практичная стратегия MVP+

Для production upgrade использовать гибрид:

- если paragraph содержит один run → заменить текст в этом run;
- если paragraph содержит несколько runs → сохранить первый значимый run как style carrier;
- если есть hyperlink runs → не разрушать XML-структуру hyperlink;
- если run-level fidelity критична → перейти на XML-level replacement.

### 7.5 Advanced вариант

Если run-aware replacement недостаточен:

- использовать `lxml`;
- работать с `word/document.xml`;
- изменять `w:t` внутри `w:r`;
- сохранять `w:rPr`;
- отдельно обработать hyperlinks.

### 7.6 Тесты P1

Добавить DOCX fixtures или генерировать документы в тестах:

- bold text остается bold;
- italic text остается italic;
- hyperlink сохраняется;
- список остается списком;
- таблица сохраняет структуру;
- mixed runs не исчезают после перевода.

### 7.7 Экономия токенов P1

- Не отправлять форматирование в AI.
- Не просить AI возвращать markup.
- Не отправлять XML в prompt.
- Форматирование восстанавливать локально.

## 8. Этап P2 — Redis Cache

Приоритет: средний-высокий.

### 8.1 Цель

Заменить in-memory cache на Redis cache, общий для всех worker-ов.

Текущий cache работает только внутри одного документа и одного процесса.

Новый cache должен:

- работать между worker-ами;
- переживать обработку нескольких документов;
- иметь TTL;
- уменьшать AI-вызовы.

### 8.2 Новый компонент

```text
app/core/cache.py
```

Функции:

- `get_translation(key)`;
- `set_translation(key, value, ttl)`;
- `build_cache_key(source_text, source_lang, target_lang)`;
- нормализация текста;
- graceful fallback при недоступном Redis.

### 8.3 Настройки `.env`

```text
TRANSLATION_CACHE_TTL_SECONDS=2592000
TRANSLATION_CACHE_ENABLED=true
```

### 8.4 Поведение

Перед AI-вызовом:

1. Нормализовать текст.
2. Построить ключ с языковой парой.
3. Проверить Redis.
4. Если найден перевод → не отправлять блок в AI.
5. Если не найден → отправить в AI.
6. После успешного AI-ответа сохранить перевод в Redis.

### 8.5 Тесты P2

- cache hit не вызывает AI;
- cache miss вызывает AI;
- после AI response перевод сохраняется в Redis;
- TTL задается при сохранении;
- при недоступном Redis pipeline продолжает работать без cache.

### 8.6 Экономия токенов P2

- Redis cache должен проверяться до batch construction или до AI call.
- Повторяющиеся фразы между документами не должны доходить до AI.
- Пустые и технические строки не кэшировать.

## 9. Этап P3 — Streaming / Progress Updates

Приоритет: средний.

### 9.1 Цель

Показывать пользователю прогресс обработки в реальном времени.

Рекомендуемый вариант:

```text
GET /stream/{job_id}
```

через Server-Sent Events.

### 9.2 Почему SSE

SSE проще WebSocket для MVP+:

- однонаправленный поток server → client;
- легко читать из браузера;
- проще тестировать;
- достаточно для progress updates.

### 9.3 Новый компонент

```text
app/api/stream.py
```

и Redis pub/sub или Redis streams для событий.

### 9.4 Формат события

```json
{
  "job_id": "uuid",
  "stage": "translating",
  "progress": 45,
  "message": "Batch 3/7 translated"
}
```

### 9.5 События

- `queued`;
- `parsing started`;
- `segments created`;
- `estimating completed`;
- `translating batch 1/n`;
- `building document`;
- `completed`;
- `failed`.

### 9.6 Тесты P3

- stream endpoint отдает SSE headers;
- completed job отправляет финальное событие;
- failed job отправляет событие с безопасной ошибкой;
- события не содержат полный текст документа.

### 9.7 Экономия токенов P3

- В event message не включать исходный или переведенный текст.
- Писать только stage, batch index, total batches и progress.

## 10. Этап P4 — Translation Memory

Приоритет: средний-низкий.

### 10.1 Цель

Добавить persistent translation memory как ядро CAT-системы.

Translation memory должна переиспользовать переводы между документами и повышать консистентность.

### 10.2 Storage

На первом шаге можно использовать SQLite или PostgreSQL.

Для production предпочтительнее PostgreSQL.

Таблица:

```text
translation_memory
├── id
├── source_text
├── normalized_source_text
├── translated_text
├── source_lang
├── target_lang
├── domain
├── frequency
├── created_at
└── updated_at
```

### 10.3 Новый компонент

```text
app/services/translation_memory.py
```

Функции:

- lookup exact match;
- save translation;
- increment frequency;
- optional domain filtering;
- optional fuzzy match в будущих версиях.

### 10.4 Глоссарий

Добавить отдельный слой терминологии.

Пример:

```text
WPS → сварочный позиционер
```

Глоссарий должен:

- применяться до AI-вызова как context constraints;
- не раздувать prompt;
- передавать только термины, найденные в текущем batch.

### 10.5 Prompt strategy для глоссария

Не отправлять весь глоссарий.

Отправлять только найденные пары терминов:

```json
{
  "terms": [
    {"source": "WPS", "target": "сварочный позиционер"}
  ],
  "blocks": [
    {"id": "b1", "text": "Source text"}
  ]
}
```

### 10.6 Тесты P4

- exact match используется без AI;
- новый перевод сохраняется в memory;
- frequency увеличивается;
- glossary terms попадают только в релевантный batch;
- glossary не отправляется целиком.

### 10.7 Экономия токенов P4

- Exact matches не отправлять в AI.
- Не передавать весь glossary в prompt.
- Не делать AI-запрос для поиска терминов.
- Искать термины локально.

## 11. Этап P5 — Multi-document batch processing

Приоритет: низкий для первого production upgrade.

### 11.1 Цель

Поддержать загрузку нескольких DOCX за один запрос.

### 11.2 API

```text
POST /translate/batch
```

Request:

- zip-файл;
- `source_lang`;
- `target_lang`.

Response:

```json
{
  "batch_job_id": "uuid",
  "jobs": [
    "job_1",
    "job_2"
  ]
}
```

### 11.3 Обработка

1. Проверить zip.
2. Распаковать во временную папку.
3. Найти `.docx`.
4. Отклонить не-DOCX.
5. Создать отдельный job на каждый документ.
6. Создать batch job state.
7. Возвращать общий progress.

### 11.4 Batch status

```text
GET /batch/status/{batch_job_id}
```

Response:

```json
{
  "batch_job_id": "uuid",
  "status": "translating",
  "progress": 55,
  "jobs": [
    {
      "job_id": "job_1",
      "status": "completed",
      "result_file": "outputs/a_translated_to_ru.docx"
    },
    {
      "job_id": "job_2",
      "status": "translating",
      "result_file": null
    }
  ]
}
```

### 11.5 Тесты P5

- zip с DOCX создает несколько jobs;
- zip без DOCX возвращает ошибку;
- не-DOCX внутри zip отклоняются или игнорируются по выбранной политике;
- batch progress считается по дочерним jobs;
- результат каждого документа доступен отдельно.

### 11.6 Экономия токенов P5

- Общий Redis cache и translation memory должны использоваться между всеми документами batch.
- Одинаковые фразы из разных файлов не должны повторно уходить в AI.
- Не распаковывать и не читать файлы, превышающие лимит.

## 12. Надежность

### 12.1 Retry

Нужно сохранить текущий retry AI-запросов и добавить retry на уровне Celery task.

Правила:

- retry только для временных ошибок;
- не retry для validation errors;
- не увеличивать prompt при retry;
- не повторять уже успешно переведенные блоки, если они есть в Redis cache.

### 12.2 Job recovery

После рестарта API:

- job state должен остаться в Redis;
- completed jobs должны показывать `result_file`;
- failed jobs должны показывать безопасную ошибку;
- queued/running jobs должны быть восстановимы Celery worker-ом или переведены в `failed` по timeout policy.

### 12.3 Timeout policy

Добавить настройки:

```text
JOB_TIMEOUT_SECONDS=1800
AI_BATCH_TIMEOUT_SECONDS=120
```

### 12.4 Ошибки

Пользователю нельзя возвращать:

- stack trace;
- API key;
- prompt;
- полный AI response;
- внутренние пути за пределами проекта.

## 13. Логирование

Перейти на structured logs.

Минимальные поля:

```text
timestamp
level
job_id
stage
status
file_name
blocks
batches
characters
tokens
duration_ms
error_code
```

Не логировать:

- полный текст документа;
- prompt;
- AI response;
- `.env`;
- секреты.

## 14. API итогового состояния

### `GET /health`

Проверка API.

### `POST /translate/`

Создать job перевода одного DOCX.

### `GET /status/{job_id}`

Получить состояние job.

### `GET /stream/{job_id}`

Получить live progress через SSE.

### `GET /download/{job_id}`

Опционально: скачать результат по `job_id`, не раскрывая прямой путь к файлу.

### `POST /translate/batch`

Создать batch job из zip-файла.

### `GET /batch/status/{batch_job_id}`

Получить состояние batch job.

## 15. Миграционная стратегия

### Шаг 1

Добавить Redis/Celery инфраструктуру без изменения текущего pipeline.

### Шаг 2

Вынести общий pipeline в функцию, которую можно вызывать:

- из синхронного теста;
- из Celery worker;
- из mock pipeline.

### Шаг 3

Добавить job store и status endpoint.

### Шаг 4

Перевести `POST /translate/` на постановку задачи.

### Шаг 5

Оставить временный debug endpoint:

```text
POST /translate/sync
```

Только для локальной диагностики, если нужно.

### Шаг 6

Добавить SSE progress.

### Шаг 7

Улучшить DOCX formatting preservation.

### Шаг 8

Добавить Redis cache и translation memory.

### Шаг 9

Добавить batch processing.

## 16. Проверки после каждого этапа

После каждого этапа запускать:

```powershell
py -m pytest
```

Также проверять вручную:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8010/health"
```

Для API-загрузки DOCX использовать:

```powershell
curl.exe -X POST "http://127.0.0.1:8010/translate/" `
  -F "file=@.\tmp\api_check.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" `
  -F "source_lang=en" `
  -F "target_lang=ru"
```

## 17. Definition of Done

Upgrade считается завершенным, если:

- `POST /translate/` возвращает `job_id`;
- worker выполняет перевод в фоне;
- `GET /status/{job_id}` показывает актуальный статус;
- completed job возвращает result file;
- failed job возвращает безопасную ошибку;
- форматирование DOCX сохраняется на уровне runs;
- Redis cache работает между worker-ами;
- translation memory переиспользует переводы между документами;
- SSE stream отдает live progress;
- batch endpoint создает несколько jobs;
- текущие MVP-тесты не сломаны;
- новые тесты P0-P5 проходят;
- реальные AI-вызовы не происходят в unit-тестах.

## 18. Приоритеты реализации

```text
P0  Async Job System
P1  DOCX formatting preservation
P2  Redis cache
P3  Streaming progress
P4  Translation memory
P5  Multi-document batch processing
```

Рекомендуемый порядок:

1. P0 - без async job system сервис нельзя считать production-ready.
2. P1 - сохранение форматирования важно для качества результата.
3. P2 - Redis cache снижает стоимость и нужен для масштабирования worker-ов.
4. P3 - progress нужен для UX на длинных документах.
5. P4 - translation memory повышает качество и снижает расходы.
6. P5 - batch processing лучше добавлять после стабилизации одиночных jobs.
