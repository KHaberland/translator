# PLAN UPGRADE 04

# План добавления Layout-Aware PDF Translation Engine v2

## 1. Цель

Добавить новый режим PDF-перевода:

```text
PDF (layout mode)
    -> layout_parser
    -> PDFTextBlock[]
    -> existing translator
    -> translations dict
    -> layout_builder
    -> output PDF поверх оригинала
```

Главная цель:

- сохранить оригинальный PDF как основу;
- заменить текст переводом в тех же координатах;
- сохранить изображения, страницы и базовое визуальное оформление;
- не увеличивать расход LLM-токенов по сравнению с текущим PDF pipeline.

## 2. Главный принцип

Новый layout-aware PDF mode добавляется как отдельный flow.

Не переписывать:

- DOCX pipeline;
- текущий PDF simple mode;
- core translation pipeline;
- Redis job store;
- Celery app config;
- Translation Cache;
- Translation Memory.

Текущий PDF simple mode остается fallback:

```text
POST /translate/pdf -> старый PDF pipeline
```

Новый layout-aware mode работает отдельно:

```text
POST /translate/pdf-layout -> новый PDF layout pipeline
```

## 3. Архитектурное решение

Новый pipeline:

```text
PDF
    -> layout_parser
    -> PDFTextBlock[]
    -> adapter to DocumentBlock[]
    -> translate_document_blocks(...)
    -> translations dict
    -> layout_builder
    -> translated PDF with original page content
```

Ключевые решения:

- layout granularity = line-level;
- AI получает только `block_id` и `text`;
- AI не получает bbox, координаты, шрифты, изображения или metadata страницы;
- PDF builder не пересоздает документ с нуля;
- PDF builder открывает оригинал и накладывает перевод поверх него;
- исходный текст скрывается overlay-прямоугольниками;
- redaction не использовать как основной механизм;
- изображения не отправлять в LLM;
- OCR не реализовывать.

## 4. Новые файлы

Добавить:

```text
app/services/pdf/
    layout_parser.py
    layout_builder.py
    fit_engine.py
```

Изменить минимально:

```text
app/services/pdf/translator.py
app/api/translate.py
workers/translation_worker.py
app/models/jobs.py
app/models/schemas.py
tests/test_services.py
tests/test_desktop_api_client.py
```

Если `app/services/pdf/translator.py` отсутствует к моменту внедрения, допускается добавить `translate_pdf_layout_file(...)` в существующий `app/services/translator.py`, но предпочтение отдать отдельному PDF integration layer.

## 5. Этап L0 — Подготовка типов job и API-схем

Файлы:

```text
app/models/jobs.py
app/models/schemas.py
```

Минимальные изменения:

- расширить `file_type` значением `pdf_layout`;
- сохранить default `docx`;
- не менять существующие DOCX и PDF simple responses;
- добавить response model для layout PDF только если текущих схем недостаточно.

Важно:

- Redis job store структуру не менять;
- новые значения должны сериализоваться через существующую модель job;
- старые job не должны ломаться.

Критерий готовности:

- `file_type="docx"` работает как раньше;
- `file_type="pdf"` работает как раньше;
- `file_type="pdf_layout"` сохраняется в job;
- тесты существующих DOCX/PDF job проходят без изменения контракта.

## 6. Этап L1 — Layout Parser

Файл:

```text
app/services/pdf/layout_parser.py
```

Задача:

Создать parser для нового layout mode. Он не заменяет текущий `extract_pdf_blocks` в simple mode.

Вход:

```text
PDF file path
```

Выход:

```python
list[PDFTextBlock]
```

Модель `PDFTextBlock`:

```python
@dataclass(frozen=True)
class PDFTextBlock:
    block_id: str
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    font_size: float
    font_name: str | None
    translatable: bool
```

Требования:

- использовать PyMuPDF `page.get_text("rawdict")`;
- группировать по lines, не по blocks;
- сохранять line-level bbox;
- сохранять page index;
- извлекать примерный `font_size`;
- извлекать примерный `font_name`;
- фильтровать пустые строки;
- генерировать стабильный `block_id`, например `p{page}l{line}`;
- использовать текущие правила определения непереводимого текста, если они доступны локально;
- не отправлять layout metadata дальше в AI.

Фильтрация непереводимых блоков:

- пустые строки;
- строки без букв;
- номера страниц;
- URL;
- email;
- технические коды;
- артикулы;
- номера сертификатов;
- номера чертежей.

Примеры непереводимого текста:

```text
EN ISO 15614-1
WPS-001
12345678
https://example.com
```

Критерий готовности:

- PDF преобразуется в `list[PDFTextBlock]`;
- у каждого блока есть `page`, `bbox`, `font_size`;
- порядок чтения стабилен;
- пустые строки не попадают в результат;
- технические строки помечаются `translatable=False`;
- старый `app/services/pdf/parser.py` не изменен или не ломает simple mode.

## 7. Этап L2 — Adapter PDFTextBlock -> DocumentBlock

Файл:

```text
app/services/pdf/translator.py
```

Задача:

Сделать тонкий adapter, который позволяет использовать существующий translator без изменения его логики.

Логика:

```text
PDFTextBlock[] -> DocumentBlock[] -> translate_document_blocks(...) -> translations dict
```

Правила:

- `block_id` сохраняется;
- `text` сохраняется;
- `translatable` сохраняется;
- bbox/page/font не передаются в AI;
- layout metadata остается только в `PDFTextBlock`.

Критерий готовности:

- существующий `translate_document_blocks(...)` используется без изменения;
- Translation Cache работает;
- Translation Memory работает;
- in-memory deduplication работает;
- AI получает только текст текущего batch.

## 8. Этап L3 — Layout Builder

Файл:

```text
app/services/pdf/layout_builder.py
```

Задача:

Создать PDF поверх оригинала через overlay translation.

API:

```python
def build_translated_pdf(
    source_pdf_path: Path,
    output_pdf_path: Path,
    blocks: list[PDFTextBlock],
    translations: dict[str, str],
) -> None:
    ...
```

Логика:

1. Открыть оригинал:

```python
doc = fitz.open(source_pdf_path)
```

2. Для каждого `PDFTextBlock`:

- найти страницу по `block.page`;
- построить `fitz.Rect(block.bbox)`;
- скрыть исходный текст белым overlay-прямоугольником;
- вставить перевод через `page.insert_textbox(...)`.

3. Сохранить PDF в `output_pdf_path`.

Важно:

- redaction не использовать как основной механизм;
- не пересоздавать страницы с нуля;
- не извлекать и не вставлять изображения вручную на первом этапе;
- изображения сохраняются потому, что используется оригинальная страница;
- white rectangle overlay является MVP-компромиссом.

Пример вставки:

```python
page.insert_textbox(
    rect,
    translated_text,
    fontsize=block.font_size,
    fontname="helv",
)
```

Критерий готовности:

- количество страниц сохраняется;
- изображения в исходном PDF остаются;
- текст виден в исходных областях;
- результат открывается стандартным PDF viewer;
- старый `app/services/pdf/builder.py` продолжает работать для simple mode.

## 9. Этап L4 — Fit-to-box Engine

Файл:

```text
app/services/pdf/fit_engine.py
```

Задача:

Сделать простой механизм влезания переведенного текста в исходный bbox.

API:

```python
@dataclass(frozen=True)
class FittedText:
    text: str
    font_size: float
    overflow: bool

def fit_text(
    text: str,
    bbox: tuple[float, float, float, float],
    font_size: float,
    min_font_size: float = 6,
) -> FittedText:
    ...
```

Алгоритм:

1. Нормализовать пробелы.
2. Попробовать исходный `font_size`.
3. Если текст не помещается, уменьшать размер шрифта.
4. Минимальный размер шрифта: `6`.
5. Если текст все равно не помещается, вернуть `overflow=True`.

Допустимое MVP-упрощение:

- использовать приближенную оценку ширины символов;
- не реализовывать сложный layout engine;
- не делать font embedding;
- не делать переносы по слогам.

Критерий готовности:

- в простых случаях текст не выходит за bbox;
- читаемость сохраняется;
- overflow явно возвращается;
- builder использует fitted `font_size`.

## 10. Этап L5 — PDF Layout Integration Layer

Файл:

```text
app/services/pdf/translator.py
```

Добавить:

```python
async def translate_pdf_layout_file(
    source_path: Path,
    original_filename: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
    progress_callback: ProgressCallback | None = None,
) -> TranslationResult:
    ...
```

