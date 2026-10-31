# Critique the workflow

The workflow is meant to be scrutinized, so every page of this portal has a critique box. Go back to [the portal's home](home.md), or read how to [implement the workflow](implement.md).

## Every page names what it is about

Each page lists its source and its source version. For a knowledge base entry the source is the file the entry describes and the version is the one its heading records. For a procedure or a documentation page the source is the file the page is built from and the version is the start of that file's checksum. A critique carries both, so it stays tied to the text it is about even after the page changes.

## Write a critique

1. Open the page you want to critique.
2. At the foot of the page, under Critique this page, write your name.
3. Choose the section the critique is about, one of the page's headings or the whole page.
4. Write what is wrong, missing, or unclear, and what you would do instead.
5. Press Copy to put the critique on the clipboard, or Save to download it as a file named `critique_<page id>_<date>.yaml`.

## What a critique holds

A saved critique is a small YAML file like this one.

```yaml
schema: "portal-critique"
schema_version: 1
page: "procedures-build"
title: "The build procedure"
source: "verification_procedures/graphs/build.yaml"
source_commit: "sha256:9b896c086d04"
section: "whole page"
by: "A. Scholar"
date: "2026-10-29"
text: "The rebuild step does not say what happens when Pandoc's version differs."
```

## Where critiques go

The portal sends nothing anywhere and collects nothing. Keep the saved file, or send it to the workflow's authors in whatever way suits you. If the page's script does not run, write the same keys in a file by hand.
