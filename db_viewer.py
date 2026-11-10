"""DB 직접 조회 화면: 로컬 hrdb에 바로 붙어서 테이블을 조회하는 작은 웹 화면.

실행: .venv/bin/python db_viewer.py   → 브라우저에서 http://127.0.0.1:8765
끄기: 터미널에서 Ctrl+C (DB도 같이 꺼짐)

- 사본이 아니라 매번 DB에 SQL로 조회함 → DB가 바뀌면 새로고침만 하면 최신 값
- 스키마 4개(erp·hr·rag·app)의 모든 테이블, 페이지 넘김(100행), 검색(행 전체에서 글자 찾기)
- SQL 칸: 직접 SELECT 실행 가능. 읽기 전용 트랜잭션이라 데이터를 바꾸는 문장은 DB가 거부함
- 내 컴퓨터(127.0.0.1)에서만 열림. 다른 컴퓨터에서는 접속 불가
"""
import json
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from db_setup import connect, get_server

HOST, PORT = "127.0.0.1", 8765
SCHEMAS = ["erp", "hr", "rag", "app"]
PAGE = 100
SQL_LIMIT = 1000
HTML = (Path(__file__).parent / "db_viewer.html").read_text(encoding="utf-8")

SRV = get_server()  # 이 프로그램이 켜져 있는 동안 DB도 켜져 있음


def db():
    con = connect(SRV)
    con.execute("SET default_transaction_read_only = on")  # 읽기 전용
    con.execute("SET statement_timeout = '15s'")
    return con


def cell(v):
    if v is None or isinstance(v, (int, float, bool, str)):
        return v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def tables(con):
    rows = con.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name",
        (SCHEMAS,)).fetchall()
    out = {s: [] for s in SCHEMAS}
    for s, t in rows:
        n = con.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0]
        out[s].append({"name": t, "n": n})
    return out


def table_rows(con, schema, table, page, q):
    known = con.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                        (schema, table)).fetchone()
    if not known or schema not in SCHEMAS:
        raise ValueError("없는 테이블")
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=%s AND table_name=%s "
        "ORDER BY ordinal_position", (schema, table)).fetchall()
    pk = [r[0] for r in con.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) "
        "WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)",
        (f'"{schema}"."{table}"',)).fetchall()]
    order = ", ".join(f'"{c}"' for c in (pk or [cols[0][0]]))
    where, args = "", []
    if q:
        where, args = 'WHERE t::text ILIKE %s', [f"%{q}%"]   # 행 전체를 글자로 바꿔 검색
    base = f'FROM "{schema}"."{table}" t {where}'
    total = con.execute(f"SELECT count(*) {base}", args).fetchone()[0]
    rows = con.execute(f"SELECT * {base} ORDER BY {order} LIMIT {PAGE} OFFSET %s",
                       args + [page * PAGE]).fetchall()
    return {"cols": [{"name": c, "type": t} for c, t in cols], "pk": pk, "total": total, "page": page,
            "pages": max(1, -(-total // PAGE)), "rows": [[cell(v) for v in r] for r in rows]}


def run_sql(con, sql):
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise ValueError("문장은 한 번에 하나만 실행할 수 있습니다")
    if s.split(None, 1)[0].lower() not in ("select", "with", "table", "explain", "show", "values"):
        raise ValueError("조회 문장(SELECT, WITH 등)만 실행할 수 있습니다. 이 화면은 데이터를 바꾸지 않습니다")
    sql = s
    t0 = time.time()
    with con.transaction():
        cur = con.execute(sql)
        if cur.description is None:
            return {"cols": [], "rows": [], "note": "결과 행이 없는 문장입니다", "ms": int((time.time() - t0) * 1000)}
        rows = cur.fetchmany(SQL_LIMIT + 1)
    cut = len(rows) > SQL_LIMIT
    return {"cols": [{"name": d.name, "type": ""} for d in cur.description],
            "rows": [[cell(v) for v in r] for r in rows[:SQL_LIMIT]],
            "note": f"앞쪽 {SQL_LIMIT}행만 보여 줍니다" if cut else "", "ms": int((time.time() - t0) * 1000)}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        p = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.send(200, HTML.encode(), "text/html; charset=utf-8")
            with db() as con:
                if u.path == "/api/tables":
                    return self.send(200, tables(con))
                if u.path == "/api/rows":
                    return self.send(200, table_rows(con, p.get("schema", ""), p.get("table", ""),
                                                     max(0, int(p.get("page", 0))), p.get("q", "").strip()))
            self.send(404, {"error": "없는 주소"})
        except Exception as e:
            self.send(400, {"error": str(e).strip()})

    def do_POST(self):
        if urlparse(self.path).path != "/api/sql":
            return self.send(404, {"error": "없는 주소"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            with db() as con:
                self.send(200, run_sql(con, body.get("sql", "")))
        except Exception as e:
            self.send(400, {"error": str(e).strip()})


if __name__ == "__main__":
    print(f"DB 조회 화면: http://{HOST}:{PORT}   (끄려면 Ctrl+C)")
    try:
        ThreadingHTTPServer((HOST, PORT), H).serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
