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
- `app/routers/categories.py` — CRUD для "конструктора рейтинга"
  (админ добавляет/убирает/меняет вес категорий через API)
- `app/routers/shifts.py` — загрузка отдельного файла "смены/часы"
  (заготовка, формат колонок нужно уточнить под реальный файл)
- `app/auth.py` — проверка Supabase-токена, подтягивание роли
  (admin/manager/supervisor) из `user_profiles`, как в старой версии
- `app/db/schema.sql` — новые таблицы (`rating_categories`, `shift_records`)
- `railway.json` / `Procfile` — конфиг для деплоя на Railway

## Что ЕЩЁ НЕ перенесено из старой JS-версии (следующие шаги)

Это специфичная бизнес-логика, которую нужно доперенести в Python,
уже опираясь на обобщённый движок как фундамент:

1. **Тиры ЛК** (тир A/Б/В по картам+конверсии) — особый случай, отдельно
   от generic-движка
2. **"Регион УК" и "Выходы на Пики"** — группы с урезанным набором категорий
3. **ЛГ-коэффициенты** (1.4…0.25 по тирам) и их перенос на следующую неделю
   для расчёта ЗП
4. **Двухэтапная ведомость ЗП** (аванс нед.1-2 / расчёт нед.3-5)
5. **Дашборды** (сводка, воронка новичков, каналы, аномалии) — сейчас
   вся эта логика в JS на фронтенде, для бэкенд-архитектуры разумно
   перенести на сервер как отдельные эндпоинты
6. **Формат ведомости под конкретного бухгалтера/руководителя**
7. **Формула для смен/часов** — уточнить: это ЗАМЕНА текущей ЗП
   (ставка+бонусы×коэфф.) или ДОПОЛНЕНИЕ к ней

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
