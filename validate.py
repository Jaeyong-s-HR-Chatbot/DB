"""정합성 검사: data/hr/*.csv (팀 데이터 기준서 CSV 14종)를 읽어 테이블끼리 숫자가 맞는지 확인.
하나라도 틀리면 종료 코드 1. 실행: .venv/bin/python validate.py
"""
import csv
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from common import (ATT_END, RULES, TODAY, age_on, annual_grant, base_pay, d, deductions, family_allowance,
                    first_workday, hourly_wage, is_workday, long_service_allowance, month_end, month_start,
                    ordinary_wage, probation_end, school_level, shift_allowance, welfare_allocation, won10, workdays)

# 기본은 data/ 폴더. 6단계 커넥터는 hr 스키마를 임시 폴더로 꺼내 그 폴더를 넘김: validate.py <폴더>
ROOT_DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data"
DATA = ROOT_DATA / "hr"
EXTRA = ROOT_DATA / "extra"
SPEC = ["employees", "employee_pii", "family", "leave_balance", "leave_history", "absence_history", "hr_history",
        "business_trips", "payroll", "welfare_points", "training", "requests", "departments", "users", "audit_log"]


def load(path):
    with open(path, encoding="utf-8-sig") as fp:  # BOM 있는 CSV도 읽기
        rows = list(csv.DictReader(fp))
    for r in rows:
        for k in r:
            r[k] = r[k] if r[k] != "" else None
    return rows


T = {n: load(DATA / f"{n}.csv") for n in SPEC}
T["attendance"] = load(EXTRA / "attendance.csv")
EMP = {e["emp_id"]: e for e in T["employees"]}
FAM = {f["family_id"]: f for f in T["family"]}
DEPT = {x["dept_id"]: x for x in T["departments"]}
REQ = {r["request_id"]: r for r in T["requests"]}
for r in T["requests"]:
    r["p"] = json.loads(r["payload"])
fam_by = defaultdict(list)
for f in T["family"]:
    # common.py 계산 함수가 쓰는 내부 이름으로 맞춤
    f["is_dependent_b"] = f["is_dependent"] == "Y"
    fam_by[f["emp_id"]].append(dict(relation={"조부모": "조부"}.get(f["relation"], f["relation"]),
                                    birth_date=f["birth_date"], is_dependent=f["is_dependent"] == "Y",
                                    added_date=f["registered_at"] or "2999-12-31", death_date=f["deceased_date"]))
hist_by = defaultdict(list)
for h in T["hr_history"]:
    hist_by[h["emp_id"]].append(h)
for v in hist_by.values():
    v.sort(key=lambda h: (h["effective_date"], h["event_type"] != "입사", h["history_id"]))
absence = defaultdict(list)
for a in T["absence_history"]:
    absence[a["emp_id"]].append((d(a["start_date"]), d(a["end_date"])))

results = []


def check(name, errors):
    results.append((name, len(errors), errors[:3]))


def in_abs(emp_id, day):
    return any(s <= day <= t for s, t in absence[emp_id])


def active_on(e, day):
    return d(e["hire_date"]) <= day and (e["retire_date"] is None or day <= d(e["retire_date"]))


def pattern_at(emp_id, day):
    pat = None
    for h in hist_by[emp_id]:
        if d(h["effective_date"]) <= day and h["to_work_pattern"]:
            pat = h["to_work_pattern"]
    return pat


# 0. 파일 구성 = 팀 기준서
errs = [n for n in SPEC if not (DATA / f"{n}.csv").exists()]
errs += [p.name for p in DATA.glob("*.csv") if p.stem not in SPEC]
check("파일 구성 = 팀 기준서 (CSV 14종 + audit_log)", errs)

# 1. 참조 무결성
errs = []
for t in ["employee_pii", "family", "leave_balance", "leave_history", "absence_history", "hr_history", "business_trips",
          "payroll", "welfare_points", "training", "requests", "users"]:
    errs += [f"{t}:{r['emp_id']}" for r in T[t] if r["emp_id"] not in EMP]
