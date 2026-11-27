"""rag_unwrap.py 시험: pytest test_rag_unwrap.py -q

줄바꿈 규칙(가이드 예시 + 실제 chunks.jsonl 에서 찾은 경계 사례), 점수 동점일 때 코퍼스 빈도 가르기,
파일 처리(조문·부칙만 고침 · id 유지 · --dry-run · 멱등)를 확인함. Kiwi(kiwipiepy)가 없으면 건너뜀.
"""
import json
import re
import sys

import pytest

pytest.importorskip("kiwipiepy")
import rag_unwrap as u  # noqa: E402

# (입력, 기대 결과). vocab 없이 규칙과 Kiwi 점수만으로 정해지는 것
CASES = {
    # --- Notion 가이드 예시
    "낱말 중간(직원)":      ("특정직 직\n원에게는", "특정직 직원에게는"),
    "낱말 중간(자녀)":      ("다만, 자\n녀는 4명을", "다만, 자녀는 4명을"),
    "낱말 중간(7시간)":     ("1일 7시\n간·1주", "1일 7시간·1주"),
    "낱말 중간(본인의)":    ("본인\n의 신청", "본인의 신청"),
    "개정표시 띄움":        ("<개정\n2010.06.28.>", "<개정 2010.06.28.>"),
    # --- 줄바꿈 유지
    "항 경계":              ("① 가나다\n② 라마바", "① 가나다\n② 라마바"),
    "호 경계":              ("1. 본인의 신청\n2. 휴직", "1. 본인의 신청\n2. 휴직"),
    "가지번호 호":          ("1의2. 제1호 위반\n1의3. 제2호 위반", "1의2. 제1호 위반\n1의3. 제2호 위반"),
    "목 번호":              ("지급한다.\n가. 휴직\n나. 복직", "지급한다.\n가. 휴직\n나. 복직"),
    "목 다. 유지":          ("가. 견책 : 1년\n나. 감봉 : 2년\n다. 강등 : 3년", "가. 견책 : 1년\n나. 감봉 : 2년\n다. 강등 : 3년"),
    "목 다. + 앞 낱말 끊김": ("가. 철도운임\n나. 선박운임 실\n비액\n다. 업무상 필요", "가. 철도운임\n나. 선박운임 실비액\n다. 업무상 필요"),
    "빈 줄":                ("제1항의 규정\n\n제2항의 규정", "제1항의 규정\n\n제2항의 규정"),
    "제목 줄 뒤":           ("제3장 복지후생\n지급한\n다.", "제3장 복지후생\n지급한다."),
    "부칙 조문 머리": (
        "제2조부터 제7조까지 생략\n제8조 (다른 법률의 개정) ① 생략\n제9조 생략\n부칙(국가공무원법) <제1호,2012.1.1>",
        "제2조부터 제7조까지 생략\n제8조 (다른 법률의 개정) ① 생략\n제9조 생략\n부칙(국가공무원법) <제1호,2012.1.1>"),
    # --- 문장 끝 '다.' (목 번호와 구분)
    "문장 끝 다.":          ("지급한\n다.", "지급한다."),
    "문장 끝 다. + 개정표시": ("운영은 담당한\n다. <개정 2023.04.25.>", "운영은 담당한다. <개정 2023.04.25.>"),
    "문장 끝 다. 다만,":    ("결정한다. 다만, 승인한\n다. 다만, 그러하다", "결정한다. 다만, 승인한다. 다만, 그러하다"),
    "다) 로 시작":          ("…한\n다)지급에", "…한다)지급에"),
    # --- 앞 줄바꿈을 유지해도 그 뒤 줄바꿈을 놓치지 않음 / 여러 줄에 걸친 낱말
    "유지 뒤의 끊김":       ("용어는 다음과 같다.\n자\n녀란", "용어는 다음과 같다.\n자녀란"),
    "한 낱말이 3줄":        ("근로시\n간을 정\n하여 시행", "근로시간을 정하여 시행"),
    # --- 숫자·단위
    "제N조":                ("제30\n조를 적용", "제30조를 적용"),
    "제N호":                ("제4\n호까지의", "제4호까지의"),
    "제 + 숫자":            ("다만 제\n2장의 규정은", "다만 제2장의 규정은"),
    "숫자 + 단위(근거 없음)": ("2\n개월 이내", "2개월 이내"),
    "숫자 + 이상은 띄움":   ("100\n이상", "100 이상"),
    # --- Kiwi 점수 동점 + 근거 없음
    "동점 → 띄움":          ("연 120일의\n유급휴가를", "연 120일의 유급휴가를"),
    "명사 + 하여 → 붙임":   ("서류를 준수\n하여 제출", "서류를 준수하여 제출"),
    "조사 + 하여야 → 띄움": ("공고로\n하여야 한다", "공고로 하여야 한다"),
    # --- 공백 종류
    "NBSP · CRLF":          ("직 \n원은\r\n있다", "직원은 있다"),
}


@pytest.mark.parametrize("name", CASES)
def test_unwrap_cases(name):
    src, want = CASES[name]
    assert u.unwrap(src) == want


@pytest.mark.parametrize("name", CASES)
def test_unwrap_is_idempotent(name):
    once = u.unwrap(CASES[name][0])
    assert u.unwrap(once) == once


@pytest.mark.parametrize("name", CASES)
def test_unwrap_keeps_every_character(name):
    src = CASES[name][0]
    assert re.sub(r"\s", "", u.unwrap(src)) == re.sub(r"\s", "", src)


# ---------- 점수 동점일 때 코퍼스 빈도

def test_tie_without_vocab_is_spaced():
    assert u.unwrap("세부\n사항은") == "세부 사항은"


