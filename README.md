# ЗДР KPI — Python-бэкенд (каркас)

Стартовый каркас для переноса с Netlify+статический HTML на
GitHub + Railway + Python (FastAPI). База данных остаётся на Supabase —
это не меняется, меняется только то, где живёт и на чём работает логика
расчёта.

## Что уже есть

- `app/main.py` — FastAPI-приложение, роутеры, CORS, `/health`
- `app/services/rating_engine.py` — **обобщённый движок рейтинга**,
  управляется конфигурацией из таблицы `rating_categories` вместо
  захардкоженных 5 категорий. Покрыт тестами (`tests/test_rating_engine.py`).
- `app/services/tier_lk.py` — **тир ЛК (A/Б/В)**, точный перенос из
  старой JS-версии; определяет место сотрудника внутри категории "ЛК".
  Покрыт тестами (`tests/test_tier_lk.py`).
- `app/services/ladder_groups.py` — **ЛГ (лестничные группы, тиры 1..10)**,
  точный перенос из старой JS-версии; распределяет коэффициенты по
  итоговому месту в рейтинге, отдельно внутри каждого супервайзера.
  Коэффициенты настраиваются через `GET/PUT /ladder-tiers`
  (`ladder_tier_coefficients` в Supabase) — `TIER_COEFFICIENTS` в коде
  остался только запасным вариантом на случай пустой/недоступной
  таблицы, не единственным источником истины. Покрыт тестами
  (`tests/test_ladder_groups.py`).
- `app/services/salary.py` — **ЗП недели**: (недельная база + бонус075 +
  бонус2) × коэффициент ЛГ ПРОШЛОЙ недели. Применяется только к
  недельным периодам. Покрыт тестами (`tests/test_salary.py`).
- `app/services/periods.py` — поиск "предыдущего периода" по
  `период_label` (сортировка по `месяц*10+неделя` для недельных, по
  строке для дневных) — используется формулой ЗП. Покрыт тестами
  (`tests/test_periods.py`).
- `app/services/weekly_rating.py` — **связывает всё в один пайплайн**:
  категории конструктора → тир ЛК → итоговое место → ЛГ. Используется
  эндпоинтом `POST /ratings/compute` (`app/routers/ratings.py`) — принимает
  xlsx + `period_label` + `weeks_in_month`, категории берёт из
  `rating_categories`, считает рейтинг за неделю и ЗП (для недельных
  периодов), пишет результат в `kpi_uploads`/`kpi_ratings`
  (`app/services/ratings_repository.py`, схема этих таблиц уже есть в
  Supabase) и возвращает посчитанные строки вместе с `upload_id`.
- `app/services/excel_parsing.py` — разбор реального xlsx (точные
  заголовки колонок, группы супервайзеров по строкам "ГРУППА: ...",
  отказоустойчивость к отсутствующим "кол-во"-колонкам, выбор канала
  Радио+ТВ/Интернет по `supervisor_channels` с эвристикой-заглушкой как
  fallback, и разбиение "операторы без супервизора" на Регион УК/Выходы
  на Пики). Покрыто тестом на реалистичном примере (`tests/test_weekly_rating.py`).
- `app/services/group_naming.py` — Регион УК / Выходы на Пики: урезанный
  набор категорий (c1/lk/time) для Регион УК в `weekly_rating.py`,
  человекочитаемое название группы для API. Покрыт тестами
  (`tests/test_group_naming.py`, `tests/test_region_uk.py`).
- `app/services/payroll.py` — двухэтапная ведомость ЗП (аванс нед.1-2 /
  расчёт нед.3-5), эндпоинт `GET /payroll/two-stage`; штраф/премию за
  этап (`payroll_stage_adjustments` — один раз на (месяц, год, ФИО), не
  по неделям, только для этапа "Расчёт") правит `PUT /payroll/stage-adjustment`.
  Подключено к `static/index.html` (панель "💰 Ведомость ЗП"). Покрыт
  тестами (`tests/test_payroll.py`).
- `app/services/dashboards.py` — 4 дашборда (сводка, воронка новичков,
  каналы, аномалии), эндпоинты `GET /dashboards/*`. Покрыт тестами
  (`tests/test_dashboards.py`).
- `app/routers/categories.py` — CRUD для "конструктора рейтинга"
  (админ добавляет/убирает/меняет вес категорий через API)
