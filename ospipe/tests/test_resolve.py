import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.foundation import MissingKeyError, fixture as f_fix  # noqa: E402
from ospipe.resolve import ResolveError, resolve  # noqa: E402
from ospipe.resolve import fixture as r_fix  # noqa: E402


class TestSubstitution:
    def test_end_to_end_real_shape(self):
        manifest = dict(r_fix.MANIFEST)
        tables = {"widget_summary": f_fix.SAMPLE_TABLE}
        out = resolve(f_fix.SAMPLE_MD, manifest, tables)
        assert "33.5" in out
        assert "98.2%" in out
        assert "(p = 0.050)" in out
        assert "{{num:" not in out
        assert "{{table:" not in out
        assert "| widget | 33.5 |" in out

    def test_values_land_verbatim_no_formatting(self):
        out = resolve("p = {{num:widget-p-method}}", r_fix.MANIFEST, {})
        assert out == "p = 0.050"

    def test_table_block_gets_exactly_one_blank_line_each_side(self):
        text = "Before.\n{{table:tiny_table}}\nAfter.\n"
        out = resolve(text, r_fix.MANIFEST, r_fix.TABLES)
        assert "Before.\n\n| a | b |" in out
        assert "| 1.5 | 2 |\n\nAfter." in out

    def test_table_at_file_start_has_no_leading_blanks(self):
        out = resolve(r_fix.START_MD, r_fix.MANIFEST, r_fix.TABLES)
        assert out.startswith("| a | b |")
        assert "1.5 units" in out

    def test_table_containing_num_placeholder_resolves_same_pass(self):
        out = resolve("{{table:tiny_table}}", r_fix.MANIFEST, r_fix.TABLES)
        assert "| 1.5 | 2 |" in out

    def test_two_placeholders_on_one_line(self):
        out = resolve(r_fix.TWO_ON_ONE_LINE_MD, r_fix.MANIFEST, {})
        assert "Rates were 1.5 and then 97.4% at follow-up." in out


class TestMissingKeys:
    def test_all_missing_keys_both_kinds_in_one_failure(self):
        with pytest.raises(MissingKeyError) as exc:
            resolve(r_fix.MISSING_BOTH_MD, r_fix.MANIFEST, r_fix.TABLES)
        assert exc.value.keys == ["ghost_number", "phantom_table"]

    def test_missing_num_inside_used_table_is_collected(self):
        tables = {"bad_table": "| x |\n|---|\n| {{num:nowhere}} |\n"}
        with pytest.raises(MissingKeyError) as exc:
            resolve("{{table:bad_table}}", r_fix.MANIFEST, tables)
        assert "nowhere" in exc.value.keys


class TestRemnantScan:
    def test_typo_remnant_raises_with_line_and_remnant(self):
        with pytest.raises(ResolveError) as exc:
            resolve(r_fix.TYPO_MD, r_fix.MANIFEST, {})
        assert exc.value.line == 2
        assert exc.value.remnant == "{{numb:"

    def test_fenced_code_is_exempt(self):
        out = resolve(r_fix.FENCE_EXEMPT_MD, r_fix.MANIFEST, {})
        assert "{{fake:thing}}" in out

    def test_inline_code_span_is_exempt(self):
        # Track L, Step L6. Inline code is left as written, as pandoc prints it,
        # so a remnant there is no longer one.
        out = resolve(r_fix.INLINE_SPAN_MD, r_fix.MANIFEST, {})
        assert out == r_fix.INLINE_SPAN_MD

    def test_a_remnant_after_a_fence_that_never_closes_is_caught(self):
        # Pandoc prints such a fence and what follows it as text.
        with pytest.raises(ResolveError) as exc:
            resolve("```\nThis has a {{numb:alpha}} typo.\n", r_fix.MANIFEST, {})
        assert exc.value.line == 2

    def test_a_remnant_after_code_is_named_on_its_own_line(self):
        text = "```\n{{num:alpha}}\n```\nSee `{{x:1}}`.\nThis has a {{numb:alpha}} typo.\n"
        with pytest.raises(ResolveError) as exc:
            resolve(text, r_fix.MANIFEST, {})
        assert exc.value.line == 5
        assert exc.value.remnant == "{{numb:"

    def test_foundation_fence_braces_survive_untouched(self):
        tables = {"widget_summary": f_fix.SAMPLE_TABLE}
        out = resolve(f_fix.SAMPLE_MD, dict(r_fix.MANIFEST), tables)
        assert "{{'literal': 'braces in a fence stay untouched'}}" in out


