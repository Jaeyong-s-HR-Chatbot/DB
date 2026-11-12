"""골든셋 페르소나 3명: 기존 직원 3명을 골든셋(RAG 저장소 eval/golden_set.json) 페르소나에 맞게 바꿈.

generate.py 끝에서 자동으로 실행됨 (따로 실행: python golden_personas.py).
- 다른 직원 데이터는 건드리지 않음. 바꾼 3명의 생년월일·부서·직급·가족과, 거기에 따라 달라지는
  급여·복지포인트·인사이력·주민번호 앞자리만 규칙표(common.py)로 다시 계산.
- 고른 기준: 같은 일근 근무, 팀원(팀장 아님), 휴직 이력 없음, 가족이 걸린 신청서 없음, 입사 시기가 페르소나와 맞음.
- 결과: data/meta/golden_personas.json (페르소나 → 사번)
"""
import csv
import datetime as dt
import json
import random
from pathlib import Path

from common import (RULES, age_on, base_pay, deductions, family_allowance, hourly_wage, long_service_allowance,
                    month_start, ordinary_wage, school_level, shift_allowance, welfare_allocation, won10)

HERE = Path(__file__).parent
HR = HERE / "data/hr"
D = dt.date.fromisoformat
TODAY = dt.date(2026, 11, 12)

# 페르소나 ↔ 바꿀 직원. family: (관계, 성별, 이름, 생년월일, 부양 여부, 등록일)
GOLDEN = [
    dict(key="G1", golden="P1", emp_id="E1634", birth="1993-03-14", dept="D62", grade=5,
         profile="본사 경영지원본부 사무직, 33세 남성, 2024년 입사(3년차), 5급 사원, 부모님(66·61세) 둘 다 피부양자, 미혼",
         family=[("부", "M", "이정호", "1960-05-20", True, "2024-02-01"),
                 ("모", "F", "김미경", "1965-08-11", True, "2024-02-01")]),
    dict(key="G2", golden="P2", emp_id="E1033", birth="1967-04-15", dept="D31", grade=3,
         profile="차량본부 차량계획팀(일근), 59세 남성, 1996년 입사, 3급 과장, 아내(56)·아들(24)·딸(19), 정년 2027-06-30",
         family=[("배우자", "F", "한정숙", "1970-05-10", True, "2000-05-01"),
                 ("자녀", "M", "최민혁", "2002-02-20", None, "2002-03-01"),
                 ("자녀", "F", "최서연", "2007-04-05", None, "2007-05-01")]),
    dict(key="G3", golden="P3", emp_id="E1768", birth="1997-07-20", dept="D64", grade=5,
         profile="본사 경영지원본부 홍보팀 사무직, 29세 여성, 2026-04 입사(1년 미만), 5급 사원, 어머니(56) 피부양자, 남편(32)",
         family=[("모", "F", "박영희", "1970-03-02", True, "2026-04-01"),
                 ("배우자", "M", "정우진", "1994-09-10", True, "2026-04-01")]),
]


def read(name):
    with open(HR / f"{name}.csv", encoding="utf-8-sig", newline="") as fp:
        r = csv.reader(fp)
        cols = next(r)
        return cols, [dict(zip(cols, row)) for row in r]


def write(name, cols, rows):
    with open(HR / f"{name}.csv", "w", newline="", encoding="utf-8-sig") as fp:  # generate.py 와 같은 형식
        w = csv.writer(fp)
        w.writerow(cols)
        for row in rows:
            w.writerow([row.get(c, "") for c in cols])


def fam_for_calc(rows):
    """common.py 계산 함수가 쓰는 이름으로 (validate.py 와 같은 변환)."""
    return [dict(relation=f["relation"], birth_date=f["birth_date"], is_dependent=f["is_dependent"] == "Y",
                 added_date=f["registered_at"] or "2999-12-31", death_date=f["deceased_date"] or None) for f in rows]


