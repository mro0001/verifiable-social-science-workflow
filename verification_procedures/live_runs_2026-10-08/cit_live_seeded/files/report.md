# Citation verification report

Document: `draft.md` (sha256:397d3090b864c7dc860a68b869467947287bfdd4f8654494c5b76daa4c637ede). Only AI-contributed citations are checked; a citation the author introduced, in a sentence the author wrote, is listed as the author's warrant and not checked.

**17 citation rows: 4 verified, 11 problems, 0 couldn't check, 2 author's warrant (not checked).**

- Verified on the abstract only: 1. Verdicts carried over from an earlier check: 1.
- To confirm any verdict: open the retrieved copy named in its trail, search for the quoted passage, and read it beside the claim. Every ask and answer is saved under `prompts/` and `responses/` in the run folder.

## Summary

- Blocking: 11
- Warnings: 8
- Notes: 6

## Problems

| Severity | Check | Item | Problem | Evidence |
|---|---|---|---|---|
| blocking | check_existence | ferrante2021 | citation may not exist: no record for DOI 10.5555/nmr.2021.0388 (not in the metadata cache, and live lookup was off) | 10.5555/nmr.2021.0388 |
| blocking | check_existence | lindqvist2020 | author mismatch: reference lists Lindqvist H., Moreau J.; record lists Lindqvist H., Morales J. | 10.5555/nmr.2020.0157 |
| blocking | check_existence | okafor2018 | year mismatch: reference says 2018; record says 2019 | 10.5555/psq.2019.0044 |
| blocking | judge_support | r05 | source does not support the claim: The source states retention fell by 24%, whereas the claim incorrectly asserts a 42% decline. | Programs that reduced orientation to a single session saw twelve-month retention fall by 24% relative to programs that … |
| blocking | judge_support | r07 | source does not support the claim: The source describes the records as 'administrative traces' but does not use the specific term 'civic paradata' attributed t… | This article studies the administrative traces of volunteer activity: sign-in sheets, shift logs, and incident forms. T… |
| blocking | judge_support | r08 | source does not support the claim: The source explicitly states that recognition events had no measurable effect on exit and that exit actually rose slightly, … | Recognition events had no measurable effect on exit among long-serving volunteers. If anything, exit rose slightly in t… |
| blocking | judge_support | r13 | source does not support the claim: The source states the effect held in only two of the three cities with a non-significant difference in the third, directly c… | In two of the three cities, volunteers assigned a named staff contact stayed longer than those without one. In the thir… |
| blocking | match_references | pruitt2022 | cited key @pruitt2022 has no entry in the reference list | refs.yaml |
| blocking | verify_quote | r04 | quoted words are not in the source (a paraphrase presented as a direct quote): "volunteers leave when the work stops feeling like their own" | source_brennan2016.txt |
| blocking | verify_quote | r05 | number 42% in the claim does not appear in the source | source_kessler2019.txt |
| blocking | verify_quote | r07 | the source never uses the quoted term "civic paradata" | source_marchetti2012.txt |
| warning | attribute_origin | r15 | origin unknown (no citation-log entry for @dumont2014); checked as if AI-contributed | dumont2014 |
| warning | check_access | r02 | not checked: no usable retrieved copy of @ferrante2021 | no source_ferrante2021.txt |
| warning | check_access | r11 | not checked: no usable retrieved copy of @pruitt2022 | no source_pruitt2022.txt |
| warning | check_access | r12 | abstract only: the verdict covers the abstract, not the full text | source_iversen2018.txt |
| warning | check_existence | haldane2017 | author initials differ: Haldane (R. vs P.) | 10.5555/psq.2017.0090 |
| warning | check_existence | sorensen2022 | stage mismatch: reference describes a published article-journal; the DOI resolves to a posted-content | 10.5555/jca.2022.0301 |
| warning | check_existence | sorensen2022 | venue differs: reference says Journal of Civic Administration; record says CivicArXiv | 10.5555/jca.2022.0301 |
| warning | judge_support | r06 | source only partly supports the claim: The source specifies that the comparison was against volunteers receiving only a verbal briefing, whereas the claim broa… | Volunteers who received a written description of their role remained active longer than volunteers who received only a … |

