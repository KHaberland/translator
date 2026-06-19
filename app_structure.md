# Архитектура приложения

## Назначение

`Translator_MVP` - сервис перевода DOCX-документов с отдельным desktop-клиентом для ручного тестирования полного flow.

Система состоит из четырех основных частей:

- FastAPI backend принимает DOCX, считает предварительную оценку стоимости, создает translation job и отдает status/download endpoints.
- Celery worker выполняет перевод в фоне.
- Redis хранит состояние jobs, Celery broker/result backend, progress events и межзадачный cache переводов.
- PySide6 desktop UI выбирает DOCX, отправляет файл в backend, опрашивает статус и скачивает готовый результат.

DOCX pipeline остается в backend-сервисах. Desktop UI не вызывает перевод напрямую и работает только через HTTP API.

## Технологический стек

Backend:

- Python 3.11+
- FastAPI
- Uvicorn
- Celery
- Redis
- python-docx
- SQLite
- Pydantic
- pydantic-settings
- OpenAI SDK
- python-multipart
- python-dotenv
- pytest

Desktop UI:

- PySide6
- requests
- python-dotenv

## Дерево проекта

```text
Translator_MVP/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── download.py
│   │   ├── estimate.py
│   │   ├── status.py
│   │   ├── stream.py
│   │   └── translate.py
│   ├── core/
│   │   ├── ai_client.py
│   │   ├── cache.py
│   │   ├── celery_app.py
│   │   ├── config.py
│   │   ├── job_store.py
│   │   └── progress_events.py
│   ├── models/
│   │   ├── jobs.py
│   │   └── schemas.py
│   └── services/
│       ├── builder.py
│       ├── cost_estimator.py
│       ├── docx_parser.py
│       ├── price_estimator.py
│       ├── run_preserver.py
│       ├── segmenter.py
│       ├── translation_cache.py
│       ├── translation_memory.py
│       └── translator.py
├── desktop_ui/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── requirements.txt
│   ├── core/
│   │   ├── __init__.py
│   │   ├── api_client.py
│   │   └── worker.py
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py
│       └── widgets.py
├── workers/
│   └── translation_worker.py
├── tests/
│   ├── test_desktop_api_client.py
│   └── test_services.py
├── data/
├── uploads/
├── outputs/
├── tmp/
├── MANUAL_TESTS.md
├── PLAN.md
├── plan_upgrade01.md
├── plan_upgrade02.md
├── paln_upgrade02.md
├── app_structure.md
├── .env.example
└── requirements.txt
```

`data/`, `uploads/`, `outputs/` и `tmp/` - рабочие директории. Backend создает их при старте через lifespan.

## Runtime-компоненты

```text
Desktop UI (PySide6)
        |
        | HTTP: /estimate, /translate, /status, /download
        v
FastAPI backend
        |
        | create/update job, progress events, cache
        v
Redis
        ^
        | broker/result backend
        |
Celery worker
        |
        v
DOCX pipeline + OpenAI/Mock AI + SQLite translation memory
```

Для полного async flow нужны одновременно:

- Redis на `localhost:6379` или другой URL из `.env`;
- FastAPI backend;
- Celery worker;
- desktop UI.

Если Redis не запущен, backend может стартовать, но создание jobs, Celery queue и status/progress flow работать не будут корректно.

## Backend API

### `app/main.py`

Точка входа FastAPI.

Отвечает за:

- создание `FastAPI` app;
- lifespan-инициализацию директорий `uploads/`, `outputs/`, `tmp/`, `data/`;
- endpoint `GET /health`;
- подключение router-ов `translate`, `estimate`, `status`, `stream`, `download`.

### `app/api/translate.py`

Endpoint-ы загрузки DOCX.

Реализовано:

- `POST /translate/` - основной async endpoint;
- `POST /translate/sync` - синхронный endpoint для локальных проверок и тестов.

`POST /translate/`:

- принимает multipart DOCX в поле `file`;
- принимает `source_lang` и `target_lang`;
- запрещает одинаковые языки;
- проверяет расширение `.docx`;
- проверяет MIME/content-type;
- проверяет размер файла;
- сохраняет исходный файл в `uploads/`;
- создает `TranslationJob`;
- сохраняет job в Redis job store;
- ставит Celery task `workers.translation_worker.run_translation_job`;
- возвращает `job_id` и начальный статус.

`POST /translate/sync` выполняет DOCX pipeline сразу в API-процессе и возвращает путь к готовому файлу. Основной UI его не использует.

### `app/api/estimate.py`

Endpoint `POST /estimate/`.

Реализует предварительную оценку DOCX без создания translation job и без постановки Celery task.

