"""누리철도㈜ 가상 임직원 데이터 생성 → data/hr/*.csv (팀 데이터 기준서 CSV 14종)

실행: .venv/bin/python generate.py
- 800명(사번 E1001~E1800), 전원 정규직, 기준일 2026-11-09
- 시연 인물 10명은 사건(결혼 예정·출산·배우자 출산·부친상·육아휴직·정년 임박·신입·인사담당)을 고정
- 숫자 규칙은 rules/rules.json 하나에서 읽음 (validate.py도 같은 파일 사용)
- 고용형태·복리후생 금액은 코레일 2025년 공시 형식(rules.json의 employment_types, welfare_korail)
"""
import csv
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

from faker import Faker

from common import (ATT_END, ATT_START, PAY_MONTHS, RULES, TODAY, add_months, age_on, annual_grant, base_pay,
                    deductions, family_allowance, hourly_wage, is_workday, long_service_allowance, month_end,
                    month_start, ordinary_wage, probation_end, school_level, service_years, shift_allowance,
                    welfare_allocation, won10, workdays)

SEED = 42
N_EMPLOYEES = 800
TEST_PASSWORD = "Test1234!"  # 로컬 개발용 테스트 계정 비밀번호 (README 참고)
ET = RULES["employment_types"]          # 코레일 고용형태 3종
REGULAR = ET["regular"]                 # 이번 범위는 정규직만 (팀 결정)
CO = RULES["company"]
WK = RULES["welfare_korail"]

random.seed(SEED)
Faker.seed(SEED)
fake = Faker("ko_KR")
OUT = Path(__file__).parent / "data" / "hr"
D = dt.date
DAY = dt.timedelta(days=1)

# ---------------------------------------------------------------- 조직
DEPTS = [  # id, 이름, 상위, 종류, 직군, 인원(정원), 근무형태, 근무지 — 팀 노션 "부서 구성"(2026-11-10)
    ("D10", "운전본부", None, "본부", "운전·승무", 0, "일근", "본사"),
    ("D11", "운전계획팀", "D10", "팀", "운전·승무", 8, "일근", "본사"),
    ("D12", "종합관제팀", "D10", "팀", "운전·승무", 32, "교번근무", "본사"),
    ("D13", "승무1사업소", "D10", "사업소", "운전·승무", 70, "교번근무", "수도권"),
    ("D14", "승무2사업소", "D10", "사업소", "운전·승무", 70, "교번근무", "충청권"),
    ("D15", "승무3사업소", "D10", "사업소", "운전·승무", 60, "교번근무", "영남권"),
    ("D20", "영업본부", None, "본부", "역무", 0, "일근", "본사"),
    ("D21", "영업계획팀", "D20", "팀", "역무", 8, "일근", "본사"),
    ("D22", "고객서비스팀", "D20", "팀", "역무", 12, "일근", "본사"),
    ("D23", "역무1센터", "D20", "센터", "역무", 60, "교대근무", "수도권"),
    ("D24", "역무2센터", "D20", "센터", "역무", 60, "교대근무", "충청권"),
    ("D25", "역무3센터", "D20", "센터", "역무", 60, "교대근무", "영남권"),
    ("D30", "차량본부", None, "본부", "차량정비", 0, "일근", "본사"),
    ("D31", "차량계획팀", "D30", "팀", "차량정비", 8, "일근", "본사"),
    ("D32", "차량1사업소", "D30", "사업소", "차량정비", 45, "교대근무", "수도권"),
    ("D33", "차량2사업소", "D30", "사업소", "차량정비", 45, "교대근무", "영남권"),
    ("D34", "중정비팀", "D30", "팀", "차량정비", 22, "일근", "충청권"),
    ("D40", "기술본부", None, "본부", "시설·전기", 0, "일근", "본사"),
    ("D41", "기술계획팀", "D40", "팀", "시설·전기", 6, "일근", "본사"),
    ("D42", "궤도팀", "D40", "팀", "시설·전기", 28, "일근", "본사"),
    ("D43", "건축설비팀", "D40", "팀", "시설·전기", 20, "일근", "본사"),
    ("D44", "전력팀", "D40", "팀", "시설·전기", 24, "일근", "본사"),
    ("D45", "신호팀", "D40", "팀", "시설·전기", 22, "일근", "본사"),
    ("D46", "통신팀", "D40", "팀", "시설·전기", 20, "일근", "본사"),
    ("D50", "경영지원본부", None, "본부", "사무", 0, "일근", "본사"),
    ("D51", "비서실", "D50", "실", "사무", 5, "일근", "본사"),
    ("D52", "기획팀", "D50", "팀", "사무", 8, "일근", "본사"),
    ("D53", "예산팀", "D50", "팀", "사무", 6, "일근", "본사"),
    ("D54", "인사팀", "D50", "팀", "사무", 5, "일근", "본사"),
    ("D55", "교육훈련팀", "D50", "팀", "사무", 10, "일근", "본사"),
    ("D56", "재무팀", "D50", "팀", "사무", 9, "일근", "본사"),
    ("D57", "회계팀", "D50", "팀", "사무", 7, "일근", "본사"),
    ("D58", "총무팀", "D50", "팀", "사무", 13, "일근", "본사"),
    ("D59", "계약팀", "D50", "팀", "사무", 7, "일근", "본사"),
    ("D60", "IT팀", "D50", "팀", "사무", 14, "일근", "본사"),
    ("D61", "안전총괄팀", "D50", "팀", "사무", 10, "일근", "본사"),
    ("D62", "재난안전팀", "D50", "팀", "사무", 8, "일근", "본사"),
    ("D63", "감사팀", "D50", "팀", "사무", 6, "일근", "본사"),
    ("D64", "홍보팀", "D50", "팀", "사무", 8, "일근", "본사"),
    ("D65", "법무팀", "D50", "팀", "사무", 4, "일근", "본사"),
]
DEPT = {r[0]: dict(dept_id=r[0], dept_name=r[1], parent_id=r[2], dept_type=r[3], job_family=r[4], w=r[5],
                   pattern=r[6], site=r[7]) for r in DEPTS}
assert sum(v["w"] for v in DEPT.values()) == N_EMPLOYEES
TEAMS = [k for k, v in DEPT.items() if v["w"] > 0]
PLAN_TEAM = {"D10": "D11", "D20": "D21", "D30": "D31", "D40": "D41", "D50": "D52"}  # 본부장이 소속되는 팀
HR_DEPT = "D54"                     # 인사팀 → hr_admin 권한
SHIFT_PATTERNS = ("교대근무", "교번근무")
PROMO_GAP = {5: (3, 5), 4: (4, 6), 3: (5, 8), 2: (8, 14)}  # 1~5급(사원=5급), 부장 승진은 드묾

# ---------------------------------------------------------------- 시연 인물
PERSONAS = [
    dict(key="P1", name="이서준", gender="M", birth=D(1997, 5, 14), hire=D(2023, 1, 1), dept="D45", grade=4,
         scenario="결혼 예정(2026-12-12) — 결혼 휴가·경조금·가족수당 변경 질문"),
    dict(key="P2", name="박지현", gender="F", birth=D(1991, 2, 3), hire=D(2017, 3, 1), dept="D22", grade=3,
         scenario="출산휴가 중(2026-10-19~2027-01-16, 출산 예정 11/18) — 육아휴직·출산 지원 질문"),
    dict(key="P3", name="최도윤", gender="M", birth=D(1990, 9, 21), hire=D(2016, 1, 1), dept="D32", grade=3,
         scenario="둘째 출생(2026-08-14) — 배우자출산휴가 20일 사용, 9월부터 가족수당 증가"),
    dict(key="P4", name="정하은", gender="F", birth=D(1985, 12, 2), hire=D(2011, 1, 1), dept="D56", grade=2,
         scenario="부친상(2026-06-08) — 청원휴가 5일, 조위금 질문"),
    dict(key="P5", name="강민재", gender="M", birth=D(1988, 7, 19), hire=D(2015, 7, 1), dept="D60", grade=3,
         scenario="육아휴직 중(2026-07-01~2027-06-30) — 복직·휴직 중 급여 질문"),
    dict(key="P6", name="윤영호", gender="M", birth=D(1968, 3, 25), hire=D(1994, 1, 1), dept="D11", grade=1,
         scenario="운전본부장, 근속 32년·정년 2년 전(2028-03 만 60세) — 퇴직금·임금피크·연차 25일 질문"),
    dict(key="P7", name="한소율", gender="F", birth=D(2001, 8, 30), hire=D(2026, 3, 1), dept="D23", grade=5,
         scenario="2026-03 신입(수습 2개월 종료) — 1년 미만 월차, 복지포인트 비례 배정 질문"),
    dict(key="P8", name="김수아", gender="F", birth=D(1989, 4, 11), hire=D(2013, 1, 1), dept="D54", grade=2,
         scenario="인사팀 담당자(hr_admin) — 관리자 화면·집계 시연"),
    dict(key="P9", name="임태윤", gender="M", birth=D(1993, 6, 2), hire=D(2019, 3, 1), dept="D13", grade=4,
         scenario="배우자 출산 예정(2026-12-03, 첫째) · 승무1사업소 교번근무 — 배우자출산휴가·출산축하금·교번수당 질문"),
    dict(key="P10", name="서지호", gender="M", birth=D(1987, 10, 9), hire=D(2014, 1, 1), dept="D44", grade=3,
         scenario="장기 출장 중(광역시, 2026-10-12~2026-12-11, 61일) — 일비 감액·숙박비·출장 중 초과근무 질문"),
]