Flow:

```text
extracting_layout
    -> layout_parser.extract_pdf_layout_blocks(...)
extracting_text
    -> adapter PDFTextBlock[] to DocumentBlock[]
translating
    -> translate_document_blocks(...)
rebuilding_pdf
    -> layout_builder.build_translated_pdf(...)
completed
```

Важно:

- core translator не переписывать;
- layout metadata не отправлять в AI;
- `output_name` использовать существующий стиль `*_translated_to_{target}.pdf`;
- ошибки документа заворачивать в `DocumentProcessingError`;
- ошибки провайдера оставлять как `TranslationProviderError`.

Критерий готовности:

- новый layout pipeline вызывается отдельной функцией;
- simple PDF pipeline продолжает использовать старую функцию;
- DOCX pipeline не изменен;
- progress callback получает новые этапы.

## 11. Этап L6 — Worker integration

Файл:

```text
workers/translation_worker.py
```

Добавить Celery task:

```python
run_pdf_layout_translation_job
```

Добавить processor:

```python
process_pdf_layout_translation_job(job_id: str) -> None
```

Логика:

- загрузить job из Redis;
- проверить, что job существует;
- вызвать `translate_pdf_layout_file(...)`;
- обновлять progress через callback;
- сохранить `result_file`;
- выставить `status=completed`, `progress=100`;
- при ошибках сохранять безопасные сообщения.

Новые статусы для layout PDF:

```text
queued
extracting_layout
extracting_text
translating
rebuilding_pdf
completed
failed
```

Важно:

- DOCX-статусы оставить без изменений;
- simple PDF flow не менять;
- Redis job store не менять по структуре.

Критерий готовности:

- layout PDF job выполняется отдельной Celery task;
- progress обновляется по этапам;
- старые DOCX/PDF tasks работают как раньше.

## 12. Этап L7 — API

Файл:

```text
app/api/translate.py
```

Добавить endpoint:

```text
POST /translate/pdf-layout
```

Поведение:

- идентично `/translate/pdf` по валидации;
- принимает только `.pdf`;
- требует `content_type = application/pdf`;
- создает job с `file_type="pdf_layout"`;
- ставит `run_pdf_layout_translation_job`;
- возвращает `job_id`, статус и `file_type`.

Не менять:

```text
POST /translate/
POST /translate/pdf
POST /estimate/
GET /status/{job_id}
GET /download/{job_id}
```

Критерий готовности:

- `/translate/pdf-layout` создает отдельную layout job;
- `/translate/pdf` продолжает запускать simple PDF mode;
- `/translate/` продолжает запускать DOCX mode.

## 13. Этап L8 — Estimate для layout PDF

Файл:

```text
app/api/estimate.py
```

Минимальный вариант:

- оставить `file_type=pdf` для simple PDF estimate;
- добавить `file_type=pdf_layout`, если UI будет различать режимы estimate.

Для `pdf_layout`:

- использовать layout parser;
- считать только `translatable=True`;
- не учитывать изображения;
- не учитывать пустые блоки;
- не учитывать технические идентификаторы;
- не учитывать найденные дубликаты внутри документа;
- не вызывать OpenAI.

Важно:

- порядок экономии токенов должен совпадать с translation flow;
- estimate должен быть ближе к реальной стоимости, чем текущий simple parser.

Критерий готовности:

- PDF layout estimate не вызывает OpenAI;
- дубликаты не завышают стоимость;
- изображения не влияют на стоимость;
- DOCX estimate не изменился.

## 14. Этап L9 — Desktop UI

Файлы:

```text
desktop_ui/core/api_client.py
desktop_ui/core/worker.py
desktop_ui/ui/main_window.py
```

Минимальные варианты UI:

Вариант A:

- добавить переключатель PDF mode:
  - `Simple PDF`;
  - `Layout PDF`;
- `.docx` всегда идет в `/translate/`;
- `.pdf` в simple mode идет в `/translate/pdf`;
- `.pdf` в layout mode идет в `/translate/pdf-layout`.

Вариант B:

- временно всегда отправлять PDF в `/translate/pdf-layout`;
- оставить старый `/translate/pdf` только как backend fallback.

Рекомендуемый вариант:

