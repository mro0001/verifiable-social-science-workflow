import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.foundation import (  # noqa: E402
    PLACEHOLDER,
    SUSPECT,
    ManifestError,
    MissingKeyError,
    load_manifest,
)
from ospipe.foundation import fixture  # noqa: E402


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestPlaceholderGrammar:
    def test_matches_num_and_table(self):
        found = PLACEHOLDER.findall(fixture.SAMPLE_MD)
        kinds = {k for k, _ in found}
        keys = {key for _, key in found}
        assert kinds == {"num", "table"}
        assert "widget_smape_real" in keys
        assert "widget_summary" in keys

    def test_key_class_accepts_dots_hyphens_underscores(self):
        assert PLACEHOLDER.fullmatch("{{num:widget.compliance.rate}}")
        assert PLACEHOLDER.fullmatch("{{num:widget-p-method}}")
        assert PLACEHOLDER.fullmatch("{{table:tbl_F1}}")

    def test_key_class_rejects_spaces_and_slashes(self):
        assert PLACEHOLDER.fullmatch("{{num:bad key}}") is None
        assert PLACEHOLDER.fullmatch("{{num:bad/key}}") is None

    def test_suspect_catches_typos_but_not_fence_braces(self):
        assert SUSPECT.search("text {{numb:x}} text")
        assert SUSPECT.search("{{tab:x}}")
        assert SUSPECT.search("{{'literal': 'value'}}") is None


class TestLoadManifest:
    def test_values_become_strings_real_shape(self, tmp_path):
        m = load_manifest(_write(tmp_path, "numbers.yml", fixture.MANIFEST_YAML))
        assert m["widget_smape_real"] == "33.5"
        assert m["widget.compliance.rate"] == "98.2%"
        assert m["widget-p-method"] == "0.050"
        assert m["n_cities"] == "24"
        assert all(isinstance(v, str) for v in m.values())

    def test_overlay_adds_keys(self, tmp_path):
        m = load_manifest(
            _write(tmp_path, "numbers.yml", fixture.MANIFEST_YAML),
            _write(tmp_path, "numbers_manual.yml", fixture.OVERLAY_YAML),
        )
        assert m["gadget_icc"] == "0.91"
        assert m["n_cities"] == "24"

    def test_overlay_collision_is_an_error(self, tmp_path):
        with pytest.raises(ManifestError, match="n_cities"):
            load_manifest(
                _write(tmp_path, "numbers.yml", fixture.MANIFEST_YAML),
                _write(tmp_path, "numbers_manual.yml", fixture.OVERLAY_COLLIDING_YAML),
            )

    def test_missing_overlay_is_fine(self, tmp_path):
        m = load_manifest(
            _write(tmp_path, "numbers.yml", fixture.MANIFEST_YAML),
            tmp_path / "does_not_exist.yml",
        )
        assert "widget_smape_real" in m

    def test_non_mapping_manifest_rejected(self, tmp_path):
        with pytest.raises(ManifestError):
            load_manifest(_write(tmp_path, "bad.yml", "- 1\n- 2\n"))

    def test_non_scalar_value_rejected(self, tmp_path):
        with pytest.raises(ManifestError):
            load_manifest(_write(tmp_path, "bad.yml", "k:\n  - 1\n"))

    def test_bad_key_grammar_rejected(self, tmp_path):
        with pytest.raises(ManifestError):
            load_manifest(_write(tmp_path, "bad.yml", '"bad key": 1\n'))


class TestNumbersShape:
    """The data procedure's numbers.yml: each key maps to {value, from, field, where}."""

    NUMBERS = (
        "numbers:\n"
        '  n_cities: {value: "24", from: table.csv, field: n}\n'
        '  widget.rate: {value: "98.2%", from: table.csv, field: rate, where: {row: widget}}\n'
        '  p_value: {value: "0.050", from: model.json, field: p}\n'
    )

    def test_values_are_read_as_display_strings(self, tmp_path):
        m = load_manifest(_write(tmp_path, "numbers.yml", self.NUMBERS))
        assert m == {"n_cities": "24", "widget.rate": "98.2%", "p_value": "0.050"}

    def test_entry_without_value_rejected(self, tmp_path):
        text = self.NUMBERS + "  orphan: {from: table.csv, field: n}\n"
        with pytest.raises(ManifestError, match="orphan"):
            load_manifest(_write(tmp_path, "numbers.yml", text))

    def test_overlay_still_adds_only(self, tmp_path):
        base = _write(tmp_path, "numbers.yml", self.NUMBERS)
        m = load_manifest(base, _write(tmp_path, "extra.yml", 'late_key: "7"\n'))
        assert m["late_key"] == "7" and m["n_cities"] == "24"
        with pytest.raises(ManifestError, match="n_cities"):
            load_manifest(base, _write(tmp_path, "clash.yml", 'n_cities: "25"\n'))


class TestMissingKeyError:
    def test_carries_all_keys_sorted(self):
        err = MissingKeyError(["zeta", "alpha", "alpha"])
        assert err.keys == ["alpha", "zeta"]