def rand_date(a, b):
    return a + dt.timedelta(days=random.randint(0, max(0, (b - a).days)))


def add_years(day, n):
    try:
        return day.replace(year=day.year + n)
    except ValueError:
        return day.replace(year=day.year + n, day=28)


def first_of_next_month(day):
    return D(day.year + (day.month == 12), day.month % 12 + 1, 1)


def next_workday(day):
    while not is_workday(day):
        day += DAY
    return day


def take_workdays(start, n):
    out, cur = [], next_workday(start)
    while len(out) < n:
        if is_workday(cur):
            out.append(cur)
        cur += DAY
    return out


# ---------------------------------------------------------------- 직원 기본
employees, careers, families, leaves, attendance, payroll, welfare, training, users = [], [], [], [], [], [], [], [], []
fam_seq, leave_seq = [0], [0]


def new_employee(**kw):
    gender = kw.get("gender") or random.choice("MF" if random.random() < 0.5 else "MMF")
    if "hire" in kw:
        hire, birth = kw["hire"], kw["birth"]
    else:
        age_now = random.choices(range(24, 60), weights=[3 if a < 35 else 2 if a < 50 else 1 for a in range(24, 60)])[0]
        age_hire = random.randint(23, min(32, age_now))
        hy = TODAY.year - (age_now - age_hire)
        hm = random.randint(1, 10 if hy == TODAY.year else 12)
        hire = D(hy, hm, 1)
        birth = rand_date(D(hy - age_hire - 1, hm, 2), D(hy - age_hire, hm, 1) - DAY)
        if age_on(birth, TODAY) >= RULES["company"]["retire_age"]:
            birth = add_years(birth, 1)
    name = kw.get("name") or (fake.last_name() + (fake.first_name_male() if gender == "M" else fake.first_name_female()))
    e = dict(name=name, gender=gender, birth=birth, hire=hire, persona=kw.get("key"), scenario=kw.get("scenario"),
             dept=kw["dept"], target_grade=kw.get("grade"),
             employment_type=REGULAR, contract_end=None, retire_date=None, retire_reason=None,
             absences=[], events=[], duty="팀원", perf_grade=random.choices("SABC", [10, 30, 50, 10])[0])
    # 이번 범위는 정규직만 (팀 결정 2026-11-10)
    e["job_family"] = DEPT[e["dept"]]["job_family"]
    e["pattern_changes"] = []       # (날짜, 이전, 이후)
    e["work_pattern"] = DEPT[e["dept"]]["pattern"]   # 근무형태는 부서로 정해짐
    e["trip_days"] = set()
    employees.append(e)
    return e


DEPT_POOL = [k for k in TEAMS for _ in range(DEPT[k]["w"])]
for p in PERSONAS:
    DEPT_POOL.remove(p["dept"])
random.shuffle(DEPT_POOL)
for p in PERSONAS:
    new_employee(**p)
while len(employees) < N_EMPLOYEES:
    new_employee(dept=DEPT_POOL.pop())

# 사번: 입사일 순
employees.sort(key=lambda e: (e["hire"], e["birth"]))
for i, e in enumerate(employees):
    e["emp_id"] = f"{CO['emp_id_prefix']}{CO['emp_id_start'] + i}"
BY_KEY = {e["persona"]: e for e in employees if e["persona"]}


# ---------------------------------------------------------------- 경력(승진·전보)
def build_career(e):
    rows = []
    start_grade = 5
    if e["target_grade"] is None and e["employment_type"] == REGULAR:
        age_hire = age_on(e["birth"], e["hire"])
        start_grade = random.choices([5, 4, 3], [85, 10, 5 if age_hire >= 30 else 0])[0]
    first_dept = e["dept"]
    moved = None
    if not e["persona"] and random.random() < 0.35 and e["hire"] < D(2024, 1, 1):
        same_kind = [t for t in TEAMS if DEPT[t]["job_family"] == DEPT[e["dept"]]["job_family"] and t != e["dept"]]
        if same_kind:
            first_dept = random.choice(same_kind)
            moved = D(random.randint(e["hire"].year + 1, 2026), 1, 1)
    rows.append(dict(change_date=e["hire"], change_type="입사", from_dept=None, to_dept=first_dept, from_grade=None,
                     to_grade=start_grade, absence_type=None, end_date=None, note=e["employment_type"]))
    grade, cur = start_grade, e["hire"]
    if e["employment_type"] == REGULAR:
        if e["target_grade"] is not None:  # 시연 인물: 목표 직급까지 고르게 승진
            steps = start_grade - e["target_grade"]
            span = (D(2026, 1, 1).year - e["hire"].year)
            for k in range(1, steps + 1):
                y = e["hire"].year + max(1, round(span * k / steps))
                rows.append(dict(change_date=D(min(y, 2026), 1, 1), change_type="승진", from_dept=None, to_dept=None,
                                 from_grade=grade, to_grade=grade - 1, absence_type=None, end_date=None, note=None))
                grade -= 1
        else:
            while grade > 1:
                lo, hi = PROMO_GAP[grade]
                nxt = D(cur.year + random.randint(lo, hi), 1, 1)
                if nxt > TODAY:
                    break
                rows.append(dict(change_date=nxt, change_type="승진", from_dept=None, to_dept=None, from_grade=grade,
                                 to_grade=grade - 1, absence_type=None, end_date=None, note=None))
                grade, cur = grade - 1, nxt
    if moved:
        rows.append(dict(change_date=moved, change_type="전보", from_dept=first_dept, to_dept=e["dept"], from_grade=None,
                         to_grade=None, absence_type=None, end_date=None, note=None))
    rows.sort(key=lambda r: (r["change_date"], r["change_type"] != "입사"))
    e["career"], e["grade"] = rows, grade


for e in employees:
    build_career(e)


def grade_at(e, day):
    g = None
    for r in e["career"]:
        if r["change_date"] <= day and r["to_grade"] is not None:
            g = r["to_grade"]
    return g


# ---------------------------------------------------------------- 가족
def add_family(e, relation, gender, birth, added, dependent, death=None, lives=False):
    fam_seq[0] += 1
    f = dict(family_id=fam_seq[0], emp_id=e["emp_id"], relation=relation, name=None, gender=gender, birth_date=birth,
             is_dependent=dependent, lives_together=lives, added_date=added, death_date=death)
    if relation in ("자녀", "형제자매") or relation.startswith("배우자") or relation in ("부", "모", "조부", "조모"):
        last = e["name"][0] if relation in ("부", "조부", "자녀", "형제자매") and e["gender"] == "M" else fake.last_name()
        if relation == "형제자매":
            last = e["name"][0]
        if relation == "자녀":
            last = e["name"][0] if e["gender"] == "M" else e["spouse_last"]
        f["name"] = last + (fake.first_name_male() if gender == "M" else fake.first_name_female())
    e.setdefault("family", []).append(f)
    return f