def test_tie_goes_to_the_more_frequent_form():
    # 줄 안쪽에서 "세부사항은"이 "세부 사항은"보다 많이 나오면 붙이고, 반대면 띄움
    glued = u.build_vocab(["가 세부사항은 나"] * 3)
    spaced = u.build_vocab(["가 세부 사항은 나"] * 3)
    assert u.unwrap("세부\n사항은", glued) == "세부사항은"
    assert u.unwrap("세부\n사항은", spaced) == "세부 사항은"


def test_build_vocab_ignores_first_and_last_word_of_each_line():
    words, pairs = u.build_vocab(["직 원에게는 배우자 포함 4명\n짧은 줄"])
    assert set(words) == {"원에게는", "배우자", "포함"}  # 잘렸을 수 있는 줄 첫·끝 낱말은 세지 않음
    assert pairs[("원에게는", "배우자")] == 1


def test_score_wins_over_vocab():
    # 낱말 중간 끊김은 Kiwi 점수가 분명해서 코퍼스에 띄운 형태가 많아도 붙임
    spaced = u.build_vocab(["가 직 원에게는 나"] * 5)
    assert u.unwrap("직\n원에게는", spaced) == "직원에게는"


# ---------- leftovers (남은 끊김 점검)

def test_leftovers_ignores_designed_line_breaks():
    text = "가. 하나\n나. 둘\n다. 셋\n제3장 복지후생\n제1절 통칙\n제8조 (개정)"
    assert u.leftovers(text) == []


def test_leftovers_reports_real_mid_word_break():
    assert len(u.leftovers("직원\n에게는")) == 1


# ---------- 파일 처리

def _write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


BROKEN = "제24조(가족수당) ① 부양가족이 있는 일반직, 전문직 및 특정직 직\n원에게는 배우자 포함 4명 범위에서 가족수당을 지급한다. 다만, 자\n녀는 4명을 초과하더라도 지급한다."
FIXED = BROKEN.replace("직\n원에게는", "직원에게는").replace("자\n녀는", "자녀는")
TABLE = "| 직\n원 | 금\n액 |"


@pytest.fixture
def hang_dir(tmp_path):
    base = dict(document_id="r04", article_id="r04:제24조", searchable=True)
    _write(tmp_path / "chunks.jsonl", [
        dict(base, chunk_id="r04-0008-01", chunk_type="조문", text=BROKEN),
        dict(base, chunk_id="r04-0009", chunk_type="부칙", text="부칙 <개정\n2010.06.28.>\n이 규정은 시행한\n다."),
        dict(base, chunk_id="r04-별표1", chunk_type="별표", text=TABLE),
        dict(base, chunk_id="d-1", chunk_type="전결항목", text="업무\n구분"),
    ])
    _write(tmp_path / "articles.jsonl", [dict(article_id="r04:제24조", text=BROKEN)])
    return tmp_path


def run_main(monkeypatch, hang_dir, *args):
    monkeypatch.setattr(sys, "argv", ["rag_unwrap.py", "--dir", str(hang_dir), *args])
    u.main()


def test_main_fixes_only_target_types(monkeypatch, hang_dir, capsys):
    run_main(monkeypatch, hang_dir)
    rows = {r["chunk_id"]: r for r in _read(hang_dir / "chunks.jsonl")}
    assert rows["r04-0008-01"]["text"] == FIXED
    assert rows["r04-0009"]["text"] == "부칙 <개정 2010.06.28.>\n이 규정은 시행한다."
    assert rows["r04-별표1"]["text"] == TABLE          # 별표는 그대로
    assert rows["d-1"]["text"] == "업무\n구분"          # 전결항목은 그대로
    assert _read(hang_dir / "articles.jsonl")[0]["text"] == FIXED
    out = capsys.readouterr().out
    assert "조각 2개, 조문 원문 1건 고침" in out


def test_main_keeps_ids_and_other_fields(monkeypatch, hang_dir):
    before = _read(hang_dir / "chunks.jsonl")
    run_main(monkeypatch, hang_dir)
    after = _read(hang_dir / "chunks.jsonl")
    assert [r["chunk_id"] for r in after] == [r["chunk_id"] for r in before]
    assert [r["article_id"] for r in after] == [r["article_id"] for r in before]
    for b, a in zip(before, after):
        assert {k: v for k, v in b.items() if k != "text"} == {k: v for k, v in a.items() if k != "text"}


def test_main_dry_run_writes_nothing(monkeypatch, hang_dir, capsys):
    before = (hang_dir / "chunks.jsonl").read_bytes(), (hang_dir / "articles.jsonl").read_bytes()
    run_main(monkeypatch, hang_dir, "--dry-run")
    assert ((hang_dir / "chunks.jsonl").read_bytes(), (hang_dir / "articles.jsonl").read_bytes()) == before
    assert "조각 2개" in capsys.readouterr().out


def test_main_second_run_changes_nothing(monkeypatch, hang_dir, capsys):
    run_main(monkeypatch, hang_dir)
    first = (hang_dir / "chunks.jsonl").read_bytes()
    capsys.readouterr()
    run_main(monkeypatch, hang_dir)
    assert (hang_dir / "chunks.jsonl").read_bytes() == first
    assert "조각 0개, 조문 원문 0건 고침" in capsys.readouterr().out
    assert not list(hang_dir.glob("*.tmp"))             # 임시 파일이 남지 않음


def test_main_works_without_articles_file(monkeypatch, hang_dir):
    (hang_dir / "articles.jsonl").unlink()
    run_main(monkeypatch, hang_dir)
    assert not (hang_dir / "articles.jsonl").exists()
    assert _read(hang_dir / "chunks.jsonl")[0]["text"] == FIXED
