-- ============================================================
-- Новые таблицы для Python-бэкенда: конструктор рейтинга + смены
-- Вставить в Supabase → SQL Editor → Run
-- (основные таблицы kpi_uploads/kpi_ratings/user_profiles и т.д.
--  уже должны существовать из предыдущей версии на Supabase)
-- ============================================================

-- Конструктор рейтинга: админ определяет, какие категории считаются,
-- по какой колонке исходного файла и с каким весом.
create table if not exists rating_categories (
  id uuid primary key default gen_random_uuid(),
  key text not null unique,           -- внутренний идентификатор, напр. 'c1'
  label text not null,                -- как показывать в интерфейсе
  source_column text not null,        -- имя колонки в исходном Excel-файле
  weight numeric not null default 1,
  direction text not null check (direction in ('asc','desc')),
  enabled boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now()
);

alter table rating_categories enable row level security;

drop policy if exists "categories_select" on rating_categories;
create policy "categories_select" on rating_categories
  for select using (auth.role() = 'authenticated');

drop policy if exists "categories_write" on rating_categories;
create policy "categories_write" on rating_categories
  for all using (is_admin_or_manager()) with check (is_admin_or_manager());

-- Стартовый набор категорий = то, что было захардкожено в старой версии,
-- чтобы после переезда рейтинг считался так же, как раньше.
insert into rating_categories (key, label, source_column, weight, direction, sort_order)
values
  ('c1', '1 обращение', 'c1_per_contact', 3, 'desc', 1),
  ('lk', 'ЛК', 'lk_per_contact', 1.5, 'desc', 2),
  ('channel', 'Радио+ТВ / Интернет', 'ch_per_contact', 2.5, 'desc', 3),
  ('time', 'Время/контакт', 'time_per_contact', 1, 'asc', 4),
  ('errors', '% ошибок', 'errors_pct', 1, 'asc', 5)
on conflict (key) do nothing;

-- ============================================================
-- Супервайзер → канал (Радио+ТВ / Интернет)
-- ============================================================
-- Канал НЕЛЬЗЯ вычислить из сумм в файле (проверено на реальных данных —
-- эвристика "больше сумма" ошибается примерно в 40% случаев: у части
-- супервайзеров исторически больше денег идёт по чужому каналу). Поэтому
-- это настройка, которую вводит админ, а не вычисляемое поле. Если для
-- супервайзера ещё нет записи, при расчёте недели используется эвристика
-- как временная заглушка с пометкой в ответе API (channel_is_guessed).
create table if not exists supervisor_channels (
  supervisor text primary key,        -- название группы, как в файле (после "ГРУППА:")
  channel text not null check (channel in ('radio','inet')),
  updated_at timestamptz not null default now()
);

alter table supervisor_channels enable row level security;

drop policy if exists "supervisor_channels_select" on supervisor_channels;
create policy "supervisor_channels_select" on supervisor_channels
  for select using (auth.role() = 'authenticated');

drop policy if exists "supervisor_channels_write" on supervisor_channels;
create policy "supervisor_channels_write" on supervisor_channels
  for all using (is_admin_or_manager()) with check (is_admin_or_manager());

-- Известные на сегодня соответствия (сверено вручную с реальными данными).
insert into supervisor_channels (supervisor, channel) values
  ('Супервайзер - Курбанова Зарина Рахимджановна', 'inet'),
  ('Супервайзер - Пуць Екатерина Григорьевна', 'radio'),
  ('Супервайзер - Филипский Дмитрий Юрьевич', 'radio'),
  ('Супервайзер.- Клюйко Анатолий Анатольевич', 'radio'),
  ('Супервайзер - Гордиенко Виталий Валерьевич', 'radio'),
  ('Супервайзер - Лиштва Ольга Васильевна', 'radio'),
  ('Супервизор Галина Элина Альфредовна', 'radio')
on conflict (supervisor) do nothing;

