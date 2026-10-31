---
title: "How Context Narrows a Model's Next Word"
subtitle: "A test manuscript for the reproducible pipeline"
---

This is a test manuscript. It shows a research product built from plain text by a build script, with every number filled in at build time from results the project's code computed.

## Data

The data come from a talk on prompting. A model, {{num:model}}, was asked to finish the sentence "{{num:question}}" with one word. It answered {{num:n_per_condition}} times in each of three conditions, at temperature {{num:temperature}}. The first condition gave only the question, the second added a job posting, and the third added a definition of "ideal candidate". The data file keeps the counts of the six most common words in each condition and the number of different words.

## Results

With the question alone, the model gave {{num:none.distinct}} different words, and its most common word, "{{num:none.top_word}}", made up {{num:none.top_pct}} percent of its answers. With the posting and the definition, it gave {{num:definition.distinct}} different words, led by "{{num:definition.top_word}}" at {{num:definition.top_pct}} percent. The table lists the three most common words in each condition.

{{table:top_words}}

More context did not make the model's answer certain, but it moved the answers toward words that match the posting and the definition.

Castellanos and Ibe describe retention as a matter of fit between the volunteer's goals and the tasks offered [@castellanos2017]. Clear end dates for assignments made volunteers more willing to sign up again [@dumont2014]. Recognition events reduced exit among long-serving volunteers [@nakamura2020].

## References
