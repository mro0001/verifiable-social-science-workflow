"""Return the refusal's code and the problem read_request stated, and no entry."""
import _lib

call = _lib.read_json("request_ok.json")
_lib.write_json("answer.json", {
    "tool": call["tool"],
    "result": {"error": {"code": call["error_code"], "message": call["problem"]}},
    "returned": [],
})