## Rows

**Problems (11)**

### r02: not checked, @ferrante2021

- **Claim:** Exit is steepest among volunteers recruited through online portals [@ferrante2021].
- **Reference:** Ferrante, L. (2021). Digital recruitment and early exit among civic volunteers. Nonprofit Management Review. doi:10.5555/nmr.2021.0388 Check: citation may not exist: no record for DOI 10.5555/nmr.2021.0388 (not in the metadata cache, and live lookup was off).
- **Verdict:** not checked. No usable retrieved copy
- **Access:** no retrieved copy
- **Problems found:** citation may not exist: no record for DOI 10.5555/nmr.2021.0388 (not in the metadata cache, and live lookup was off); not checked: no usable retrieved copy of @ferrante2021
- **Proposed fix:** The citation to Ferrante (2021) must be removed because the reference appears to be fabricated (DOI 10.5555/nmr.2021.0388 does not exist) and no source was retrieved to verify the claim that exit is steepest among volunteers recruited through online portals.
- **Origin:** ai_added (AI introduced the source)
- **Trail:** reference checked (records 05_fetch_metadata, 06_check_existence); fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r04: supports, @brennan2016

- **Claim:** Brennan puts it plainly: "volunteers leave when the work stops feeling like their own" [@brennan2016, p. 12].
- **Reference:** Brennan, S. (2016). The work is theirs. Civic Press. doi:10.5555/cp.2016.0007 Check: exists; metadata matches.
- **Passage:** "Volunteers tend to exit once they no longer experience the work as theirs." (p. 12)
- **Verdict:** supports. The source passage explicitly states that volunteers exit when they no longer experience the work as theirs, which directly matches the claim's assertion that they leave when the work stops feeling like their own.
- **Access:** full text
- **Problems found:** quoted words are not in the source (a paraphrase presented as a direct quote): "volunteers leave when the work stops feeling like their own"
- **Proposed fix:** Brennan puts it plainly that volunteers tend to exit once they no longer experience the work as theirs [@brennan2016, p. 12].
- **Origin:** ai_reworded (author's source, AI rewrote the sentence)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_brennan2016.txt sha256:661edc2f7373...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r05: does not support; second checker agrees, @kessler2019

- **Claim:** Programs that cut orientation to a single session saw retention fall by 42% within a year [@kessler2019].
- **Reference:** Kessler, D. (2019). Orientation length and volunteer retention. Journal of Civic Administration. doi:10.5555/jca.2019.0215 Check: exists; metadata matches.
- **Passage:** "Programs that reduced orientation to a single session saw twelve-month retention fall by 24% relative to programs that kept a multi-session orientation." (p. 9)
- **Verdict:** does not support; second checker agrees. The source states retention fell by 24%, whereas the claim incorrectly asserts a 42% decline.
- **Access:** full text
- **Problems found:** number 42% in the claim does not appear in the source
- **Proposed fix:** Programs that cut orientation to a single session saw retention fall by 24% within a year [@kessler2019].
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); second check by live:openai/gpt-oss-120b (record 14_second_check); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_kessler2019.txt sha256:7d9630b8ffa5...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r06: partly supports; second checker agrees, @okafor2018

- **Claim:** Volunteers who received written role descriptions stayed longer than those who did not [@okafor2018, p. 4].
- **Reference:** Okafor, A. (2018). Written role descriptions and volunteer tenure. Public Service Quarterly. doi:10.5555/psq.2019.0044 Check: year mismatch: reference says 2018; record says 2019.
- **Passage:** "Volunteers who received a written description of their role remained active longer than volunteers who received only a verbal briefing." (p. 4)
- **Verdict:** partly supports; second checker agrees. The source specifies that the comparison was against volunteers receiving only a verbal briefing, whereas the claim broadly states 'those who did not' receive written descriptions, omitting this specific condition.
- **Access:** full text
- **Problems found:** year mismatch: reference says 2018; record says 2019
- **Proposed fix:** Volunteers who received written role descriptions stayed longer than those who received only a verbal briefing [@okafor2018, p. 4]. The reference year should be corrected to 2019 to match the publication record.
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); second check by live:openai/gpt-oss-120b (record 14_second_check); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_okafor2018.txt sha256:6a6b24c93e2b...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r07: does not support; second checker agrees, @marchetti2012