- `app/routers/supervisor_channels.py` — CRUD для соответствия
  супервайзер → канал (Радио+ТВ/Интернет)
- `app/routers/ladder_tiers.py` — чтение/изменение ЛГ-коэффициентов
  по тирам (см. выше)
- `app/routers/shifts.py` — загрузка отдельного файла "смены/часы"
  (заготовка, формат колонок нужно уточнить под реальный файл)
- `app/auth.py` — проверка Supabase-токена, подтягивание роли
  (admin/manager/supervisor) из `user_profiles`, как в старой версии
- `app/db/schema.sql` — новые таблицы (`rating_categories`, `shift_records`,
  `supervisor_channels`, `ladder_tier_coefficients`, `payroll_stage_adjustments`)
- `railway.json` / `Procfile` — конфиг для деплоя на Railway

## Что ЕЩЁ НЕ перенесено из старой JS-версии (следующие шаги)

Это специфичная бизнес-логика, которую нужно доперенести в Python,
уже опираясь на обобщённый движок как фундамент:

1. ~~**Тиры ЛК** (тир A/Б/В по картам+конверсии) — особый случай, отдельно
   от generic-движка~~ — перенесено, см. `app/services/tier_lk.py`
2. ~~**"Регион УК" и "Выходы на Пики"** — группы с урезанным набором
   категорий~~ — перенесено, см. `app/services/group_naming.py`
3. ~~**ЛГ-коэффициенты** (1.4…0.25 по тирам) и их перенос на следующую
   неделю для расчёта ЗП~~ — перенесено, см. `app/services/ladder_groups.py`
   + `app/services/salary.py` + `app/services/periods.py` (поиск
   "предыдущего периода" по `месяц*10+неделя`, корректно работает через
   границу месяца; год в `period_label` не участвует — осознанное
   ограничение самой старой системы)
4. ~~**Двухэтапная ведомость ЗП** (аванс нед.1-2 / расчёт нед.3-5)~~ —
   перенесено, см. `app/services/payroll.py`. Пока не подключено:
   `payment_requisites` (должность/реквизиты) — отдельная фича, TODO
5. ~~**Дашборды** (сводка, воронка новичков, каналы, аномалии)~~ —
   перенесено, см. `app/services/dashboards.py`
6. **Формат ведомости под конкретного бухгалтера/руководителя**
7. **Формула для смен/часов** — уточнить: это ЗАМЕНА текущей ЗП
   (ставка+бонусы×коэфф.) или ДОПОЛНЕНИЕ к ней. Сам формат файла
   ("Часы_на_линии_...") уже известен, загрузка/хранение (без формулы)
   — следующий шаг

Рекомендую переносить по одному пункту за раз, с тестами — так же,
как мы строили движок рейтинга.

## Локальный запуск

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# впишите в .env реальные SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY,
# SUPABASE_SERVICE_KEY (Settings → API в Supabase)

uvicorn app.main:app --reload
# документация API: http://localhost:8000/docs
```

## Тесты

```bash
pytest tests/ -v
```

## Деплой

### 1. GitHub

```bash
git init
git add .
git commit -m "Initial backend scaffold"
gh repo create zdr-kpi-backend --private --source=. --push
# или вручную: создать репозиторий на github.com, затем
git remote add origin https://github.com/ВАШ-АККАУНТ/zdr-kpi-backend.git
git push -u origin main
```

### 2. Railway

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Выбрать репозиторий `zdr-kpi-backend`
3. В **Variables** добавить те же переменные, что в `.env`:
   `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_KEY`, `CORS_ORIGINS`
4. Railway сам подставит `PORT` и задеплоит по `railway.json`
5. После первого деплоя получите постоянный адрес вида
   `https://zdr-kpi-backend-production.up.railway.app`

### 3. SQL в Supabase

Выполнить `app/db/schema.sql` в SQL Editor (добавляет `rating_categories`
и `shift_records` к уже существующим таблицам).

## Дальше — через Claude Code

Откройте эту папку в Claude Code (`claude` в терминале внутри папки
проекта, либо через десктопное приложение → вкладка Code) и попросите
продолжить перенос логики по пунктам из раздела выше — так будет
значительно быстрее, чем через чат: Claude Code видит весь репозиторий
сразу, может гонять тесты после каждого шага и коммитить постепенно.