Поведение:

- принимает multipart DOCX в поле `file`;
- принимает `source_lang` и `target_lang`;
- запрещает одинаковые языки;
- использует общую DOCX-валидацию upload endpoint-а;
- временно сохраняет файл в `tmp/`;
- извлекает блоки через DOCX parser;
- считает переводимые и пропущенные блоки;
- оценивает input/output/total tokens;
- считает примерную стоимость в USD;
- возвращает бюджет и `budget_status`: `ok` или `exceeded`;
- удаляет временный файл после обработки.

### `app/api/status.py`

Endpoint `GET /status/{job_id}`.

Возвращает:

- `job_id`;
- текущий статус;
- progress `0..100`;
- `result_file`, если перевод завершен;
- безопасную ошибку, если job завершился неуспешно.

### `app/api/download.py`

Endpoint `GET /download/{job_id}`.

Поведение:

- если job не найден: `404`;
- если job не `completed` или `result_file` пустой: `409`;
- если файл результата отсутствует на диске: `404`;
- если все корректно: возвращает `FileResponse` с DOCX media type.

Desktop UI скачивает результат именно через этот endpoint.

### `app/api/stream.py`

Endpoint `GET /stream/{job_id}` для Server-Sent Events.

Отвечает за:

- проверку существования job;
- отдачу истории progress events из Redis Stream;
- ожидание новых событий;
- keep-alive сообщения;
- завершение stream на статусах `completed` и `failed`.

Desktop UI в MVP использует polling через `/status/{job_id}`. SSE остается backend-возможностью и потенциальным v2 для UI.

## Backend core

### `app/core/config.py`

Настройки backend через `pydantic-settings` и `.env`.

Основные параметры:

- `MOCK_AI_ENABLED`;
- `OPENAI_API_KEY`;
- `OPENAI_MODEL`;
- `OPENAI_BASE_URL`;
- `OPENAI_TIMEOUT_SECONDS`;
- `OPENAI_MAX_RETRIES`;
- `OPENAI_INPUT_PRICE_PER_1M_TOKENS`;
- `OPENAI_OUTPUT_PRICE_PER_1M_TOKENS`;
- `TRANSLATION_BUDGET_USD`;
- `ESTIMATED_OUTPUT_TOKEN_MULTIPLIER`;
- `MAX_BATCH_CHARS`;
- `MAX_BATCH_BLOCKS`;
- `MAX_FILE_SIZE_MB`;
- `REDIS_URL`;
- `CELERY_BROKER_URL`;
- `CELERY_RESULT_BACKEND`;
- `JOB_TTL_SECONDS`;
- `TRANSLATION_CACHE_TTL_SECONDS`;
- `PROGRESS_STREAM_MAX_EVENTS`;
- `TRANSLATION_MEMORY_DB_PATH`;
- `UPLOAD_DIR`;
- `OUTPUT_DIR`;
- `TMP_DIR`.

Важно: `.env` может содержать секреты и не должен попадать в коммит.

### `app/core/celery_app.py`

Конфигурация Celery.

Использует:

- Redis broker из `CELERY_BROKER_URL`;
- Redis result backend из `CELERY_RESULT_BACKEND`;
- include worker-а `workers.translation_worker`;
- JSON serialization;
- `task_acks_late`;
- `task_reject_on_worker_lost`;
- `worker_prefetch_multiplier=1`.

### `app/core/job_store.py`

Хранилище состояния jobs.

Содержит:

- `JobStore` protocol;
- `RedisJobStore` - основное runtime-хранилище с TTL;
- `InMemoryJobStore` - тестовая реализация;
- обновление `updated_at`;
- сериализацию job state для логов.

### `app/core/progress_events.py`

Хранилище progress events для SSE.

Использует Redis Streams:

- `xadd` для публикации событий;
- `xrange` для истории;
- `xread` для ожидания новых событий;
- TTL на stream job;
- ограничение длины stream через `PROGRESS_STREAM_MAX_EVENTS`.

### `app/core/cache.py`

Redis-кэш переводов между jobs и worker-ами.

Отвечает за:

- нормализацию исходного текста;
- построение ключей `translation_cache:{source}:{target}:{sha256}`;
- чтение и запись переводов в Redis;
- TTL для кэшированных переводов;
- graceful fallback, если Redis временно недоступен для cache get/set.

### `app/core/ai_client.py`

AI-клиент перевода.

Содержит:

- `OpenAICompatibleClient` на базе OpenAI SDK;
- `MockAIClient` для локального режима без реальных API-вызовов;
- JSON payload для batch-перевода;
- поддержку glossary terms;
- системный prompt;
- retry для временных ошибок;
- timeout через настройки;
- валидацию JSON-ответа и соответствия `block_id`.

