"""5단계 회사 DB 흉내: 표준 CSV(팀 기준서) → 회사식 이름·코드·날짜로 바꿔서 → hrdb 의 erp 스키마.

실행: .venv/bin/python load_erp.py

왜 바꾸나: 실제 고객사 DB는 우리 형식과 다름 (열 이름이 '사원번호', 고용형태가 코드 '1', 날짜가 '20260109').
           6단계 커넥터가 이 차이를 연결표(mapping/nuri.yaml)로 메우는 걸 보여 주려고 일부러 다르게 만듦.

하는 일
  1. mapping/nuri.yaml 읽기 (표준 이름 ↔ 회사 이름, 코드표, 날짜 형식)
  2. CSV 16개를 읽어 연결표를 "거꾸로" 적용: 테이블·열 이름 → 회사식, 코드 열 → 코드값, 날짜 → 8자리 글자
  3. erp 스키마를 지우고 새로 만들어 적재 (기본키·외래키 포함, 여러 번 돌려도 결과 같음)
  4. 왕복 검사: erp에서 다시 읽어 연결표를 "그대로" 적용하면 원래 CSV와 한 칸도 안 틀리는지 확인
     → 통과하면 연결표가 빠짐없이 맞다는 뜻 (6단계 커넥터가 같은 표를 씀)
"""
import csv
import json
import re
from decimal import Decimal
from pathlib import Path

import yaml

from db_setup import connect, get_server

HERE = Path(__file__).parent
SRC = [HERE / "data/hr", HERE / "data/extra"]
MAP = yaml.safe_load(open(HERE / "mapping/nuri.yaml", encoding="utf-8"))

# 적재 순서 = 외래키 순서 (사원이 먼저 있어야 나머지가 참조 가능). 이름은 표준 이름
ORDER = ["departments", "employees", "employee_pii", "users", "family", "hr_history",
         "absence_history", "leave_balance", "leave_history", "requests", "payroll",
         "welfare_points", "training", "business_trips", "audit_log", "attendance"]
PK = {"leave_balance": ["emp_id", "year"], "welfare_points": ["emp_id", "year"],
      "attendance": ["emp_id", "work_date"]}          # 나머지는 첫 번째 열
FK = {"employees": [("dept_id", "departments", "dept_id")],
      "absence_history": [("child_family_id", "family", "family_id")]}
for t in ORDER[2:]:
    if t != "audit_log":
        FK.setdefault(t, []).insert(0, ("emp_id", "employees", "emp_id"))

PATTERNS = [("integer", r"-?\d{1,9}"), ("bigint", r"-?\d+"), ("numeric", r"-?\d+\.\d+|-?\d+"),
            ("date", r"\d{4}-\d{2}-\d{2}"), ("time", r"\d{2}:\d{2}(:\d{2})?"), ("boolean", r"true|false")]
KEEP_TEXT = {"emp_id", "zipcode", "mobile", "account_no", "rrn", "pay_month"}  # 숫자처럼 보여도 글자


def std_type(col, values):
    """표준 CSV 값 모양으로 표준 타입 추정 (6단계 hr 스키마도 같은 함수를 씀)."""
    vals = [v for v in values if v != ""]
    if col == "payload":
        return "jsonb"
    if col in KEEP_TEXT or not vals:
        return "text"
    for typ, pat in PATTERNS:
        if all(re.fullmatch(pat, v) for v in vals):
            return typ
    return "text"


def tname(t):
    return MAP["tables"][t]["name"]


def cname(t, c):
    return MAP["tables"][t]["columns"][c]


def code_table(t, c):
    key = MAP["code_columns"].get(f"{t}.{c}")
    return MAP["codes"][key] if key else None


def to_company(t, c, typ, v):
    """표준 값 → 회사 DB 값 (연결표를 거꾸로)."""
    if v == "":
        return None
    codes = code_table(t, c)
    if codes is not None:
        if v not in codes:
            raise ValueError(f"{t}.{c} 값 '{v}'가 코드표에 없음 → mapping/nuri.yaml codes에 추가 필요")
        return codes[v]
    if typ == "date":
        return v.replace("-", "")
    return v


def company_type(t, c, typ):
    if code_table(t, c) is not None:
        return "varchar(4)"
    return {"date": "char(8)", "boolean": "char(1)"}.get(typ, typ)


def to_standard(t, c, v):
    """회사 DB 값 → 표준 값 (연결표 그대로, 6단계 커넥터와 같은 규칙). 왕복 검사용."""
    if v is None:
        return ""
    codes = code_table(t, c)
    if codes is not None:
        back = {code: std for std, code in codes.items()}
        return back[v]
    if isinstance(v, str) and re.fullmatch(r"\d{8}", v) and c not in KEEP_TEXT:
        return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    return v