errs += [e["emp_id"] for e in T["employees"] if e["dept_id"] not in DEPT]
errs += [l["leave_id"] for l in T["leave_history"] if l["request_id"] not in REQ or REQ[l["request_id"]]["emp_id"] != l["emp_id"]]
errs += [a["absence_id"] for a in T["absence_history"] if a["child_family_id"] and a["child_family_id"] not in FAM]
errs += [r["request_id"] for r in T["requests"] if r["p"].get("family_id") and r["p"]["family_id"] not in FAM]
check("참조 무결성 (사번·부서·가족·신청서 ID 존재)", errs)

# 2~4. 연차
errs2, errs3 = [], []
used = defaultdict(float)
for l in T["leave_history"]:
    if l["leave_type"] in ("연차", "반차"):
        used[(l["emp_id"], d(l["start_date"]).year)] += float(l["days"])
errs4 = []
for b in T["leave_balance"]:
    g, c, u = float(b["granted_days"]), float(b["carried_days"]), float(b["used_days"])
    if abs(g + c - u - float(b["remaining_days"])) > 1e-9:
        errs2.append(f"{b['emp_id']} {b['year']}")
    if g != annual_grant(d(EMP[b["emp_id"]]["hire_date"]), int(b["year"]), d(b["asof_date"])):
        errs3.append(f"{b['emp_id']} {b['year']}")
    if abs(u - used[(b["emp_id"], int(b["year"]))]) > 1e-9:
        errs4.append(f"{b['emp_id']} {b['year']}")
check("연차 잔여 = 부여 + 이월 − 사용", errs2)
check("연차 부여 일수 = 규칙표 공식", errs3)
check("연차 사용 일수 = 휴가 기록(연차·반차) 합계", errs4)

# 5. 휴가 날짜 규칙 + 장기재직휴가 사용 여부
errs, seen = [], defaultdict(set)
lsl = {(l["emp_id"], d(l["start_date"]).year) for l in T["leave_history"] if l["leave_type"] == "장기재직"}
for l in T["leave_history"]:
    s, t = d(l["start_date"]), d(l["end_date"])
    e = EMP[l["emp_id"]]
    if l["leave_type"] == "출산전후":
        days = [x for x in (s + dt.timedelta(days=i) for i in range((t - s).days + 1)) if is_workday(x)]
        if (t - s).days + 1 != RULES["maternity_leave"]["days"]:
            errs.append(f"{l['leave_id']} 출산전후휴가 기간")
    else:
        days = workdays(s, t)
        expect = 0.5 if l["leave_type"] == "반차" else len(days)
        if float(l["days"]) != expect:
            errs.append(f"{l['leave_id']} 일수≠근무일")
    for x in days:
        if x in seen[l["emp_id"]]:
            errs.append(f"{l['leave_id']} 겹침 {x}")
        seen[l["emp_id"]].add(x)
        if in_abs(l["emp_id"], x) or not active_on(e, x):
            errs.append(f"{l['leave_id']} 휴직·재직기간 밖 {x}")
    if l["leave_type"] != "병가" and (l["is_work_related"] == "Y" or l["has_medical_cert"] == "Y"):
        errs.append(f"{l['leave_id']} 병가 아닌데 업무상·진단서 표시")
for b in T["leave_balance"]:
    if (b["long_service_leave_used"] == "Y") != ((b["emp_id"], int(b["year"])) in lsl):
        errs.append(f"{b['emp_id']} {b['year']} 장기재직휴가 사용 여부")
check("휴가: 근무일 계산·겹침 없음·휴직/재직 기간 안·병가 표시·장기재직 여부", errs)

# 6. 성별 휴가
F_ONLY = {"출산전후", "생리휴가", "유산사산휴가"}
errs = [l["leave_id"] for l in T["leave_history"]
        if (l["leave_type"] in F_ONLY and EMP[l["emp_id"]]["gender"] != "F")
        or (l["leave_type"] == "배우자출산" and EMP[l["emp_id"]]["gender"] != "M")]
check("성별에 맞는 휴가만 존재", errs)

