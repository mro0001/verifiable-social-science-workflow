import _lib
words = _lib.read_text("words.txt").split()
_lib.write_json("items.json", [{"id": f"w{i+1}", "word": w} for i, w in enumerate(words)])
_lib.write_json("count.json", {"n": len(words)})
