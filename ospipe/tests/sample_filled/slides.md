---
title: Prompting Techniques
subtitle: Getting the output you want, by the process you want
author: Anonymous Authors
---

## Context changes the next word

Asked to finish "The ideal candidate for this internship is someone who is", mistral-small:22b gave 16 different words in 60 tries. With the job posting and a definition added, it gave 10.

| Condition | Different words | Most common words (share of answers) |
|---|---|---|
| Question only | 16 | proactive (30.0%), adaptable (28.3%), resilient (6.7%) |
| Plus the job posting | 15 | analytical (25.0%), curious (23.3%), proactive (16.7%) |
| Plus a definition | 10 | meticulous (30.0%), reliable (28.3%), organized (11.7%) |

Table: The model's one-word answers, 60 per condition.

## New session for a new task

Start over often. A new session clears out irrelevant or biasing context.

- Turn one asked for parody song lyrics about a university.
- Turn two asked for a resume edit, and the resume came back "brilliant" and "bold".

The song was still in the context while the model edited the resume.

## One task per prompt

One task per prompt keeps the request simple. Complexity adds breaking points.

- Four tasks in one prompt gave interview questions built from the resume, not the job description.
- The same request on its own gave questions built around the job description.