# 7. 청원·배우자출산 휴가 ↔ 신청서 ↔ 가족 기록 ↔ 규칙표
errs = []
rel_cat = {"부": "부모 사망", "모": "부모 사망", "배우자부": "배우자 부모 사망", "배우자모": "배우자 부모 사망",
           "조부모": "조부모 사망", "배우자": "본인 결혼"}
for l in T["leave_history"]:
    r = REQ.get(l["request_id"])
    if not r:
        continue
    if r["request_type"] != "휴가신청" or r["status"] != "승인" or r["p"]["leave_type"] != l["leave_type"] \
            or r["p"]["start_date"] != l["start_date"] or float(r["p"]["days"]) != float(l["days"]):
        errs.append(f"{l['leave_id']} 신청서 내용≠휴가 기록")
    if d(r["decided_at"]) < d(r["created_at"]):
        errs.append(f"{l['leave_id']} 결정일 < 신청일")
    if l["leave_type"] in ("청원", "배우자출산"):
        f = FAM.get(r["p"].get("family_id"))
        if not f or f["emp_id"] != l["emp_id"]:
            errs.append(f"{l['leave_id']} 가족 연결 없음")
            continue
    if l["leave_type"] == "청원":
        ev = r["event_type"]
        if rel_cat.get(f["relation"]) != ev:
            errs.append(f"{l['leave_id']} 관계-사유 불일치")
        if float(l["days"]) != RULES["condolence_leave"][ev]:
            errs.append(f"{l['leave_id']} 일수≠규칙표")
        if "사망" in ev:
            if not f["deceased_date"] or d(l["start_date"]) != first_workday(d(f["deceased_date"])):
                errs.append(f"{l['leave_id']} 사망일 불일치")
            elif d(r["created_at"]) < d(f["deceased_date"]) or d(r["decided_at"]) < d(f["deceased_date"]):
                errs.append(f"{l['leave_id']} 사망일 전에 신청·승인됨")
    if l["leave_type"] == "배우자출산":
        if f["relation"] != "자녀" or not (0 <= (d(l["start_date"]) - d(f["birth_date"])).days <= 120):
            errs.append(f"{l['leave_id']} 자녀 출생일과 불일치")
        if float(l["days"]) != RULES["paternity_leave"]["days"]:
            errs.append(f"{l['leave_id']} 일수≠20")
check("청원·배우자출산 휴가 ↔ 신청서 ↔ 가족 기록 ↔ 규칙표", errs)

# 8. 출퇴근(부가 파일): 종일 휴가·휴직·휴일 기록 없음, 반차 일치
full_leave, half_leave = set(), set()
for l in T["leave_history"]:
    s, t = d(l["start_date"]), d(l["end_date"])
    if l["leave_type"] == "반차":
        half_leave.add((l["emp_id"], s))
    else:
        for i in range((t - s).days + 1):
            full_leave.add((l["emp_id"], s + dt.timedelta(days=i)))
errs, att_days = [], set()
for a in T["attendance"]:
    x = d(a["work_date"])
    k = (a["emp_id"], x)
    att_days.add(k)
    if k in full_leave:
        errs.append(f"{a['emp_id']} {x} 휴가일 출근")
    if in_abs(a["emp_id"], x):
        errs.append(f"{a['emp_id']} {x} 휴직 중 출근")
    if not is_workday(x) or not active_on(EMP[a["emp_id"]], x):
        errs.append(f"{a['emp_id']} {x} 휴일/재직기간 밖")
    if (k in half_leave) != (a["status"] in ("오전반차", "오후반차")):
        errs.append(f"{a['emp_id']} {x} 반차 상태 불일치")
for k in half_leave:
    if d("2025-11-01") <= k[1] <= ATT_END and k not in att_days:
        errs.append(f"{k} 반차인데 출근 기록 없음")
check("출퇴근(부가): 휴가·휴직·휴일 기록 없음, 반차 일치", errs)

# 9. 급여 재계산
att_m = defaultdict(lambda: [0.0, 0.0])
for a in T["attendance"]:
    k = (a["emp_id"], a["work_date"][:7])
    att_m[k][0] += float(a["overtime_hours"])
    att_m[k][1] += float(a["night_hours"])
