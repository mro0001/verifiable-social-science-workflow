# References report

The text read is the final build's text, `draft.md` (sha256:667c48dc9515ec4faa145da42436a7696a65a60039dbba57ae800f7fa7520d05). Each citation in it is listed with who first named the cited work in the record of sessions and artifacts. For each citation from an AI, the report says whether the work could be found, and for each work found it gives the AI's recorded reason and a quote, which a program then looks for in the source text. Nothing here is a verdict. The scholar approves or holds each citation from an AI and each one the record never names.

| Count | Number |
|---|---|
| Citations in the final build | 15 |
| From an AI | 11 |
| The scholar's | 2 |
| Never named in the record | 2 |
| Works not found | 2 |
| Works not looked up | 0 |
| AI citations with no quote found in their source | 1 |
| Quotes in the record not found in their source | 1 |
| AI citations with no recorded reason | 2 |

## Citations

**From an AI (11)**

### r01: @abara2019

- **Sentence:** In a panel of 48 city programs, 31% of first-year volunteers left before completing six months of service [@abara2019, p. 7].
- **Origin:** First named by an AI at 2026-10-12T09:00:05Z in session S3a41c0d2e9f7, where the record reads "Abara and Hollis (2019) report that 31% of first-year volunteers left within six months."
- **Session:** S3a41c0d2e9f7
- **Reference:** Abara, N., Hollis, T. (2019). Ownership and exit in municipal volunteer programs. Journal of Civic Administration. doi:10.5555/jca.2019.0142
- **Found:** found in the metadata cache (DOI 10.5555/jca.2019.0142). The record reads Abara, N., Hollis, T. (2019). Ownership and exit in municipal volunteer programs. Journal of Civic Administration. Type journal-article.
- **Reason:** "Abara and Hollis (2019) report that 31% of first-year volunteers left within six months. Their panel paper gives the figure directly, "Across the 48 programs in our panel, 31% of first-year volunteers exited before completing six months of service." It fits the opening claim about first-year loss." (said by the AI at 2026-10-12T09:00:05Z in session S3a41c0d2e9f7)
- **Quote:** "Across the 48 programs in our panel, 31% of first-year volunteers exited before completing six months of service." (from the record, at 2026-10-12T09:00:05Z in session S3a41c0d2e9f7)
- **Quote check:** found in source_abara2019.txt, at p. 7, which holds the full text
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_abara2019.txt sha256:ad8f787f260f... (record 07_pin_sources); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r02: @ferrante2021

- **Sentence:** Exit is steepest among volunteers recruited through online portals [@ferrante2021].
- **Origin:** First named by an AI at 2026-10-12T09:02:11Z in session S3a41c0d2e9f7, where the record reads "Ferrante, L. (2021). Digital recruitment and early exit among civic volunteers. Nonprofit Management Review."
- **Session:** S3a41c0d2e9f7
- **Reference:** Ferrante, L. (2021). Digital recruitment and early exit among civic volunteers. Nonprofit Management Review. doi:10.5555/nmr.2021.0388
- **Found:** not found, since DOI 10.5555/nmr.2021.0388 is not in the metadata cache and live lookup was off
- **Notes:** @ferrante2021 was not found, since DOI 10.5555/nmr.2021.0388 is not in the metadata cache and live lookup was off
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); times are each record's started_at

### r04: @brennan2016

- **Sentence:** Brennan puts it plainly that volunteers leave once the work no longer feels like their own [@brennan2016, p. 12].
- **Origin:** First named by an AI at 2026-10-12T09:05:30Z in session S3a41c0d2e9f7, where the record reads "Brennan (2016) makes the point in plain words."
- **Session:** S3a41c0d2e9f7
- **Reference:** Brennan, S. (2016). The work is theirs. Civic Press. doi:10.5555/cp.2016.0007
- **Found:** found in the metadata cache (DOI 10.5555/cp.2016.0007). The record reads Brennan, S. (2016). The work is theirs. Civic Press. Type book.
- **Reason:** "Brennan (2016) makes the point in plain words, "volunteers leave when the work stops feeling like their own", which suits the second section." (said by the AI at 2026-10-12T09:05:30Z in session S3a41c0d2e9f7)
- **Quote:** "volunteers leave when the work stops feeling like their own" (from the record, at 2026-10-12T09:05:30Z in session S3a41c0d2e9f7); "Volunteers tend to exit once they no longer experience the work as theirs." (located by recorded:recorded_judge.json, at p. 12)
- **Quote check:** not found in source_brennan2016.txt; found in source_brennan2016.txt, at p. 12, which holds the full text
- **Notes:** the quote given for @brennan2016 is not in its source text source_brennan2016.txt
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_brennan2016.txt sha256:661edc2f7373... (record 07_pin_sources); passage located by recorded:recorded_judge.json (record 09_locate_passage); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r05: @kessler2019

