# PLAN UPGRADE 02

# План доработки оценки стоимости перевода DOCX

## 1. Цель

Добавить в программу предварительную оценку стоимости перевода DOCX до запуска реального OpenAI-перевода.

Оценка должна показывать:

- количество переводимых символов;
- примерное количество input/output/total tokens;
- ориентировочную стоимость в USD;
- статус бюджета: `ok` или `exceeded`.

Важно: оценка не должна отправлять текст в OpenAI и не должна ломать текущий flow:

```text
UI -> upload -> /translate -> Redis job -> Celery worker -> status -> download
```

## 2. Главный принцип

Использовать уже существующую backend-логику:

- `app/services/docx_parser.py`;
- `app/services/cost_estimator.py`;
- текущую валидацию DOCX из `translate.py`;
- текущие настройки через `.env`.

Не переписывать DOCX pipeline, Celery worker, Redis job store и download flow.

## 3. Этап P0 — Backend-модель ответа

Добавить schema для ответа оценки.

Файл:

```text
app/models/schemas.py
```

Новая модель:

```python
class EstimateResponse(BaseModel):
    file_name: str
    source_lang: str
    target_lang: str
    translatable_blocks: int
    skipped_blocks: int
    estimated_characters: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float
    budget_usd: float
    budget_status: str
```

Критерий готовности:

- модель импортируется;
- существующие схемы не изменены несовместимо.

## 4. Этап P1 — Настройки стоимости

Добавить настройки в `Settings`.

Файл:

```text
app/core/config.py
```

Новые параметры:

```text
OPENAI_INPUT_PRICE_PER_1M_TOKENS=0.15
OPENAI_OUTPUT_PRICE_PER_1M_TOKENS=0.60
TRANSLATION_BUDGET_USD=10
ESTIMATED_OUTPUT_TOKEN_MULTIPLIER=1.2
```

Критерий готовности:

- значения имеют безопасные defaults;
- старый `.env` продолжает работать.

## 5. Этап P2 — Сервис расчёта стоимости

Добавить маленький сервис без OpenAI-вызовов.

Файл:

```text
app/services/price_estimator.py
```

Функции:

```python
estimate_output_tokens(input_tokens, multiplier)
estimate_translation_cost_usd(input_tokens, output_tokens, settings)
budget_status(cost, budget)
```

Формула:

```text
input_cost = input_tokens / 1_000_000 * input_price
output_cost = output_tokens / 1_000_000 * output_price
total = input_cost + output_cost
```

Критерий готовности:

- сервис не зависит от FastAPI;
- сервис легко тестируется;
- OpenAI SDK не используется.

## 6. Этап P3 — Backend endpoint `/estimate/`

Добавить новый router.

Файл:

```text
app/api/estimate.py
```

Endpoint:

```text
POST /estimate/
```

Вход:

```text
file: DOCX
source_lang
target_lang
```

Поведение:

1. Проверить разные языки.
2. Проверить `.docx`.
3. Проверить content-type.
4. Проверить размер файла.
5. Сохранить файл во временный путь или `tmp/`.
6. Извлечь blocks через `extract_docx_blocks`.
7. Посчитать переводимые и пропущенные blocks.
8. Посчитать characters/tokens через существующий `cost_estimator`.
9. Посчитать цену через новый `price_estimator`.
10. Вернуть `EstimateResponse`.

Важно:

- не создавать `TranslationJob`;
- не писать в Redis job store;
- не ставить Celery task;
- не вызывать OpenAI;
- не сохранять результат в `outputs/`.

Критерий готовности:

- `POST /estimate/` возвращает оценку;
- текущий `/translate/` не изменён по контракту.

## 7. Этап P4 — Подключить router

Файл:

```text
app/main.py
```

Добавить:

```python
from app.api.estimate import router as estimate_router
app.include_router(estimate_router)
```

Критерий готовности:

- `/health` работает;
- `/translate/` работает;
- `/estimate/` доступен.

## 8. Этап P5 — Desktop ApiClient

