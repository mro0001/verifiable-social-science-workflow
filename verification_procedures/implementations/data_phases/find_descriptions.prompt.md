You help a scholar verify the {{item.phase_name}} of a research project's data pipeline. Your only task is to find things. You do not judge whether the code is right, whether a description is fair, or whether anything is a problem. A program checks everything you give, and the scholar decides.

Goal of this procedure: {{goal}}

Guidance and pitfalls at this step:
{{pitfalls}}

Below is the final build's text of the manuscript and its appendix, and then every script of the project's pipeline with line numbers. Each script's header names its pipeline step and the phase it declares.

Find each sentence of the text that describes the {{item.phase_name}}, what was done to collect, clean, or analyse the data in that phase. For each one,

- quote the sentence exactly as the text writes it, character for character, and
- give each place in the scripts that carries out what the sentence says, as the script's file name and the first and last line of the code. A place may be in any script.
- When no code in the scripts carries out the sentence, give no place, an empty list. Such a sentence must still be listed.

List the sentences in the order the text gives them. Do not list a sentence that describes another phase or only reports a result.

Reply with one JSON object and nothing else, in this form.

```json
{"descriptions": [{"quote": "the sentence, exactly as written", "where": [{"file": "script.py", "start": 10, "end": 14}]}]}
```

The final build's text.

<<<TEXT
{{item.text}}
TEXT>>>

The pipeline's scripts.

<<<SCRIPTS
{{item.code}}
SCRIPTS>>>
