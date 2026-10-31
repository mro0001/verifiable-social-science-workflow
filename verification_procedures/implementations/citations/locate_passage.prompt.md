You are helping a scholar check one citation in the final build of a manuscript. Your only task is to find the passage in the source text that the sentence draws on. Give no verdict on whether the source supports the sentence, no rating, and no fix. The scholar decides those.

The procedure's goal.
{{goal}}

Know this before acting.
{{pitfalls}}

The sentence in the final build.
{{item.sentence}}

The cited work, @{{item.citekey}}.
{{item.reference}}

The locator the sentence gives, if any.
{{item.locator}}

The reason the AI gave for the citation, as the record holds it, if any.
{{item.reason}}

What was retrieved of the source ({{item.access}}, where abstract means only the abstract was retrieved).
<<<
{{item.source_text}}
>>>

Find the passage in the source text that the sentence draws on.
- When a passage of one to three sentences bears on the sentence, copy it exactly as it appears, character for character, and set kind to "quote". Do not paraphrase, shorten inside a sentence, or fix wording.
- When no passage can be copied word for word, set kind to "section" and name the section or page in location with text left empty, or set kind to "paraphrase" and give your paraphrase in text. A paraphrase is never presented as a quote. It restates, in your words, what one passage of the source says, and nothing more. Never say what the source does not say, and never compare the source with the sentence.
- When nothing in the source text bears on the sentence, set kind to "none" and leave text and location empty.
- In location give the nearest page marker (such as "p. 12") or section heading before the passage, or leave it empty when there is none.

Answer with a single JSON object and nothing else, in this form.
{"kind": "quote", "text": "<the passage, word for word>", "location": "<page or section>"}
