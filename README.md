# 누리철도㈜ HR 데이터 파이프라인 (운영관리)

HR 복리후생 챗봇 팀 프로젝트의 **데이터·DB 쪽** 저장소입니다. 가상 임직원 데이터를 만들고, 고객사 DB를 흉내 낸 뒤, 연결표로 우리 표준 형식(hr)으로 동기화하고, 규정 문서를 조문 단위로 잘라 검색용(rag)으로 넣습니다.

**모든 인물·값은 가상 데이터입니다.** 실제 인물·회사와 무관합니다. 금액 기준은 ALIO 코레일 복리후생비 공시(2025)를 썼습니다.

## 한눈에 보기

| 단계 | 파일 | 하는 일 |
| --- | --- | --- |
| 1 기준표 | `rules/rules.json` | 규정 숫자(경조금·수당·연차 등)를 한 파일에 모음. 생성기·검사기·챗봇 계산이 같은 값을 씀 |
| 2 가상 임직원 | `generate.py` | 800명(사번 E1001~E1800, 전원 정규직) + 1~2년치 인사 기록 → `data/hr/*.csv` 15개 + `data/extra/attendance.csv`. seed 42 고정 |
| 3 정합성 검사 | `validate.py`, `test_validate.py` | 테이블끼리 숫자가 맞는지 18개 검사, 오류 11종 주입 시험 |
| 4 DB 준비 | `db_setup.py` | pgserver로 로컬 PostgreSQL 16 + pgvector, DB `hrdb`, 스키마 erp / hr / rag / app |
| 5 회사 DB 흉내 | `load_erp.py`, `mapping/nuri.yaml` | CSV를 회사식 이름(사원·사원번호)·코드값·8자리 날짜로 바꿔 `erp`에 적재, 왕복 검사 |
| 6 커넥터 | `connector.py`, `mapping/standard.yaml` | 읽기 전용 뷰(`erp_ro`) → 연결표로 변환 → `hr_staging` → 검사 통과 시 `hr`로 교체, `app.sync_log` 기록 |
| 7 규정·법령 RAG | `rag_fetch.py` → `rag_build.py` → `rag_embed.py` → `rag_load.py` → `rag_search.py` | ALIO 코레일 규정 33건 → 조문 조각(`data/regs/chunks.jsonl`) → BGE-M3 임베딩 → `rag` 스키마. 법령 13건은 법제처 Open API로 받아 같은 표에 넣음(`doc_kind='법령'`, 아래 참고) |
| DB 배포 | `docker-compose.yml`, `deploy/`, `db_export.py` | 덤프(8MB)로 팀원 누구나 같은 hrdb를 띄움 → [deploy/README.md](deploy/README.md) |
| 조회 화면 | `db_viewer.py` | http://127.0.0.1:8765 에서 DB 직접 조회 (읽기 전용 SQL) |

## DB 바로 쓰기 (팀원용)

```bash
docker compose up -d        # PostgreSQL 16 + pgvector, 접속 postgresql://hr:hrpass@localhost:5432/hrdb
```

스크립트를 이 DB에 붙일 때는 `export HRDB_URL=postgresql://hr:hrpass@localhost:5432/hrdb` (없으면 pgserver로 내 컴퓨터에 띄움)

## 회사 설정 (팀 "부서 구성")

- 5개 본부 · 35개 부서 · 800명: 운전·승무 240 / 역무 200 / 차량정비 120 / 시설·전기 120 / 사무 120
- 근무형태: 일근 · 교대근무 · 교번근무, 근무지: 본사 · 수도권 · 충청권 · 영남권 (근무형태 배정·근무지는 가정값)
- 개인정보는 `employee_pii.csv`에만, 모두 가짜 형식 (주민번호 검증숫자 일부러 틀림, 계좌 999-, 주소 누리로 등)

## 실행 순서

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python generate.py        # 2단계 (약 10초)
.venv/bin/python validate.py        # 3단계 → 18/18 통과
.venv/bin/python test_validate.py   # 3단계 오류 주입 시험 → 11/11
.venv/bin/python db_setup.py        # 4단계
.venv/bin/python load_erp.py        # 5단계
.venv/bin/python connector.py       # 6단계
.venv/bin/python rag_fetch.py       # 7단계: 규정 원문 받기 (data/regs/raw, 저장소에는 안 올림)
.venv/bin/python rag_build.py       # 7단계: 조문 조각
python rag_embed.py                 # 7단계: torch + sentence-transformers 환경에서 (BGE-M3)
.venv/bin/python rag_load.py        # 7단계: rag 스키마 적재
.venv/bin/python db_viewer.py       # DB 조회 화면
```

## 팀 업무 카테고리 (규정 조각 category)

근태관리 / 수당 / 교육 / 출장 / 기타 복리후생 / 생애이벤트-결혼 / 생애이벤트-출산 / 생애이벤트-휴직·퇴직 / 생애이벤트-입사·승진 / 공통 — `rules/regulations.yaml`

## 저장소에 없는 것

- `pgdata/` (DB 파일, 대신 `deploy/initdb/01_hrdb.sql.gz` 덤프로 배포), 규정 원문 파일(`data/regs/raw`, `rag_fetch.py`로 다시 받음), 임베딩 벡터(`rag_embed.py`로 다시 만듦), zip 묶음
- 로컬 테스트 계정 비밀번호는 `generate.py`의 `TEST_PASSWORD` (가상 계정 전용)

## 법령 13건 (rag)
근로기준법·남녀고용평등법(+시행령)·고용보험법(+시행령)·근로자퇴직급여 보장법 시행령·고령자고용법·산업안전보건법 시행규칙·철도안전법 시행규칙·민방위기본법·성매매/성폭력/가정폭력방지법 시행령.
- 기준일 2026-11-11 **현행판만** 받음 (시행 예정판은 제외, 자동화는 나중에)
- 순서: `law_fetch_api.py`(법제처 Open API, `.env`에 `LAW_OC=인증키` 필요, 호출 IP 등록 필요) → `law_build.py` → `rag_embed.py data/laws` → `rag_load.py`
- `rag.documents`: `doc_kind`(내부규정/법령), `law_mst`(법령 일련번호), `status`(현행), `base_date`, `promulgated_date`, `law_type`, `dept`, `source_url`. `rag.chunks.doc_kind`
- 법령 조각 1,608개(검색 대상 1,459): 조문 + 별표(API 텍스트) + 부칙. 서식(신청서 등)은 제외
- 출처 표기: 법제처 국가법령정보센터 (법령을 근거로 답할 때 출처를 함께 보여줘야 함)
- `law_attach.py`는 별표 PDF로 받는 대체 방법 (API: 7.0초 / PDF: 19.6초, API가 띄어쓰기·표 구조를 더 잘 보존)
- 검색 시험(`rag_search.py`) 23문항: 1위 14, 3위 안 21. 법령이 규정을 밀어낼 수 있어 검색 시 `doc_kind='내부규정'`을 우선하는 규칙 필요
- ERD: `docs/erd/` (변경 표시본 `erd_rag_app_변경표시.png`)
