# Citation verification report

Document: `draft.md` (sha256:ff7b50f02cfb3322979fc44dd2cdd26895c05699906b14005162534e89254373). Only AI-contributed citations are checked; a citation the author introduced, in a sentence the author wrote, is listed as the author's warrant and not checked.

**6 citation rows: 5 verified, 0 problems, 0 couldn't check, 1 author's warrant (not checked).**

- Verified on the abstract only: 0. Verdicts carried over from an earlier check: 1.
- To confirm any verdict: open the retrieved copy named in its trail, search for the quoted passage, and read it beside the claim. Every ask and answer is saved under `prompts/` and `responses/` in the run folder.

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 4

## Problems

None.

## Rows

**Problems (0)**

None.

**Couldn't check (0)**

None.

**Verified (5)**

### r01: supports, @abara2019

- **Claim:** In a panel of 48 city programs, 31% of first-year volunteers left before completing six months of service [@abara2019, p. 7].
- **Reference:** Abara, N., Hollis, T. (2019). Ownership and exit in municipal volunteer programs. Journal of Civic Administration. doi:10.5555/jca.2019.0142 Check: exists; metadata matches.
- **Passage:** "Across the 48 programs in our panel, 31% of first-year volunteers exited before completing six months of service. Exit was concentrated in the first eight weeks." (p. 7)
- **Verdict:** supports. The located passage on page 7 explicitly states that across the 48 programs in the panel, 31% of first-year volunteers exited before completing six months of service, which matches the claim's numbers, scope, and direction exactly.
- **Access:** full text
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_abara2019.txt sha256:ad8f787f260f...; times: each record's started_at

### r03: supports, @moreno2018

- **Claim:** Moreno calls this the "role-match problem" and argues that it is invisible in sign-up data [@moreno2018, p. 33].
- **Reference:** Moreno, L. (2018). Matching volunteers to roles. Civic Press. doi:10.5555/cp.2018.0011 Check: exists; metadata matches.
- **Passage:** "I call this the role-match problem: the tasks a program needs done and the tasks volunteers came to do drift apart. Because sign-up forms record availability rather than purpose, the role-match problem is invisible in sign-up data." (p. 33)
- **Verdict:** supports. The located passage on page 33 explicitly states that Moreno calls the issue the 'role-match problem' and argues it is invisible in sign-up data because such forms record availability rather than purpose, matching the claim exactly.
- **Access:** full text
- **Origin:** ai_reworded (author's source, AI rewrote the sentence)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_moreno2018.txt sha256:77ce51d061bf...; times: each record's started_at

### r04: supports, @devries2021

- **Claim:** Flexible scheduling was associated with more hours per volunteer but not with longer tenure [@devries2021].
- **Reference:** de Vries, M. (2021). Scheduling flexibility and volunteer hours. Nonprofit Management Review. doi:10.5555/nmr.2021.0120 Check: exists; metadata matches.
- **Passage:** "Volunteers offered flexible schedules contributed more hours per month, but their tenure did not differ from that of volunteers on fixed schedules." (p. 14)
- **Verdict:** supports. The located passage explicitly states that volunteers with flexible schedules contributed more hours but had no difference in tenure, which directly matches the claim's assertion of an association with more hours but not longer tenure.
- **Access:** full text
- **Origin:** ai_added (AI introduced the source)
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_devries2021.txt sha256:c0368a8d7e00...; times: each record's started_at

### r05: supports, @whitlock2020

- **Claim:** Whitlock found that assigning a named staff contact kept volunteers longer in two of the three cities studied [@whitlock2020, p. 112].
- **Reference:** Whitlock, G. (2020). Named contacts and volunteer tenure in three cities. Urban Affairs Notes. doi:10.5555/uan.2020.0230 Check: exists; metadata matches.
- **Passage:** "In two of the three cities, volunteers assigned a named staff contact stayed longer than those without one. In the third city the difference was small and not statistically significant." (p. 112)
- **Verdict:** supports. The located passage explicitly states that in two of the three cities, volunteers with a named staff contact stayed longer, which directly matches the claim's assertion regarding the number of cities and the outcome.
- **Access:** full text
- **Origin:** ai_sourced_author_worded (AI suggested the source; author reworded or moved the sentence); sentence moved, text unchanged
- **Trail:** passage located by live:qwen/qwen3.5-122b (record 10_locate_passage), checked mechanically (record 11_verify_quote), verdict by live:qwen/qwen3.5-122b (record 12_judge_support); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_whitlock2020.txt sha256:dfea1280766c...; times: each record's started_at

### r06: supports, @tanaka2016

- **Claim:** Training length alone did not predict retention [@tanaka2016].
- **Reference:** Tanaka, H. (2016). Training length and volunteer retention. Public Service Quarterly. doi:10.5555/psq.2016.0071 Check: exists; metadata matches.
- **Passage:** "Once role clarity was accounted for, the length of training alone did not predict retention." (p. 19)
- **Verdict:** supports. The source reports that training length alone did not predict retention once role clarity was accounted for.
- **Access:** full text
- **Origin:** ai_added (AI introduced the source)
- **Trail:** verdict carried over from the check by live:qwen/qwen3.5-122b on 2026-09-30 (record 08_reuse_prior); reference checked (records 05_fetch_metadata, 06_check_existence); retrieved copy source_tanaka2016.txt sha256:233d015db381...; times: each record's started_at

**Author's warrant, not checked (1)**

- r02, @castellanos2017: Castellanos and Ibe describe retention as a matter of fit between the volunteer's goals and the tasks offered [@castellanos2017]. (moved, text unchanged)

## Notes

- attribute_origin / r02: not checked, author's warrant (sentence moved, text unchanged)
- match_references / castellanos2017: cited only in the author's own sentences; reference not checked
- match_references / osei2015: in the reference list but not cited in the draft
- reuse_prior / r06: verdict carried over from the check of 2026-09-30 (sentence and retrieved copy unchanged)
