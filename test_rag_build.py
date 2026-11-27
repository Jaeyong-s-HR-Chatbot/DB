import unittest
from unittest.mock import patch

import rag_appendix_links
import rag_build
from rag_forms import with_guides


class AppendixTests(unittest.TestCase):
    def test_only_supported_headings_start_appendices(self):
        lines = [
            (1, "제1조(제목) 본문"),
            (1, "별표1의3 중 경력점수로 인정되는 업무"),
            (1, "[별표4]의 직무운영소속"),
            (1, "별표2의 전기통신직렬에 해당"),
            (1, "[별표 1-2]의 기준"),
            (1, "본문의 【별표 1-2】에 따른 기준"),
            (1, "본문 중간의 【별표6】에 따른 기준"),
            (1, "【별표6】에 따른 기준"),
            (1, "[별표]의 기준"),
            (2, "[별표 1의3] <개정 " + "2020.01.01. " * 12 + ">"),
            (2, "표 제목"),
            (3, "[별표 4]"),
            (3, "다른 표 제목"),
            (4, "【별표6】(제20조 관련)"),
            (4, "표 여섯"),
            (5, "【별표 6의2】"),
            (5, "표 여섯의 둘"),
            (6, "[별표]"),
            (6, "번호 없는 표"),
            (7, "[별표 1-2]"),
            (7, "하이픈 표"),
            (8, "【별표 1-2】"),
            (8, "다른 하이픈 표"),
        ]
        reg = {"id": "test", "name": "시험", "category": "공통", "tier": "핵심"}
        manifest = {"file_name": "시험.pdf", "alio_date": "2020.01.01", "kind": "pdf"}
        with patch.dict(rag_build.MANIFEST, {"test": manifest}), patch.object(
            rag_build, "load_lines", return_value=(lines, [], 8)
        ):
            chunks, _ = rag_build.chunk_reg(reg)
        appendices = [c for c in chunks if c["chunk_type"] == "별표"]
        self.assertEqual(
            [c["article"] for c in appendices],
            ["별표 1의3", "별표 4", "별표 6", "별표 6의2", "별표", "별표 1-2", "별표 1-2"],
        )
        self.assertIn("[별표4]의 직무운영소속", chunks[0]["text"])
        self.assertIn("별표2의 전기통신직렬에 해당", chunks[0]["text"])
        self.assertIn("본문 중간의 【별표6】에 따른 기준", chunks[0]["text"])
        self.assertIn("【별표6】에 따른 기준", chunks[0]["text"])
        self.assertIn("[별표]의 기준", chunks[0]["text"])
        self.assertIn("[별표 1-2]의 기준", chunks[0]["text"])

    def test_articles_inside_form_stay_in_form(self):
        # 전문직 직원 운영 세칙 별지 1 근로계약서의 제1조(당사자)… 는 규정 조문이 아님
        lines = [(1, "제1조(목적) 규정 본문"),
                 (2, "[별지 제1호서식]"), (2, "근로계약서(제8조 관련)"),
                 (2, "제1조(당사자) 갑과 을"), (2, "제2조(계약기간) 1년"),
                 (3, "[별지 제2호서식]"), (3, "평정서")]
        reg = {"id": "test", "name": "시험", "category": "공통", "tier": "핵심"}
        manifest = {"file_name": "시험.pdf", "alio_date": "2020.01.01", "kind": "pdf"}
        with patch.dict(rag_build.MANIFEST, {"test": manifest}), patch.object(
            rag_build, "load_lines", return_value=(lines, [], 3)
        ):
            chunks, _ = rag_build.chunk_reg(reg)
        self.assertEqual([c["article"] for c in chunks if c["chunk_type"] == "조문"], ["제1조"])
        inside = [c for c in chunks if c["text"].startswith(("제1조(당사자)", "제2조(계약기간)"))]
        self.assertEqual(len(inside), 2)
        head = next(c for c in chunks if c["text"].startswith("[별지 제1호서식]"))
        for c in inside:
            self.assertEqual((c["chunk_type"], c["article"], c["searchable"]), ("서식", "별지 1", False))
            self.assertEqual(c["article_title"], head["article_title"])

    def test_unnumbered_form_is_separate_and_has_a_valid_guide(self):
        for heading in ("[별지서식]", "[별지 서식]"):
            with self.subTest(heading=heading):
                lines = [(1, "[별표]"), (1, "별표 내용"),
                         (1, f"본문 중간의 {heading}에 따른 기준"),
                         (1, f"{heading}의 기준"),
                         (2, f"{heading} (제9조 관련)"), (2, "개인별 심사자료"),
                         (2, "부 서"), (2, "서식 내용")]
                reg = {"id": "test", "name": "시험", "category": "공통", "tier": "핵심"}
                manifest = {"file_name": "시험.pdf", "alio_date": "2020.01.01", "kind": "pdf"}
                with patch.dict(rag_build.MANIFEST, {"test": manifest}), patch.object(
                    rag_build, "load_lines", return_value=(lines, [], 2)
                ):
                    chunks, _ = rag_build.chunk_reg(reg)
                appendix, form = chunks
                self.assertEqual(appendix["chunk_type"], "별표")
                self.assertNotIn("서식 내용", appendix["text"])
                self.assertIn(f"{heading}의 기준", appendix["text"])
                self.assertEqual((form["chunk_type"], form["article"], form["searchable"]), ("서식", "별지", False))
                guide = with_guides(chunks)[-1]
                self.assertEqual(guide["chunk_type"], "서식안내")
                self.assertIn("[별지 서식]", guide["text"])
                self.assertEqual(guide["article_title"], "개인별 심사자료")
                self.assertNotIn("제호", guide["text"])

    def test_hyphen_reference_links_to_hyphenated_appendix(self):
        articles = [{"article_id": "test:제1조", "document_id": "test", "text": "별표 1-2에 따른다."}]
        appendices = {"test:별표 1": [{}], "test:별표 1-2": [{}]}
        with patch.object(rag_appendix_links, "ARTICLES", articles), patch.object(
            rag_appendix_links, "APPX", appendices
        ):
            links = rag_appendix_links.forward_links()
        self.assertEqual(links["test:제1조"], {"test:별표 1-2"})

    def test_form_links_from_article_text_and_related_line(self):
        articles = [
            {"article_id": "t:제3조", "document_id": "t", "text": "제3조(신청) 별지 제2호 서식에 따라 신청한다. 별\n표 1과 같다."},
            {"article_id": "t:제5조", "document_id": "t", "text": "제5조(심사) 개인별 심사자료(별지서식)를 낸다."},
            {"article_id": "t:제7조", "document_id": "t", "text": "제7조(기타) 서식 언급 없음"},
            {"article_id": "t:제9조의2", "document_id": "t", "text": "제9조의2(위원) 본문"},
        ]
        guide = lambda fid, rel: [{"document_id": "t", "chunk_type": "서식안내", "article_id": fid,
                                   "text": f"[별지 서식] 제목\n소속 규정: 시험\n관련 조항: {rel}\n"}]
        forms = {"t:별지 2": guide("t:별지 2", "제3조(신청), 제7조제1항"), "t:별지": guide("t:별지", "없음"),
                 "t:별지 4": guide("t:별지 4", "제9조의2(위원)")}
        with patch.object(rag_appendix_links, "ARTICLES", articles), patch.object(rag_appendix_links, "FORMS", forms), \
                patch.object(rag_appendix_links, "ARTICLE_IDS", {a["article_id"] for a in articles}):
            links = rag_appendix_links.form_links()
        self.assertEqual(links["t:제3조"], {"t:별지 2": "양쪽"})
        self.assertEqual(links["t:제7조"], {"t:별지 2": "서식→조"})       # '제7조제1항' → 제7조
        self.assertEqual(links["t:제5조"], {"t:별지": "조→서식"})          # 번호 없는 '별지서식'
        self.assertEqual(links["t:제9조의2"], {"t:별지 4": "서식→조"})

    def test_long_appendix_repeats_heading_and_related_line_without_splitting_rows(self):
        header = ["[별표 1]", "표 제목", "(제9조 관련)"]
        rows = [f"행 {i}: " + "가" * 280 for i in range(10)]
        text = "\n".join(header + rows)
        parts = rag_build.split_appendix(text, header[1])
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= rag_build.MAX_CHARS for p in parts))
        self.assertTrue(all(p.startswith("\n".join(header) + "\n") for p in parts))
        recovered = parts[0].splitlines()
        for part in parts[1:]:
            recovered.extend(part.splitlines()[len(header):])
        self.assertEqual(recovered, header + rows)

    def test_combined_title_and_related_line_is_not_duplicated(self):
        title = "표 제목(제9조제1항 관련)"
        text = "\n".join(["[별표 1]", title] + ["가" * 500] * 4)
        parts = rag_build.split_appendix(text, title)
        self.assertGreater(len(parts), 1)
        self.assertEqual(parts[1].splitlines()[:2], ["[별표 1]", title])
        self.assertEqual(parts[1].count(title), 1)

    def test_oversized_row_fails_instead_of_splitting(self):
        with self.assertRaisesRegex(ValueError, "1,500자"):
            rag_build.split_appendix("[별표 1]\n" + "가" * 1500, None)


if __name__ == "__main__":
    unittest.main()
