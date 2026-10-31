"""The one list of setup's decisions (step S1).

Every decision a scholar meets during setup, once per scholar and once per
project, in the order setup meets them. The terminal questions, the AI
session's guide, and the portal page all read this list, so they cannot
drift apart (scope report section 3).

Each entry holds these.

  id        a name unique across the list
  scope     system (once per scholar) or project (once per project)
  question  the exact words setup asks, or None when nothing is asked
  explain   one or two plain sentences on what the decision is
  how       ask, detect, default, or yes (covered by the one yes on the
            review screen)
  when      for a question asked only in some cases, the case, else None
  default   the value taken when the scholar gives none, or None
  changes   what the answer changes once setup acts on it

The wording comes from the scope report
(handoff/clean_build_2026-10-28/submission/30_setup_walkthrough_scope.md),
its section 3 for the questions and its section 2 tables for the rest.
"""
import collections

Decision = collections.namedtuple(
    "Decision", "id scope question explain how when default changes")

SCOPES = ("system", "project")
HOWS = ("ask", "detect", "default", "yes")

YES_QUESTION = "Make these changes? Each one is listed above. [yes]"


def _system(id, how, explain, changes, question=None, when=None, default=None):
    return Decision(id, "system", question, explain, how, when, default, changes)


def _project(id, how, explain, changes, question=None, when=None, default=None):
    return Decision(id, "project", question, explain, how, when, default, changes)