OT = RULES["overtime"]
errs = []
for p in T["payroll"]:
    e = EMP[p["emp_id"]]
    ym, ms, me = p["pay_month"], month_start(p["pay_month"]), month_end(p["pay_month"])
    i = lambda k: int(p[k])
    bp = base_pay(int(p["grade"]), d(e["hire_date"]), ms)
    duty = RULES["duty_allowance"][e["duty"]]
    pat = pattern_at(p["emp_id"], ms)
    if pat != p["work_pattern"]:
        errs.append(f"{p['emp_id']} {ym} 근무형태≠인사이력")
    shift, lsa = shift_allowance(p["work_pattern"]), long_service_allowance(d(e["hire_date"]), ms)
    ordinary = ordinary_wage(bp, duty, shift, lsa)
    ot, night = att_m[(p["emp_id"], ym)]
    hw = hourly_wage(ordinary)
    want = {
        "base_pay": bp, "duty_allowance": duty, "shift_allowance": shift, "long_service_allowance": lsa,
        "ordinary_wage": ordinary, "meal_allowance": RULES["meal_allowance"]["amount"],
        "family_allowance": family_allowance(fam_by[p["emp_id"]], ym),
        "overtime_pay": won10(hw * OT["overtime_rate"] * ot), "night_pay": won10(hw * OT["night_extra_rate"] * night),
        "holiday_pay": won10(hw * OT["holiday_rate"] * float(p["holiday_hours"])),
        "holiday_bonus": won10(bp * RULES["bonus"]["holiday_rate"]) if ym in RULES["bonus"]["holiday_months"] else 0,
    }
    for k, v in want.items():
        if i(k) != v:
            errs.append(f"{p['emp_id']} {ym} {k} {i(k)}≠{v}")
    gross = sum(i(k) for k in ["base_pay", "duty_allowance", "shift_allowance", "long_service_allowance",
                               "meal_allowance", "family_allowance", "overtime_pay", "night_pay", "holiday_pay",
                               "holiday_bonus", "performance_bonus"])
    if gross != i("gross_pay"):
        errs.append(f"{p['emp_id']} {ym} 총지급액")
    ded = deductions(gross, i("meal_allowance"))
    if any(i(k) != v for k, v in ded.items()) or i("deductions") != sum(ded.values()):
        errs.append(f"{p['emp_id']} {ym} 공제")
    if i("net_pay") != gross - sum(ded.values()):
        errs.append(f"{p['emp_id']} {ym} 실수령액")
    if abs(float(p["overtime_hours"]) - ot) > 1e-9:
        errs.append(f"{p['emp_id']} {ym} 연장시간≠출퇴근 합계")
    if not active_on(e, ms) or not active_on(e, me) or any(s <= ms and me <= t for s, t in absence[p["emp_id"]]):
        errs.append(f"{p['emp_id']} {ym} 재직·휴직 기간 위반")
    g = None
    for h in hist_by[p["emp_id"]]:
        if d(h["effective_date"]) <= ms and h["to_grade"]:
            g = int(h["to_grade"])
    if g != int(p["grade"]):
        errs.append(f"{p['emp_id']} {ym} 직급≠인사이력")
check("급여: 규칙표·가족·출퇴근·인사이력으로 재계산 일치 (통상임금·교대·장기근속·휴일 포함)", errs)

# 10. 복지포인트 (연도별 요약)
errs = []
for w in T["welfare_points"]:
    e = EMP[w["emp_id"]]
    g, u = int(w["granted_points"]), int(w["used_points"])
    if g != welfare_allocation(d(e["hire_date"]), fam_by[w["emp_id"]], int(w["year"])):
        errs.append(f"{w['emp_id']} {w['year']} 배정≠공식")
    if not 0 <= u <= g:
        errs.append(f"{w['emp_id']} {w['year']} 사용>배정")
    if w["expires_on"] != f"{w['year']}-12-31":
        errs.append(f"{w['emp_id']} {w['year']} 소멸일")
    if e["employment_type"] not in RULES["welfare_korail"]["selective_welfare"]["eligible"]:
        errs.append(f"{w['emp_id']} 선택복지 대상 아님")
