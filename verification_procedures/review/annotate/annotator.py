"""Word margin comments anchored to text. FROZEN surface documented in CONTRACT.md."""
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence

import docx
import yaml


class Annotation(NamedTuple):
    anchor: str
    text: str
    tag: Optional[str] = None


class AnnotateResult(NamedTuple):
    count: int
    out_path: str
    misses: List[str]


def load_annotations(yaml_path) -> List[Annotation]:
    raw = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{yaml_path}: annotation spec must be a YAML list")
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "anchor" not in item or "text" not in item:
            raise ValueError(f"{yaml_path}: item {i} needs 'anchor' and 'text' keys")
        out.append(Annotation(str(item["anchor"]), str(item["text"]), item.get("tag")))
    return out


def _comment_body(ann: Annotation) -> str:
    return f"[{ann.tag}] {ann.text}" if ann.tag else ann.text


def annotate(docx_path, annotations: Sequence[Annotation], out_path, author: str = "Claude") -> AnnotateResult:
    doc = docx.Document(str(docx_path))
    paragraphs = list(doc.paragraphs)
    count = 0
    misses: List[str] = []
    for ann in annotations:
        target = None
        for para in paragraphs:
            if ann.anchor in para.text and para.runs:
                target = para
                break
        if target is None:
            misses.append(ann.anchor)
            continue
        initials = "".join(w[0] for w in author.split()[:2]).upper() or "A"
        doc.add_comment(runs=target.runs, text=_comment_body(ann), author=author, initials=initials)
        count += 1
    out_path = str(out_path)
    doc.save(out_path)
    return AnnotateResult(count=count, out_path=out_path, misses=misses)