class TestCodeIsLeftAlone:
    """Track L, Step L6. Placeholders inside inline code and fenced code blocks are
    left as written, as pandoc prints them, and only those outside code are filled.
    Each case was also read with pandoc 3.9 (-f markdown -t native)."""

    def test_a_placeholder_in_inline_code_is_left_and_one_in_text_is_filled(self):
        # Track Q, Step Q3. A key the manifest does not hold stays an example.
        text = "Write `{{num:key}}` to cite a number, as in {{num:alpha}}.\n"
        out = resolve(text, r_fix.MANIFEST, {})
        assert out == "Write `{{num:key}}` to cite a number, as in 1.5.\n"

    def test_a_missing_key_in_inline_code_does_not_stop_the_build(self):
        text = "A table is `{{table:any_name}}` and a number `{{num:any_key}}`.\n"
        assert resolve(text, r_fix.MANIFEST, {}) == text

    def test_a_longer_backtick_run_holds_a_backtick_inside(self):
        text = "As in ``say `{{num:ghost}}` here`` and {{num:beta}}.\n"
        out = resolve(text, r_fix.MANIFEST, {})
        assert out == "As in ``say `{{num:ghost}}` here`` and 97.4%.\n"

    @pytest.mark.parametrize(
        "opening, closing",
        [
            ("```", "```"),
            ("````", "`````"),
            ("```markdown", "```"),
            ("~~~", "~~~"),
            ("~~~~ {.md}", "~~~~"),
            ("   ```", "```"),
        ],
    )
    def test_a_placeholder_in_a_fenced_block_is_left(self, opening, closing):
        text = (
            "Before {{num:alpha}}.\n\n"
            + opening + "\n"
            + "{{num:ghost}} and {{table:phantom}} and {{numb:typo}}\n"
            + "``` is not a close here\n~~~ nor this\n"
            + closing + "\n\nAfter {{num:beta}}.\n"
        )
        out = resolve(text, r_fix.MANIFEST, {})
        assert out == text.replace("{{num:alpha}}", "1.5").replace("{{num:beta}}", "97.4%")

    def test_a_run_with_no_close_is_read_again_from_its_second_backtick(self):
        # Pandoc prints the first backtick as text and opens code at the second.
        text = "a ``{{num:ghost}}` b\n"
        assert resolve(text, r_fix.MANIFEST, {}) == text

    def test_a_backtick_fence_right_under_a_line_of_text_is_code(self):
        text = "Para.\n```\n{{num:ghost}}\n```\n"
        assert resolve(text, r_fix.MANIFEST, {}) == text

    def test_a_tilde_fence_right_under_a_line_of_text_is_text(self):
        # Pandoc reads it as part of the paragraph, so the placeholder is printed
        # as text and is filled.
        text = "Para.\n~~~\n{{num:alpha}}\n~~~\n"
        assert resolve(text, r_fix.MANIFEST, {}) == "Para.\n~~~\n1.5\n~~~\n"

    @pytest.mark.parametrize(
        "text, expected",
        [
            # A backtick with no closing run is text.
            ("a `{{num:alpha}} b\n", "a `1.5 b\n"),
            # An escaped backtick opens no code.
            ("a \\`{{num:alpha}}` b\n", "a \\`1.5` b\n"),
            # Inline code ends at a blank line.
            ("a `{{num:alpha}}\n\nb` c\n", "a `1.5\n\nb` c\n"),
            # A fence that never closes opens no block.
            ("```\n{{num:alpha}}\n", "```\n1.5\n"),
            # A closing run of another length does not close the code.
            ("a ``{{num:alpha}}``` b\n", "a ``1.5``` b\n"),
        ],
    )
    def test_what_pandoc_prints_as_text_is_filled(self, text, expected):
        assert resolve(text, r_fix.MANIFEST, {}) == expected

    def test_missing_keys_in_text_are_all_listed_and_those_in_code_are_not(self):
        text = (
            "Shown as `{{num:shown_key}}`.\n\n```\n{{table:shown_table}}\n```\n\n"
            + r_fix.MISSING_BOTH_MD
        )
        with pytest.raises(MissingKeyError) as exc:
            resolve(text, r_fix.MANIFEST, r_fix.TABLES)
        assert exc.value.keys == ["ghost_number", "phantom_table"]

    def test_a_table_placeholder_in_code_is_left_and_one_in_text_is_filled(self):
        text = "Write `{{table:tiny_table}}` on its own line.\n{{table:tiny_table}}\n"
        out = resolve(text, r_fix.MANIFEST, r_fix.TABLES)
        assert out.startswith("Write `{{table:tiny_table}}` on its own line.\n\n| a | b |")
        assert "| 1.5 | 2 |" in out

    def test_code_inside_a_table_is_left_too(self):
        tables = {"coded": "| `{{num:ghost}}` | {{num:alpha}} |\n"}
        out = resolve("{{table:coded}}\n", r_fix.MANIFEST, tables)
        assert out == "| `{{num:ghost}}` | 1.5 |\n\n"

    def test_text_without_code_resolves_exactly_as_before(self):
        tables = {"widget_summary": f_fix.SAMPLE_TABLE}
        out = resolve(f_fix.SAMPLE_MD, dict(r_fix.MANIFEST), tables)
        assert "| widget | 33.5 |" in out
        assert "{{num:" not in out

    @pytest.mark.parametrize(
        "first, second",
        [
            ("1. ", "2. "),
            ("1) ", "2) "),
            ("- ", "- "),
            ("* ", "* "),
            ("+ ", "+ "),
            ("a. ", "b. "),
            ("(1) ", "(2) "),
            ("#. ", "#. "),
        ],
    )
    def test_a_stray_backtick_in_one_list_item_does_not_reach_the_next(self, first, second):
        # Pandoc ends inline code at the end of its list item, so the stray
        # backtick is text and the placeholder in the next item is text too.
        text = (
            first + "Run the script with a ` before it.\n"
            + second + "The mean is {{num:alpha}} and see `out.csv`.\n"
        )
        assert resolve(text, r_fix.MANIFEST, {}) == text.replace("{{num:alpha}}", "1.5")

    @pytest.mark.parametrize(
        "line",
        [
            "> The mean is {{num:alpha}} and see `out.csv`.\n",
            "# The mean is {{num:alpha}} and see `out.csv`.\n",
            "| The mean is {{num:alpha}} | `out.csv` |\n",
        ],
    )
    def test_a_stray_backtick_above_a_line_that_starts_a_block_leaves_it_filled(self, line):
        # Where pandoc could read the line either way, the placeholder is filled.
        text = "A stray ` here.\n" + line
        assert resolve(text, r_fix.MANIFEST, {}) == text.replace("{{num:alpha}}", "1.5")

    def test_code_that_runs_across_two_lines_is_filled(self):
        # Pandoc prints this placeholder inside code, but whether a span runs
        # across a line depends on how the blocks fall, so it is filled, the
        # safe way to err.
        text = "Para `a\nb {{num:alpha}}` end\n"
        assert resolve(text, r_fix.MANIFEST, {}) == "Para `a\nb 1.5` end\n"

    @pytest.mark.parametrize(
        "text",
        [
            # A line that starts a list inside a paragraph is part of the
            # paragraph, so the stray backtick pairs with the next one.
            "A ` stray\n1. text ` {{num:alpha}} `x`.\n",
            "A ` stray\n- then ` {{num:alpha}} `x`.\n",
            # A line block line that runs on to the next line.
            "| line ` stray\n  more ` text {{num:alpha}} `x`.\n",
            # The pairing is set by backticks in an earlier list item.
            "1. text ``` one `\n: two\n  - three\n  four ``` ` five\n#. `` {{num:alpha}} \\` `\n",
            # Simple, multiline and grid tables cut a line into cells.
            "  Name     Value\n--------  ------------\n  `run    {{num:alpha}}`\n\n",
            "-----------------\n Name     Value\n-------- --------\n `run     x\n\n"
            " `y      {{num:alpha}}`\n-----------------\n\n",
            "+-------+-------+\n| `a    | {{num:alpha}}` |\n+-------+-------+\n",
            # An autolink, raw HTML, a link target or math holds a backtick.
            "See <http://x`y> and {{num:alpha}} `x`.\n",
            '<span title="`">a</span> {{num:alpha}} `x`.\n',
            "[a](x`y) {{num:alpha}} `x`.\n",
            "$a`b$ {{num:alpha}} `x`.\n",
            # So does a TeX command.
            "\\emph{`} {{num:alpha}} `x`.\n",
            # A fence whose words after the backticks hold a space opens no block.
            "``` a b\nx ``` {{num:alpha}}\n```\n",
            # So does one with braces that are not attributes.
            "~~~ {r}\n{{num:alpha}}\n~~~\n",
            "~~~ x{y}\n{{num:alpha}}\n~~~\n",
            # A break other than a newline does not end a line for pandoc.
            "\u2028~~~\n{{num:alpha}}\n~~~\n",
        ],
    )
    def test_what_pandoc_prints_as_text_is_filled_however_backticks_pair(self, text):
        # Each case was read with pandoc 3.9.0.2, which prints the placeholder
        # as text.
        assert resolve(text, r_fix.MANIFEST, {}) == text.replace("{{num:alpha}}", "1.5")

    def test_code_holding_a_pipe_in_a_pipe_table_is_left(self):
        # Pandoc keeps a code span whole across a pipe in a pipe table cell.
        text = "| a | b |\n|---|---|\n| `x | {{num:ghost}}` | {{num:alpha}} |\n"
        assert resolve(text, r_fix.MANIFEST, {}) == text.replace("{{num:alpha}}", "1.5")

    def test_a_manifest_value_holding_the_stand_in_character_comes_out_unchanged(self):
        manifest = dict(r_fix.MANIFEST, alpha="")
        out = resolve("See `{x}` and {{num:alpha}}.\n", manifest, {})
        assert out == "See `{x}` and .\n"