- Вариант A, чтобы можно было сравнить simple и layout output.

Критерий готовности:

- пользователь может выбрать layout mode для PDF;
- DOCX поведение визуально не меняется;
- simple PDF mode остается доступен;
- download использует общий `/download/{job_id}`.

## 15. Этап L10 — Tests

Backend:

- layout parser возвращает `PDFTextBlock`;
- `PDFTextBlock` содержит `bbox`, `page`, `font_size`;
- порядок чтения стабилен;
- layout parser фильтрует пустые строки;
- layout parser помечает технические строки как `translatable=False`;
- layout builder сохраняет количество страниц;
- layout builder сохраняет изображения;
- layout builder вставляет переведенный текст;
- fit engine уменьшает шрифт при переполнении;
- `/translate/pdf-layout` валидирует PDF;
- layout PDF job получает `file_type = pdf_layout`;
- worker запускает layout pipeline;
- download отдает PDF для `pdf_layout`;
- estimate для `pdf_layout` не вызывает OpenAI.

Desktop:

- `ApiClient` выбирает `/translate/pdf-layout` для layout mode;
- `.pdf` simple mode продолжает идти в `/translate/pdf`;
- `.docx` продолжает идти в `/translate/`.

Регрессия:

- DOCX tests проходят;
- текущие PDF simple tests проходят;
- cache/memory tests проходят.

GUI-тесты не добавлять.

## 16. Ручная проверка

1. Запустить Redis/Memurai.
2. Запустить backend.
3. Запустить worker.
4. Запустить UI.
5. Перевести DOCX и проверить старый flow.
6. Перевести PDF через simple mode.
7. Перевести тот же PDF через layout mode.
8. Проверить, что layout PDF:
   - открывается в PDF viewer;
   - содержит переведенный текст;
   - сохранил количество страниц;
   - сохранил изображения;
   - сохранил общий порядок элементов;
   - визуально ближе к исходнику, чем simple PDF mode.
9. Проверить, что OpenAI вызывается только для реально переводимых блоков.
10. Проверить, что повторный перевод использует cache/memory.

## 17. Что не делать в v2 MVP

- Не добавлять OCR.
- Не переводить scanned PDF без text layer.
- Не делать font embedding.
- Не делать полноценный layout reconstruction engine.
- Не делать table detection ML.
- Не делать full PDF rewrite.
- Не использовать redaction как основной механизм скрытия текста.
- Не отправлять layout metadata в LLM.
- Не отправлять изображения в LLM.
- Не менять DOCX pipeline.
- Не удалять старый PDF simple mode.
- Не менять Redis/Celery/job store структуру.

## 18. Риски и компромиссы

### Белые overlay-прямоугольники

Риск:

- если исходный текст находится поверх цветного фона или изображения, белый прямоугольник будет заметен.

Причина принятия:

- это самый простой MVP-механизм;
- redaction может удалить графику;
- layout rewrite слишком дорогой для текущего этапа.

### Длина перевода

Риск:

- перевод может быть длиннее исходного текста и не помещаться в bbox.

Компромисс:

- fit engine уменьшает шрифт до `6`;
- при невозможности поместить текст выставляется `overflow=True`;
- сложный reflow переносится за рамки v2 MVP.

### Шрифты

Риск:

- исходный font может быть недоступен для повторной вставки.

Компромисс:

- использовать `helv` как fallback;
- сохранять исходный `font_size`, но не пытаться встраивать исходные шрифты.

### Таблицы

Риск:

- line-level overlay в таблицах может быть неточным.

Компромисс:

- table detection и сложные merged cells не входят в v2 MVP;
- line-level bbox дает приемлемый первый результат.

## 19. Definition of Done

Готово, если:

- `/translate/pdf-layout` доступен;
- layout parser возвращает line-level `PDFTextBlock`;
- AI получает только текст;
- Translation Cache и Translation Memory работают;
- дубликаты не переводятся повторно;
- layout builder использует оригинальный PDF как основу;
- изображения сохраняются;
- количество страниц сохраняется;
- переведенный текст вставляется в исходные области;
- результат открывается стандартным PDF viewer;
- старый `/translate/pdf` продолжает работать;
- DOCX flow не изменился;
- backend tests проходят;
- desktop `ApiClient` умеет выбирать layout PDF endpoint.
