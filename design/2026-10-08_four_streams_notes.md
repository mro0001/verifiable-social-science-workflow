These are the authors' design notes of October 8, 2026, kept verbatim, which the graphs cite by date.

## The authors' design notes (2026-10-08, verbatim)

Four streams
- Prose: text editor
  - verification: versioned drafts with rationalized comments from AI changes.
- Citations: Citation manager
  - Verification: 1) is the citation real, 2) is it being used correctly.
- Data: python, R, quarto
  - Verification: reproducible data scripts data collection to data tables/graphs for manuscript. Method steps need their own documentation (literature programming?) and parameter settings need to be something that gets set and then simultaneous populates a table that is a record of the parameters and the models themselves. Make sense?
- Build structure: pandoc, makefiles, etc.,
  - Note the build structure is the automated script that build the component parts into the final deliverable. The final deliverable can be a manuscript, draft, research compendium, html presentation, etc., The primary point is that the final deliverable is derived using the build structure and should not be directly touched by AI. The build structure needs to automatically build from the various streams.
  - Verification: Not sure. People need to know that their build preferences are integrated into the build files and that AI is not directly touching the final deliverable. This is the equivalent of ensure that results are not being hard coded in coded, but are the result of a process.
