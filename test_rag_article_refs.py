import unittest
from unittest.mock import patch

import rag_article_refs as R

NAMES = {"r03": "취업규칙", "r04": "유연근무제 운영세칙", "r13": "인사규정", "r14": "인사규정 시행세칙",
         "L04": "고용보험법", "L05": "고용보험법 시행령"}
KINDS = {d: ("법령" if d.startswith("L") else "내부규정") for d in NAMES}
IDS = {"r03:제23조", "r03:제24조", "r03:제25조", "r04:제5조", "r04:제12조", "r04:제25조", "r13:제29조", "r14:제3조",
       "r14:제7의2조", "L04:제31조", "L04:제40조", "L05:제10조", "L05:제11조", "L05:제12조"}


def refs(article_id, text):
    doc = article_id.split(":")[0]
    by_name = {R.squash(n): d for d, n in NAMES.items()}
    with patch.object(R, "DOC_NAME", NAMES), patch.object(R, "DOC_KIND", KINDS), \
            patch.object(R, "DOC_BY_NAME", by_name), patch.object(R, "NAMES_LONGEST", sorted(by_name, key=len, reverse=True)), \
            patch.object(R, "ARTICLE_IDS", IDS | {article_id}):
        return sorted(R.refs_of({"article_id": article_id, "document_id": doc, "text": text}))


class ArticleRefTests(unittest.TestCase):
    def test_named_and_chained_refs_follow_the_named_document(self):
        got = refs("r04:제25조", "제25조(휴가) 1. 공가: 「취업규칙」 제24조 및 제25조에 따른다. 2. 연차는 제12조에 따른다.")
        self.assertEqual(got, [("r03:제24조", "따른다"), ("r03:제25조", "따른다"), ("r04:제12조", "따른다")])

    def test_bare_document_name_without_brackets(self):
        self.assertEqual(refs("r04:제5조", "제5조(휴직) 인사규정 제29조제2항제3호에 따른 육아휴직"),
                         [("r13:제29조", "따른다")])

    def test_prefix_in_enforcement_decree_and_rules(self):
        got = refs("L05:제12조", "제12조(지원) ① 법 제31조제2항에 따라 지원한다. ② 제10조 및 제11조를 준용한다.")
        self.assertEqual(got, [("L04:제31조", "따른다"), ("L05:제10조", "준용"), ("L05:제11조", "준용")])
        self.assertEqual(refs("r14:제3조", "제3조(정의) 규정 제29조에 따라"), [("r13:제29조", "따른다")])  # 시행세칙의 '규정' = 상위 규정

    def test_exception_kind_and_unknown_documents_are_dropped(self):
        got = refs("r04:제12조", "제12조(특례) 제5조에도 불구하고 「도로교통법」 제20조 및 동법 시행규칙 제34조에 따라 정한다. "
                                 "법 제40조에 따른 것은 제외")   # 내부규정의 '법 제N조'는 어느 법인지 모름
        self.assertEqual(got, [("r04:제5조", "예외")])

    def test_history_notes_and_same_article_are_not_refs(self):
        self.assertEqual(refs("r03:제23조", "제23조(연차) ① 연차는 같은 조 제2항에 따른다. [종전 제24조에서 이동 2010.06.28.]"), [])

    def test_kind_skips_paragraph_numbers_and_titles(self):
        self.assertEqual(refs("r04:제5조", "제5조(신청) 인사규정 시행세칙 제7조의2(인사위원회 제척) 제3항 및 제4항에 따라 처리"),
                         [("r14:제7의2조", "따른다")])


if __name__ == "__main__":
    unittest.main()