## Models

### `app/models/schemas.py`

Pydantic-схемы API и переводимых блоков.

Содержит:

- `LanguageCode` - `ru`, `en`, `lv`, `lt`, `et`;
- `LANGUAGE_NAMES`;
- `DocumentBlock`;
- `TranslateResponse`;
- `EstimateResponse`;
- `TranslateJobResponse`;
- `JobStatusResponse`;
- `ProgressEvent`.

### `app/models/jobs.py`

Модель translation job.

Содержит:

- `JobStatus` - `queued`, `parsing`, `estimating`, `translating`, `building`, `completed`, `failed`;
- `TranslationJob`;
- progress validation `0..100`;
- `created_at` и `updated_at`;
- `upload_path`;
- `result_file`;
- `error`.

## DOCX services

### `app/services/translator.py`

Главный orchestration-сервис DOCX pipeline.

Выполняет:

1. Парсинг DOCX в `DocumentBlock`.
2. In-memory дедупликацию повторяющихся блоков внутри документа.
3. Поиск переводов в Redis cache.
4. Поиск переводов в SQLite translation memory.
5. Оценку символов и токенов только для непереведенных блоков.
6. Сегментацию в batch-и.
7. Вызов AI-клиента или mock-клиента.
8. Передачу релевантных glossary terms в batch.
9. Сохранение новых переводов в in-memory cache, Redis cache и translation memory.
10. Применение переводов к дубликатам.
11. Сборку итогового DOCX.
12. Отправку progress callback для worker-а и SSE.

Разделяет ошибки на:

- `DocumentProcessingError`;
- `TranslationProviderError`.

### `app/services/docx_parser.py`

Парсер DOCX.

Отвечает за:

- чтение документа через `python-docx`;
- извлечение обычных абзацев;
- извлечение текста из таблиц;
- стабильные `block_id`: `p1`, `t1r1c1p1` и т.п.;
- пропуск пустых блоков;
- пометку технического и code-like текста как непереводимого.

### `app/services/segmenter.py`

Сегментация переводимых блоков.

Отвечает за:

- группировку блоков в batch-и;
- лимит `MAX_BATCH_CHARS`;
- лимит `MAX_BATCH_BLOCKS`;
- исключение непереводимых блоков;
- ошибку, если один блок превышает лимит символов.

### `app/services/translation_cache.py`

In-memory кэш внутри одного DOCX-прохода.

Используется для:

- нормализации текста;
- поиска повторяющихся строк;
- привязки дубликата к первому `block_id`;
- применения уже полученного перевода к дубликатам.

### `app/services/translation_memory.py`

SQLite translation memory и glossary.

Содержит:

- таблицу `translation_memory`;
- таблицу `translation_glossary`;
- точный lookup по нормализованному тексту, языкам и domain;
- счетчик частоты использования;
- сохранение новых переводов;
- выбор glossary terms, которые реально встречаются в текущем batch.

### `app/services/cost_estimator.py`

Локальная оценка объема перевода.

Считает:

- количество символов только в переводимых блоках;
- примерную оценку токенов как `ceil(characters / 4)`.

### `app/services/price_estimator.py`

Оценка стоимости перевода в USD.

Считает:

- output tokens по multiplier из настроек;
- стоимость input tokens по цене за 1M tokens;
- стоимость output tokens по цене за 1M tokens;
- итоговую стоимость с округлением;
- статус бюджета `ok` или `exceeded`.

### `app/services/builder.py`

Сборка итогового DOCX.

Отвечает за:

- открытие исходного DOCX;
- замену текста в обычных абзацах;
- замену текста в таблицах;
- сохранение результата в `outputs/`;
- сохранение базовой структуры документа.

### `app/services/run_preserver.py`

Замена текста с сохранением run-структуры.

Используется builder-ом, чтобы:

- не удалять существующие runs;
- сохранять форматирование вроде bold/italic;
- сохранять hyperlink container;
- распределять перевод по исходным runs пропорционально длине;
- корректно обрабатывать пробелы через `xml:space="preserve"`.

## Worker

### `workers/translation_worker.py`

Celery worker для фонового перевода.

Отвечает за:

- получение `job_id`;
- загрузку job из Redis job store;
- запуск `translate_docx_file`;
- обновление job state;
- публикацию progress events;
- retry provider errors;
- безопасное сохранение ошибок без traceback и текста документа.

Worker должен запускаться отдельно от FastAPI.

## Desktop UI

