"""오류 주입 시험: 복사본에 오류를 하나씩 넣고 validate.py가 잡는지 확인. 실행: .venv/bin/python test_validate.py"""
import csv, json, shutil, subprocess, sys, tempfile
from pathlib import Path
SRC = Path(__file__).parent
PY = str(SRC / ".venv/bin/python")

def rw(root, name, fn, folder="hr"):
    p = root / "data" / folder / f"{name}.csv"
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig"))); cols = list(rows[0].keys()) if rows else []
    fn(rows)
    w = csv.DictWriter(open(p, "w", newline="", encoding="utf-8-sig"), fieldnames=cols); w.writeheader(); w.writerows(rows)

def first(rows, cond): return next(r for r in rows if cond(r))

CASES = {
 "비정규직 직원 1명": ("employees", lambda R: first(R, lambda r: True).update(employment_type="비정규직")),
 "휴대폰 형식 틀림(자리수)": ("employee_pii", lambda R: R[5].update(mobile="010-123-4567")),
 "휴대폰 번호 중복": ("employee_pii", lambda R: R[5].update(mobile=R[6]["mobile"])),
 "주민번호 검증숫자를 맞게(실제처럼)": ("employee_pii", None),
 "조의금 금액 틀림(100만→70만)": ("requests", lambda R: first(R, lambda r: r["request_type"]=="경조금신청" and "사망" in r["event_type"] and "부모" in r["event_type"]).update(
        payload=json.dumps({**json.loads(first(R, lambda r: r["request_type"]=="경조금신청" and "사망" in r["event_type"] and "부모" in r["event_type"])["payload"]), "amount": 700000}, ensure_ascii=False))),
 "자녀 순위 틀림": ("family", lambda R: first(R, lambda r: r["child_order"]=="2").update(child_order="1")),
 "휴직 지급률 틀림": ("absence_history", lambda R: R[0].update(pay_rate="0.9")),
 "출장 박수 틀림": ("business_trips", lambda R: first(R, lambda r: int(r["nights"])>0).update(nights="0")),
 "교대수당 누락(급여)": ("payroll", lambda R: first(R, lambda r: r["work_pattern"]=="교대근무").update(shift_allowance="0")),
 "수습 종료일 틀림": ("employees", lambda R: R[3].update(probation_end_date="2099-01-01")),
 "결정일이 신청일보다 빠름": ("requests", lambda R: first(R, lambda r: r["request_type"]=="출장신청").update(decided_at="2000-01-01")),
}
def rrn_valid(R):
    W=[2,3,4,5,6,7,8,9,2,3,4,5]; r=R[7]; body=r["rrn"].replace("-","")[:12]
    c=(11-sum(int(a)*w for a,w in zip(body,W))%11)%10; r["rrn"]=r["rrn"][:-1]+str(c)
CASES["주민번호 검증숫자를 맞게(실제처럼)"]=("employee_pii", rrn_valid)

caught = 0
for name, (table, fn) in CASES.items():
    tmp = Path(tempfile.mkdtemp())
    for f in ["common.py", "validate.py"]: shutil.copy(SRC / f, tmp / f)
    shutil.copytree(SRC / "rules", tmp / "rules"); shutil.copytree(SRC / "data", tmp / "data")
    rw(tmp, table, fn)
    out = subprocess.run([PY, "validate.py"], cwd=tmp, capture_output=True, text=True).stdout
    fails = [l for l in out.splitlines() if l.startswith("[FAIL]")]
    ok = bool(fails); caught += ok
    print(f"{'✅ 잡음' if ok else '❌ 놓침'} | {name}")
    for l in fails: print("      ", l[:150])
    shutil.rmtree(tmp)
print(f"\n{caught}/{len(CASES)} 잡음")
