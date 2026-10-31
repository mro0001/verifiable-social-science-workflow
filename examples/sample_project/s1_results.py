"""Compute the results the sample manuscript and slides cite.

Purpose:
    Turn the counts of a model's one-word answers into the results both research
    products cite: each condition's most common word and that word's share of the
    answers, the number of different words the data file records, and a table of
    the most common words in each condition.
Inputs:
    next_word_counts.json - counts of one-word answers in three conditions, as sampled.
Outputs:
    next_word_results.json - the run facts and each condition's results, the source the manuscript numbers name.
    top_words.md - the table the manuscript and the slides both include.
    params_record_results.csv - the parameters this run read, written by the run.
Parameters:
    top_words - how many of each condition's most common words the table lists.
    share_digits - decimals shown in every published share.
Assumptions:
    The data file lists each condition's most common words in descending order of
    count, so its first word is the most common. A share is a word's count over all
    of the condition's answers, n, not over the words listed. Conditions keep the
    order of the data file.
"""
import json

import params_io

# step: Parameters
P = params_io.Params(step="results", script="s1_results.py")
LABELS = {"none": "Question only", "context": "Plus the job posting", "definition": "Plus a definition"}


# step: Shares
def share(count, n):
    """Return count as a percent of n, rounded to share_digits decimals, as text."""
    return "%.*f" % (P["share_digits"], 100.0 * count / n)


# step: Summary
def summarize(data):
    """Gather each condition's results: its recorded count of different words, its most
    common word, and the shares of that word and of each listed word."""
    conditions = {}
    for cond in data["conditions"]:
        top, n = cond["top"], cond["n"]
        conditions[cond["key"]] = {
            "label": LABELS[cond["key"]],
            "n": n,
            "distinct": cond["distinct"],
            "top_word": top[0]["w"],
            "top_pct": share(top[0]["count"], n),
            # The table lists the first top_words words, which the data file orders by count.
            "listed": [{"word": t["w"], "pct": share(t["count"], n)} for t in top[:P["top_words"]]],
        }
    return {
        "model": data["model"],
        "question": data["question"],
        "n_per_condition": data["n_per_condition"],
        "temperature": data["temperature"],
        "conditions": conditions,
    }


# step: Table
def table(results):
    """Build the markdown table of each condition's most common words and return it as text."""
    lines = ["| Condition | Different words | Most common words (share of answers) |", "|---|---|---|"]
    for cond in results["conditions"].values():
        words = ", ".join("%s (%s%%)" % (w["word"], w["pct"]) for w in cond["listed"])
        lines.append("| %s | %d | %s |" % (cond["label"], cond["distinct"], words))
    lines += ["", "Table: The model's one-word answers, %d per condition." % results["n_per_condition"]]
    return "\n".join(lines) + "\n"


# step: Outputs
def main():
    """Read the counts, write the results and the table, then write the parameter record."""
    with open("next_word_counts.json", encoding="utf-8") as f:
        data = json.load(f)
    results = summarize(data)
    with open("next_word_results.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(results, indent=2) + "\n")  # not-a-param: JSON layout, not an analytic choice
    with open("top_words.md", "w", encoding="utf-8") as f:
        f.write(table(results))
    P.write_record()


if __name__ == "__main__":
    main()
