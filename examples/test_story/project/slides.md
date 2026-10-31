---
title: Prompting Techniques
subtitle: Getting the output you want, by the process you want
author: Anonymous Authors
---

## Context changes the next word

Asked to finish "{{num:question}}", {{num:model}} gave {{num:none.distinct}} different words in {{num:n_per_condition}} tries. With the job posting and a definition added, it gave {{num:definition.distinct}}.

{{table:top_words}}

## New session for a new task

Start over often. A new session clears out irrelevant or biasing context.

- Turn one asked for parody song lyrics about a university.
- Turn two asked for a resume edit, and the resume came back "brilliant" and "bold".

The song was still in the context while the model edited the resume.

## One task per prompt

One task per prompt keeps the request simple. Complexity adds breaking points.

- Four tasks in one prompt gave interview questions built from the resume, not the job description.
- The same request on its own gave questions built around the job description.