### `desktop_ui/main.py`

Точка входа desktop-приложения.

Создает `QApplication`, открывает `MainWindow` и запускает Qt event loop.

Запуск:

```powershell
py -m desktop_ui.main
```

### `desktop_ui/config.py`

Настройки desktop UI.

Читает `.env` через `python-dotenv` и переменные окружения:

- `DESKTOP_API_BASE_URL`;
- fallback `API_BASE_URL`;
- `POLL_INTERVAL`;
- `REQUEST_TIMEOUT`.

По умолчанию `API_BASE_URL = http://localhost:8000`.

Если на `8000` запущено другое приложение, UI нужно запускать так:

```powershell
$env:DESKTOP_API_BASE_URL = "http://127.0.0.1:8010"
py -m desktop_ui.main
```

### `desktop_ui/core/api_client.py`

HTTP-клиент UI.

Методы:

- `estimate(file_path, source, target)` -> `POST /estimate/`;
- `upload(file_path, source, target)` -> `POST /translate/`;
- `get_status(job_id)` -> `GET /status/{job_id}`;
- `download(job_id, save_path, result_file)` -> `GET /download/{job_id}`.

Отвечает за:

- multipart upload;
- multipart estimate request;
- сохранение скачанного DOCX в выбранный путь;
- короткие пользовательские ошибки;
- fallback-сообщение с `result_file`, если backend без `/download/{job_id}` вернул `404 Not Found`.

UI не читает `outputs/` напрямую как универсальное решение.

### `desktop_ui/core/worker.py`

QThread worker-ы для сетевых операций без блокировки UI.

Содержит:

- `EstimateWorker`;
- `UploadWorker`;
- `PollingWorker`;
- `DownloadWorker`.

Signals:

- estimate: `started_signal`, `estimated_signal(dict)`, `error_signal(str)`;
- upload: `started_signal`, `uploaded_signal(dict)`, `error_signal(str)`;
- polling: `status_signal(str)`, `progress_signal(int)`, `completed_signal(dict)`, `failed_signal(str)`, `error_signal(str)`;
- download: `started_signal`, `downloaded_signal(str)`, `error_signal(str)`.

### `desktop_ui/ui/main_window.py`

Главное окно PySide6.

UI элементы:

- `Select DOCX`;
- label выбранного пути;
- source language dropdown;
- target language dropdown;
- `Estimate cost`;
- `Translate`;
- `Job ID`;
- `Status`;
- progress bar;
- message/error label;
- `Download result`.

Поведение:

- принимает только `.docx`;
- запрещает одинаковые языки;
- позволяет предварительно оценить стоимость перевода;
- показывает characters, tokens, estimated cost, budget и статус бюджета;
- при превышении бюджета просит подтверждение перед запуском перевода;
- отключает input во время estimate/upload;
- запускает polling после успешного upload;
- отображает все backend-статусы, включая `estimating`;
- включает download только при `completed`;
- предлагает имя результата вида `source_translated_to_ru.docx`;
- не закрывает окно во время активного estimate/upload/download;
- останавливает polling при закрытии окна.

## Основной async flow

```text
Desktop UI
        |
        | POST /estimate/ (optional preflight)
        v
FastAPI validates DOCX + estimates chars/tokens/cost/budget
        |
        v
Desktop UI shows estimate and may ask confirmation if budget exceeded
        |
        | POST /translate/
        v
FastAPI validates DOCX + languages + size
        |
        v
uploads/<source>.docx
        |
        v
TranslationJob(status=queued, progress=0)
        |
        v
RedisJobStore
        |
        v
Celery task: workers.translation_worker.run_translation_job
        |
        v
Worker loads job
        |
        v
translate_docx_file(...)
        |
        v
parsing -> estimating -> translating -> building -> completed
        |
        v
outputs/*_translated_to_{target}.docx
        |
        v
RedisJobStore(result_file, status=completed, progress=100)
        |
        v
Desktop UI polls GET /status/{job_id}
        |
        v
Desktop UI downloads GET /download/{job_id}
```

## DOCX pipeline

```text
DOCX source file
        |
        v
extract_docx_blocks()
        |
        v
DocumentBlock[]
        |
        v
Фильтрация пустых, технических и code-like блоков
        |
        v
In-memory deduplication внутри документа
        |
        v
Redis cache lookup
        |
        v
SQLite translation memory lookup
        |
        v
Cost estimate для оставшихся блоков
        |
        v
Batch segmentation
        |
        v
OpenAI-compatible client / Mock client
        |
        v
Redis cache + SQLite memory save
        |
        v
Применение переводов к дубликатам
        |
        v
build_translated_docx()
        |
        v
outputs/*_translated_to_{lang}.docx
```