SAMPLE_PROJECT = Path(__file__).resolve().parents[2] / "examples" / "sample_project"


class TestBoundNumbersInCodeAreFilled:
    """Track Q, Step Q3. Inside inline code and fenced code, a placeholder whose
    key the manifest holds is filled and any other placeholder is left as
    written. Outside code the rule is unchanged."""

    def test_a_bound_key_in_inline_code_is_filled(self):
        text = "Run `head -n {{num:n_cities}} cities.csv` to see them.\n"
        out = resolve(text, r_fix.MANIFEST, {})
        assert out == "Run `head -n 24 cities.csv` to see them.\n"

    @pytest.mark.parametrize(
        "opening, closing",
        [
            ("```", "```"),
            ("````", "`````"),
            ("```r", "```"),
            ("~~~", "~~~"),
            ("~~~~ {.r}", "~~~~"),
            ("   ```", "```"),
        ],
    )
    def test_a_bound_key_in_a_fenced_block_is_filled(self, opening, closing):
        text = (
            "Before {{num:alpha}}.\n\n"
            + opening + "\n"
            + "n_cities <- {{num:n_cities}}\n"
            + "rate <- \"{{num:widget.compliance.rate}}\"\n"
            + closing + "\n\nAfter {{num:beta}}.\n"
        )
        out = resolve(text, r_fix.MANIFEST, {})
        assert out == (
            "Before 1.5.\n\n"
            + opening + "\n"
            + "n_cities <- 24\n"
            + "rate <- \"98.2%\"\n"
            + closing + "\n\nAfter 97.4%.\n"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Write `{{num:key}}` to cite a number.\n",
            "```\nx <- {{num:ghost}}\n```\n",
            "~~~ {.md}\nCite {{num:any_key}} like this.\n~~~\n",
        ],
    )
    def test_an_unknown_key_in_code_is_left_without_stopping_the_build(self, text):
        assert resolve(text, r_fix.MANIFEST, {}) == text

    def test_bound_and_unknown_keys_in_one_span_are_each_handled(self):
        text = "As in `{{num:alpha}} and {{num:ghost}}` here.\n"
        out = resolve(text, r_fix.MANIFEST, {})
        assert out == "As in `1.5 and {{num:ghost}}` here.\n"

    def test_an_unknown_key_in_text_still_stops_the_build_with_every_missing_key(self):
        text = (
            "Code `{{num:alpha}}` and `{{num:shown_key}}`.\n\n"
            "```\n{{num:n_cities}} {{num:fenced_key}}\n```\n\n"
            + r_fix.MISSING_BOTH_MD
            + "Also {{num:second_ghost}}.\n"
        )
        with pytest.raises(MissingKeyError) as exc:
            resolve(text, r_fix.MANIFEST, r_fix.TABLES)
        assert exc.value.keys == ["ghost_number", "phantom_table", "second_ghost"]

    def test_a_table_placeholder_in_code_is_still_left_though_the_table_exists(self):
        text = "Write `{{table:tiny_table}}` on its own line.\n"
        assert resolve(text, r_fix.MANIFEST, r_fix.TABLES) == text

    def test_a_bound_key_in_code_inside_a_table_is_filled(self):
        tables = {"coded": "| `{{num:alpha}}` | `{{num:ghost}}` |\n"}
        out = resolve("{{table:coded}}\n", r_fix.MANIFEST, tables)
        assert out == "| `1.5` | `{{num:ghost}}` |\n\n"

    def test_a_remnant_in_code_is_still_not_a_remnant(self):
        text = "```\n{{numb:alpha}} and {{num:alpha}}\n```\n"
        out = resolve(text, r_fix.MANIFEST, {})
        assert out == "```\n{{numb:alpha}} and 1.5\n```\n"

    @pytest.mark.parametrize("name", ["manuscript.md", "slides.md"])
    def test_the_sample_project_fills_to_the_same_text_as_before(self, name):
        # The filled text each A4 sample build keeps as v001.md, as built before
        # Step Q3, is kept in tests/sample_filled. It is compared as text, not by
        # checksum, so a copy that rewrites a word in both still passes.
        from ospipe.foundation import load_manifest

        manifest = load_manifest(SAMPLE_PROJECT / "numbers.yml")
        tables = {
            path.stem: path.read_text(encoding="utf-8")
            for path in sorted(SAMPLE_PROJECT.glob("*.md"))
        }
        text = (SAMPLE_PROJECT / name).read_text(encoding="utf-8")
        out = resolve(text, manifest, tables)
        assert out == (Path(__file__).resolve().parent / "sample_filled" / name).read_text(encoding="utf-8")