- **Claim:** Marchetti calls the records volunteers leave behind "civic paradata" [@marchetti2012].
- **Reference:** Marchetti, P. (2012). Administrative traces of volunteer work. Records and Society. doi:10.5555/rs.2012.0109 Check: exists; metadata matches.
- **Passage:** "This article studies the administrative traces of volunteer activity: sign-in sheets, shift logs, and incident forms. These records are kept for operational reasons and are rarely analyzed." (p. 3)
- **Verdict:** does not support; second checker agrees. The source describes the records as 'administrative traces' but does not use the specific term 'civic paradata' attributed to Marchetti in the claim.
- **Access:** full text
- **Problems found:** the source never uses the quoted term "civic paradata"
- **Proposed fix:** Marchetti describes the records volunteers leave behind as 'administrative traces' [@marchetti2012].
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); second check by live:openai/gpt-oss-120b (record 14_second_check); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_marchetti2012.txt sha256:bf71479d4325...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r08: does not support; second checker agrees, @nakamura2020

- **Claim:** Recognition events reduced exit among long-serving volunteers [@nakamura2020].
- **Reference:** Nakamura, E. (2020). Recognition events and the long-serving volunteer. Voluntary Sector Studies. doi:10.5555/vss.2020.0063 Check: exists; metadata matches.
- **Passage:** "Recognition events had no measurable effect on exit among long-serving volunteers. If anything, exit rose slightly in the quarter after an event, a pattern we attribute to volunteers treating the event as a natural point to step down." (p. 15)
- **Verdict:** does not support; second checker agrees. The source explicitly states that recognition events had no measurable effect on exit and that exit actually rose slightly, which directly contradicts the claim that they reduced exit.
- **Access:** full text
- **Proposed fix:** Recognition events did not reduce exit among long-serving volunteers; if anything, exit rose slightly in the quarter after an event [@nakamura2020].
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); second check by live:openai/gpt-oss-120b (record 14_second_check); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_nakamura2020.txt sha256:b76d203442be...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r09: supports, @lindqvist2020

- **Claim:** Supervisors' feedback quality predicted whether volunteers returned for a second season [@lindqvist2020].
- **Reference:** Lindqvist, H., Moreau, J. (2020). Supervisor feedback and seasonal return. Nonprofit Management Review. doi:10.5555/nmr.2020.0157 Check: author mismatch: reference lists Lindqvist H., Moreau J.; record lists Lindqvist H., Morales J.
- **Passage:** "The quality of supervisors' feedback predicted whether volunteers returned for a second season, net of program size and volunteer age." (p. 6)
- **Verdict:** supports. The located passage explicitly states that the quality of supervisors' feedback predicted whether volunteers returned for a second season, matching the claim's assertion exactly.
- **Access:** full text
- **Problems found:** author mismatch: reference lists Lindqvist H., Moreau J.; record lists Lindqvist H., Morales J.
- **Proposed fix:** Correct the reference metadata to list the second author as Morales J. instead of Moreau J. The sentence remains accurate as the source explicitly states that the quality of supervisors' feedback predicted whether volunteers returned for a second season.
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_lindqvist2020.txt sha256:15c8420dce9e...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r10: supports, @haldane2017

