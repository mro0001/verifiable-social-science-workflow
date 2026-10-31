"""Synthetic fixture for the annotate contract. Fake values, real shape."""
import docx

from .annotator import Annotation


def build_source_docx(path):
    doc = docx.Document()
    doc.add_heading("Widget compliance results", level=2)
    doc.add_paragraph("The gadget cohort improved by 12.5 percent overall in the trial window.")
    doc.add_paragraph("Prior work established the benchmark rate for comparable cohorts.")
    doc.save(str(path))
    return path


ANNOTATIONS = [
    Annotation(
        anchor="Widget compliance results",
        text="Section job. Establish that compliance discriminates between models before accuracy is discussed.",
        tag="section-job",
    ),
    Annotation(
        anchor="Prior work established the benchmark",
        text="Needs a grounded citation; route through the grounding loop before submission.",
        tag="grounding",
    ),
    Annotation(
        anchor="this text appears nowhere in the document",
        text="This one must miss.",
        tag=None,
    ),
]