check("복지포인트: 배정 공식·사용≤배정·연말 소멸·대상 고용형태", errs)

# 11. 직원·가족·조직·계정 논리
errs = []
CO = RULES["company"]
for idx, e in enumerate(T["employees"]):
    eid = e["emp_id"]
    h = hist_by[eid]
    if eid != f"{CO['emp_id_prefix']}{CO['emp_id_start'] + idx}":
        errs.append(f"{eid} 사번 형식·순서")
    if e["employment_type"] not in RULES["employment_types"]["in_scope"]:
        errs.append(f"{eid} 범위 밖 고용형태 {e['employment_type']}")
    if age_on(d(e["birth_date"]), d(e["hire_date"])) < 18:
        errs.append(f"{eid} 18세 미만 입사")
    if e["status"] != "퇴직" and age_on(d(e["birth_date"]), TODAY) >= CO["retire_age"]:
        errs.append(f"{eid} 정년 초과 재직")
    if (e["status"] == "휴직") != in_abs(eid, TODAY):
        errs.append(f"{eid} 상태≠휴직 기간")
    if (e["status"] == "퇴직") != (e["retire_date"] is not None and d(e["retire_date"]) < TODAY):
        errs.append(f"{eid} 상태≠퇴직일")
    if (e["retire_date"] is None) != (e["retire_type"] is None):
        errs.append(f"{eid} 퇴직일↔퇴직 유형")
    depts = [x["to_dept"] for x in h if x["to_dept"]]
    if depts[-1] != e["dept_id"] or e["site"] != DEPT[e["dept_id"]]["site"]:
        errs.append(f"{eid} 부서·근무지≠마지막 발령")
    grades = [x["to_grade"] for x in h if x["to_grade"]]
    if int(grades[-1]) != int(e["grade"]) or RULES["grades"][e["grade"]]["position"] != e["position"]:
        errs.append(f"{eid} 직급·직위≠발령")
    promos = [x["effective_date"] for x in h if x["event_type"] == "승진"]
    if (promos[-1] if promos else None) != e["last_promotion_date"]:
        errs.append(f"{eid} 최근 승진일")
    if h[0]["event_type"] != "입사" or h[0]["effective_date"] != e["hire_date"]:
        errs.append(f"{eid} 첫 이력≠입사")
    if d(e["probation_end_date"]) != probation_end(d(e["hire_date"])):
        errs.append(f"{eid} 수습 종료일")
    if pattern_at(eid, TODAY) != e["work_pattern"] \
            or int(e["weekly_hours"]) != RULES["work_patterns"][e["work_pattern"]]["weekly_hours"]:
        errs.append(f"{eid} 근무형태≠인사이력")
    chg = [x["effective_date"] for x in h if x["event_type"] == "근무형태변경"]
    if e["work_pattern_since"] != (chg[-1] if chg else e["hire_date"]):
        errs.append(f"{eid} 근무형태 시작일")
    if int(e["base_salary"]) != base_pay(int(e["grade"]), d(e["hire_date"]), month_start("2026-11")):
        errs.append(f"{eid} 기본급≠규칙표")
    if e["email"] != f"{eid.lower()}@{CO['email_domain']}":
        errs.append(f"{eid} 이메일 형식")
    for x in h:
        if x["event_type"] == "전보":
            reloc = DEPT[x["from_dept"]]["site"] != DEPT[x["to_dept"]]["site"]
            if (x["is_relocation"] == "Y") != reloc:
                errs.append(f"{x['history_id']} 원거리 전근 표시")
