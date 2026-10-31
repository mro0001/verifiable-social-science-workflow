---
title: "How Context Narrows a Model's Next Word"
subtitle: "A test manuscript for the reproducible pipeline"
---

This is a test manuscript. It shows a research product built from plain text by a build script [@healy2020], with every number filled in at build time from results the project's code computed.

## Data

The data come from a talk on prompting. A model, mistral-small:22b, was asked to finish the sentence "The ideal candidate for this internship is someone who is" with one word. It answered 60 times in each of three conditions, at temperature 1.0. The first condition gave only the question, the second added a job posting, and the third added a definition of "ideal candidate". The data file keeps the counts of the six most common words in each condition and the number of different words.

## Results

With the question alone, the model gave 16 different words, and its most common word, "proactive", made up 30.0 percent of its answers. With the posting and the definition, it gave 10 different words, led by "meticulous" at 30.0 percent. The table lists the three most common words in each condition.

| Condition | Different words | Most common words (share of answers) |
|---|---|---|
| Question only | 16 | proactive (30.0%), adaptable (28.3%), resilient (6.7%) |
| Plus the job posting | 15 | analytical (25.0%), curious (23.3%), proactive (16.7%) |
| Plus a definition | 10 | meticulous (30.0%), reliable (28.3%), organized (11.7%) |

Table: The model's one-word answers, 60 per condition.

More context did not make the model's answer certain, but it moved the answers toward words that match the posting and the definition.

## References