- **Sentence:** Programs that cut orientation to a single session saw retention fall [@kessler2019].
- **Origin:** First named by an AI at 2026-10-12T09:07:02Z in session S3a41c0d2e9f7, where the record reads "Kessler (2019) compared single-session orientation with longer ones and found that retention fell."
- **Session:** S3a41c0d2e9f7
- **Reference:** Kessler, D. (2019). Orientation length and volunteer retention. Journal of Civic Administration. doi:10.5555/jca.2019.0215
- **Found:** found in the metadata cache (DOI 10.5555/jca.2019.0215). The record reads Kessler, D. (2019). Orientation length and volunteer retention. Journal of Civic Administration. Type journal-article.
- **Reason:** "Kessler (2019) compared single-session orientation with longer ones and found that retention fell. That supports the orientation sentence." (said by the AI at 2026-10-12T09:07:02Z in session S3a41c0d2e9f7)
- **Quote:** "Programs that cut orientation to a single session saw retention fall by 42% within a year." (located by recorded:recorded_judge.json, at p. 9)
- **Quote check:** not found in source_kessler2019.txt, which holds the full text
- **Notes:** the quote given for @kessler2019 is not in its source text source_kessler2019.txt
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_kessler2019.txt sha256:7d9630b8ffa5... (record 07_pin_sources); passage located by recorded:recorded_judge.json (record 09_locate_passage); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r06: @okafor2018

- **Sentence:** Volunteers who received written role descriptions stayed longer than those who did not [@okafor2018, p. 4].
- **Origin:** First named by an AI at 2026-10-12T09:08:15Z in session S3a41c0d2e9f7, where the record reads "Okafor, A. (2018). Written role descriptions and volunteer tenure. Public Service Quarterly."
- **Session:** S3a41c0d2e9f7
- **Reference:** Okafor, A. (2018). Written role descriptions and volunteer tenure. Public Service Quarterly. doi:10.5555/psq.2019.0044
- **Found:** found in the metadata cache (DOI 10.5555/psq.2019.0044). The record reads Okafor, A. (2019). Written role descriptions and volunteer tenure. Public Service Quarterly. Type journal-article.
- **Reason:** no reason recorded
- **Quote:** "Volunteers who received a written description of their role remained active longer than volunteers who received only a verbal briefing." (located by recorded:recorded_judge.json, at p. 4)
- **Quote check:** found in source_okafor2018.txt, at p. 4, which holds the full text
- **Notes:** no reason is recorded for @okafor2018, since the record holds no AI words around its first AI appearance
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_okafor2018.txt sha256:6a6b24c93e2b... (record 07_pin_sources); passage located by recorded:recorded_judge.json (record 09_locate_passage); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r07: @marchetti2012

- **Sentence:** Marchetti studies the records volunteers leave behind [@marchetti2012].
- **Origin:** First named by an AI at 2026-10-13T10:01:00Z in session S7be25f19c0a4 in notes/sources.md, where the record reads "Marchetti (2012) studies the records volunteers leave behind."
- **Session:** S7be25f19c0a4
- **Reference:** Marchetti, P. (2012). Administrative traces of volunteer work. Records and Society. doi:10.5555/rs.2012.0109
- **Found:** found in the metadata cache (DOI 10.5555/rs.2012.0109). The record reads Marchetti, P. (2012). Administrative traces of volunteer work. Records and Society. Type journal-article.
- **Reason:** "Marchetti (2012) studies the records volunteers leave behind, sign-in sheets and shift logs, and is a good anchor for the records sentence." (said by the AI at 2026-10-13T10:01:00Z in session S7be25f19c0a4 in notes/sources.md)
- **Quote:** a section pointer, p. 3, on the administrative traces of volunteer activity (located by recorded:recorded_judge.json)
- **Quote check:** not checked word for word, since it is a section pointer
- **Notes:** no exact quote was given for @marchetti2012, since the passage step gave a section pointer, which is not checked word for word
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_marchetti2012.txt sha256:bf71479d4325... (record 07_pin_sources); passage located by recorded:recorded_judge.json (record 09_locate_passage); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r08: @nakamura2020

