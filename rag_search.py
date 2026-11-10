"""7단계-5 검색 확인: 직원이 물을 법한 질문으로 rag.chunks를 검색해 근거 조문이 위에 나오는지 봄.

실행: ~/rag_local/.venv/bin/python rag_search.py   (질문 임베딩에 BGE-M3가 필요해서 torch 환경에서 실행)
  1) 질문을 BGE-M3로 벡터로 바꿔 data/regs/query_vectors.json 에 저장
  2) hr_db/.venv 의 파이썬을 불러 DB에서 코사인 거리로 상위 3개 조회 (rag_search.py --db 모드)
질문마다 기대 규정·조문(expected)을 적어 두고, 상위 3개 안에 있으면 맞음으로 셈
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
REG = HERE / "data/regs"
QUERIES = [  # (질문, 기대 규정, 기대 조문/별표 앞부분, 팀 카테고리)
    ("결혼하면 휴가 며칠 받아요?", "취업규칙", "별표 3", "생애이벤트-결혼"),
    ("연차휴가는 몇 일이고 최대 몇 일까지 늘어나?", "취업규칙", "제23조", "근태관리"),
    ("병가는 1년에 며칠까지 쓸 수 있어?", "취업규칙", "제25조", "근태관리"),
    ("배우자가 출산하면 휴가 있어?", "취업규칙", "제56조", "생애이벤트-출산"),
    ("육아휴직은 몇 년까지 가능해?", "인사규정", "제44조", "생애이벤트-휴직·퇴직"),
    ("퇴직금은 어떻게 계산해?", "퇴직급여 지급 규정", "제4조", "생애이벤트-휴직·퇴직"),
    ("월급날이 언제야?", "보수규정", "제5조", "수당"),
    ("시간외근무수당 계산 방법 알려줘", "보수규정", "", "수당"),
    ("서울 출장 가면 숙박비 얼마까지 나와?", "여비및시험수당지급세칙", "별표 2", "출장"),
    ("복지포인트는 몇 점 주나요?", "복지후생 규정", "제5조", "기타 복리후생"),
    ("학자금 대여 몇 번까지 받을 수 있어?", "복지후생규정 시행세칙", "제15조", "기타 복리후생"),
    ("수습 기간은 얼마나 돼?", "인사규정", "제17조", "생애이벤트-입사·승진"),
    ("교육 수료 기준 점수가 몇 점이야?", "교육훈련규정", "제21조", "교육"),
    ("승진 평정 점수 비율이 어떻게 돼?", "인사규정", "제28조", "생애이벤트-입사·승진"),
    ("재직증명서는 어떻게 발급받아?", "인사규정 시행세칙", "제71조", "공통"),
]


def embed():
    from sentence_transformers import SentenceTransformer
    import torch
    m = SentenceTransformer("BAAI/bge-m3", device="mps" if torch.backends.mps.is_available() else "cpu")
    v = m.encode([q[0] for q in QUERIES], normalize_embeddings=True)
    json.dump([x.tolist() for x in v], open(REG / "query_vectors.json", "w"))


def search():
    sys.path.insert(0, str(HERE))
    from db_setup import connect, get_server
    vecs = json.load(open(REG / "query_vectors.json"))
    hit1 = hit3 = 0
    with connect(get_server()) as con:
        for (q, doc, art, cat), v in zip(QUERIES, vecs):
            lit = "[" + ",".join(f"{x:.6f}" for x in v) + "]"
            rows = con.execute("SELECT doc_name, article, article_title, category, 1 - (embedding <=> %s::vector) AS score "
                               "FROM rag.chunks WHERE searchable ORDER BY embedding <=> %s::vector LIMIT 3", (lit, lit)).fetchall()
            ranks = [i for i, r in enumerate(rows) if r[0] == doc and r[1].startswith(art)]
            hit1 += bool(ranks and ranks[0] == 0)
            hit3 += bool(ranks)
            mark = "✅" if ranks and ranks[0] == 0 else "🟡" if ranks else "❌"
            print(f"{mark} {q}\n   기대: {doc} {art}  |  1위: {rows[0][0]} {rows[0][1]}({rows[0][2][:20]}) {rows[0][4]:.3f}"
                  + "".join(f"\n        {i + 2}위: {r[0]} {r[1]}({r[2][:20]}) {r[4]:.3f}" for i, r in enumerate(rows[1:])))
    n = len(QUERIES)
    print(f"\n상위 1위 정답 {hit1}/{n}, 상위 3위 안 정답 {hit3}/{n}")
    json.dump({"top1": hit1, "top3": hit3, "n": n}, open(REG / "search_check.json", "w"))


if __name__ == "__main__":
    if "--db" in sys.argv:
        search()
    else:
        embed()
        subprocess.run([str(HERE / ".venv/bin/python"), __file__, "--db"], check=True)