- **Claim:** Volunteers in smaller programs reported stronger attachment to staff [@haldane2017].
- **Reference:** Haldane, R. (2017). Program size and attachment to staff. Public Service Quarterly. doi:10.5555/psq.2017.0090 Check: author initials differ: Haldane (R. vs P.).
- **Passage:** "Volunteers in smaller programs reported stronger attachment to paid staff than volunteers in large programs." (p. 21)
- **Verdict:** supports. The located passage explicitly states that volunteers in smaller programs reported stronger attachment to paid staff than those in large programs, which directly confirms the claim.
- **Access:** full text
- **Problems found:** author initials differ: Haldane (R. vs P.)
- **Proposed fix:** Correct the reference metadata to list the author as Haldane, P. (2017) to match the source, as the located passage explicitly confirms that volunteers in smaller programs reported stronger attachment to paid staff than those in large programs.
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_haldane2017.txt sha256:82db46999166...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r11: not checked, @pruitt2022

- **Claim:** Exit interviews are rarely conducted in municipal programs [@pruitt2022].
- **Reference:** (no reference entry) Check: cited key has no entry in the reference list.
- **Verdict:** not checked. No usable retrieved copy
- **Access:** no retrieved copy
- **Problems found:** cited key @pruitt2022 has no entry in the reference list; not checked: no usable retrieved copy of @pruitt2022
- **Proposed fix:** Exit interviews are rarely conducted in municipal programs. [Citation needed: The reference @pruitt2022 is missing from the bibliography and could not be verified.]
- **Origin:** ai_added (AI introduced the source)
- **Trail:** reference checked (records 05_fetch_metadata, 06_check_existence); fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r13: does not support; second checker agrees, @whitlock2020

- **Claim:** Whitlock found that assigning a named staff contact kept volunteers longer in all three cities studied [@whitlock2020, p. 112].
- **Reference:** Whitlock, G. (2020). Named contacts and volunteer tenure in three cities. Urban Affairs Notes. doi:10.5555/uan.2020.0230 Check: exists; metadata matches.
- **Passage:** "In two of the three cities, volunteers assigned a named staff contact stayed longer than those without one. In the third city the difference was small and not statistically significant." (p. 112)
- **Verdict:** does not support; second checker agrees. The source states the effect held in only two of the three cities with a non-significant difference in the third, directly contradicting the claim that it occurred in all three cities.
- **Access:** full text
- **Proposed fix:** Whitlock found that assigning a named staff contact kept volunteers longer in two of the three cities studied, with a non-significant difference in the third [@whitlock2020, p. 112].
- **Origin:** ai_sourced_author_worded (AI suggested the source; author reworded or moved the sentence); sentence moved, text unchanged
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); second check by live:openai/gpt-oss-120b (record 14_second_check); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_whitlock2020.txt sha256:dfea1280766c...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

### r14: supports, @sorensen2022

- **Claim:** Turnover among volunteer coordinators tends to precede spikes in volunteer exit [@sorensen2022].
- **Reference:** Sorensen, M. (2022). Coordinator turnover and volunteer exit. Journal of Civic Administration. doi:10.5555/jca.2022.0301 Check: venue differs: reference says Journal of Civic Administration; record says CivicArXiv; stage mismatch: reference describes a published article-journal; the DOI resolves to a posted-content.
- **Passage:** "Turnover among volunteer coordinators tends to precede spikes in volunteer exit by one to two months." (p. 8)
- **Verdict:** supports. The located passage explicitly states that turnover among volunteer coordinators tends to precede spikes in volunteer exit, matching the claim's assertion of temporal precedence and direction.
- **Access:** full text
- **Problems found:** stage mismatch: reference describes a published article-journal; the DOI resolves to a posted-content; venue differs: reference says Journal of Civic Administration; record says CivicArXiv
- **Proposed fix:** Turnover among volunteer coordinators tends to precede spikes in volunteer exit by one to two months [@sorensen2022]. The reference metadata should be corrected to reflect that the work is a preprint on CivicArXiv rather than a published article in the Journal of Civic Administration.
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_sorensen2022.txt sha256:641e25777266...; fix proposed by live:qwen/qwen3.5-122b (record 16_draft_fix); times: each record's started_at

**Couldn't check (0)**

None.

**Verified (4)**

### r01: supports, @abara2019

