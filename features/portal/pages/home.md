# The portal

This portal gathers the AI-enhanced workflow for verifiable social science in one place, so a scholar can learn how it works, set it up, and critique any part of it. It is built from the workflow's own files, the verification procedures written as procedural graphs, the knowledge base entries, and the documentation. Every page names the file it comes from and that file's version, and every page has a box for writing a critique of it.

## The four streams

The workflow sorts AI contributions into four streams. Each stream has its own tools and its own verification procedure, and each procedure has a page that lists its steps in order and the edges between them.

| Stream | Tools | Verification procedure |
|---|---|---|
| Prose | Text editor | [Change review](../../../verification_procedures/graphs/prose.yaml) |
| References | Citation manager | [Source support](../../../verification_procedures/graphs/citations.yaml) |
| Data and analysis code | R, Python, Quarto | [Code](../../../verification_procedures/graphs/data.yaml) |
| Build | Pandoc, Make | [Build integrity](../../../verification_procedures/graphs/build.yaml) |

## Where to start

- To learn how a check works, open one of the four procedures above, then read [how the verification graphs run](../../../verification_procedures/README.md). The knowledge base entries under Learn explain each part of the workflow in a short answer first.
- To set the workflow up and try it on the sample project, read [Implement the workflow](implement.md).
- To say what is wrong, missing, or unclear, read [Critique the workflow](critique.md), then use the critique box at the foot of any page.

The search box at the top finds pages by their title, short answer, group, and kind. The buttons below show one section of the catalog at a time.