kids_by = defaultdict(list)
for f in T["family"]:
    e = EMP[f["emp_id"]]
    born = d(f["birth_date"]) <= TODAY
    if f["relation"] == "자녀":
        kids_by[f["emp_id"]].append(f)
        want_dep = born and age_on(d(f["birth_date"]), TODAY) < 20
        if (f["is_dependent"] == "Y") != want_dep:
            errs.append(f"{f['family_id']} 자녀 부양 여부")
        if (f["school_level"] or "") != school_level(d(f["birth_date"]), TODAY):
            errs.append(f"{f['family_id']} 학교급")
        if not born and f["registered_at"]:
            errs.append(f"{f['family_id']} 출생 전 가족 등록")
    elif f["child_order"] or f["school_level"]:
        errs.append(f"{f['family_id']} 자녀 아닌데 순위·학교급")
    if f["deceased_date"] and d(f["deceased_date"]) > TODAY:
        errs.append(f"{f['family_id']} 미래 사망일")
    if f["relation"] == "배우자" and f["gender"] == e["gender"]:
        errs.append(f"{f['family_id']} 배우자 성별")
for eid, ks in kids_by.items():
    ks.sort(key=lambda f: f["birth_date"])
    if [int(f["child_order"]) for f in ks] != list(range(1, len(ks) + 1)):
        errs.append(f"{eid} 자녀 순위")
heads = [x["head_emp_id"] for x in T["departments"] if x["head_emp_id"]]
errs += [h for h in heads if EMP[h]["duty"] not in ("팀장", "본부장")]
errs += [u["emp_id"] for u in T["users"] if (u["is_active"] == "true") == (EMP[u["emp_id"]]["status"] == "퇴직")]
errs += [u["emp_id"] for u in T["users"] if u["login_id"] != u["emp_id"].lower()]
check("직원·가족·조직·계정 논리 (사번·정규직·수습·근무형태·승진일·근무지·자녀 순위·학교급)", errs)

# 12. 교육
errs = []
for t in T["training"]:
    if (t["status"] == "이수") != (t["completed_on"] is not None) or (t["completed_on"] and d(t["completed_on"]) > ATT_END):
        errs.append(f"{t['training_id']} 이수 상태↔이수일")
    if (t["course_type"] in ("법정", "신규", "승진", "리더십")) != (t["required"] == "Y"):
        errs.append(f"{t['training_id']} 필수 여부")
new_hires = {e["emp_id"] for e in T["employees"] if d(e["hire_date"]).year in (2025, 2026)}
has_new = {t["emp_id"] for t in T["training"] if t["course_type"] == "신규"}
errs += [f"{x} 신규입사자 교육 없음" for x in new_hires - has_new]
errs += [f"{x} 신규 아닌데 신규 교육" for x in has_new - new_hires]
check("교육: 이수 상태·필수 여부·신규입사자 교육", errs)

# 13. 개인정보 분리·가짜 형식 (마스킹 기준서 7장)
errs = []
PII_IN_EMP = {"phone", "mobile", "address", "rrn", "account_no"}
errs += [f"employees에 개인정보 열 {c}" for c in T["employees"][0] if c in PII_IN_EMP]
pii = {p["emp_id"]: p for p in T["employee_pii"]}
errs += [f"{x} pii 없음" for x in EMP if x not in pii]
W = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
for eid, p in pii.items():
    e = EMP[eid]
    m = re.fullmatch(r"(\d{6})-(\d)(\d{6})", p["rrn"] or "")
    if not m:
        errs.append(f"{eid} 주민번호 형식"); continue
    b = d(e["birth_date"])
    gd = (1 if e["gender"] == "M" else 2) + (2 if b.year >= 2000 else 0)
    if m.group(1) != b.strftime("%y%m%d") or int(m.group(2)) != gd:
        errs.append(f"{eid} 주민번호 앞자리≠생년월일·성별")
    digits = m.group(1) + m.group(2) + m.group(3)
    if (11 - sum(int(c) * w for c, w in zip(digits[:12], W)) % 11) % 10 == int(digits[12]):
        errs.append(f"{eid} 주민번호 검증숫자가 맞음(실제 번호처럼 보임)")
    if not re.fullmatch(r"999-\d{2}-\d{6}", p["account_no"] or "") or p["bank_name"] != "테스트은행":
        errs.append(f"{eid} 계좌 형식")
    if not re.fullmatch(r"010-[2-9]\d{3}-\d{4}", p["mobile"] or "") or not re.fullmatch(r"010-[2-9]\d{3}-\d{4}", p["emergency_phone"] or ""):
        errs.append(f"{eid} 전화 형식(010-XXXX-XXXX)")