- **Sentence:** Recognition events had no clear effect on exit among long-serving volunteers [@nakamura2020].
- **Origin:** First named by an AI at 2026-10-13T10:03:20Z in session S7be25f19c0a4, where the record reads "Nakamura (2020) looked at recognition events among long-serving volunteers."
- **Session:** S7be25f19c0a4
- **Reference:** Nakamura, E. (2020). Recognition events and the long-serving volunteer. Voluntary Sector Studies. doi:10.5555/vss.2020.0063
- **Found:** found in the metadata cache (DOI 10.5555/vss.2020.0063). The record reads Nakamura, E. (2020). Recognition events and the long-serving volunteer. Voluntary Sector Studies. Type journal-article.
- **Reason:** "Nakamura (2020) looked at recognition events among long-serving volunteers. Their result belongs beside the feedback finding." (said by the AI at 2026-10-13T10:03:20Z in session S7be25f19c0a4)
- **Quote:** "Recognition events had no measurable effect on exit among long-serving volunteers." (located by recorded:recorded_judge.json, at p. 15)
- **Quote check:** found in source_nakamura2020.txt, at p. 15, which holds the full text
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_nakamura2020.txt sha256:b76d203442be... (record 07_pin_sources); passage located by recorded:recorded_judge.json (record 09_locate_passage); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r09: @lindqvist2020

- **Sentence:** Supervisors' feedback quality predicted whether volunteers returned for a second season [@lindqvist2020].
- **Origin:** First named by an AI at 2026-10-13T10:04:44Z in session S7be25f19c0a4, where the record reads "Lindqvist, H., & Moreau, J. (2020). Supervisor feedback and seasonal return."
- **Session:** S7be25f19c0a4
- **Reference:** Lindqvist, H., Moreau, J. (2020). Supervisor feedback and seasonal return. Nonprofit Management Review. doi:10.5555/nmr.2020.0157
- **Found:** found in the metadata cache (DOI 10.5555/nmr.2020.0157). The record reads Lindqvist, H., Morales, J. (2020). Supervisor feedback and seasonal return. Nonprofit Management Review. Type journal-article.
- **Reason:** no reason recorded
- **Quote:** "The quality of supervisors' feedback predicted whether volunteers returned for a second season, net of program size and volunteer age." (located by recorded:recorded_judge.json, at p. 6)
- **Quote check:** found in source_lindqvist2020.txt, at p. 6, which holds the full text
- **Notes:** no reason is recorded for @lindqvist2020, since the record holds no AI words around its first AI appearance
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_lindqvist2020.txt sha256:15c8420dce9e... (record 07_pin_sources); passage located by recorded:recorded_judge.json (record 09_locate_passage); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r10: @haldane2017

- **Sentence:** Volunteers in smaller programs reported stronger attachment to staff [@haldane2017].
- **Origin:** First named by an AI at 2026-10-13T10:06:10Z in session S7be25f19c0a4, where the record reads "Haldane (2017) compared attachment to staff across program sizes."
- **Session:** S7be25f19c0a4
- **Reference:** Haldane, R. (2017). Program size and attachment to staff. Public Service Quarterly. doi:10.5555/psq.2017.0090
- **Found:** found in the metadata cache (DOI 10.5555/psq.2017.0090). The record reads Haldane, P. (2017). Program size and attachment to staff. Public Service Quarterly. Type journal-article.
- **Reason:** "Haldane (2017) compared attachment to staff across program sizes, so it fits the sentence on smaller programs." (said by the AI at 2026-10-13T10:06:10Z in session S7be25f19c0a4)
- **Quote:** none, since there is no source text
- **Notes:** there is no source text for @haldane2017, so no quote was located or checked
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); times are each record's started_at

### r12: @iversen2018

- **Sentence:** Peer mentoring was associated with higher retention in youth volunteer programs [@iversen2018].
- **Origin:** First named by an AI at 2026-10-13T10:08:00Z in session S7be25f19c0a4, where the record reads "Iversen (2018) studied peer mentoring in youth programs."
- **Session:** S7be25f19c0a4
- **Reference:** Iversen, T. (2018). Peer mentoring in youth volunteer programs. Youth and Civic Life. doi:10.5555/ycl.2018.0012
- **Found:** found in the metadata cache (DOI 10.5555/ycl.2018.0012). The record reads Iversen, T. (2018). Peer mentoring in youth volunteer programs. Youth and Civic Life. Type journal-article.
- **Reason:** "Iversen (2018) studied peer mentoring in youth programs. The abstract says "Youth volunteer programs that paired new volunteers with a peer mentor had higher retention at six months than programs without mentoring."" (said by the AI at 2026-10-13T10:08:00Z in session S7be25f19c0a4)
- **Quote:** "Youth volunteer programs that paired new volunteers with a peer mentor had higher retention at six months than programs without mentoring." (from the record, at 2026-10-13T10:08:00Z in session S7be25f19c0a4)
- **Quote check:** found in source_iversen2018.txt, which holds the abstract only
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); source text source_iversen2018.txt sha256:f0e7b5216a4b... (record 07_pin_sources); quote checked by a program (record 10_verify_quote); times are each record's started_at