-- ============================================================
-- Смены/часы — отдельный файл, привязан к периоду (upload_id)
-- ============================================================
create table if not exists shift_records (
  id uuid primary key default gen_random_uuid(),
  upload_id uuid not null references kpi_uploads(id) on delete cascade,
  fio text not null,
  hours_worked numeric,
  rate_per_shift numeric,
  amount numeric,              -- итоговая сумма за смены (hours * rate, либо своя формула)
  created_at timestamptz not null default now()
);

create index if not exists idx_shift_records_upload on shift_records(upload_id);
create index if not exists idx_shift_records_fio on shift_records(fio);

alter table shift_records enable row level security;

drop policy if exists "shifts_select" on shift_records;
create policy "shifts_select" on shift_records
  for select using (is_admin_or_manager());

drop policy if exists "shifts_write" on shift_records;
create policy "shifts_write" on shift_records
  for all using (is_admin_or_manager()) with check (is_admin_or_manager());

-- ============================================================
-- ЛГ-коэффициенты (1.4..0.25 по тирам 1..10) — настраиваемые
-- ============================================================
-- Раньше это был захардкоженный TIER_COEFFICIENTS в ladder_groups.py.
-- Теперь админ может их менять через /ladder-tiers, не трогая код.
create table if not exists ladder_tier_coefficients (
  tier_number int primary key check (tier_number between 1 and 10),
  coefficient numeric not null,
  updated_at timestamptz not null default now()
);

alter table ladder_tier_coefficients enable row level security;

drop policy if exists "ladder_tiers_select" on ladder_tier_coefficients;
create policy "ladder_tiers_select" on ladder_tier_coefficients
  for select using (auth.role() = 'authenticated');

drop policy if exists "ladder_tiers_write" on ladder_tier_coefficients;
create policy "ladder_tiers_write" on ladder_tier_coefficients
  for all using (is_admin_or_manager()) with check (is_admin_or_manager());

-- seed теми же значениями, что были захардкожены, чтобы после переезда
-- на настройку расчёт не изменился
insert into ladder_tier_coefficients (tier_number, coefficient) values
  (1,1.4),(2,1.3),(3,1.2),(4,1.1),(5,1.05),(6,1),(7,0.9),(8,0.75),(9,0.5),(10,0.25)
on conflict (tier_number) do nothing;

-- ============================================================
-- Штраф/премия за этап ведомости ЗП (не за неделю!)
-- ============================================================
-- Один раз на весь этап "Расчёт" (месяц, год, ФИО) — не привязан к
-- конкретной неделе/upload_id, в отличие от старой payroll_penalties
-- (та per-week и остаётся как есть). Применяется ТОЛЬКО к stage="2"
-- (недели 3-5), см. services/payroll.py.
create table if not exists payroll_stage_adjustments (
  id uuid primary key default gen_random_uuid(),
  month int not null check (month between 1 and 12),
  year int not null,
  fio text not null,
  penalty numeric not null default 0,
  premium numeric not null default 0,
  comment text,
  updated_at timestamptz not null default now(),
  unique(month, year, fio)
);

alter table payroll_stage_adjustments enable row level security;

drop policy if exists "stage_adj_select" on payroll_stage_adjustments;
create policy "stage_adj_select" on payroll_stage_adjustments
  for select using (is_admin_or_manager());

drop policy if exists "stage_adj_write" on payroll_stage_adjustments;
create policy "stage_adj_write" on payroll_stage_adjustments
  for all using (is_admin_or_manager()) with check (is_admin_or_manager());

-- ============================================================
-- Кол-во ошибок (сырое число, рядом с уже существующим errors_pct)
-- ============================================================
-- Только для информации в таблице — НЕ участвует в местах/расчёте
-- категории "% ошибок" (та как считалась по errors_pct, так и считается).
-- Необязательная колонка в исходном Excel — может быть null.
alter table kpi_ratings add column if not exists errors_count numeric;