Файл:

```text
desktop_ui/core/api_client.py
```

Добавить метод:

```python
def estimate(self, file_path: str, source: str, target: str) -> dict:
    ...
```

Endpoint:

```text
POST {API_BASE_URL}/estimate/
```

Ошибки обрабатывать так же, как upload:

- backend unavailable;
- timeout;
- invalid DOCX;
- equal languages;
- file too large.

Критерий готовности:

- можно вызвать без Qt;
- ошибки возвращаются коротким текстом.

## 9. Этап P6 — EstimateWorker

Файл:

```text
desktop_ui/core/worker.py
```

Добавить `EstimateWorker(QThread)`.

Signals:

```text
started_signal()
estimated_signal(dict)
error_signal(str)
```

Критерий готовности:

- UI не зависает во время оценки;
- оценка не блокирует окно.

## 10. Этап P7 — UI-кнопка Estimate cost

Файл:

```text
desktop_ui/ui/main_window.py
```

Добавить кнопку:

```text
Estimate cost
```

Поведение:

- активна только при валидном `.docx` и разных языках;
- при нажатии запускает `EstimateWorker`;
- показывает результат в message label или отдельном label.

Минимальный текст:

```text
Text: 4,582 chars
Tokens: 2,446
Estimated cost: $0.0015
Budget: $10.00
Status: OK
```

Если бюджет превышен:

```text
Estimated cost: $12.40
Budget: $10.00
Status: Budget exceeded
```

Критерий готовности:

- пользователь видит цену до перевода;
- Translate flow не сломан.

## 11. Этап P8 — Защита бюджета

Если последняя оценка есть и:

```text
budget_status == exceeded
```

то перед `Translate` показать confirmation dialog:

```text
Estimated cost exceeds your budget. Continue anyway?
```

Кнопки:

```text
Cancel
Continue
```

Если оценки нет, перевод разрешён как раньше.

Критерий готовности:

- превышение бюджета не запускает перевод случайно;
- пользователь может явно продолжить.

## 12. Этап P9 — Тесты backend

Файл:

```text
tests/test_services.py
```

Добавить тесты:

- estimate endpoint принимает DOCX;
- считает только переводимые blocks;
- возвращает `estimated_characters`;
- возвращает `estimated_total_tokens`;
- считает `estimated_cost_usd`;
- возвращает `budget_status = ok`;
- возвращает `budget_status = exceeded`;
- не создаёт job;
- не вызывает Celery.

## 13. Этап P10 — Тесты desktop ApiClient

Файл:

```text
tests/test_desktop_api_client.py
```

Добавить тесты:

- `ApiClient.estimate()` возвращает dict;
- backend error превращается в короткое сообщение;
- timeout превращается в `Request timed out`.

GUI-тесты не добавлять.

## 14. Ручная проверка

1. Запустить Redis.
2. Запустить backend.
3. Запустить worker.
4. Запустить UI.
5. Выбрать DOCX.
6. Нажать `Estimate cost`.
7. Проверить, что цена появилась.
8. Убедиться, что OpenAI-запросов в worker нет.
9. Нажать `Translate`.
10. Проверить, что старый flow работает.

## 15. Что не делать

- Не отправлять текст в OpenAI во время оценки.
- Не переводить документ во время оценки.
- Не учитывать картинки в стоимости.
- Не считать размер DOCX как стоимость.
- Не менять контракт `/translate/`.
- Не переписывать Celery worker.
- Не менять download endpoint.
- Не добавлять сложный billing dashboard.
- Не добавлять batch processing в этой задаче.

## 16. Definition of Done

Доработка готова, если:

- UI показывает оценку стоимости до перевода;
- оценка работает без OpenAI-запроса;
- картинки не увеличивают стоимость;
- цена считается по тексту;
- бюджет `$10` отображается и проверяется;
- при превышении бюджета есть предупреждение;
- старый flow перевода не сломан;
- backend tests проходят;
- desktop ApiClient tests проходят.
