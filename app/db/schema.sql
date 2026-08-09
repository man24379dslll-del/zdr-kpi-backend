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
