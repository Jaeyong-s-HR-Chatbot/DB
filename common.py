"""생성(generate.py)과 검증(validate.py)이 함께 쓰는 규칙 계산 함수.
숫자는 모두 rules/rules.json 에서 읽는다 (AI가 계산하지 않고 이 공식으로만 계산)."""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).parent
RULES = json.loads((ROOT / "rules" / "rules.json").read_text(encoding="utf-8"))
HOLIDAYS = {dt.date.fromisoformat(d) for d in RULES["holidays"]}

TODAY = dt.date(2026, 11, 9)           # 기준일
ATT_START = dt.date(2025, 11, 1)       # 출퇴근 기록 시작
ATT_END = dt.date(2026, 11, 6)         # 출퇴근·휴가 기록 끝 (기준일 직전 금요일)
PAY_MONTHS = [f"{y}-{m:02d}" for y, m in [(2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 11)]]


def d(s):
    return s if isinstance(s, dt.date) or s is None else dt.date.fromisoformat(s)


def is_workday(day):
    return day.weekday() < 5 and day not in HOLIDAYS


def workdays(start, end):
    out, cur = [], start
    while cur <= end:
        if is_workday(cur):
            out.append(cur)
        cur += dt.timedelta(days=1)
    return out


def month_start(ym):
    y, m = map(int, ym.split("-"))
    return dt.date(y, m, 1)


def month_end(ym):
    s = month_start(ym)
    nxt = dt.date(s.year + (s.month == 12), s.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def age_on(birth, on):
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def service_years(hire, on):
    return age_on(hire, on)


# ---------- 연차 ----------
def annual_grant(hire, year, asof):
    r = RULES["annual_leave"]
    if hire.year == year:  # 입사 첫해: 1개월 개근마다 1일
        months, cur = 0, hire
        while True:
            y, m = cur.year + (cur.month == 12), cur.month % 12 + 1
            cur = dt.date(y, m, min(hire.day, 28))
            if cur > asof or cur.year > year:
                break
            months += 1
        return min(r["first_year_max"], months * r["first_year_monthly"])
    n = year - hire.year  # 1월 1일 기준 근속연수(간이)
    return min(r["max"], r["base"] + (n - 1) // r["add_every_years"])


# ---------- 가족수당 ----------
def family_allowance(family_rows, ym, grade=None):
    """보수규정 시행세칙 제24조·별표 17. family_rows: 해당 직원의 가족 dict 목록, grade: 그 달 직급.
    월 1일 기준, 등록일이 그 이전인 부양가족만. 배우자 포함 4명까지(자녀는 넘어도 지급), 2급 이상은 자녀분만."""
    r = RULES["family_allowance"]
    ms = month_start(ym)
    spouse, kids, parents = 0, [], 0
    for f in family_rows:
        if f["is_dependent"] not in (True, "true", "True"):
            continue
        if d(f["added_date"]) >= ms:
            continue
        if f["death_date"] and d(f["death_date"]) < ms:
            continue
        b = d(f["birth_date"])
        if f["relation"] == "배우자":
            spouse = 1
        elif f["relation"] == "자녀" and age_on(b, ms) < r["child_age_limit"]:
            kids.append(b)
        elif f["relation"] in ("부", "배우자부") and age_on(b, ms) >= r["parent_age_min_male"]:
            parents += 1
        elif f["relation"] in ("모", "배우자모") and age_on(b, ms) >= r["parent_age_min_female"]:
            parents += 1
    total = sum(r["자녀"][min(i, 2)] for i, _ in enumerate(sorted(kids)))
    if grade is not None and int(grade) <= r["children_only_from_grade"]:
        return total
    paid_parents = max(0, min(spouse + parents, r["non_child_max"]) - spouse)
    return total + spouse * r["배우자"] + paid_parents * r["직계존속"]


# ---------- 급여 ----------
def base_pay(grade, hire, ms):
    return RULES["grades"][str(grade)]["base"] + RULES["step_increment"]["per_service_year"] * service_years(hire, ms)


def long_service_allowance(hire, ms):
    """근속연수 구간별 월 정액 (rules.long_service_allowance)."""
    n, amt = service_years(hire, ms), 0
    for years, won in RULES["long_service_allowance"]["brackets"]:
        if n >= years:
            amt = won
    return amt


def shift_allowance(pattern):
    return RULES["work_patterns"][pattern]["shift_allowance"]


def ordinary_wage(base, duty_allow, shift_allow, long_allow):
    """통상임금 = 매월 고정 지급 항목 합계."""
    return base + duty_allow + shift_allow + long_allow


def hourly_wage(ordinary):
    return ordinary / RULES["overtime"]["monthly_hours"]


def add_months(day, n):
    y, m = day.year + (day.month - 1 + n) // 12, (day.month - 1 + n) % 12 + 1
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(day.day, last))


def probation_end(hire):
    return add_months(hire, RULES["company"]["probation_months"]) - dt.timedelta(days=1)


def school_level(birth, on):
    """만 나이 기준 학교급 (간이)."""
    a = age_on(birth, on)
    if a < 0:
        return ""
    return "미취학" if a < 7 else "초" if a < 13 else "중" if a < 16 else "고" if a < 19 else "대" if a < 23 else ""


def first_workday(day):
    while not is_workday(day):
        day += dt.timedelta(days=1)
    return day


def won10(x):
    return int(x // 10 * 10)


def deductions(gross, meal):
    ins, tax = RULES["insurance"], RULES["income_tax"]
    taxable = gross - meal
    pension = won10(min(taxable, ins["pension_ceiling"]) * ins["national_pension"])
    health = won10(taxable * ins["health"])
    ltc = won10(health * ins["long_term_care_of_health"])
    emp_ins = won10(taxable * ins["employment"])
    rate = next(rt for cap, rt in tax["brackets"] if taxable <= cap)
    income_tax = won10(taxable * rate)
    local_tax = won10(income_tax * tax["local_tax_rate"])
    return dict(national_pension=pension, health_insurance=health, long_term_care=ltc,
                employment_insurance=emp_ins, income_tax=income_tax, local_tax=local_tax)


def welfare_allocation(hire, family_rows, year):
    r = RULES["welfare_points"]
    jan1 = dt.date(year, 1, 1)
    asof = max(jan1, hire)
    amt = r["base"] + min(r["service_max"], r["per_service_year"] * service_years(hire, asof))
    for f in family_rows:
        if d(f["added_date"]) > asof or (f["death_date"] and d(f["death_date"]) <= asof):
            continue
        if f["relation"] == "배우자":
            amt += r["spouse"]
        elif f["relation"] == "자녀" and age_on(d(f["birth_date"]), asof) < 20:
            amt += r["per_child"]
    if hire.year == year:  # 입사 연도는 남은 달만큼 비례
        amt = won10(amt * (13 - hire.month) / 12)
    return amt