mobiles = [p["mobile"] for p in T["employee_pii"]] + [p["emergency_phone"] for p in T["employee_pii"]]
if len(mobiles) != len(set(mobiles)):
    errs.append("전화번호 중복")
check("개인정보 분리·가짜 형식 (pii 파일만, 전화 010-XXXX-XXXX·중복 없음, 999 계좌, 주민번호 검증숫자 틀림)", errs)

# 14. 경조금·출산축하금 신청서 (코레일 2025 기준표)
WK = RULES["welfare_korail"]
CM, BB = WK["condolence_money"], WK["birth_bonus"]
DEATH_CAT = {"부": "부모 사망", "모": "부모 사망", "배우자부": "배우자 부모 사망", "배우자모": "배우자 부모 사망",
             "조부모": "조부모 사망", "배우자": "배우자 사망", "자녀": "자녀 사망"}
ORDER = {"첫째 출생": ("first", 1), "둘째 출생": ("second", 2), "셋째 이상 출생": ("third_plus", 3)}
errs, seen_k = [], set()
paid = set()
for r in T["requests"]:
    if r["request_type"] not in ("경조금신청", "출산축하금신청") or r["status"] != "지급완료":
        continue
    rid, e, p = r["request_id"], EMP[r["emp_id"]], r["p"]
    f = FAM.get(p.get("family_id"))
    if not f or f["emp_id"] != r["emp_id"]:
        errs.append(f"{rid} 가족 연결 없음"); continue
    ev, amt, et = d(p["event_date"]), int(p["amount"]), e["employment_type"]
    paid.add((f["family_id"], p["pay_type"]))
    if not (ev <= d(r["created_at"]) <= d(r["decided_at"]) <= ATT_END):
        errs.append(f"{rid} 신청·지급일 순서")
    if not active_on(e, ev):
        errs.append(f"{rid} 재직 기간 밖 사건")
    key = (f["family_id"], p["pay_type"], r["event_type"])
    if key in seen_k:
        errs.append(f"{rid} 중복 지급")
    seen_k.add(key)
    if p["pay_type"] in ("축의금", "조의금"):
        if r["request_type"] != "경조금신청" or et not in CM["eligible"]:
            errs.append(f"{rid} 경조금 대상·종류")
        if amt != CM[p["pay_type"]].get(r["event_type"]):
            errs.append(f"{rid} 금액≠기준표")
        if r["event_type"] == "본인 결혼" and (f["relation"] != "배우자" or f["registered_at"] != p["event_date"]):
            errs.append(f"{rid} 결혼일≠배우자 등록일")
        if p["pay_type"] == "조의금" and (DEATH_CAT.get(f["relation"]) != r["event_type"] or f["deceased_date"] != p["event_date"]):
            errs.append(f"{rid} 사망 기록 불일치")
        if "팔순" in r["event_type"]:
            want = "부모 팔순" if f["relation"] in ("부", "모") else "배우자 부모 팔순"
            if want != r["event_type"] or age_on(d(f["birth_date"]), ev) != 80 or d(f["birth_date"]).replace(year=ev.year) != ev:
                errs.append(f"{rid} 팔순 날짜·관계")
    elif p["pay_type"] == "출산축하금":
        if r["request_type"] != "출산축하금신청" or et not in BB["eligible"]:
            errs.append(f"{rid} 출산축하금 대상 아님({et})")
        k, o = ORDER.get(r["event_type"], (None, 0))
        if f["relation"] != "자녀" or f["birth_date"] != p["event_date"] or min(int(f["child_order"]), 3) != o:
            errs.append(f"{rid} 출생 순서·날짜")
        if k and amt != BB[k]:
            errs.append(f"{rid} 금액≠기준표")