def main():
    T = {n: read(n) for n in ("employees", "departments", "family", "hr_history", "payroll", "welfare_points",
                              "employee_pii", "requests", "absence_history")}
    depts = {d["dept_id"]: d for d in T["departments"][1]}
    heads = {d["head_emp_id"] for d in depts.values() if d["head_emp_id"]}
    emp_by = {e["emp_id"]: e for e in T["employees"][1]}
    pattern_by_dept = {}
    for e in T["employees"][1]:
        pattern_by_dept.setdefault(e["dept_id"], (e["job_family"], e["work_pattern"]))
    out = []

    for g in GOLDEN:
        eid = g["emp_id"]
        e = emp_by[eid]
        # 고른 직원이 조건에 맞는지 (데이터가 바뀌어 조건이 깨지면 여기서 멈춤)
        assert e["work_pattern"] == "일근" and e["duty"] == "팀원" and eid not in heads, eid
        assert e["work_pattern"] == pattern_by_dept[g["dept"]][1], f"{eid} 근무형태가 {g['dept']}와 다름"
        assert not any(a["emp_id"] == eid for a in T["absence_history"][1]), f"{eid} 휴직 이력 있음"
        assert not any(r["emp_id"] == eid and '"family_id": "F' in r["payload"] for r in T["requests"][1]), \
            f"{eid} 가족이 걸린 신청서 있음"
        hire = D(e["hire_date"])

        # 1) 인사이력: 입사 부서를 새 부서로, 목표 직급보다 높은 승진은 지움
        hist = [h for h in T["hr_history"][1] if h["emp_id"] == eid]
        assert all(h["event_type"] in ("입사", "승진") for h in hist), f"{eid} 전보·근무형태 변경 이력 있음"
        keep = []
        for h in hist:
            if h["event_type"] == "입사":
                h["to_dept"] = g["dept"]
            if h["event_type"] == "승진" and int(h["to_grade"]) < g["grade"]:
                continue
            keep.append(h)
        drop = {h["history_id"] for h in hist} - {h["history_id"] for h in keep}
        T["hr_history"] = (T["hr_history"][0], [h for h in T["hr_history"][1] if h["history_id"] not in drop])
        promos = [h["effective_date"] for h in keep if h["event_type"] == "승진"]

        # 2) 직원 정보
        e.update(birth_date=g["birth"], dept_id=g["dept"], site=depts[g["dept"]]["site"],
                 job_family=pattern_by_dept[g["dept"]][0], grade=str(g["grade"]),
                 position=RULES["grades"][str(g["grade"])]["position"],
                 last_promotion_date=promos[-1] if promos else "",
                 base_salary=str(base_pay(g["grade"], hire, month_start("2026-11"))))

        # 3) 가족: 기존 가족 지우고 페르소나 가족으로 (ID는 지운 것부터 다시 씀)
        old = [f for f in T["family"][1] if f["emp_id"] == eid]
        ids = sorted(f["family_id"] for f in old)
        nxt = max(int(f["family_id"][1:]) for f in T["family"][1])
        new = []
        kids = sorted([x for x in g["family"] if x[0] == "자녀"], key=lambda x: x[3])
        for rel, gender, name, birth, dep, reg in g["family"]:
            if ids:
                fid = ids.pop(0)
            else:
                nxt += 1
                fid = f"F{nxt:04d}"
            b = D(birth)
            if rel == "자녀":  # validate.py 규칙: 부양 여부 = 20세 미만, 학교급·순위
                dep = age_on(b, TODAY) < 20
            new.append(dict(family_id=fid, emp_id=eid, relation=rel, name=name, birth_date=birth, gender=gender,
                            child_order=str(kids.index(next(k for k in kids if k[3] == birth)) + 1) if rel == "자녀" else "",
                            is_dependent="Y" if dep else "N",
                            school_level=school_level(b, TODAY) if rel == "자녀" else "",
                            disabled="N", deceased_date="", registered_at=reg))
        T["family"] = (T["family"][0], [f for f in T["family"][1] if f["emp_id"] != eid] + new)
        T["family"][1].sort(key=lambda f: int(f["family_id"][1:]))
        fam = fam_for_calc(new)

        # 4) 급여: 직급·가족이 바뀐 만큼 다시 계산 (generate.py 와 같은 공식)
        B, OT = RULES["bonus"], RULES["overtime"]
        for p in T["payroll"][1]:
            if p["emp_id"] != eid:
                continue
            ms = month_start(p["pay_month"])
            gr = min(int(h["to_grade"]) for h in keep if h["to_grade"] and D(h["effective_date"]) <= ms)
            old_base = int(p["base_pay"])
            base = base_pay(gr, hire, ms)
            duty, shift = int(p["duty_allowance"]), shift_allowance(p["work_pattern"])
            lsa = long_service_allowance(hire, ms)
            ordinary = ordinary_wage(base, duty, shift, lsa)
            hw = hourly_wage(ordinary)
            perf = won10(base * int(p["performance_bonus"]) / old_base) if int(p["performance_bonus"]) else 0
            p.update(grade=str(gr), base_pay=str(base), ordinary_wage=str(ordinary),
                     family_allowance=str(family_allowance(fam, p["pay_month"], gr)),
                     overtime_pay=str(won10(hw * OT["overtime_rate"] * float(p["overtime_hours"]))),
                     night_pay=str(won10(hw * OT["night_extra_rate"] * float(p["night_hours"]))),
                     holiday_pay=str(won10(hw * OT["holiday_rate"] * float(p["holiday_hours"]))),
                     holiday_bonus=str(won10(base * B["holiday_rate"]) if p["pay_month"] in B["holiday_months"] else 0),
                     performance_bonus=str(perf))
            gross = sum(int(p[k]) for k in ("base_pay", "duty_allowance", "shift_allowance", "long_service_allowance",
                                            "meal_allowance", "family_allowance", "overtime_pay", "night_pay",
                                            "holiday_pay", "holiday_bonus", "performance_bonus"))
            ded = deductions(gross, int(p["meal_allowance"]))
            p.update(gross_pay=str(gross), **{k: str(v) for k, v in ded.items()},
                     deductions=str(sum(ded.values())), net_pay=str(gross - sum(ded.values())))

        # 5) 복지포인트 배정 (가족에 따라 달라짐). 사용액이 배정보다 크면 배정액으로 맞춤
        for w in T["welfare_points"][1]:
            if w["emp_id"] == eid:
                amt = welfare_allocation(hire, fam, int(w["year"]))
                w["granted_points"], w["used_points"] = str(amt), str(min(int(w["used_points"]), amt))

        # 6) 주민번호 앞자리 = 새 생년월일·성별 (검증숫자는 일부러 틀리게, 별도 난수)
        rng = random.Random(f"golden-{eid}")
        W = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
        b = D(g["birth"])
        gd = (1 if e["gender"] == "M" else 2) + (2 if b.year >= 2000 else 0)
        body = b.strftime("%y%m%d") + str(gd) + "".join(str(rng.randint(0, 9)) for _ in range(5))
        check = (11 - sum(int(c) * w for c, w in zip(body, W)) % 11) % 10
        for pii in T["employee_pii"][1]:
            if pii["emp_id"] == eid:
                pii["rrn"] = f"{body[:6]}-{body[6:]}{(check + rng.randint(1, 9)) % 10}"
                pii["emergency_relation"] = "배우자" if any(f["relation"] == "배우자" for f in new) else "부모"

        out.append(dict(key=g["key"], golden_persona=g["golden"], emp_id=eid, login_id=eid.lower(), name=e["name"],
                        dept=depts[g["dept"]]["dept_name"], grade=g["grade"], position=e["position"],
                        hire_date=e["hire_date"], birth_date=g["birth"], profile=g["profile"]))

    for n in ("employees", "family", "hr_history", "payroll", "welfare_points", "employee_pii"):
        write(n, *T[n])
    (HERE / "data/meta/golden_personas.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("golden personas:", ", ".join(f"{o['golden_persona']}→{o['emp_id']} {o['name']}" for o in out))


if __name__ == "__main__":
    main()
