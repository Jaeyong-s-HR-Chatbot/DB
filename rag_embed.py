"""7단계-3 임베딩: data/regs/chunks.jsonl 의 검색 대상 조각을 BGE-M3(로컬)로 1024차원 벡터로 바꿔 data/regs/embeddings.npy 저장.

실행 (torch가 있는 환경): ~/rag_local/.venv/bin/python rag_embed.py [data/regs | data/laws]
- 모델: BAAI/bge-m3 (기획서 결정, 다국어·한국어 지원, 처음 한 번 약 2.3GB 다운로드 후 로컬에서만 실행)
- 넣는 글: "규정명 조문 제목\n본문" (규정명·조문 제목도 검색에 걸리게)
- 벡터는 길이 1로 정규화 → pgvector 코사인 거리로 검색
- 순서: chunks.jsonl 의 searchable=true 조각 순서 그대로 (embedding_ids.json 에 chunk_id 목록)
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).parent
REG = HERE / (sys.argv[1] if len(sys.argv) > 1 else "data/regs")  # 인자로 data/laws 를 주면 법령 조각만 임베딩
MODEL = "BAAI/bge-m3"


def doc_text(c):
    head = f"{c['doc_name']} {c['article']} {c['article_title']}".strip()
    return f"{head}\n{c['text']}"


def main():
    chunks = [json.loads(l) for l in open(REG / "chunks.jsonl", encoding="utf-8")]
    target = [c for c in chunks if c["searchable"]]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    t0 = time.time()
    model = SentenceTransformer(MODEL, device=device)
    model.max_seq_length = 1024
    print(f"모델 로드 {time.time() - t0:.0f}초 ({device})")
    t0 = time.time()
    emb = model.encode([doc_text(c) for c in target], batch_size=16, normalize_embeddings=True,
                       show_progress_bar=True, convert_to_numpy=True)
    np.save(REG / "embeddings.npy", emb.astype(np.float32))
    json.dump([c["chunk_id"] for c in target], open(REG / "embedding_ids.json", "w"))
    json.dump({"model": MODEL, "dim": int(emb.shape[1]), "count": len(target), "normalized": True,
               "input": "규정명 조문 제목\\n본문", "device": device},
              open(REG / "embedding_meta.json", "w"), ensure_ascii=False, indent=1)
    print(f"임베딩 {len(target)}개 × {emb.shape[1]}차원, {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