## Рабочие директории

### `uploads/`

Хранит загруженные исходные DOCX-файлы.

### `outputs/`

Хранит готовые переведенные DOCX-файлы.

### `tmp/`

Используется для временных файлов и локальных проверок.

### `data/`

Хранит SQLite translation memory, по умолчанию `data/translation_memory.sqlite3`.

## Режимы AI

### Mock-режим

Включается через:

```powershell
$env:MOCK_AI_ENABLED = "true"
```

В этом режиме реальные AI-запросы не выполняются. `MockAIClient` возвращает текст в формате `source text [target_lang]`.

### Реальный AI-режим

Используется при:

```powershell
$env:MOCK_AI_ENABLED = "false"
```

Нужны:

- `OPENAI_API_KEY`;
- `OPENAI_MODEL`;
- опционально `OPENAI_BASE_URL`.

## Endpoint-ы

Реализовано:

- `GET /health`;
- `POST /estimate/`;
- `POST /translate/`;
- `POST /translate/sync`;
- `GET /status/{job_id}`;
- `GET /stream/{job_id}`;
- `GET /download/{job_id}`.

Не реализовано:

- Web UI;
- batch upload;
- история переводов;
- пользовательское управление glossary через API;
- авторизация;
- production installer для desktop UI.

## Локальный запуск

### Установка backend-зависимостей

```powershell
py -m pip install -r requirements.txt
```

### Установка desktop UI-зависимостей

```powershell
py -m pip install -r .\desktop_ui\requirements.txt
```

### Redis

Redis обязателен для async jobs, Celery, job state и progress events.

Проверка:

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 6379
```

Если Redis не установлен, его нужно установить или запустить через доступный runtime. На Windows один из вариантов:

```powershell
choco install redis-64 -y
redis-server
```

Если используется Docker:

```powershell
docker run --name translator-redis -p 6379:6379 redis:7
```

### Backend

Если порт `8000` свободен:

```powershell
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Если `8000` занят другим приложением:

```powershell
py -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Проверка:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8010/health"
```

### Celery worker

На Windows предпочтительно запускать через Python-модуль:

```powershell
py -m celery -A app.core.celery_app worker --pool=solo --loglevel=info
```

Если executable `celery` есть в `PATH`, можно так:

```powershell
celery -A app.core.celery_app worker --pool=solo --loglevel=info
```

### Desktop UI

Если backend на `8000`:

```powershell
py -m desktop_ui.main
```

Если backend на `8010`:

```powershell
$env:DESKTOP_API_BASE_URL = "http://127.0.0.1:8010"
py -m desktop_ui.main
```

## Тесты

Тесты находятся в `tests/`.

Основные группы:

- `tests/test_services.py` - backend, DOCX services, worker, endpoints, SSE, download, estimate endpoint, price estimator;
- `tests/test_desktop_api_client.py` - desktop `ApiClient.estimate()` без запуска Qt.

Покрывается:

- парсинг абзацев и таблиц;
- сохранение run-форматирования;
- сохранение list style;
- сохранение структуры таблиц;
- сохранение hyperlink container;
- in-memory translation cache;
- Redis translation cache;
- segmenter limits;
- cost estimator;
- price estimator;
- estimate endpoint;
- валидация upload endpoint;
- mock DOCX-проход;
- Redis cache hit/save;
- translation memory hit/save;
- glossary terms per batch;
- создание queued job;
- status endpoint;
- download endpoint;
- SSE stream endpoint;
- worker success/failure flow;
- desktop API error mapping;
- desktop estimate API flow.

Запуск:

```powershell
py -m pytest
```

В исходниках сейчас 40 test-функций. Актуальный результат проверки нужно обновлять после запуска `py -m pytest`.

## Текущий статус архитектуры

Приложение больше не является backend-only MVP:

- есть отдельный PySide6 desktop UI;
- есть предварительная оценка стоимости через `/estimate/`;
- основной перевод выполняется через async jobs;
- состояние job хранится в Redis;
- progress доступен через status endpoint и SSE;
- результат скачивается через `/download/{job_id}`;
- worker отделен от API-процесса;
- Redis cache переиспользует переводы между worker-ами;
- SQLite translation memory хранит накопленные переводы и glossary;
- DOCX builder сохраняет run-level форматирование;
- full desktop flow зависит от корректного запуска Redis, FastAPI, Celery worker и UI.

Следующие крупные расширения лучше добавлять после стабилизации одиночного DOCX flow: batch upload, история переводов, glossary UI/API, авторизация и installer.
