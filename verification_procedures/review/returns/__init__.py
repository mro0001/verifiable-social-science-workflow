"""returns node: extract tracked edits and margin comments from a reviewed docx."""
from review.returns.extractor import Comment, Delta, ReturnBundle, extract

__all__ = ["Comment", "Delta", "ReturnBundle", "extract"]
