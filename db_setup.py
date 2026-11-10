"""4단계 DB 준비: 로컬 PostgreSQL(pgserver) 켜기 → hrdb 데이터베이스 → pgvector → 스키마 4개.

실행: .venv/bin/python db_setup.py
- 여러 번 실행해도 안전함 (이미 있으면 건너뜀)
- 데이터 파일은 hr_db/pgdata 폴더에 저장됨 (맥을 껐다 켜도 남음)

스키마 4개 (회사 DB와 우리 서비스를 분리하는 구조)
  erp : 고객사 인사 DB 역할. 회사식 열 이름 그대로 (5단계에서 적재)
  hr  : 우리 표준 형식. 챗봇은 여기만 읽음 (6단계 커넥터가 채움)
  rag : 규정 문서 조문 청크 + 임베딩 벡터 (7단계)
  app : 대화 기록, 동기화 기록, 감사 로그
"""
from pathlib import Path

import pgserver
import psycopg

HERE = Path(__file__).parent
DB_NAME = "hrdb"

SCHEMAS = {
    "erp": "고객사 인사 DB 역할(원천). 회사식 열 이름. 5단계에서 CSV 적재",
    "hr": "우리 표준 형식. 챗봇 조회 도구는 이 스키마만 읽음. 6단계 커넥터가 채움",
    "rag": "규정 문서 조문 청크와 임베딩 벡터(pgvector). 7단계",
    "app": "운영 기록: 동기화 로그, 대화 기록, 감사 로그",
}


def get_server():
    """pgserver로 로컬 PostgreSQL을 켜고 서버 객체를 돌려줌."""
    return pgserver.get_server(str(HERE / "pgdata"))


def connect(srv, dbname=DB_NAME):
    uri = srv.get_uri()  # postgresql://postgres:@/postgres?host=...
    return psycopg.connect(uri.replace("/postgres?", f"/{dbname}?"), autocommit=True)


def main():
    srv = get_server()

    # 1. 데이터베이스 hrdb 만들기 (postgres 기본 DB에 접속해서 생성)
    with connect(srv, "postgres") as con:
        exists = con.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone()
        if not exists:
            con.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"[생성] 데이터베이스 {DB_NAME}")
        else:
            print(f"[있음] 데이터베이스 {DB_NAME}")

    with connect(srv) as con:
        # 2. pgvector 확장 (rag 스키마의 임베딩 검색용)
        con.execute("CREATE EXTENSION IF NOT EXISTS vector")
        ver = con.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
        print(f"[확인] pgvector {ver}")

        # 3. 스키마 4개 + 설명
        for name, desc in SCHEMAS.items():
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")
            con.execute(f"COMMENT ON SCHEMA {name} IS %s".replace("%s", "'" + desc.replace("'", "''") + "'"))
            print(f"[확인] 스키마 {name:<4} — {desc}")

        # 4. 결과 확인
        rows = con.execute(
            "SELECT nspname, obj_description(oid, 'pg_namespace') FROM pg_namespace "
            "WHERE nspname = ANY(%s) ORDER BY nspname", (list(SCHEMAS),)).fetchall()
        print(f"\n{DB_NAME} 안의 스키마 {len(rows)}개: {', '.join(r[0] for r in rows)}")
        print(f"접속 주소: {srv.get_uri().replace('/postgres?', f'/{DB_NAME}?')}")


if __name__ == "__main__":
    main()