def same(a, b):
    """왕복 비교: 표준 CSV 글자 a 와 되돌린 값 b 가 같은 값인지."""
    if isinstance(b, (dict, list)):
        return json.loads(a) == b
    if isinstance(b, (int, float, Decimal)):
        return a != "" and Decimal(a) == Decimal(b)
    if hasattr(b, "strftime"):  # time
        return b.strftime("%H:%M") == a[:5]
    return str(b) == a


def find_csv(t):
    return next(d / f"{t}.csv" for d in SRC if (d / f"{t}.csv").exists())


def main():
    srv = get_server()
    report, fails = [], []
    with connect(srv) as con:
        con.execute("DROP SCHEMA IF EXISTS erp CASCADE")
        con.execute("CREATE SCHEMA erp")
        con.execute("COMMENT ON SCHEMA erp IS '고객사(누리철도) 인사 DB 역할. 회사식 이름·코드·8자리 날짜. 5단계 load_erp.py'")

        for t in ORDER:
            with open(find_csv(t), encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            header, data = rows[0], rows[1:]
            if set(header) != set(MAP["tables"][t]["columns"]):
                raise SystemExit(f"{t}: CSV 열과 연결표 열이 다름 → {set(header) ^ set(MAP['tables'][t]['columns'])}")
            types = [std_type(c, [r[i] for r in data]) for i, c in enumerate(header)]

            cols = [f'"{cname(t, c)}" {company_type(t, c, ty)}' for c, ty in zip(header, types)]
            cols.append("PRIMARY KEY (" + ", ".join(f'"{cname(t, c)}"' for c in PK.get(t, [header[0]])) + ")")
            for c, rt, rc in FK.get(t, []):
                cols.append(f'FOREIGN KEY ("{cname(t, c)}") REFERENCES erp."{tname(rt)}"("{cname(rt, rc)}")')
            con.execute(f'CREATE TABLE erp."{tname(t)}" (\n  ' + ",\n  ".join(cols) + "\n)")

            col_list = ", ".join(f'"{cname(t, c)}"' for c in header)
            with con.cursor().copy(f'COPY erp."{tname(t)}" ({col_list}) FROM STDIN') as cp:
                for r in data:
                    cp.write_row([to_company(t, c, ty, v) for c, ty, v in zip(header, types, r)])

            # 왕복 검사: erp → 표준으로 되돌려 CSV와 비교
            back = con.execute(f'SELECT {col_list} FROM erp."{tname(t)}" ORDER BY ' +
                               ", ".join(f'"{cname(t, c)}"' for c in PK.get(t, [header[0]]))).fetchall()
            pk_idx = [header.index(c) for c in PK.get(t, [header[0]])]
            key = (lambda r: tuple(int(r[i]) if r[i].isdigit() else r[i] for i in pk_idx))
            data_sorted = sorted(data, key=key)
            bad = 0
            for orig, row in zip(data_sorted, back):
                for i, c in enumerate(header):
                    if not same(orig[i], to_standard(t, c, row[i])):
                        bad += 1
                        if len(fails) < 5:
                            fails.append(f"{t}.{c}: CSV '{orig[i]}' ≠ 되돌린 값 '{row[i]}'")
            report.append((t, tname(t), len(data), len(back), bad))

        con.execute(f'ALTER TABLE erp."{tname("departments")}" ADD FOREIGN KEY ("{cname("departments", "head_emp_id")}") '
                    f'REFERENCES erp."{tname("employees")}"("{cname("employees", "emp_id")}")')
        for t in ORDER:
            if t not in ("employees", "audit_log") and "emp_id" in MAP["tables"][t]["columns"]:
                con.execute(f'CREATE INDEX ON erp."{tname(t)}" ("{cname(t, "emp_id")}")')

    print(f"{'표준 이름':<16} {'회사 DB 이름':<12} {'CSV':>8} {'DB':>8}  왕복 검사")
    for t, ct, n_csv, n_db, bad in report:
        print(f"{t:<16} {ct:<12} {n_csv:>8} {n_db:>8}  {'일치' if bad == 0 and n_csv == n_db else f'틀림 {bad}칸'}")
    ok = all(b == 0 and a == c for _, _, a, c, b in report)
    print(f"\n{len(report)}개 테이블 적재 — " + ("행 수·값 모두 일치 (연결표로 원래대로 되돌릴 수 있음)" if ok else "문제 있음"))
    for f in fails:
        print("  ", f)


if __name__ == "__main__":
    main()
