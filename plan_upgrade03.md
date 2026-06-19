# PLAN UPGRADE 03

# План добавления PDF-перевода

## 1. Цель

Добавить перевод PDF без изменения core translation engine.

PDF должен идти через существующий pipeline:

```text
PDF -> DocumentBlock[] -> segmentation -> AI translation -> cache/memory -> PDF builder
```

DOCX flow должен остаться совместимым:

```text
UI -> upload -> Redis job -> Celery worker -> status -> download
```

## 2. Главный принцип

PDF добавляется как новый input/output adapter.

Не переписывать:

- core translation pipeline;
- DOCX parser/builder;
- cache и translation memory;
- Redis job store;
- существующий `/translate/` для DOCX.

## 3. Этап P0 — Зависимости и структура

Добавить зависимости:

```text
PyMuPDF
reportlab
```

Добавить пакет:

```text
app/services/pdf/
    __init__.py
    parser.py
    builder.py
```

Критерий готовности:

- проект импортируется;
- DOCX-тесты не требуют изменений из-за PDF.

## 4. Этап P1 — Job file_type

Файл:

```text
app/models/jobs.py
```

Добавить поле:

```python
file_type: Literal["docx", "pdf"] = "docx"
```

Важно:

- default `docx` нужен для совместимости старых job;
- существующий DOCX flow не должен менять ответ.

Критерий готовности:

- новые PDF job сохраняют `file_type = pdf`;
- старые DOCX job работают как раньше.

## 5. Этап P2 — PDF parser

Файл:

```text
app/services/pdf/parser.py
```

Функция:

```python
extract_pdf_blocks(file_path: str) -> list[DocumentBlock]
```

Логика:

1. Открыть PDF через `fitz`.
2. Пройти страницы.
3. Извлечь текстовые blocks.
4. Нормализовать пробелы.
5. Вернуть `DocumentBlock`.

Metadata:

```python
{
    "page": page_number,
    "source": "pdf"
}
```

Критерий готовности:

- text-based PDF превращается в blocks;
- пустые blocks пропускаются;
- OCR не добавляется.

## 6. Этап P3 — PDF builder

Файл:

```text
app/services/pdf/builder.py
```

Функция:

```python
build_pdf(blocks: list[DocumentBlock], output_path: str) -> None
```

MVP-логика:

- создать PDF через `reportlab`;
- записать переведённый текст блоками;
- переносить страницы при нехватке места;
- сохранить файл в `outputs/`.

Критерий готовности:

- результат скачивается как `.pdf`;
- layout оригинала не сохраняется намеренно.

## 7. Этап P4 — Backend endpoint `/translate/pdf`

Файл:

```text
app/api/translate.py
```

Endpoint:

```text
POST /translate/pdf
```

Вход:

```text
file: PDF
source_lang
target_lang
```

Валидация:

- расширение `.pdf`;
- MIME type `application/pdf`;
- размер `<= MAX_FILE_SIZE_MB`;
- `source_lang != target_lang`.

Поведение:

1. Сохранить файл в `uploads/`.
2. Создать `TranslationJob`.
3. Установить `status = queued`.
4. Установить `file_type = pdf`.
5. Запустить `run_pdf_translation_job(job_id)`.
6. Вернуть `job_id`, `status`, `file_type`.

Критерий готовности:

- `/translate/` для DOCX не меняет контракт;
- PDF endpoint создаёт отдельную PDF job.

## 8. Этап P5 — Celery PDF worker

Файл:

```text
workers/translation_worker.py
```

Добавить task:

```python
run_pdf_translation_job(job_id: str)
```

Этапы:

1. Загрузить job.
2. Прочитать PDF из `uploads/`.
3. Получить blocks через `extract_pdf_blocks`.
4. Использовать существующую логику перевода blocks.
5. Собрать PDF через `build_pdf`.
6. Обновить job: `completed`, `progress = 100`, `result_file`.

Важно:

- не дублировать AI/cache/memory логику без необходимости;
- если общая функция перевода blocks уже есть, переиспользовать её;
- если общей функции нет, вынести минимальный helper без изменения поведения DOCX.

Критерий готовности:

- PDF job проходит queued -> processing -> completed;
- DOCX worker продолжает работать.

## 9. Этап P6 — Download

Файл:

```text
app/api/download.py
```

Поведение:

- `file_type == docx` -> вернуть DOCX;
- `file_type == pdf` -> вернуть PDF.

HTTP:

- `404` job не найден;
- `409` job не завершён;
- `404` result file отсутствует;
- `200` `FileResponse`.

Критерий готовности:

- PDF скачивается с `application/pdf`;
- DOCX download не сломан.

## 10. Этап P7 — Estimate

Рекомендуемый вариант:

```text
POST /estimate/
```

Добавить параметр:

```text
file_type: docx | pdf
```

Поведение:

- `docx` -> текущий `extract_docx_blocks`;
- `pdf` -> новый `extract_pdf_blocks`;
- расчёт стоимости остаётся общим.

Критерий готовности:

- оценка PDF не вызывает OpenAI;
- текущая оценка DOCX работает как раньше.

## 11. Этап P8 — Desktop ApiClient и UI

Файлы:

```text
desktop_ui/core/api_client.py
desktop_ui/core/worker.py
desktop_ui/ui/main_window.py
```

Минимальные изменения:

- file picker принимает `.docx` и `.pdf`;
- по расширению выбрать endpoint;
- для PDF вызвать `/translate/pdf`;
- estimate передаёт `file_type`;
- download использовать общий `/download/{job_id}`.

Критерий готовности:

- пользователь может выбрать PDF;
- DOCX поведение визуально не меняется.

## 12. Этап P9 — Тесты

Backend:

- PDF parser возвращает `DocumentBlock`;
- `/translate/pdf` валидирует файл;
- PDF job получает `file_type = pdf`;
- download отдаёт PDF;
- estimate работает для PDF без OpenAI.

Desktop:

- `ApiClient` выбирает PDF endpoint;
- `.docx` продолжает идти в старый endpoint.

GUI-тесты не добавлять.

## 13. Ручная проверка

1. Запустить Redis.
2. Запустить backend.
3. Запустить worker.
4. Запустить UI.
5. Перевести DOCX и проверить старый flow.
6. Выбрать text-based PDF.
7. Запустить estimate.
8. Запустить translate.
9. Проверить status.
10. Скачать PDF через `/download/{job_id}`.

## 14. Что не делать в MVP

- Не добавлять OCR.
- Не сохранять оригинальный PDF layout.
- Не восстанавливать таблицы как структуры.
- Не переносить изображения.
- Не менять core translation engine.
- Не ломать контракт DOCX endpoint.
- Не добавлять новый storage.
- Не делать batch PDF processing.

## 15. Definition of Done

Готово, если:

- PDF загружается через `/translate/pdf`;
- PDF парсится в `DocumentBlock`;
- перевод использует существующий pipeline;
- результат собирается в PDF;
- `/download/{job_id}` отдаёт PDF или DOCX по `file_type`;
- estimate поддерживает DOCX и PDF;
- Desktop UI принимает `.docx` и `.pdf`;
- существующий DOCX flow не сломан;
- backend tests проходят.
