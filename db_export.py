"""DB 배포 파일 만들기: 로컬 hrdb 전체를 SQL 덤프로 꺼내 deploy/initdb/ 에 저장하고, 새 DB에 되살려 건수가 같은지 확인.

실행: .venv/bin/python db_export.py
결과
  deploy/initdb/00_extensions.sql   pgvector 확장 + 커넥터 역할
  deploy/initdb/01_hrdb.sql.gz      스키마 erp·erp_ro·hr·rag·app 전체 (테이블·뷰·색인·데이터·임베딩)
  deploy/initdb/02_grants.sql       커넥터 역할 권한 (erp_ro 뷰 SELECT만)
→ docker-compose.yml 이 이 폴더를 /docker-entrypoint-initdb.d 로 올려서, 처음 켤 때 자동으로 같은 DB가 만들어짐
확인: 덤프를 임시 DB(hrdb_restore_check)에 되살려 모든 테이블 건수를 원본과 비교한 뒤 임시 DB 삭제
"""
import gzip
import shutil
import subprocess
from pathlib import Path

import pgserver

from db_setup import DB_NAME, connect, get_server, host_args

HERE = Path(__file__).parent
OUT = HERE / "deploy/initdb"
BIN = Path(pgserver.__file__).parent / "pginstall/bin"
SCHEMAS = ["erp", "erp_ro", "hr", "rag", "app"]
CHECK_DB = "hrdb_restore_check"


def counts(con):
    rows = con.execute("SELECT table_schema, table_name FROM information_schema.tables "
                       "WHERE table_schema = ANY(%s) AND table_type='BASE TABLE' ORDER BY 1, 2", (SCHEMAS,)).fetchall()
    return {f"{s}.{t}": con.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0] for s, t in rows}


def main():
    srv = get_server()
    host = host_args(srv)
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "00_extensions.sql").write_text(
        "-- 1) 확장과 역할 (덤프보다 먼저 실행됨)\n"
        "CREATE EXTENSION IF NOT EXISTS vector;\n"
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hr_connector') THEN\n"
        "  CREATE ROLE hr_connector NOLOGIN; END IF; END $$;\n", encoding="utf-8")
    (OUT / "02_grants.sql").write_text(
        "-- 3) 커넥터 역할은 고객사가 열어 준 읽기 전용 뷰(erp_ro)만 읽을 수 있음\n"
        "REVOKE ALL ON SCHEMA erp FROM hr_connector;\n"
        "GRANT USAGE ON SCHEMA erp_ro TO hr_connector;\n"
        "GRANT SELECT ON ALL TABLES IN SCHEMA erp_ro TO hr_connector;\n", encoding="utf-8")

    dump = OUT / "01_hrdb.sql"
    cmd = [str(BIN / "pg_dump"), *host, "-U", "postgres", "-d", DB_NAME, "--no-owner", "--no-privileges",
           "--quote-all-identifiers", "-f", str(dump)] + sum((["-n", s] for s in SCHEMAS), [])
    subprocess.run(cmd, check=True)
    with open(dump, "rb") as f, gzip.open(str(dump) + ".gz", "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    dump.unlink()

    with connect(srv, DB_NAME) as con:
        src = counts(con)
    with connect(srv, "postgres") as con:
        con.execute(f'DROP DATABASE IF EXISTS "{CHECK_DB}"')
        con.execute(f'CREATE DATABASE "{CHECK_DB}"')
    psql = [str(BIN / "psql"), *host, "-U", "postgres", "-d", CHECK_DB, "-q", "-v", "ON_ERROR_STOP=1"]
    subprocess.run(psql + ["-f", str(OUT / "00_extensions.sql")], check=True)
    with gzip.open(str(dump) + ".gz", "rb") as g:
        subprocess.run(psql, input=g.read(), check=True, stdout=subprocess.DEVNULL)
    subprocess.run(psql + ["-f", str(OUT / "02_grants.sql")], check=True)
    with connect(srv, CHECK_DB) as con:
        dst = counts(con)
        vec = con.execute("SELECT count(embedding) FROM rag.chunks").fetchone()[0]
    with connect(srv, "postgres") as con:
        con.execute(f'DROP DATABASE "{CHECK_DB}"')

    diff = {k: (src[k], dst.get(k)) for k in src if src[k] != dst.get(k)}
    size = (OUT / "01_hrdb.sql.gz").stat().st_size / 1e6
    print(f"덤프 deploy/initdb/01_hrdb.sql.gz {size:.1f}MB — 테이블 {len(src)}개, 총 {sum(src.values()):,}행, 임베딩 {vec}개")
    print("되살리기 확인:", "모든 테이블 건수 일치" if not diff and len(src) == len(dst) else f"불일치 {diff}")


if __name__ == "__main__":
    main()
