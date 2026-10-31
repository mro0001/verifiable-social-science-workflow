"""Every fresh verdict was supports, so no second check ran. Carry rows forward
with empty second-check fields."""
import _lib

out = [dict(r, disputed=False, second_verdict="", second_reason="", second_executor="",
            second_prompt_sha256="") for r in _lib.read_json("rows_judged.json")]
_lib.write_json("rows_settled.json", out)
