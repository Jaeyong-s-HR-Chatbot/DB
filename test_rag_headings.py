"""조문 끝의 다음 장·절 제목은 떼고, 문장 속 "제N장"은 남김."""
from rag_rechunk import NEXT_HEADING


def cut(s):
    return NEXT_HEADING.sub("", s)


def test_trailing_headings_removed():
    assert cut("제2조(적용대상) 임원 및 직원에 대하여 적용한다.\n제2장\xa0선택적복지제도") == "제2조(적용대상) 임원 및 직원에 대하여 적용한다."
    assert cut("제9조(준용) 따른다.\n제2장 복무\n제1절 통칙\n") == "제9조(준용) 따른다."


def test_sentences_kept():
    for s in ("제5조(적용) 다음에 따른다.\n제2장 및 제3장의 규정은 준용한다.", "제3조(범위) 제2장 에 따른 사람으로 한다."):
        assert cut(s) == s
