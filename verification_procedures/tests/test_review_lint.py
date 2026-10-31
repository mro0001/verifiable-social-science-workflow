import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.lint import Finding, lint  # noqa: E402
from review.lint import fixture as l_fix  # noqa: E402


class TestFixtureContract:
    def test_allowlisted_run_yields_exactly_the_bare_percentage(self):
        findings = lint(l_fix.SAMPLE_MD, l_fix.ALLOWLIST)
        assert [(f.line, f.token) for f in findings] == [(5, "12.5%")]

    def test_without_allowlist_the_literature_constant_also_flags(self):
        findings = lint(l_fix.SAMPLE_MD)
        assert {(f.line, f.token) for f in findings} == {(5, "12.5%"), (7, "42.7")}


class TestNotFlaggedCategories:
    def test_fenced_code_not_flagged(self):
        assert lint("```\nx = 0.75\n```\n") == []

    def test_inline_code_span_not_flagged(self):
        assert lint("Set `retries = 3` before running.\n") == []

    def test_years_not_flagged(self):
        assert lint("Fieldwork ran 2019 to 2024.\n") == []

    def test_placeholder_not_flagged(self):
        assert lint("The rate was {{num:widget.rate}} overall.\n") == []

    def test_citation_years_not_flagged(self):
        assert lint("As shown earlier (Chung et al. 2025; Darwin 1859).\n") == []

    def test_list_markers_and_heading_numbers_not_flagged(self):
        assert lint("## 3. Results\n\n1. First step\n2. Second step\n") == []

    def test_table_separator_not_flagged(self):
        assert lint("| a | b |\n|---|---|\n") == []


class TestFlagged:
    def test_bare_integer_decimal_percent_flagged(self):
        findings = lint("We saw 42 events, a mean of 3.7, and 12% churn.\n")
        assert [f.token for f in findings] == ["42", "3.7", "12%"]

    def test_finding_shape(self):
        f = lint("A bare 42 here.\n")[0]
        assert isinstance(f, Finding)
        assert f.line == 1
        assert f.token == "42"
        assert f.context == "A bare 42 here."


class TestNameAttachedNumbers:
    def test_mid_sentence_model_names_and_dates_not_flagged(self):
        assert lint("Parse failures reached 90% for Phi 4 and for Qwen 3 overall.\n") == [
            f for f in lint("Parse failures reached 90% for Phi 4 and for Qwen 3 overall.\n") if f.token == "90%"
        ]
        assert [f.token for f in lint("Results shown in Table 4 follow the June 10 additions.\n")] == []

    def test_sentence_initial_capitalized_quantity_still_flagged(self):
        assert [f.token for f in lint("Approximately 40 respondents agreed.\n")] == ["40"]


class TestBehavior:
    def test_never_raises_on_content_only_on_type(self):
        lint("")
        lint("no numbers at all")
        with pytest.raises(TypeError):
            lint(b"bytes are not text")


class TestOwnPlaceholderPattern:
    def test_pattern_matches_both_kinds_with_kind_and_key_groups(self):
        from review.lint.linter import PLACEHOLDER

        num = PLACEHOLDER.fullmatch("{{num:a.b-c_1}}")
        assert num is not None
        assert (num.group(1), num.group(2)) == ("num", "a.b-c_1")
        table = PLACEHOLDER.fullmatch("{{table:t1}}")
        assert table is not None
        assert (table.group(1), table.group(2)) == ("table", "t1")

    def test_pattern_rejects_unknown_kind_and_empty_key(self):
        from review.lint.linter import PLACEHOLDER

        assert PLACEHOLDER.search("{{numb:x}}") is None
        assert PLACEHOLDER.search("{{num:}}") is None