- **Claim:** In a panel of 48 city programs, 31% of first-year volunteers left before completing six months of service [@abara2019, p. 7].
- **Reference:** Abara, N., Hollis, T. (2019). Ownership and exit in municipal volunteer programs. Journal of Civic Administration. doi:10.5555/jca.2019.0142 Check: exists; metadata matches.
- **Passage:** "Across the 48 programs in our panel, 31% of first-year volunteers exited before completing six months of service. Exit was concentrated in the first eight weeks." (p. 7)
- **Verdict:** supports. The located passage on page 7 explicitly states that across the 48 programs in the panel, 31% of first-year volunteers exited before completing six months of service, which matches the claim's numbers, scope, and direction exactly.
- **Access:** full text
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_abara2019.txt sha256:ad8f787f260f...; times: each record's started_at

### r12: supports (abstract only), @iversen2018

- **Claim:** Peer mentoring was associated with higher retention in youth volunteer programs [@iversen2018].
- **Reference:** Iversen, T. (2018). Peer mentoring in youth volunteer programs. Youth and Civic Life. doi:10.5555/ycl.2018.0012 Check: exists; metadata matches.
- **Passage:** "Youth volunteer programs that paired new volunteers with a peer mentor had higher retention at six months than programs without mentoring." (Abstract)
- **Verdict:** supports (abstract only). The abstract explicitly states that youth volunteer programs with peer mentoring had higher retention at six months than those without, which directly confirms the claim's assertion of an association between peer mentoring and higher retention.
- **Access:** abstract only
- **Flags:** abstract only: the verdict covers the abstract, not the full text
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_iversen2018.txt sha256:f0e7b5216a4b...; times: each record's started_at

### r15: supports, @dumont2014

- **Claim:** Clear end dates for assignments made volunteers more willing to sign up again [@dumont2014].
- **Reference:** Dumont, C. (2014). Fixed-term assignments and volunteer re-enlistment. Voluntary Sector Studies. doi:10.5555/vss.2014.0048 Check: exists; metadata matches.
- **Passage:** "Assignments with a clear end date made volunteers more willing to sign up again for a later assignment." (p. 11)
- **Verdict:** supports. The located passage explicitly states that assignments with a clear end date made volunteers more willing to sign up again, which directly matches the claim's assertion.
- **Access:** full text
- **Flags:** origin unknown (no citation-log entry for @dumont2014); checked as if AI-contributed
- **Origin:** unknown (no log entry; checked as if AI)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_dumont2014.txt sha256:b7f33c539a05...; times: each record's started_at

### r16: supports, @tanaka2016

- **Claim:** Training length alone did not predict retention [@tanaka2016].
- **Reference:** Tanaka, H. (2016). Training length and volunteer retention. Public Service Quarterly. doi:10.5555/psq.2016.0071 Check: exists; metadata matches.
- **Passage:** "Once role clarity was accounted for, the length of training alone did not predict retention." (p. 19)
- **Verdict:** supports. The source reports that training length alone did not predict retention once role clarity was accounted for.
- **Access:** full text
- **Origin:** ai_added (AI introduced the source)
- **Trail:** verdict carried over from the check by live:qwen/qwen3.5-122b on 2026-09-30 (record 08_reuse_prior); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_tanaka2016.txt sha256:233d015db381...; times: each record's started_at

**Author's warrant, not checked (2)**

- r03, @castellanos2017: Castellanos and Ibe describe retention as a matter of fit between the volunteer's goals and the tasks offered [@castellanos2017]. (moved, text unchanged)
- r17, @quinlan2015: Quinlan reports that 57% of volunteers named scheduling conflicts as their main reason for leaving [@quinlan2015]. (moved, text unchanged)

## Notes

- attribute_origin / r03: not checked, author's warrant (sentence moved, text unchanged)
- attribute_origin / r17: not checked, author's warrant (sentence moved, text unchanged)
- match_references / castellanos2017: cited only in the author's own sentences; reference not checked
- match_references / osei2015: in the reference list but not cited in the draft
- match_references / quinlan2015: cited only in the author's own sentences; reference not checked
- reuse_prior / r16: verdict carried over from the check of 2026-09-30 (sentence and retrieved copy unchanged)
