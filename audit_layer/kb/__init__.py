"""The audit layer's knowledge base (appendix A2.4).

The entries are plain files in the corpus folder beside this file, one
<group lowercased>/<id>.md per entry, with the index llms.txt. Sessions in any
project read them through the knowledge base server. The knowledge base moved
here from ospipe on 2026-10-29.
"""
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus"