for f in T["family"]:
    e = EMP[f["emp_id"]]
    if f["deceased_date"] and f["relation"] in DEATH_CAT and d("2025-01-01") <= d(f["deceased_date"]) <= ATT_END \
            and e["employment_type"] in CM["eligible"] and active_on(e, d(f["deceased_date"])) \
            and (f["family_id"], "조의금") not in paid:
        errs.append(f"{f['family_id']} 조의금 누락")
check("경조금·출산축하금 신청서: 금액=기준표·대상·가족 기록 일치·중복/누락 없음", errs)

# 15. 휴직 이력 ↔ 인사 이력 ↔ 규칙표
errs = []
for a in T["absence_history"]:
    h = hist_by[a["emp_id"]]
    if not any(x["event_type"] == "휴직" and x["effective_date"] == a["start_date"] for x in h):
        errs.append(f"{a['absence_id']} 인사이력에 휴직 없음")
    ret = a["return_date"]
    if (ret is not None) != (d(a["end_date"]) < TODAY):
        errs.append(f"{a['absence_id']} 복직일 유무")
    if ret and (d(ret) != d(a["end_date"]) + dt.timedelta(days=1)
                or not any(x["event_type"] == "복직" and x["effective_date"] == ret for x in h)):
        errs.append(f"{a['absence_id']} 복직일≠인사이력")
    if float(a["pay_rate"]) != RULES["absence_pay_rate"][a["absence_type"]]:
        errs.append(f"{a['absence_id']} 지급률≠규칙표")
    c = FAM.get(a["child_family_id"])
    if (a["absence_type"] == "육아") != (c is not None) or (c and (c["relation"] != "자녀" or c["emp_id"] != a["emp_id"])):
        errs.append(f"{a['absence_id']} 육아휴직 대상 자녀")
check("휴직 이력 ↔ 인사 이력 ↔ 규칙표 (복직일·지급률·대상 자녀)", errs)

# 16. 출장
errs, trip_days = [], defaultdict(set)
for t in T["business_trips"]:
    s, e_ = d(t["start_date"]), d(t["end_date"])
    emp = EMP[t["emp_id"]]
    if int(t["nights"]) != (e_ - s).days or t["region_type"] not in RULES["business_trip"]["region_types"]:
        errs.append(f"{t['trip_id']} 박수·지역")
    want = "완료" if e_ < TODAY else "진행중" if s <= TODAY else "승인"
    if t["status"] != want:
        errs.append(f"{t['trip_id']} 상태")
    for i in range((e_ - s).days + 1):
        x = s + dt.timedelta(days=i)
        if (t["emp_id"], x) in full_leave or in_abs(t["emp_id"], x) or not active_on(emp, x) or x in trip_days[t["emp_id"]]:
            errs.append(f"{t['trip_id']} 휴가·휴직·다른 출장과 겹침 {x}")
            break
        trip_days[t["emp_id"]].add(x)
    if not any(r["request_type"] == "출장신청" and r["p"].get("trip_id") == t["trip_id"] for r in T["requests"]):
        errs.append(f"{t['trip_id']} 출장신청서 없음")
check("출장: 박수·지역·상태·겹침 없음·신청서", errs)

# 17. 신청서 공통
errs = []
for r in T["requests"]:
    if r["request_type"] not in RULES["request_types"]:
        errs.append(f"{r['request_id']} 신청 종류")
    if r["status"] == "대기":
        if r["decided_at"]:
            errs.append(f"{r['request_id']} 대기인데 결정일")
    elif not r["decided_at"] or d(r["decided_at"]) < d(r["created_at"]):
        errs.append(f"{r['request_id']} 결정일")
check("신청서: 종류·상태·신청일 ≤ 결정일", errs)

# ---------------------------------------------------------------- 결과
fail = 0
for name, n, sample in results:
    mark = "PASS" if n == 0 else "FAIL"
    fail += n > 0
    print(f"[{mark}] {name}" + ("" if n == 0 else f"  ({n}건, 예: {sample})"))
print(f"\n{len(results) - fail}/{len(results)} 통과")
sys.exit(1 if fail else 0)
