# 누리철도㈜ HR 데이터 파이프라인 (운영관리)

HR 복리후생 챗봇 팀 프로젝트의 **데이터·DB 쪽** 저장소입니다. 가상 임직원 데이터를 만들고, 고객사 DB를 흉내 낸 뒤, 연결표로 우리 표준 형식(hr)으로 동기화하고, 규정 문서를 조문 단위로 잘라 검색용(rag)으로 넣습니다.

**모든 인물·값은 가상 데이터입니다.** 실제 인물·회사와 무관합니다. 금액 기준은 ALIO 코레일 복리후생비 공시(2025)를 썼습니다.

## 한눈에 보기

| 단계 | 파일 | 하는 일 |
| --- | --- | --- |
| 1 기준표 | `rules/rules.json` | 규정 숫자(경조금·수당·연차 등)를 한 파일에 모음. 생성기·검사기·챗봇 계산이 같은 값을 씀 |
| 2 가상 임직원 | `generate.py` | 800명(사번 E1001~E1800, 전원 정규직) + 1~2년치 인사 기록 → `data/hr/*.csv` 15개 + `data/extra/attendance.csv`. seed 42 고정. 끝에 `golden_personas.py`가 직원 3명을 RAG 골든셋 페르소나로 바꿈(E1634·E1033·E1768 → `data/meta/golden_personas.json`) |
| 3 정합성 검사 | `validate.py`, `test_validate.py` | 테이블끼리 숫자가 맞는지 18개 검사, 오류 11종 주입 시험 |
| 4 DB 준비 | `db_setup.py` | pgserver로 로컬 PostgreSQL 16 + pgvector, DB `hrdb`, 스키마 erp / hr / rag / app |
| 5 회사 DB 흉내 | `load_erp.py`, `mapping/nuri.yaml` | CSV를 회사식 이름(사원·사원번호)·코드값·8자리 날짜로 바꿔 `erp`에 적재, 왕복 검사 |
| 6 커넥터 | `connector.py`, `mapping/standard.yaml` | 읽기 전용 뷰(`erp_ro`) → 연결표로 변환 → `hr_staging` → 검사 통과 시 `hr`로 교체, `app.sync_log` 기록 |
| 7 규정·법령 RAG | `rag_fetch.py` → `rag_build.py` → `rag_embed.py` → `rag_load.py` → `rag_search.py` | ALIO 코레일 규정 33건 → 조문 조각(`data/regs/chunks.jsonl`) → BGE-M3 임베딩 → `rag` 스키마. 법령 13건은 법제처 Open API로 받아 같은 표에 넣음(`doc_kind='법령'`, 아래 참고) |
| 8 항 단위 조각 | `rag_rechunk.py` → `rag_embed_hang_colab.ipynb` → `rag_load_hang.py` | 조문 조각을 항(①②…) 단위로 다시 잘라 `data/hang/` → Colab GPU로 BGE-M3 임베딩 → `rag.chunks` 교체 + `rag.articles`(조문 원문). 아래 "항 단위 조각" 참고 |
| 9 퇴직연금(가상) | `pension/` (`gen_pension.py` → `pension_sim.py` → `pension_build.py` → `pension_load.py`, 검사 `validate_pension.py`) | 가상 운용사 4곳·상품 65개, 직원 800명의 DB/DC/미가입, 납입·보유·거래·이벤트 → `data/pension/build/*.csv` → `pension` 스키마(테이블 10 + 뷰 1). 골든셋 정답 숫자는 `eval/pension/build_pension_golden.py`가 DB에서 다시 계산. 규칙·검사는 `data/pension/README_퇴직연금_데이터.md` |
| DB 배포 | `docker-compose.yml`, `deploy/`, `db_export.py` | 덤프(8MB)로 팀원 누구나 같은 hrdb를 띄움 → [deploy/README.md](deploy/README.md) |
| 내 컴퓨터 DB | `local_db.py` | Docker·PostgreSQL 비밀번호 없이 hrdb를 띄움 (포트 5433). 아래 "Docker 없이 내 컴퓨터에서" 참고 |
| 조회 화면 | `db_viewer.py` | http://127.0.0.1:8765 에서 DB 직접 조회 (읽기 전용 SQL) |

## DB 바로 쓰기 (팀원용)

```bash
docker compose up -d        # PostgreSQL 16 + pgvector, 접속 postgresql://hr:hrpass@localhost:5432/hrdb
```

스크립트를 이 DB에 붙일 때는 `export HRDB_URL=postgresql://hr:hrpass@localhost:5432/hrdb` (없으면 pgserver로 내 컴퓨터에 띄움)

### Docker 없이 내 컴퓨터에서 (윈도우·맥·리눅스)

Docker가 없거나, 이미 깔린 PostgreSQL의 postgres 비밀번호를 몰라도 돼요. `pgserver` 패키지에 들어 있는 PostgreSQL 16 + pgvector를 `pgdata/` 폴더로 따로 켭니다. 이미 깔린 PostgreSQL(5432)과 겹치지 않게 **포트 5433**을 씁니다.

```powershell
py -3.12 -m venv .venv; .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python local_db.py load      # 처음 한 번: deploy/initdb 덤프로 hrdb 만들기 (몇 분)
.venv\Scripts\python local_db.py start     # 컴퓨터를 다시 켠 뒤에는 이것만
.venv\Scripts\python local_db.py status    # 켜짐/꺼짐
.venv\Scripts\python local_db.py stop
```

