"""
Обобщённый движок рейтинга.

Идея: вместо захардкоженных 5 категорий (1 обращение, ЛК, канал, время,
% ошибок) с фиксированными весами — берём список категорий из таблицы
Supabase `rating_categories`, которую редактирует админ через интерфейс
("конструктор рейтинга"). Каждая категория описывает:

  key            — внутренний идентификатор ('c1', 'lk', 'my_metric', ...)
  label          — название для отображения
  source_column  — из какой колонки исходного Excel брать сырое значение
  weight         — вес в итоговой сумме баллов
  direction      — 'desc' (больше = лучше) или 'asc' (меньше = лучше)
  enabled        — учитывается ли сейчас в расчёте
  sort_order     — порядок отображения

Место внутри категории считается стандартным "спортивным" рангом
(равные значения делят место, следующее отличающееся значение получает
место со сдвигом на количество делящих — как обычный RANK() в Excel).

Это ЗАМЕНА захардкоженной логике из старой JS-версии (1 обращение ×3,
ЛК ×1.5 и т.д.) — та бизнес-специфика (тиры ЛК, Регион УК с урезанным
набором категорий, коэффициенты ЛГ) сюда ещё не перенесена. Это база,
на которую предполагается доращивать конкретные правила уже в Claude Code.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RatingCategory:
    key: str
    label: str
    source_column: str
    weight: float
    direction: str  # 'desc' | 'asc'
    enabled: bool = True
    sort_order: int = 0


@dataclass
class EmployeeScore:
    fio: str
    raw: dict  # исходные значения по всем категориям
    places: dict = field(default_factory=dict)   # key -> место
    scores: dict = field(default_factory=dict)   # key -> балл (место * вес)
    total_score: float = 0.0
    final_place: int | None = None
    is_na: bool = False
    tier: int | None = None          # ЛГ (1..10), см. services/ladder_groups.py
    coefficient: float | None = None  # коэффициент ЛГ (1.4..0.25)


def rank_standard(values: list[float], value: float, direction: str) -> int:
    """Спортивный ранг: 1,1,1,4,5,... (как RANK() в Excel/Google Sheets)."""
    if direction == "desc":
        better = sum(1 for v in values if v > value)
    else:
        better = sum(1 for v in values if v < value)
    return better + 1


def apply_category_ranks(results: list[EmployeeScore], categories: list[RatingCategory]) -> None:
    """Проставляет r.places[cat.key]/r.scores[cat.key] по обычному спортивному
    рангу для каждой категории. Общая часть, которую переиспользует как
    compute_ratings, так и services/weekly_rating.py (там она применяется
    только к категориям, кроме 'lk' — та считается через tier_lk.py)."""
    for cat in categories:
        values = [r.raw.get(cat.source_column) or 0 for r in results]
        for r in results:
            v = r.raw.get(cat.source_column) or 0
            place = rank_standard(values, v, cat.direction)
            r.places[cat.key] = place
            r.scores[cat.key] = place * cat.weight


def finalize_final_places(
    results: list[EmployeeScore],
    na_predicate=None,
    tie_break_field: str | None = None,
) -> None:
    """Считает total_score/is_na/final_place по уже проставленным
    r.places/r.scores. Общая часть для compute_ratings и
    services/weekly_rating.compute_weekly_rating.

    na_predicate: функция(row) -> bool — кого не учитывать в итоговом месте
                  (аналог "Н/О" в старой системе: новички, 0 продаж и т.п.)
    tie_break_field: поле для разбивки ничьих по сумме баллов (например,
                  "c1_sum" — у кого больше, тот выше при равенстве баллов)
    """
    for r in results:
        r.total_score = sum(r.scores.values())
        r.is_na = bool(na_predicate(r.raw)) if na_predicate else False

    evaluated = [r for r in results if not r.is_na]
    for r in results:
        if r.is_na:
            r.final_place = None
            continue
        place = 1
        for other in evaluated:
            if other is r:
                continue
            if other.total_score < r.total_score:
                place += 1
            elif (
                other.total_score == r.total_score
                and tie_break_field
                and (other.raw.get(tie_break_field) or 0) > (r.raw.get(tie_break_field) or 0)
            ):
                place += 1
        r.final_place = place


def compute_ratings(
    employees: list[dict],
    categories: list[RatingCategory],
    fio_field: str = "fio",
    na_predicate=None,
    tie_break_field: str | None = None,
) -> list[EmployeeScore]:
    """
    employees: список сырых строк из загруженного файла, например
        [{"fio": "Иванов И.И.", "c1_per_contact": 1234.5, "lk_per_contact": 0, ...}, ...]
    categories: активные категории (уже отфильтрованные по enabled, если нужно)
    na_predicate/tie_break_field: см. finalize_final_places.
    """
    active = [c for c in categories if c.enabled]
    results = [EmployeeScore(fio=row.get(fio_field, ""), raw=row) for row in employees]
    apply_category_ranks(results, active)
    finalize_final_places(results, na_predicate, tie_break_field)
    return results