def build_family(e):
    e["family"] = []
    age = age_on(e["birth"], TODAY)
    p = e["persona"]
    spouse_g = "F" if e["gender"] == "M" else "M"
    e["spouse_last"] = fake.last_name()
    # 부모
    for rel, g, gap in (("부", "M", (27, 35)), ("모", "F", (24, 32))):
        b = add_years(e["birth"], -random.randint(*gap)) - dt.timedelta(days=random.randint(0, 300))
        pa = age_on(b, TODAY)
        if p == "P4" and rel == "부":
            b = D(1956, 3, 10)
            add_family(e, rel, g, b, e["hire"], False, death=D(2026, 6, 8))
            e["events"].append(("death", D(2026, 6, 8), e["family"][-1]))
            continue
        if p == "P6":
            continue  # 부모 모두 작고(기록 없음)
        alive = random.random() < (0.97 if pa < 75 else 0.75 if pa < 85 else 0.35)
        if alive:
            dep = pa >= 60 and random.random() < 0.25
            add_family(e, rel, g, b, e["hire"], dep, lives=dep)
    # 조부모(젊은 직원만)
    if age < 36 and not p:
        for rel, g in (("조부", "M"), ("조모", "F")):
            if random.random() < 0.45:
                b = add_years(e["birth"], -random.randint(52, 64))
                add_family(e, rel, g, b, e["hire"], False)
    # 결혼
    married_date = None
    if p in ("P2", "P3", "P4", "P5", "P6", "P8", "P9", "P10"):
        married_date = {"P2": D(2019, 5, 18), "P3": D(2018, 10, 13), "P4": D(2012, 4, 21), "P5": D(2020, 9, 26),
                        "P6": D(1994, 10, 15), "P8": D(2016, 11, 5), "P9": D(2023, 5, 20), "P10": D(2015, 4, 11)}[p]
    elif not p and age >= 27:
        pm = 0.2 if age < 30 else 0.55 if age < 35 else 0.78 if age < 42 else 0.86
        if random.random() < pm:
            married_date = rand_date(add_years(e["birth"], 27), min(add_years(e["birth"], min(age, 37)), TODAY - 20 * DAY))
    e["married_date"] = married_date
    if married_date:
        sb = add_years(e["birth"], random.randint(-3, 3)) + dt.timedelta(days=random.randint(-150, 150))
        add_family(e, "배우자", spouse_g, sb, max(married_date, e["hire"]), random.random() < 0.25, lives=True)
        if D(2025, 1, 1) <= married_date <= ATT_END - 7 * DAY and married_date >= e["hire"]:
            e["events"].append(("marriage", married_date, e["family"][-1]))
        # 배우자 부모
        for rel, g in (("배우자부", "M"), ("배우자모", "F")):
            b = add_years(sb, -random.randint(25, 33))
            if age_on(b, TODAY) < 88 and random.random() < 0.8:
                add_family(e, rel, g, b, max(married_date, e["hire"]), False)
        # 자녀
        if p:
            kids = {"P2": [D(2022, 4, 7)], "P3": [D(2021, 6, 30), D(2026, 8, 14)], "P4": [D(2015, 3, 3), D(2018, 9, 9)],
                    "P5": [D(2024, 3, 2)], "P6": [D(1995, 12, 1), D(1998, 6, 20)], "P8": [D(2019, 2, 14)],
                    "P9": [], "P10": [D(2017, 4, 2)]}[p]
        else:
            n = random.choices([0, 1, 2, 3], [25, 35, 33, 7])[0]
            kids, cur = [], married_date
            mom_birth = e["birth"] if e["gender"] == "F" else sb
            for _ in range(n):
                cur = cur + dt.timedelta(days=random.randint(365, 365 * 3))
                if cur > TODAY - 30 * DAY or age_on(mom_birth, cur) > 42:
                    break
                kids.append(cur)
            # 최근 출산 사건 추가 (기록 기간 안에서 출산·육아휴직 사례가 생기도록)
            if 28 <= age <= 40 and random.random() < 0.07:
                nb = rand_date(max(D(2025, 2, 1), e["hire"] + 60 * DAY), D(2026, 9, 30))
                if all(abs((nb - k).days) > 400 for k in kids) and nb > married_date + 300 * DAY:
                    kids.append(nb)
        for kb in sorted(kids):
            f = add_family(e, "자녀", random.choice("MF"), kb, max(kb, e["hire"]), age_on(kb, TODAY) < 20,
                           lives=age_on(kb, TODAY) < 25)
            if D(2025, 1, 1) <= kb <= ATT_END and kb >= e["hire"] + 30 * DAY:
                e["events"].append(("birth", kb, f))
    # 기록 기간 중 사망 사건(시연 인물 제외)
    if not p:
        for f in list(e["family"]):
            pr = {"부": 0.02, "모": 0.015, "배우자부": 0.02, "배우자모": 0.015, "조부": 0.08, "조모": 0.07}.get(f["relation"])
            if pr and random.random() < pr:
                lo = max(D(2025, 1, 5), e["hire"] + 30 * DAY, f["added_date"] + DAY)
                if lo < ATT_END - 14 * DAY:
                    f["death_date"] = rand_date(lo, ATT_END - 14 * DAY)
                    e["events"].append(("death", f["death_date"], f))


    # 형제자매 (팀 기준서 관계). 경조금·수당 대상은 아님
    for _ in range(random.choices([0, 1, 2, 3], [20, 45, 28, 7])[0]):
        sb = add_years(e["birth"], random.randint(-8, 8)) + dt.timedelta(days=random.randint(-150, 150))
        if sb != e["birth"]:
            add_family(e, "형제자매", random.choice("MF"), sb, e["hire"], False)
    # 출산 예정 자녀 (시연): 출생 전이라 수당·포인트 대상 아님
    due = {"P2": D(2026, 11, 18), "P9": D(2026, 12, 3)}.get(p)
    if due:
        f = add_family(e, "자녀", random.choice("MF"), due, due, False)
        f["name"], f["expected"] = "출산예정", True


for e in employees:
    build_family(e)


# ---------------------------------------------------------------- 휴직 사건
def add_absence(e, start, end, kind, child=None):
    e["absences"].append((start, end, kind))
    e.setdefault("absence_child", {})[start] = child["family_id"] if child else None
    e["career"].append(dict(change_date=start, change_type="휴직", from_dept=None, to_dept=None, from_grade=None,
                            to_grade=None, absence_type=kind, end_date=end, note=None))
    if end < TODAY:
        e["career"].append(dict(change_date=end + DAY, change_type="복직", from_dept=None, to_dept=None, from_grade=None,
                                to_grade=None, absence_type=None, end_date=None, note=None))


def in_absence(e, day):
    return any(s <= day <= t for s, t, _ in e["absences"])


for e in employees:
    e["all_events"] = list(e["events"])  # 지급 내역용: 휴직과 겹쳐도 경조금은 지급되므로 걸러내기 전에 복사