맥·리눅스는 이렇게 해요 (`.exe` 처리는 `local_db.py`가 알아서 해요).

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python local_db.py load      # 처음 한 번
.venv/bin/python local_db.py start     # 컴퓨터를 다시 켠 뒤에는 이것만
.venv/bin/python local_db.py status
.venv/bin/python local_db.py stop
```

- 접속: `postgresql://hr:hrpass@localhost:5433/hrdb` (backend `.env`의 `HRDB_URL`에 그대로 넣기)
- 이 PC에서만 접속할 수 있어요(localhost, 비밀번호 확인 없음). 가상 데이터 전용이에요
- 처음부터 다시: `stop` → `pgdata` 폴더 지우기 → `load`

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

근태관리 / 수당 / 교육 / 출장 / 기타 복리후생 / 생애이벤트-결혼 / 생애이벤트-출산 / 생애이벤트-휴직·복직·퇴직 / 생애이벤트-입사·승진 / 공통 — `rules/regulations.yaml`

조각 하나에 카테고리를 **여러 개** 붙여요 (`rag.chunks.categories text[]`, 규칙은 `categories.py`).
- 조문 제목(별표·서식은 앞 4줄)에 키워드가 맞는 카테고리를 전부 + 문서 기본 카테고리(공통이면 안 붙임). 아무것도 없으면 `공통`
- 예: 취업규칙 별표 3(청원휴가) → `[생애이벤트-결혼, 근태관리]`, 복지후생 규정 제12조(경조비) → `[생애이벤트-결혼, 기타 복리후생]`
- 검색: `WHERE searchable AND categories && ARRAY['근태관리','공통']` (하나라도 겹치면 통과)
- 이미 만든 조각 파일만 다시 계산: `.venv/bin/python rag_categories.py` → 조각 파일 + `deploy/initdb/03_categories.sql`

## 항 단위 조각 (8단계)

긴 조문(예: 취업규칙 제56조 1,476자)이 통째로 한 조각이라, 질문과 관계없는 항까지 답변에 들어가던 문제를 줄이려고 항(①②…) 단위로 다시 잘랐어요.

```powershell
.venv\Scripts\python rag_rechunk.py          # data/regs·data/laws 조각 → data/hang (원문 파일 없이 돌아감)
# rag_embed_hang_colab.ipynb 를 Colab(GPU)에서 실행 → zip 안의 파일 4개를 data/hang/ 에
..\backend\.venv\Scripts\python rag_load_hang.py   # torch·sentence-transformers 있는 환경. HRDB_URL 없으면 localhost:5433
```

자르는 규칙 (`rag_rechunk.py`)
- 검색 대상 **조문**만 다시 자름. 별표·부칙·서식안내·팀 가정 기준(S01)·검색 제외 조각은 그대로
- 1,500자에서 나뉘어 있던 조문(part 1, 2 …)은 먼저 붙인 뒤 다시 자름
- 항이 2개 이상이면 항마다 한 조각. 항이 없거나 1개이고 900자 이하면 조문 전체가 한 조각 (원래 조각과 글자가 같으면 chunk_id·임베딩 재사용)
- 항 하나가 900자를 넘으면 호(1. 2. …) 경계에서 나누고, 이어지는 조각 앞에 항 첫 문장을 다시 붙임
- 모든 조각 앞에 `제N조(제목)`을 붙임 (법령 원문은 조문 머리가 본문에 없음)
- 결과: 검색 조각 2,697 → 5,720개 (규정 1,238 → 2,421, 법령 1,459 → 3,299), 평균 약 230자

DB (`rag_load_hang.py`)
- 처음 실행할 때 예전 `rag.chunks`를 `rag.chunks_article`로 이름만 바꿔 남김 (비교·되돌리기용)
- 새 `rag.chunks`: 예전 칸 그대로 + `article_id`(문서id:조문, 예 `r04:제7조`), `hang`(①②…), `granularity`(항/조/그대로) → 기존 검색 SQL은 고치지 않아도 됨
- 새 `rag.articles`: 조문 원문 2,039건. 항으로 찾은 뒤 같은 `article_id`의 조문 전체를 답변에 붙일 수 있음
- 한 문서에 같은 조문 번호가 두 번 나오면(10곳) 뒤의 것은 `article_id`에 `#2`를 붙임
- 덤프보다 나중에 생긴 문서(S01 등)는 `rag.documents`에 자동으로 넣음
- 되돌리기: `DROP TABLE rag.chunks; ALTER TABLE rag.chunks_article RENAME TO chunks;`
- `deploy/initdb/01_hrdb.sql.gz` 덤프는 아직 조문 단위예요 (팀이 항 단위로 정하면 `db_export.py`로 다시 만들기)

벡터 검색 비교 (BGE-M3, 내부규정, 1위)

| 질문 | 조문 단위 | 항 단위 |
| --- | --- | --- |
| 배우자 출산휴가 기간 | 취업규칙 제56조 1,476자 (0.714) | 제56조⑤ 287자 (0.756) |
| 난임치료휴가 남성 직원 | 제56조 640자 (0.648) | 제56조⑥ 500자 (0.681) |
| 단시간근로 근무시간 변경 몇 번까지 | 유연근무제 운영세칙 제7조 795자 (0.729) | 제7조① 217자 (0.751) |
| 육아휴직 급여 특례 18개월 | 인사규정 시행세칙 부칙 제2조 (0.589) | 시행세칙 제60의6조② (0.591) |
| 결혼하면 휴가 며칠 받아요? | 제56조 (0.629), 청원휴가 별표 3은 3위 | 제56조⑧ (0.650), 별표 3은 그대로 3위 |

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