DECISIONS = [
    # Once per scholar. The questions come first, in the order of section 3.
    _system(
        "excluded_folders", "ask",
        "Folders whose AI sessions must never be recorded, such as folders holding student"
        " records. A path must start with / or ~, and the word none means there are none.",
        "The list capture, the wrappers, the events tool, and the triggers read. Nothing is"
        " recorded or started for work run there.",
        question="Which folders hold work whose AI sessions must never be recorded, such as"
                 " student records or advising notes? Give one full path a line. Type none if"
                 " there are none."),
    _system(
        "scholar_name", "detect",
        "Your name as approvals and organizer changes record it. It is taken from git's"
        " settings when git has one.",
        "The default name for organize apply and organize undo.",
        question="Your name, as your approvals will record it.",
        when="only when git's settings hold no user.name"),
    _system(
        "model_service", "ask",
        "The service that answers the checks' fixed questions, such as whether a source supports"
        " a sentence. Your assistant's own model is chosen in the assistant and does not change.",
        "provider.yaml, read by the judgment steps of the prose, references, and data checks and"
        " by session tagging. Skipped, full checks run without a judge and each judged item reads"
        " not judged.",
        question="Which model service should answer the checks' questions? Give its web address,"
                 " or press Enter to skip for now. Your assistant's own model does not change."),
    _system(
        "model", "ask",
        "The model on that service that answers the checks' questions.",
        "The model named in provider.yaml.",
        question="Which model on that service?",
        when="only when a model service is given"),
    _system(
        "second_model", "ask",
        "A second model that rechecks any verdict that a source does not fully support its"
        " sentence. Setup proposes one from the service's own list of models.",
        "The references check's recheck. Skipped, those items read not judged.",
        question="Which second model, different from the first, should recheck doubtful source"
                 " verdicts? Press Enter to skip.",
        when="only when a model service is given"),
    _system(
        "model_key", "detect",
        "The key the model service gives you. It stays in your shell and never enters the"
        " workflow's files or an AI conversation, and setup only says whether it is set.",
        "Sent with each live call. When it is not set, setup prints the one line to add to the"
        " shell profile."),
    _system(
        "token_limit", "default",
        "How long each model answer may be.",
        "token_limit and token_limit_field in provider.yaml.",
        default="4,000 tokens under max_tokens"),
    _system(
        "citation_export", "ask",
        "The BibTeX file your reference manager keeps up to date. Setup names Zotero when it"
        " finds it.",
        "refs.bib is copied from it before each build, and the references check gets its list"
        " from it.",
        question="Which file does your reference manager export, such as a BibTeX file Zotero"
                 " keeps up to date? Press Enter for none."),
    _system(
        "harness", "detect",
        "The AI assistant program you work in, such as Claude Code or ForgeCode, which runs the"
        " model and lets it read and edit your files. Each one found is connected.",
        "How sessions are captured (Claude Code at each turn's end and every 30 minutes,"
        " ForgeCode every 30 minutes, another program not at all), whether the light check can"
        " run (Claude Code only), and how the servers are registered.",
        question="No AI assistant program was found. Which do you use, Claude Code, ForgeCode, or"
                 " another? You can also install one first.",
        when="only when no harness is found"),
    # Found by detection and shown on the review screen.
    _system(
        "statistical_software", "detect",
        "The programs that run your analysis, such as R, Python, Stata, or Quarto.",
        "Which runs are logged (R, Rscript, quarto), which adapter feeds the data check, and"
        " whether the data check can rerun the analysis, which today it can only for Python."
        " Stata has no wrapper or adapter."),
    _system(
        "word", "detect",
        "Whether you review AI edits as tracked changes in Word or in the plain-text file.",
        "What the prose check reads, the Word adapter's output or the earlier draft and its"
        " versions file."),
    _system(
        "version_control", "detect",
        "Whether projects are kept in git and on GitHub. Nothing is put on GitHub unless you ask.",
        "A .gitignore for the organizer's folder, and the GitHub procedure's command."),
    _system(
        "pandoc_make", "detect",
        "The programs that turn the plain text into Word files and slides. Both are required.",
        "Whether make PRODUCT runs."),
    # Defaults, stated once on the review screen.
    _system(
        "light_check", "default",
        "A quick check at the end of each AI turn, with no model, that notes which AI"
        " contributions need a look. It is set one project at a time, with a switch.",
        "The trigger hooks in each project and the start commands.",
        default="on in each project setup lays out"),
    _system(
        "full_reports", "default",
        "The full check that writes a report for you to approve or hold. It runs only when you"
        " ask.",
        "The make verify line in each Makefile setup writes.",
        default="on request"),
    _system(
        "live_view", "default",
        "A page showing your AI sessions, tool calls, and file reads, updated after each turn.",
        "One view folder per project.",
        default="on request"),
    _system(
        "session_titles", "default",
        "Whether a model writes a title and summary for each recorded session, which sends the"
        " session's text to the model service.",
        "Table A4's model fields, and what leaves the machine.",
        default="on request"),
    _system(
        "online_lookup", "default",
        "Whether the references check looks up each DOI online to confirm the work exists.",
        "DOIs sent to Crossref.",
        default="on"),
    _system(
        "past_sessions", "default",
        "Whether sessions from before setup are recorded too. Capture starts from the day of"
        " setup, and earlier sessions are brought in only when you ask.",
        "What the audit record and the organizer's past sessions hold.",
        default="from the day of setup on"),
    _system(
        "homes", "default",
        "The folders in your home folder that hold the workflow's records and settings.",
        "Each layer's home.",
        default="~/.workflow_features, ~/.audit_layer, and ~/.workflow_connections"),
    _system(
        "hook_python", "default",
        "Which Python the hooks and the schedule start, an engineering detail with no question.",
        "Whether capture runs in the harness's environment.",
        default="the full path of the Python that ran setup"),
    # The changes outside the workflow's own folders, covered by the one yes.
    _system(
        "servers", "yes",
        "The knowledge base server and the two other servers let your assistant search the"
        " workflow's standards and procedures, and read the audit record, while it works.",
        "Three server registrations and the knowledge base index.",
        question=YES_QUESTION, default="yes"),
    _system(
        "capture_schedule", "yes",
        "A sweep every 30 minutes that records any session the end of a turn missed.",
        "One launchd agent on a Mac, one crontab line elsewhere.",
        question=YES_QUESTION, default="yes"),
    _system(
        "wrapper_functions", "yes",
        "Small shell functions so that runs of R, Quarto, Pandoc, Make, and git are logged.",
        "Six lines in the shell profile.",
        question=YES_QUESTION, default="yes"),
    _system(
        "connect", "yes",
        "Whether setup may add the workflow's hooks and servers to your assistant's settings."
        " Each change is named first.",
        "The capture and trigger hooks, the three server registrations, the knowledge base"
        " index, and the start commands.",
        question=YES_QUESTION, default="yes"),
    # Once per project.
    _project(
        "products", "ask",
        "What the project produces, such as a manuscript as a Word document or slides. A source"
        " the folder already holds is offered, and no second one is written.",
        "The source files, the Makefile's rules, and the project guide.",
        question="This project will produce manuscript.md as a Word document. Press Enter to"
                 " accept, or give each product on its own line as NAME:SOURCE:FORMAT.",
        default="manuscript.md as a Word document"),
    _project(
        "title", "default",
        "The project's name at the top of the manuscript.",
        "The source's front matter and the project guide.",
        default="the folder's name, or the title of the source the folder holds"),
    _project(
        "project_citation_export", "default",
        "The BibTeX file copied before each build.",
        "refs.bib and its copy rule.",
        default="the one system setup recorded"),
    _project(
        "word_review", "detect",
        "Whether you review AI edits as tracked changes in Word or in the plain-text file.",
        "The prose check's start command."),
    _project(
        "project_light_check", "default",
        "A quick check at the end of each AI turn, with no model, that notes which AI"
        " contributions need a look.",
        "The project's own harness settings.",
        default="on, with a switch"),
    _project(
        "github", "default",
        "Whether the project is put on GitHub.",
        "Nothing unless you ask.",
        default="on request"),
]


def system_decisions():
    """The decisions made once per scholar, in order."""
    return [item for item in DECISIONS if item.scope == "system"]


def project_decisions():
    """The decisions made once per project, in order."""
    return [item for item in DECISIONS if item.scope == "project"]


def by_id(decision_id):
    """The decision with this id, or KeyError naming it."""
    for item in DECISIONS:
        if item.id == decision_id:
            return item
    raise KeyError("there is no decision %r" % decision_id)