for e in employees:
    p = e["persona"]
    if p == "P5":
        kid = [f for f in e["family"] if f["relation"] == "자녀"][-1]
        add_absence(e, D(2026, 7, 1), D(2027, 6, 30), "육아휴직", kid)
        continue
    if p:
        continue
    for kind, day, f in e["events"]:
        if kind != "birth":
            continue
        if e["gender"] == "F":
            mat_end = day + dt.timedelta(days=RULES["maternity_leave"]["days"] - RULES["maternity_leave"]["before_birth_days"] - 1)
            if random.random() < 0.6:
                s = first_of_next_month(mat_end)
                months = random.choice([6, 12])
                end = D(s.year + (s.month - 1 + months) // 12, (s.month - 1 + months) % 12 + 1, 1) - DAY
                add_absence(e, s, end, "육아휴직", f)
        elif random.random() < 0.15:
            s = first_of_next_month(day + dt.timedelta(days=random.randint(60, 150)))
            months = random.choice([3, 6, 12])
            end = D(s.year + (s.month - 1 + months) // 12, (s.month - 1 + months) % 12 + 1, 1) - DAY
            add_absence(e, s, end, "육아휴직", f)
    if not e["absences"] and random.random() < 0.012:
        s = D(random.choice([2025, 2026]), random.randint(1, 9), 1)
        if s > e["hire"] + 365 * DAY:
            kind = random.choices(["질병휴직", "업무상재해휴직", "가족돌봄휴직"], [70, 15, 15])[0]
            end = D(s.year + (s.month + 3) // 12, (s.month + 3) % 12 + 1, 1) - DAY
            add_absence(e, s, end, kind)
    # 휴직 기간과 겹치는 사건은 제외(휴가와 휴직이 겹치지 않게)
    e["events"] = [ev for ev in e["events"] if not in_absence(e, ev[1])]

# 퇴직자: 기록 기간에 사건·휴직이 없는 직원 중
pool = [e for e in employees if not e["persona"] and not e["events"] and not e["absences"]
        and e["hire"] < D(2024, 1, 1)]
for e in random.sample(pool, 14):
    e["retire_date"] = month_end(f"2026-{random.randint(1, 9):02d}") if random.random() < 0.8 else D(2025, 12, 31)
    e["retire_reason"] = "정년퇴직" if age_on(e["birth"], e["retire_date"]) >= 57 else "의원퇴직"
    e["career"].append(dict(change_date=e["retire_date"], change_type="퇴직", from_dept=None, to_dept=None, from_grade=None,
                            to_grade=None, absence_type=None, end_date=None, note=e["retire_reason"]))
for e in employees:
    e["career"].sort(key=lambda r: (r["change_date"], r["change_type"] != "입사"))
    e["status"] = "퇴직" if e["retire_date"] and e["retire_date"] < TODAY else "휴직" if in_absence(e, TODAY) else "재직"

# ---------------------------------------------------------------- 직책(본부장·팀장)
for dept_id, dv in DEPT.items():
    if dv["dept_type"] == "본부":
        continue
    cands = [e for e in employees if e["dept"] == dept_id and e["status"] == "재직" and not e["persona"]]
    if cands:
        head = min(cands, key=lambda e: (e["grade"], e["hire"]))
        head["duty"] = "팀장"
        dv["head_emp_id"] = head["emp_id"]
for dept_id, dv in DEPT.items():
    if dv["dept_type"] != "본부":
        continue
    if dept_id == "D10":
        head = BY_KEY["P6"]
    else:
        team = PLAN_TEAM[dept_id]
        cands = [e for e in employees if e["dept"] == team and e["status"] == "재직" and e["duty"] == "팀원"
                 and not e["persona"]]
        head = min(cands, key=lambda e: (e["grade"], e["hire"]))
    head["duty"] = "본부장"   # 소속은 계획팀 그대로 (부서별 정원 유지)
    dv["head_emp_id"] = head["emp_id"]
for e in employees:
    e["position"] = RULES["grades"][str(e["grade"])]["position"]


# ---------------------------------------------------------------- 휴가
def add_leave(e, ltype, days_list, n_days=None, event_type=None, fam=None, start=None, end=None, min_approved=None):
    leave_seq[0] += 1
    s = start or days_list[0]
    t = end or days_list[-1]
    approved = s - dt.timedelta(days=random.randint(1, 10))
    if min_approved and approved < min_approved:
        approved = min_approved  # 사망 등 갑작스러운 사건: 사건일 전에 승인될 수 없음
    work_rel = ltype == "병가" and random.random() < 0.1
    e.setdefault("my_leaves", []).append(dict(leave_type=ltype, start_date=s, emp_id=e["emp_id"]))
    leaves.append(dict(leave_id=leave_seq[0], emp_id=e["emp_id"], leave_type=ltype, start_date=s, end_date=t,
                       is_work_related=work_rel,
                       has_medical_cert=ltype == "병가" and (work_rel or len(days_list) >= 3 or random.random() < 0.3),
                       days=n_days if n_days is not None else len(days_list), event_type=event_type,
                       related_family_id=fam["family_id"] if fam else None, status="승인",
                       approved_at=approved))
    for x in days_list:
        e["leave_days"][x] = ltype


def free_block(e, pool_days, n):
    for _ in range(60):
        i = random.randrange(len(pool_days))
        blk = pool_days[i:i + n]
        if len(blk) == n and all(x not in e["leave_days"] and x not in e["trip_days"] for x in blk) \
                and (blk[-1] - blk[0]).days < n + 4:
            return blk
    return None


def event_leaves(e):
    p = e["persona"]
    if p == "P2":
        s = D(2026, 10, 19)
        cal = [s + dt.timedelta(days=i) for i in range(90)]
        add_leave(e, "출산휴가", [x for x in cal if is_workday(x)], 90, "출산(예정일 2026-11-18)", start=s, end=cal[-1])
    if p == "P3":
        kid = [f for f in e["family"] if f["birth_date"] == D(2026, 8, 14)][0]
        add_leave(e, "배우자출산휴가", take_workdays(D(2026, 8, 17), 20), event_type="배우자 출산", fam=kid)
    for kind, day, f in sorted(e["events"], key=lambda x: x[1]):
        if kind == "marriage":
            s0 = day + DAY
            blk = take_workdays(s0, RULES["condolence_leave"]["본인 결혼"])
            while any(x in e["leave_days"] for x in blk):  # 다른 경조휴가와 겹치면 그 뒤로 미룸
                s0 += DAY
                blk = take_workdays(s0, RULES["condolence_leave"]["본인 결혼"])
            add_leave(e, "경조휴가", blk, event_type="본인 결혼", fam=f)
        elif kind == "death":
            cat = {"부": "부모 사망", "모": "부모 사망", "배우자부": "배우자 부모 사망", "배우자모": "배우자 부모 사망",
                   "조부": "조부모 사망", "조모": "조부모 사망"}[f["relation"]]
            blk = take_workdays(day, RULES["condolence_leave"][cat])
            if any(x in e["leave_days"] or in_absence(e, x) for x in blk):
                continue
            add_leave(e, "경조휴가", blk, event_type=cat, fam=f, min_approved=day)
        elif kind == "birth" and not p:
            if e["gender"] == "F":
                s = day - dt.timedelta(days=RULES["maternity_leave"]["before_birth_days"])
                cal = [s + dt.timedelta(days=i) for i in range(RULES["maternity_leave"]["days"])]
                if any(in_absence(e, x) or x < e["hire"] for x in cal):
                    continue
                add_leave(e, "출산휴가", [x for x in cal if is_workday(x)], RULES["maternity_leave"]["days"], "출산", f,
                          start=s, end=cal[-1])
            elif random.random() < 0.9:
                blk = take_workdays(day + DAY, RULES["paternity_leave"]["days"])
                if any(in_absence(e, x) or x in e["leave_days"] for x in blk):
                    continue
                add_leave(e, "배우자출산휴가", blk, event_type="배우자 출산", fam=f)


def year_leaves(e, y):
    start = max(D(y, 1, 1), e["hire"])
    end = min(D(y, 12, 31) if y == 2025 else ATT_END, e["retire_date"] or D(2099, 1, 1))
    if start > end:
        return
    pool_days = [x for x in workdays(start, end) if not in_absence(e, x)]
    if not pool_days:
        return
    age = age_on(e["birth"], D(y, 6, 30))
    kids_young = [f for f in e["family"] if f["relation"] == "자녀" and f["birth_date"] <= D(y, 6, 30)
                  and age_on(f["birth_date"], D(y, 6, 30)) < 12]

    def misc(ltype, prob, n_range, event_type=None, singles=False):
        if random.random() >= prob:
            return
        n = random.randint(*n_range)
        if singles:
            for _ in range(n):
                blk = free_block(e, pool_days, 1)
                if blk:
                    add_leave(e, ltype, blk, event_type=event_type)
        else:
            blk = free_block(e, pool_days, n)
            if blk:
                add_leave(e, ltype, blk, event_type=event_type)

    misc("병가", 0.12, (1, 3), "질병")
    if e["gender"] == "M" and age < 32:
        misc("공가", 0.35, (1, 1), "예비군 훈련")
    if e["gender"] == "F" and age < 50:
        misc("생리휴가", 0.15, (1, 2), singles=True)
    if kids_young:
        misc("가족돌봄휴가", 0.08, (1, 2), "자녀 돌봄")
    misc("포상휴가", 0.03, (2, 2), "우수사원 포상")
    misc("보건휴가", 0.04, (1, 1), "종합건강검진")
    if e["work_pattern"] in SHIFT_PATTERNS:
        misc("대체휴가", 0.12, (1, 1), "휴일근무 대체")
    if e["married_date"] and not [f for f in e["family"] if f["relation"] == "자녀"] and 30 <= age <= 42:
        misc("난임치료휴가", 0.15, (1, 3), "난임 시술", singles=True)
    if (y - e["hire"].year) in RULES["long_service_leave"]["years"] and random.random() < 0.8:
        blk = free_block(e, pool_days, RULES["long_service_leave"]["days"])
        if blk:
            add_leave(e, "장기재직휴가", blk, event_type=f"근속 {y - e['hire'].year}년")
    # 연차
    asof = D(2025, 12, 31) if y == 2025 else TODAY
    granted = annual_grant(e["hire"], y, asof)
    frac = random.uniform(0.55, 1.0) if y == 2025 else random.uniform(0.35, 0.85)
    if e["persona"] == "P1":
        frac = 0.3  # 결혼 대비 연차를 아껴 둔 상태
    target = min(granted, round(granted * frac * 2) / 2)
    used, tries = 0.0, 0
    while used < target and tries < 400:
        tries += 1
        rem = target - used
        r = random.random()
        if rem >= 1 and r < 0.18 and rem >= 2:
            n = random.randint(2, min(4, int(rem)))
            blk = free_block(e, pool_days, n)
            if blk:
                add_leave(e, "연차", blk)
                used += n
        elif r < 0.38 or rem < 1:
            blk = free_block(e, pool_days, 1)
            if blk:
                add_leave(e, random.choice(["오전반차", "오후반차"]), blk, 0.5)
                used += 0.5
        else:
            blk = free_block(e, pool_days, 1)
            if blk:
                add_leave(e, "연차", blk)
                used += 1
    e.setdefault("leave_balance", []).append(dict(emp_id=e["emp_id"], year=y, granted_days=granted, used_days=used,
                                                  remaining_days=granted - used, asof_date=asof))


TRIPS = []


def add_trip(e, start, end, region, purpose, ot, status=None):
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    TRIPS.append(dict(trip_id=None, emp_id=e["emp_id"], region_type=region, start_date=start, end_date=end,
                      nights=(end - start).days, purpose=purpose, overtime_hours=ot,
                      status=status or ("완료" if end < TODAY else "진행중" if start <= TODAY else "승인")))
    e["trip_days"].update(days)


for e in employees:
    if e["persona"] == "P10":  # 장기 출장 중 (휴가가 겹치지 않게 먼저 잡아 둠)
        add_trip(e, D(2026, 10, 12), D(2026, 12, 11), "광역시", "부산 협력사 신규 라인 설치 지원", 18.0)

for e in employees:
    e["leave_days"] = {}
    event_leaves(e)
    for y in (2025, 2026):
        year_leaves(e, y)

# ---------------------------------------------------------------- 출장 (팀 기준서 business_trips)
PURPOSES = {"사무": ["유관기관 업무 협의", "협력사 계약 협의", "지역 사업소 업무 점검", "철도 박람회 참관"],
            "시설·전기": ["선로 현장 점검", "전력설비 합동 점검", "신호설비 기술 지원", "통신설비 장애 지원"],
            "차량정비": ["차량 제작사 검수 입회", "타 기지 정비 지원", "부품 품질 감사"],
            "운전·승무": ["신규 노선 견습 운전", "타 사업소 승무 지원"],
            "역무": ["타 센터 역무 지원", "고객서비스 우수역 견학"]}
for e in employees:
    if e["persona"] in ("P10", "P2", "P5"):
        continue
    for y in (2025, 2026):
        start = max(D(y, 1, 2), e["hire"] + 60 * DAY)
        end = min(D(y, 12, 20) if y == 2025 else D(2026, 12, 20), e["retire_date"] or D(2099, 1, 1))
        if start >= end:
            continue
        n = random.choices([0, 1, 2, 3], [55, 27, 13, 5] if e["work_pattern"] == "일근" else [85, 12, 3, 0])[0]
        for _ in range(n):
            nights = random.choices([0, 1, 2, 3, 4], [30, 30, 20, 12, 8])[0]
            if random.random() < 0.02:
                nights = random.randint(16, 40)  # 장기 출장
            for _try in range(30):
                s0 = start + dt.timedelta(days=random.randint(0, (end - start).days))
                if not is_workday(s0):
                    continue
                span = [s0 + dt.timedelta(days=i) for i in range(nights + 1)]
                if any(x in e["leave_days"] or x in e["trip_days"] or in_absence(e, x) for x in span):
                    continue
                if e["retire_date"] and span[-1] > e["retire_date"]:
                    continue
                region = random.choices(RULES["business_trip"]["region_types"], [35, 35, 30])[0]
                ot = random.choice([0.0, 0.0, 0.0, 2.0, 3.0, 4.0]) if nights else 0.0
                add_trip(e, s0, span[-1], region, random.choice(PURPOSES[e["job_family"]]), ot)
                break
TRIPS.sort(key=lambda t: (t["start_date"], t["emp_id"]))
for i, t in enumerate(TRIPS, 1):
    t["trip_id"] = f"T{i:05d}"

# ---------------------------------------------------------------- 근무형태 변경 (교대·교번 현장 일부: 전에는 일근)
for e in employees:
    if e["work_pattern"] in SHIFT_PATTERNS and not e["persona"] and random.random() < 0.08:
        day = D(random.choice([2025, 2026]), random.randint(1, 9), 1)
        if day > e["hire"] + 180 * DAY and not (e["retire_date"] and day > e["retire_date"]):
            e["pattern_changes"].append((day, "일근", e["work_pattern"]))


def pattern_at(e, day):
    pat = e["work_pattern"]
    for when, before, _after in sorted(e["pattern_changes"], reverse=True):
        if day < when:
            pat = before
    return pat


# ---------------------------------------------------------------- 출퇴근
OT_P = {"운전·승무": 0.35, "역무": 0.3, "차량정비": 0.33, "시설·전기": 0.28, "사무": 0.2}


def hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


for e in employees:
    end = min(ATT_END, e["retire_date"] or D(2099, 1, 1))
    for x in workdays(max(ATT_START, e["hire"]), end):
        if in_absence(e, x):
            continue
        lt = e["leave_days"].get(x)
        ot = night = 0.0
        if lt in ("오전반차",):
            cin, cout, st = random.randint(830, 840), random.randint(1080, 1089), "오전반차"
        elif lt in ("오후반차",):
            cin, cout, st = random.randint(510, 539), random.randint(780, 789), "오후반차"
        elif lt:
            continue  # 종일 휴가: 출근 기록 없음
        else:
            st = "정상"
            cin = random.randint(510, 539)
            if random.random() < 0.02:
                cin, st = random.randint(541, 560), "지각"
            if random.random() < 0.02 and e["duty"] != "본부장":
                ot = random.choice([4.5, 5.0, 5.5])
                night = ot - 4
            elif random.random() < OT_P[e["job_family"]] and e["duty"] != "본부장":
                ot = random.choice([1, 1, 1.5, 2, 2, 2.5, 3])
            cout = 1080 + int(ot * 60) + random.randint(0, 9)
        attendance.append(dict(emp_id=e["emp_id"], work_date=x, check_in=hm(cin), check_out=hm(cout),
                               overtime_hours=ot, night_hours=night, status=st))

# ---------------------------------------------------------------- 급여
att_month = {}
for a in attendance:
    k = (a["emp_id"], a["work_date"].strftime("%Y-%m"))
    o, n = att_month.get(k, (0.0, 0.0))
    att_month[k] = (o + a["overtime_hours"], n + a["night_hours"])

pay_seq = 0
B = RULES["bonus"]
for e in employees:
    for ym in PAY_MONTHS:
        ms, me = month_start(ym), month_end(ym)
        if e["hire"] > ms or (e["retire_date"] and e["retire_date"] < me):
            continue
        if any(s <= ms and me <= t for s, t, _ in e["absences"]):
            continue  # 한 달 전체 휴직: 회사 급여 없음
        g = grade_at(e, ms)
        base = base_pay(g, e["hire"], ms)
        duty = RULES["duty_allowance"][e["duty"]]
        meal = RULES["meal_allowance"]["amount"]
        fam = family_allowance(e["family"], ym)
        pat = pattern_at(e, ms)
        shift = shift_allowance(pat)
        lsa = long_service_allowance(e["hire"], ms)
        ordinary = ordinary_wage(base, duty, shift, lsa)
        ot, night = att_month.get((e["emp_id"], ym), (0.0, 0.0))
        hh = random.choice([0.0, 0.0, 8.0, 8.0, 16.0]) if pat in SHIFT_PATTERNS else (8.0 if random.random() < 0.04 else 0.0)
        hw = hourly_wage(ordinary)
        ot_pay = won10(hw * RULES["overtime"]["overtime_rate"] * ot)
        night_pay = won10(hw * RULES["overtime"]["night_extra_rate"] * night)
        hol_pay = won10(hw * RULES["overtime"]["holiday_rate"] * hh)
        hol = won10(base * B["holiday_rate"]) if ym in B["holiday_months"] else 0
        perf = won10(base * B["performance_rate"][e["perf_grade"]]) if ym == B["performance_month"] and e["hire"] <= D(2025, 6, 30) else 0
        gross = base + duty + shift + lsa + meal + fam + ot_pay + night_pay + hol_pay + hol + perf
        ded = deductions(gross, meal)
        pay_seq += 1
        payroll.append(dict(pay_id=pay_seq, emp_id=e["emp_id"], pay_month=ym, grade=g, work_pattern=pat, base_pay=base,
                            ordinary_wage=ordinary, duty_allowance=duty, family_allowance=fam,
                            long_service_allowance=lsa, shift_allowance=shift, meal_allowance=meal,
                            overtime_hours=ot, overtime_pay=ot_pay, night_hours=night, night_pay=night_pay,
                            holiday_hours=hh, holiday_pay=hol_pay, holiday_bonus=hol, performance_bonus=perf,
                            gross_pay=gross, **ded, deductions=sum(ded.values()), net_pay=gross - sum(ded.values()),
                            pay_date=D(ms.year, ms.month, 25)))

# ---------------------------------------------------------------- 복지포인트 (연도별 요약)
WK = RULES["welfare_korail"]
for e in employees:
    for y in (2025, 2026):
        alloc_day = max(D(y, 1, 2), e["hire"])
        last = min(D(y, 12, 30) if y == 2025 else ATT_END, e["retire_date"] or D(2099, 1, 1))
        if alloc_day > last or e["employment_type"] not in WK["selective_welfare"]["eligible"]:
            continue
        amt = welfare_allocation(e["hire"], e["family"], y)
        bal, used = amt, 0
        for _ in range(random.randint(2, 9)):
            if bal < 10000:
                break
            spend = min(bal, random.randint(1, 25) * 10000)
            bal -= spend
            used += spend
        welfare.append(dict(emp_id=e["emp_id"], year=y, granted_points=amt, used_points=used,
                            expires_on=D(y, 12, 31)))

# ---------------------------------------------------------------- 경조금·출산축하금 (코레일 2025 기준표) → 신청서
CM, BB = WK["condolence_money"], WK["birth_bonus"]
DEATH_CAT = {"부": "부모 사망", "모": "부모 사망", "배우자부": "배우자 부모 사망", "배우자모": "배우자 부모 사망",
             "조부": "조부모 사망", "조모": "조부모 사망", "배우자": "배우자 사망", "자녀": "자녀 사망"}
BIRTH_ORDER = {1: ("첫째 출생", "first"), 2: ("둘째 출생", "second")}
payments = []


def add_payment(e, pay_type, event_type, event_day, fam, amount, source):
    pay_day = min(event_day + dt.timedelta(days=random.randint(5, 20)), ATT_END)
    payments.append(dict(emp_id=e["emp_id"], pay_type=pay_type, event_type=event_type, event_date=event_day,
                         family_id=fam["family_id"], amount=amount, pay_date=pay_day, source=source))


for e in employees:
    et = e["employment_type"]
    for kind, day, f in sorted(e["all_events"], key=lambda x: x[1]):
        if e["retire_date"] and day > e["retire_date"]:
            continue
        if kind == "marriage" and et in CM["eligible"]:
            add_payment(e, "축의금", "본인 결혼", day, f, CM["축의금"]["본인 결혼"], CM["_source"])
        elif kind == "death" and et in CM["eligible"]:
            cat = DEATH_CAT[f["relation"]]
            add_payment(e, "조의금", cat, day, f, CM["조의금"][cat], CM["_source"])
        elif kind == "birth" and et in BB["eligible"]:
            order = sorted(k["birth_date"] for k in e["family"] if k["relation"] == "자녀").index(f["birth_date"]) + 1
            label, key = BIRTH_ORDER.get(order, ("셋째 이상 출생", "third_plus"))
            add_payment(e, "출산축하금", label, day, f, BB[key], BB["_source"])
    if et in CM["eligible"]:
        for f in e["family"]:
            if f["relation"] not in ("부", "모", "배우자부", "배우자모"):
                continue
            d80 = add_years(f["birth_date"], 80)
            if max(D(2025, 1, 1), e["hire"]) <= d80 <= ATT_END and (not f["death_date"] or f["death_date"] > d80) \
                    and (not e["retire_date"] or d80 <= e["retire_date"]):
                cat = "부모 팔순" if f["relation"] in ("부", "모") else "배우자 부모 팔순"
                add_payment(e, "축의금", cat, d80, f, CM["축의금"][cat], CM["_source"])

# ---------------------------------------------------------------- 신청서 (모든 이벤트)
EMP_BY_ID = {e["emp_id"]: e for e in employees}
FAM_BY_ID = {f["family_id"]: f for e in employees for f in e["family"]}
requests = []


def fid(n):
    return f"F{n:04d}" if n else None


def add_request(emp_id, rtype, event_type, payload, status, created, decided):
    rid = f"R{len(requests) + 1:06d}"
    requests.append(dict(request_id=rid, emp_id=emp_id, request_type=rtype, event_type=event_type,
                         payload=json.dumps(payload, ensure_ascii=False, default=str), status=status,
                         created_at=created, decided_at=decided))
    return rid


LEAVE_NAME = {"오전반차": "반차", "오후반차": "반차", "경조휴가": "청원", "출산휴가": "출산전후",
              "배우자출산휴가": "배우자출산", "가족돌봄휴가": "가족돌봄", "장기재직휴가": "장기재직"}
for l in sorted(leaves, key=lambda x: (x["approved_at"], x["leave_id"])):
    created = l["approved_at"] - dt.timedelta(days=random.randint(0, 3))
    f = FAM_BY_ID.get(l["related_family_id"])
    if f and f.get("death_date") and "사망" in (l["event_type"] or ""):
        created = max(created, f["death_date"])  # 사망 전에 신청할 수 없음
    payload = dict(leave_type=LEAVE_NAME.get(l["leave_type"], l["leave_type"]), start_date=l["start_date"],
                   end_date=l["end_date"], days=l["days"], family_id=fid(l["related_family_id"]))
    if l["leave_type"] in ("오전반차", "오후반차"):
        payload["half"] = l["leave_type"][:2]
    l["request_id"] = add_request(l["emp_id"], "휴가신청", l["event_type"] or LEAVE_NAME.get(l["leave_type"], l["leave_type"]),
                                  payload, "승인", created, l["approved_at"])
for pmt in sorted(payments, key=lambda x: (x["event_date"], x["emp_id"])):
    created = pmt["event_date"] + dt.timedelta(days=random.randint(0, 3))
    created = min(created, pmt["pay_date"])
    add_request(pmt["emp_id"], "출산축하금신청" if pmt["pay_type"] == "출산축하금" else "경조금신청", pmt["event_type"],
                dict(pay_type=pmt["pay_type"], family_id=fid(pmt["family_id"]), amount=pmt["amount"],
                     event_date=pmt["event_date"], source=pmt["source"]), "지급완료", created, pmt["pay_date"])
ABS_NAME = {"육아휴직": "육아", "질병휴직": "질병", "업무상재해휴직": "업무상재해", "가족돌봄휴직": "가족돌봄"}
absence_rows = []
for e in employees:
    for s0, t0, kind in sorted(e["absences"]):
        a = ABS_NAME[kind]
        child = e.get("absence_child", {}).get(s0)
        ret = t0 + DAY if t0 < TODAY else None
        absence_rows.append(dict(absence_id=None, emp_id=e["emp_id"], absence_type=a, start_date=s0, end_date=t0,
                                 return_date=ret, pay_rate=RULES["absence_pay_rate"][a], child_family_id=fid(child)))
        c0 = max(s0 - dt.timedelta(days=21), e["hire"])
        add_request(e["emp_id"], "휴직신청", a, dict(start_date=s0, end_date=t0, child_family_id=fid(child)),
                    "승인", c0, s0 - dt.timedelta(days=7))
        if ret:
            add_request(e["emp_id"], "복직신청", a, dict(return_date=ret), "승인", t0 - dt.timedelta(days=14),
                        t0 - dt.timedelta(days=7))
absence_rows.sort(key=lambda r: (r["start_date"], r["emp_id"]))
for i, r in enumerate(absence_rows, 1):
    r["absence_id"] = f"A{i:04d}"
for t in TRIPS:
    c0 = t["start_date"] - dt.timedelta(days=random.randint(3, 10))
    add_request(t["emp_id"], "출장신청", t["purpose"], dict(trip_id=t["trip_id"], region_type=t["region_type"],
                start_date=t["start_date"], end_date=t["end_date"]), "승인", c0, c0 + dt.timedelta(days=1))
# 시연: 결혼 예정 직원의 대기 중 신청 (청원휴가·축의금)
p1 = BY_KEY["P1"]
add_request(p1["emp_id"], "휴가신청", "본인 결혼",
            dict(leave_type="청원", start_date=D(2026, 12, 14), end_date=D(2026, 12, 18), days=5, family_id=None),
            "대기", D(2026, 11, 5), None)
add_request(p1["emp_id"], "경조금신청", "본인 결혼",
            dict(pay_type="축의금", amount=CM["축의금"]["본인 결혼"], event_date=D(2026, 12, 12), source=CM["_source"]),
            "대기", D(2026, 11, 5), None)

# ---------------------------------------------------------------- 교육
JOB_COURSES = {
    "운전·승무": ["기관사 보수교육", "비상 상황 대응 훈련", "신호 체계 이해", "승객 응대 실무"],
    "역무": ["철도 고객서비스", "발권 시스템 실무", "역사 안전관리", "장애인 응대 실무"],
    "차량정비": ["전동차 정비 실무", "제동장치 정비", "차량 고장 진단", "정비 품질관리"],
    "시설·전기": ["궤도 보수 실무", "전차선 유지보수", "신호설비 점검", "철도 통신망 관리"],
    "사무": ["엑셀 데이터 분석", "비즈니스 글쓰기", "계약 실무", "생성형 AI 업무 활용"],
}
tr = 0


def add_training(e, y, name, ctype, required, reason, hours, st, en):
    global tr
    tr += 1
    done = en is not None and en <= ATT_END
    training.append(dict(training_id=f"TR{tr:05d}", emp_id=e["emp_id"], year=y, course_name=name, course_type=ctype,
                         required="Y" if required else "N", target_reason=reason, hours=hours,
                         status="이수" if done else ("미이수" if st is None else "수강중"),
                         completed_on=en if done else None))


for e in employees:
    promos = [r["change_date"] for r in e["career"] if r["change_type"] == "승진"]
    for y in (2025, 2026):
        s0 = max(D(y, 1, 2), e["hire"])
        last = min(D(y, 12, 30) if y == 2025 else ATT_END, e["retire_date"] or D(2099, 1, 1))
        days = [x for x in workdays(s0, last) if not in_absence(e, x)] if s0 <= last else []
        if not days:
            continue
        for c in RULES["mandatory_training"]["courses"]:
            cd = random.choice(days) if random.random() < (0.97 if y == 2025 else 0.82) else None
            add_training(e, y, c, "법정", True, "법정", random.choice([1, 1, 2]), cd, cd)
        if e["hire"].year == y:
            st = e["hire"] + dt.timedelta(days=random.randint(3, 14))
            add_training(e, y, "신규입사자 입문 과정", "신규", True, "신규", 16, st, st + DAY)
        for pd_ in promos:
            if pd_.year == y:
                st = pd_ + dt.timedelta(days=random.randint(10, 60))
                add_training(e, y, "승진자 역량 과정", "승진", True, "승진", 16, st, st + DAY)
        for c in random.sample(JOB_COURSES[e["job_family"]], random.randint(0, 2)):
            st = random.choice(days)
            add_training(e, y, c, "직무", False, "직무", random.choice([4, 8, 16, 24]), st,
                         st + dt.timedelta(days=random.randint(0, 4)))
        if e["duty"] in ("팀장", "본부장"):
            st = random.choice(days)
            add_training(e, y, "리더십 과정", "리더십", True, "보직변경", 16, st, st + DAY)

# ---------------------------------------------------------------- 로그인 계정 (테스트용)
for i, e in enumerate(employees, 1):
    salt = hashlib.sha256(e["emp_id"].encode()).hexdigest()[:16]
    h = hashlib.pbkdf2_hmac("sha256", TEST_PASSWORD.encode(), salt.encode(), 100_000).hex()
    users.append(dict(user_id=i, emp_id=e["emp_id"], login_id=e["emp_id"].lower(), password_hash=f"pbkdf2${salt}${h}",
                      role="hr_admin" if e["dept"] == HR_DEPT else "employee", is_active=e["status"] != "퇴직",
                      created_at=e["hire"]))

# ---------------------------------------------------------------- 개인정보 (employee_pii, 가짜 형식)
ADDR = {"본사": [("대전광역시", "동구"), ("대전광역시", "중구"), ("대전광역시", "서구"), ("대전광역시", "유성구"), ("세종특별자치시", "세종시")],
        "수도권": [("서울특별시", "용산구"), ("서울특별시", "구로구"), ("경기도", "고양시"), ("경기도", "의왕시")],
        "충청권": [("대전광역시", "대덕구"), ("충청북도", "청주시"), ("충청남도", "천안시")],
        "영남권": [("부산광역시", "동구"), ("부산광역시", "부산진구"), ("대구광역시", "동구"), ("경상북도", "경주시")]}
W = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
pii = []
# 전화번호는 별도 난수(phone_rng)로 만듦 → 기존 seed 42 흐름이 안 바뀌어 다른 값은 그대로
phone_rng = random.Random(20261110)
_used_phones = set()
def fake_phone():
    """실제처럼 보이는 010-XXXX-XXXX (가운데 2000~9999, 중복 없음). 이름·주소와 묶인 가짜 데이터임."""
    while True:
        ph = f"010-{phone_rng.randint(2000, 9999)}-{phone_rng.randint(0, 9999):04d}"
        if ph not in _used_phones:
            _used_phones.add(ph)
            return ph
for i, e in enumerate(employees):
    b = e["birth"]
    gd = (1 if e["gender"] == "M" else 2) + (2 if b.year >= 2000 else 0)
    body = b.strftime("%y%m%d") + str(gd) + "".join(str(random.randint(0, 9)) for _ in range(5))
    check = (11 - sum(int(c) * w for c, w in zip(body, W)) % 11) % 10
    wrong = (check + random.randint(1, 9)) % 10  # 일부러 틀린 검증 숫자 → 실제 주민번호가 될 수 없음
    sido, sgg = random.choice(ADDR[DEPT[e["dept"]]["site"]])
    spouse = [f for f in e["family"] if f["relation"] == "배우자" and not f["death_date"]]
    parent = [f for f in e["family"] if f["relation"] in ("부", "모") and not f["death_date"]]
    em_rel = "배우자" if spouse else ("부모" if parent else "형제자매")
    pii.append(dict(emp_id=e["emp_id"], rrn=f"{body[:6]}-{body[6:]}{wrong}", bank_name="테스트은행",
                    account_no=f"999-{random.randint(10, 99)}-{random.randint(100000, 999999)}",
                    mobile=fake_phone(), zipcode=f"{random.randint(10000, 63999)}", address_sido=sido,
                    address_sigungu=sgg, address_detail=f"누리로 {random.randint(1, 300)}",
                    address_changed_at=rand_date(e["hire"], TODAY - 30 * DAY) if random.random() < 0.3 else None,
                    emergency_name=f"비상연락{i + 1}", emergency_relation=em_rel,
                    emergency_phone=fake_phone()))


# ---------------------------------------------------------------- 저장 (팀 기준서 CSV 14종 + 부가 파일)
YN = lambda v: "Y" if v else "N"


def write(name, rows, cols, folder=OUT):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{name}.csv", "w", newline="", encoding="utf-8-sig") as fp:  # BOM: 맥 엑셀 한글 깨짐 방지
        w = csv.writer(fp)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if r.get(c) is None else ("true" if r.get(c) is True else "false" if r.get(c) is False else r.get(c))
                        for c in cols])


for old in OUT.glob("*.csv"):  # 이전 형식 파일 정리 (career_history, welfare_payments 등)
    old.unlink()
EXTRA = OUT.parent / "extra"

write("departments", [dict(v, head_emp_id=v.get("head_emp_id")) for v in DEPT.values()],
      ["dept_id", "dept_name", "parent_id", "dept_type", "site", "head_emp_id"])
RET = {"정년퇴직": "정년", "의원퇴직": "의원"}
emp_rows = []
for e in employees:
    promos = [r["change_date"] for r in e["career"] if r["change_type"] == "승진"]
    since = max([c[0] for c in e["pattern_changes"]], default=e["hire"])
    emp_rows.append(dict(emp_id=e["emp_id"], name=e["name"], gender=e["gender"], birth_date=e["birth"],
                         dept_id=e["dept"], site=DEPT[e["dept"]]["site"], job_family=e["job_family"],
                         position=e["position"], grade=e["grade"], employment_type=e["employment_type"],
                         hire_date=e["hire"], probation_end_date=probation_end(e["hire"]),
                         work_pattern=e["work_pattern"], work_pattern_since=since,
                         weekly_hours=RULES["work_patterns"][e["work_pattern"]]["weekly_hours"], status=e["status"],
                         last_promotion_date=max(promos, default=None), retire_date=e["retire_date"],
                         retire_type=RET.get(e["retire_reason"]), email=f"{e['emp_id'].lower()}@{CO['email_domain']}",
                         base_salary=base_pay(e["grade"], e["hire"], month_start("2026-11")), duty=e["duty"]))
write("employees", emp_rows, ["emp_id", "name", "gender", "birth_date", "dept_id", "site", "job_family", "position",
                              "grade", "employment_type", "hire_date", "probation_end_date", "work_pattern",
                              "work_pattern_since", "weekly_hours", "status", "last_promotion_date", "retire_date",
                              "retire_type", "email", "base_salary", "duty"])
write("employee_pii", pii, ["emp_id", "rrn", "bank_name", "account_no", "mobile", "zipcode", "address_sido",
                            "address_sigungu", "address_detail", "address_changed_at", "emergency_name",
                            "emergency_relation", "emergency_phone"])
REL_OUT = {"조부": "조부모", "조모": "조부모"}
fam_rows = []
for e in employees:
    kids = sorted((f for f in e["family"] if f["relation"] == "자녀"), key=lambda f: f["birth_date"])
    order = {f["family_id"]: i + 1 for i, f in enumerate(kids)}
    for f in e["family"]:
        expected = f.get("expected", False)
        fam_rows.append(dict(family_id=fid(f["family_id"]), emp_id=e["emp_id"], relation=REL_OUT.get(f["relation"], f["relation"]),
                             name=f["name"], birth_date=f["birth_date"], gender=f["gender"],
                             child_order=order.get(f["family_id"]), is_dependent=YN(f["is_dependent"]),
                             school_level=school_level(f["birth_date"], TODAY) if f["relation"] == "자녀" else None,
                             disabled=YN(random.random() < 0.015), deceased_date=f["death_date"],
                             registered_at=None if expected else f["added_date"]))
write("family", fam_rows, ["family_id", "emp_id", "relation", "name", "birth_date", "gender", "child_order",
                           "is_dependent", "school_level", "disabled", "deceased_date", "registered_at"])
LS_YEARS = RULES["long_service_leave"]["years"]
lb_rows = []
for e in employees:
    for b in e.get("leave_balance", []):
        lsl = any(l["emp_id"] == e["emp_id"] and l["leave_type"] == "장기재직휴가" and l["start_date"].year == b["year"]
                  for l in e.get("my_leaves", []))
        lb_rows.append(dict(b, carried_days=0, long_service_leave_used=YN(lsl)))
write("leave_balance", lb_rows, ["emp_id", "year", "granted_days", "carried_days", "used_days",
                                 "long_service_leave_used", "remaining_days", "asof_date"])
lv_rows = [dict(l, leave_type=LEAVE_NAME.get(l["leave_type"], l["leave_type"]), is_work_related=YN(l["is_work_related"]),
                has_medical_cert=YN(l["has_medical_cert"])) for l in leaves]
write("leave_history", lv_rows, ["leave_id", "emp_id", "leave_type", "start_date", "end_date", "days",
                                 "is_work_related", "has_medical_cert", "status", "request_id"])
write("absence_history", absence_rows, ["absence_id", "emp_id", "absence_type", "start_date", "end_date",
                                        "return_date", "pay_rate", "child_family_id"])
hr_rows = []
for e in employees:
    rows = []
    for r in e["career"]:
        if r["change_type"] == "휴직":
            et_ = "휴직"
        else:
            et_ = r["change_type"]
        fs = DEPT[r["from_dept"]]["site"] if r["from_dept"] else None
        ts = DEPT[r["to_dept"]]["site"] if r["to_dept"] else None
        rows.append(dict(emp_id=e["emp_id"], event_type=et_, effective_date=r["change_date"], from_dept=r["from_dept"],
                         to_dept=r["to_dept"], from_grade=r["from_grade"], to_grade=r["to_grade"],
                         from_work_pattern=None, to_work_pattern=pattern_at(e, e["hire"]) if et_ == "입사" else None,
                         is_relocation=YN(et_ == "전보" and fs is not None and ts is not None and fs != ts)
                         if et_ == "전보" else None))
    for when, before, after in e["pattern_changes"]:
        rows.append(dict(emp_id=e["emp_id"], event_type="근무형태변경", effective_date=when, from_work_pattern=before,
                         to_work_pattern=after))
    rows.sort(key=lambda r: (r["effective_date"], r["event_type"] != "입사"))
    hr_rows += rows
for i, r in enumerate(hr_rows, 1):
    r["history_id"] = f"H{i:05d}"
write("hr_history", hr_rows, ["history_id", "emp_id", "event_type", "effective_date", "from_dept", "to_dept",
                              "from_grade", "to_grade", "from_work_pattern", "to_work_pattern", "is_relocation"])
write("business_trips", TRIPS, ["trip_id", "emp_id", "region_type", "start_date", "end_date", "nights", "purpose",
                                "overtime_hours", "status"])
write("payroll", payroll, ["pay_id", "emp_id", "pay_month", "grade", "work_pattern", "base_pay", "ordinary_wage",
                           "duty_allowance", "family_allowance", "long_service_allowance", "shift_allowance",
                           "meal_allowance", "overtime_hours", "overtime_pay", "night_hours", "night_pay",
                           "holiday_hours", "holiday_pay", "holiday_bonus", "performance_bonus", "gross_pay",
                           "national_pension", "health_insurance", "long_term_care", "employment_insurance",
                           "income_tax", "local_tax", "deductions", "net_pay", "pay_date"])
write("welfare_points", welfare, ["emp_id", "year", "granted_points", "used_points", "expires_on"])
write("training", training, ["training_id", "emp_id", "year", "course_name", "course_type", "required",
                             "target_reason", "hours", "status", "completed_on"])
write("requests", requests, ["request_id", "emp_id", "request_type", "event_type", "payload", "status", "created_at",
                             "decided_at"])
write("users", users, ["user_id", "emp_id", "login_id", "password_hash", "role", "is_active", "created_at"])
write("audit_log", [], ["log_id", "actor_user_id", "action", "target_emp_id", "detail", "created_at"])
# 부가 파일 (기준서 밖): 출퇴근 기록 = 연장·야간수당 계산 근거
write("attendance", attendance, ["emp_id", "work_date", "check_in", "check_out", "overtime_hours", "night_hours",
                                 "status"], folder=EXTRA)

meta = Path(__file__).parent / "data" / "meta"
meta.mkdir(parents=True, exist_ok=True)
(meta / "demo_personas.json").write_text(json.dumps(
    [dict(key=e["persona"], emp_id=e["emp_id"], login_id=e["emp_id"].lower(), name=e["name"], dept=DEPT[e["dept"]]["dept_name"],
          site=DEPT[e["dept"]]["site"], position=e["position"], grade=e["grade"], duty=e["duty"],
          work_pattern=e["work_pattern"], status=e["status"], scenario=e["scenario"])
     for e in sorted(BY_KEY.values(), key=lambda x: int(x["persona"][1:]))], ensure_ascii=False, indent=2), encoding="utf-8")

print(f"employees {len(emp_rows)} | pii {len(pii)} | family {len(fam_rows)} | hr_history {len(hr_rows)} | "
      f"absence {len(absence_rows)} | trips {len(TRIPS)} | leave {len(leaves)} | payroll {len(payroll)} | "
      f"welfare {len(welfare)} | training {len(training)} | requests {len(requests)} | attendance(extra) {len(attendance)}")
