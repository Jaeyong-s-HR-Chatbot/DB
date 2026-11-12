"""조각 카테고리 붙이기: 조각 하나에 카테고리를 여러 개 붙인다 (rules/regulations.yaml 의 category_rules).

규칙
- 조문 제목(별표·서식은 앞 4줄)에 키워드가 있는 카테고리를 **전부** 붙인다 (예전에는 처음 맞는 것 하나만).
  예: "제56조(출산휴가)" → [생애이벤트-출산, 근태관리]
- 문서 기본 카테고리(regulations.yaml 의 category, 법령은 law_build.CATEGORY)도 같이 붙인다. 단 '공통'은 붙이지 않는다.
  예: 복지후생 규정 "제5조(경조금)" → [생애이벤트-결혼, 기타 복리후생]
- 아무것도 안 붙으면 ['공통'].
- 순서: category_rules 순서대로, 문서 기본 카테고리는 맨 뒤.

검색에서 쓰는 법: WHERE categories && ARRAY['근태관리','공통']  (하나라도 겹치면 통과)
"""
from pathlib import Path

import yaml

HERE = Path(__file__).parent
RULES = yaml.safe_load(open(HERE / "rules/regulations.yaml", encoding="utf-8"))["category_rules"]
COMMON = "공통"
ALL = [r["category"] for r in RULES] + [COMMON]


def categories_of(base, text):
    """base = 문서 기본 카테고리, text = 조문 제목(별표·서식은 앞 몇 줄). 카테고리 목록을 돌려줌."""
    out = [r["category"] for r in RULES if any(k in text for k in r["keywords"])]
    if base != COMMON and base not in out:
        out.append(base)
    return out or [COMMON]


def head_text(text, n=4):
    """별표·서식은 제목 줄이 개정 이력인 경우가 많아 앞 몇 줄로 카테고리를 정함 (rag_build 와 같은 방식)"""
    return " ".join([l.strip() for l in text.split("\n") if l.strip()][:n])