### r13: @sorensen2022

- **Sentence:** Turnover among volunteer coordinators tends to precede spikes in volunteer exit [@sorensen2022].
- **Origin:** First named by an AI at 2026-10-13T10:11:00Z in session S7be25f19c0a4, where the record reads "Sorensen (2022) reports that coordinator turnover comes before spikes in exit."
- **Session:** S7be25f19c0a4
- **Reference:** Sorensen, M. (2022). Coordinator turnover and volunteer exit. Journal of Civic Administration. doi:10.5555/jca.2022.0301
- **Found:** not found, since DOI 10.5555/jca.2022.0301 is not in the metadata cache and live lookup was off
- **Notes:** @sorensen2022 was not found, since DOI 10.5555/jca.2022.0301 is not in the metadata cache and live lookup was off
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); lookup (records 05_fetch_metadata, 06_check_existence); times are each record's started_at

**Never named in the record (2)**

### r11: @pruitt2022

- **Sentence:** Exit interviews are rarely conducted in municipal programs [@pruitt2022].
- **Origin:** The provenance record has no entry for @pruitt2022.
- **Reference:** (no entry in the reference list)
- **Notes:** @pruitt2022 is cited in the final build and has no entry in the reference list; the provenance record has no entry for @pruitt2022, so its origin is unknown and it is not checked
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); times are each record's started_at

### r14: @dumont2014

- **Sentence:** Clear end dates for assignments made volunteers more willing to sign up again [@dumont2014].
- **Origin:** The record never names @dumont2014.
- **Reference:** Dumont, C. (2014). Fixed-term assignments and volunteer re-enlistment. Voluntary Sector Studies. doi:10.5555/vss.2014.0048
- **Notes:** the record never names @dumont2014, so its origin is unknown and it is not checked
- **Trail:** origin from citation_provenance.yaml (record 04_read_origin); times are each record's started_at

**The scholar's citations, not checked further (2)**

- r03, @castellanos2017. Castellanos and Ibe describe retention as a matter of fit between the volunteer's goals and the tasks offered [@castellanos2017]. First named by the scholar at 2026-10-12T08:58:00Z in session S3a41c0d2e9f7, where the record reads "Keep my sentence on Castellanos and Ibe (2017) about fit."
- r15, @tanaka2016. Training length alone did not predict retention [@tanaka2016]. First named by the scholar at 2026-10-12T08:55:00Z in session S3a41c0d2e9f7 in drafts/author_notes.md, where the record reads "Training length alone did not predict retention (Tanaka 2016)."

## Notes

- check_existence / ferrante2021: @ferrante2021 was not found, since DOI 10.5555/nmr.2021.0388 is not in the metadata cache and live lookup was off
- check_existence / sorensen2022: @sorensen2022 was not found, since DOI 10.5555/jca.2022.0301 is not in the metadata cache and live lookup was off
- gather_reason_and_quote / r06: no reason is recorded for @okafor2018, since the record holds no AI words around its first AI appearance
- gather_reason_and_quote / r09: no reason is recorded for @lindqvist2020, since the record holds no AI words around its first AI appearance
- gather_reason_and_quote / r10: there is no source text for @haldane2017, so no quote was located or checked
- match_references / osei2015: @osei2015 is in the reference list and not cited in the final build, so it is not checked
- match_references / pruitt2022: @pruitt2022 is cited in the final build and has no entry in the reference list
- match_references / quinlan2015: @quinlan2015 is in the reference list and not cited in the final build, so it is not checked
- match_references / whitlock2020: @whitlock2020 is in the reference list and not cited in the final build, so it is not checked
- read_origin / r03: @castellanos2017 was first named by the scholar in the record, so it is not checked further
- read_origin / r11: the provenance record has no entry for @pruitt2022, so its origin is unknown and it is not checked
- read_origin / r14: the record never names @dumont2014, so its origin is unknown and it is not checked
- read_origin / r15: @tanaka2016 was first named by the scholar in the record, so it is not checked further
- verify_quote / r04: the quote given for @brennan2016 is not in its source text source_brennan2016.txt
- verify_quote / r05: the quote given for @kessler2019 is not in its source text source_kessler2019.txt
- verify_quote / r07: no exact quote was given for @marchetti2012, since the passage step gave a section pointer, which is not checked word for word
