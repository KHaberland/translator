# PLAN UPGRADE 02

# План реализации Desktop UI для DOCX Translator MVP на PySide6

## 1. Цель

Добавить отдельное desktop-приложение для ручного тестирования backend-сервиса перевода DOCX.

UI должен:

- выбрать `.docx`;
- отправить файл в `POST /translate/`;
- получить `job_id`;
- опрашивать `GET /status/{job_id}`;
- показывать статус и progress;
- скачать готовый `.docx`;
- не блокировать интерфейс во время сетевых операций.

Главное правило: не переписывать рабочий backend и DOCX pipeline. Desktop UI добавляется рядом с текущим кодом как отдельный клиент.

## 2. Текущий backend-контракт

Уже использовать:

```text
POST /translate/
GET /status/{job_id}
GET /stream/{job_id}
```

Фактические модели:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

```json
{
  "job_id": "uuid",
  "status": "translating",
  "progress": 45,
  "result_file": null,
  "error": null
}
```

Статусы backend:

```text
queued
parsing
estimating
translating
building
completed
failed
```

Важно: в ТЗ нет `estimating`, но backend уже использует этот статус. UI должен отображать его без ошибки.

## 3. Границы MVP UI

Входит:

- одно главное окно;
- выбор одного DOCX;
- выбор `source_lang` и `target_lang`;
- запрет одинаковых языков;
- upload через multipart;
- polling статуса через `QThread`;
- progress bar `0-100`;
- отображение `job_id`, `status`, ошибки;
- кнопка download активна только при `completed`;
- минимальная конфигурация `API_BASE_URL` и `POLL_INTERVAL`.

Не входит:

- batch upload;
- drag and drop;
- история переводов;
- glossary editor;
- dark mode;
- production installer;
- авторизация;
- сложный retry/backoff;
- SSE как основной механизм.

## 4. Принцип минимальных изменений

- Не менять существующие сервисы `app/services/*`.
- Не менять текущий async pipeline и Celery worker.
- Не менять контракты `POST /translate/` и `GET /status/{job_id}`.
- Добавить `desktop_ui/` отдельной папкой.
- Backend трогать только если нужен безопасный `GET /download/{job_id}`.
- Если download endpoint еще не реализован, добавить его отдельным малым шагом.

## 5. Целевая структура

```text
Translator_MVP/
├── app/
├── workers/
├── desktop_ui/
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   ├── core/
│   │   ├── __init__.py
│   │   ├── api_client.py
│   │   └── worker.py
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py
│       └── widgets.py
├── tests/
├── PLAN.md
├── plan_upgrade01.md
└── paln_upgrade02.md
```

`widgets.py` оставить пустым или минимальным, если кастомные widgets не понадобятся.

## 6. Этап P0 — Подготовка Desktop UI

Цель: добавить каркас приложения без влияния на backend.

Файлы:

```text
desktop_ui/main.py
desktop_ui/config.py
desktop_ui/requirements.txt
desktop_ui/core/__init__.py
desktop_ui/ui/__init__.py
```

Зависимости `desktop_ui/requirements.txt`:

```text
PySide6
requests
python-dotenv
```

`config.py`:

```python
API_BASE_URL = "http://localhost:8000"
POLL_INTERVAL = 2
REQUEST_TIMEOUT = 30
```

Команда запуска:

```powershell
py -m desktop_ui.main
```

Критерий готовности:

- открывается пустое главное окно;
- backend-код не изменен.

## 7. Этап P1 — MainWindow

Цель: собрать основной layout.

Компоненты:

- кнопка `Select DOCX`;
- label с выбранным путем;
- dropdown `Source language`;
- dropdown `Target language`;
- кнопка `Translate`;
- label `Job ID`;
- label `Status`;
- progress bar;
- label/error text;
- кнопка `Download result`.

Языки:

```text
en
ru
lv
lt
et
```

Начальное состояние:

- `Translate` выключена, пока файл не выбран;
- `Download result` выключена;
- progress `0`;
- status `idle`;
- source по умолчанию `en`;
- target по умолчанию `ru`.

Валидация:

- если `source == target`, выключить `Translate` и показать короткое сообщение;
- принимать только путь с расширением `.docx`.

Критерий готовности:

- можно выбрать DOCX;
- UI корректно меняет доступность кнопок;
- одинаковые языки запрещены на уровне UI.

## 8. Этап P2 — ApiClient

Цель: изолировать HTTP-логику от окна.

Файл:

```text
desktop_ui/core/api_client.py
```

Класс:

```python
class ApiClient:
    def upload(self, file_path: str, source: str, target: str) -> dict: ...
    def get_status(self, job_id: str) -> dict: ...
    def download(self, job_id: str, save_path: str) -> str: ...
```

`upload`:

- `POST {API_BASE_URL}/translate/`;
- multipart field `file`;
- form fields `source_lang`, `target_lang`;
- вернуть `job_id` и `status`;
- HTTP errors превращать в понятный текст для UI.

`get_status`:

- `GET {API_BASE_URL}/status/{job_id}`;
- вернуть `status`, `progress`, `result_file`, `error`.

`download`:

Основной вариант:

- `GET {API_BASE_URL}/download/{job_id}`;
- сохранить ответ в выбранный пользователем путь.

Fallback только для локального MVP:

- если backend вернул `result_file`, а `/download/{job_id}` еще нет, показать пользователю путь результата;
- не пытаться читать серверный `outputs/` напрямую как универсальное решение.

Критерий готовности:

- `ApiClient` можно проверить отдельно без запуска Qt;
- ошибки backend не падают traceback-ом в UI.

## 9. Этап P3 — UploadWorker

Цель: не блокировать UI при отправке файла.

Файл:

```text
desktop_ui/core/worker.py
```

Добавить `UploadWorker(QThread)` или worker object для `QThread`.

Signals:

```text
started_signal()
uploaded_signal(dict)
error_signal(str)
```

Поведение:

- при старте выключить `Select DOCX`, dropdown и `Translate`;
- после успеха показать `job_id`;
- запустить polling;
- при ошибке вернуть UI в состояние `idle` или `failed`.

Критерий готовности:

- upload не замораживает окно;
- после upload отображается `job_id`.

## 10. Этап P4 — StatusWorker

Цель: live polling статуса.

Signals:

```text
status_signal(str)
progress_signal(int)
completed_signal(dict)
failed_signal(str)
error_signal(str)
```

Polling:

- интервал `POLL_INTERVAL` секунд;
- `GET /status/{job_id}`;
- обновлять status label и progress bar;
- остановиться при `completed` или `failed`;
- поддержать ручную остановку worker при закрытии окна.

UI mapping:

```text
queued       -> progress обычный, кнопки upload выключены
parsing      -> progress обновляется
estimating   -> progress обновляется
translating  -> progress обновляется
building     -> progress обновляется
completed    -> progress 100, Download enabled
failed       -> показать ошибку, Download disabled
```

Критерий готовности:

- progress обновляется каждые 1-2 секунды;
- окно остается отзывчивым;
- при terminal status polling останавливается.

## 11. Этап P5 — Download result

Цель: сохранить готовый DOCX локально.

UI:

- кнопка `Download result` активна только при `completed`;
- открыть `QFileDialog.getSaveFileName`;
- предложить имя на основе исходного файла и target language.

Backend:

- если `GET /download/{job_id}` уже есть, использовать его;
- если нет, добавить endpoint минимально.

Минимальный backend endpoint:

```text
GET /download/{job_id}
```

Поведение endpoint:

- найти job по `job_id`;
- если job не найден: `404`;
- если status не `completed`: `409`;
- если `result_file` отсутствует или файл не найден: `404`;
- вернуть `FileResponse` с DOCX media type.

Критерий готовности:

- после `completed` файл скачивается через UI;
- скачанный DOCX открывается в Word/LibreOffice.

## 12. Этап P6 — Error handling

Обработать в UI:

- backend недоступен;
- timeout запроса;
- выбран не DOCX;
- `source == target`;
- `400 invalid file`;
- `404 job not found`;
- `409 result not ready`;
- `500/502 failed job`;
- `failed` status с полем `error`;
- закрытие окна при активном polling.

Тексты ошибок держать короткими:

```text
Backend is unavailable
Only DOCX files are supported
Source and target languages must be different
Translation failed
Result is not ready
```

Критерий готовности:

- ошибки видны пользователю;
- UI можно использовать повторно после ошибки без перезапуска.

## 13. Этап P7 — SSE как v2

Не делать в MVP, если polling работает.

Позже можно добавить:

```text
GET /stream/{job_id}
```

Правило:

- оставить polling основным путем;
- SSE добавить как альтернативный worker;
- не усложнять первый desktop UI.

## 14. UI состояния

```text
idle
uploading
queued
parsing
estimating
translating
building
completed
failed
```

Поведение:

```text
idle        Select enabled, Translate enabled only with valid DOCX
uploading   all input disabled, Download disabled
queued      input disabled, polling active
parsing     input disabled, polling active
estimating  input disabled, polling active
translating input disabled, polling active
building    input disabled, polling active
completed   input enabled, Download enabled
failed      input enabled, Download disabled
```

## 15. Ручная проверка

Запуск backend:

```powershell
py -m uvicorn app.main:app --reload --port 8000
```

Если используется Celery/Redis, запустить их текущим способом проекта.

Проверка health:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health"
```

Запуск UI:

```powershell
py -m desktop_ui.main
```

Сценарий:

1. Выбрать маленький DOCX.
2. Выбрать `en -> ru`.
3. Нажать `Translate`.
4. Убедиться, что появился `job_id`.
5. Дождаться progress/status.
6. После `completed` скачать результат.
7. Открыть скачанный DOCX.

## 16. Автотесты

Минимально:

- не добавлять тяжелые GUI-тесты в первый проход;
- покрыть `ApiClient` mock-тестами позже, если появится стабильная test-инфраструктура для UI;
- backend после добавления download endpoint проверить через существующий `pytest`.

Команда:

```powershell
py -m pytest
```

## 17. Очередность реализации

1. Добавить `desktop_ui` каркас.
2. Добавить `MainWindow` с layout и validation.
3. Добавить `ApiClient`.
4. Добавить upload в отдельном thread.
5. Добавить polling worker.
6. Добавить download UI.
7. При необходимости добавить backend `GET /download/{job_id}`.
8. Обработать ошибки и закрытие окна.
9. Провести ручную проверку полного flow.

## 18. Definition of Done

Desktop UI готов, если:

- можно выбрать DOCX;
- нельзя выбрать одинаковые языки;
- `Translate` отправляет файл в backend;
- UI получает `job_id`;
- status отображается;
- progress обновляется;
- при `completed` активируется download;
- результат сохраняется локально;
- UI не зависает;
- backend pipeline не переписан;
- существующие backend-тесты проходят.

## 19. Что не делать при реализации

- Не переносить backend-код внутрь `desktop_ui`.
- Не вызывать DOCX pipeline напрямую из UI.
- Не хранить бинарный DOCX в job state.
- Не добавлять базу данных для UI.
- Не добавлять batch, history, dark mode в MVP.
- Не заменять polling на SSE в первом проходе.
- Не переписывать `plan_upgrade01` задачи ради UI.
- Не менять рабочие сервисы без прямой необходимости.
