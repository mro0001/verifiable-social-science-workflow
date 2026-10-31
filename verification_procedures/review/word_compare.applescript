-- word_compare.applescript ORIGINAL REVISED OUTPUT LABEL
-- Runs Word's native Compare and saves the tracked-changes result.
-- The result document is left open for review.
on run argv
    set origPath to item 1 of argv
    set revPath to item 2 of argv
    set outPath to item 3 of argv
    set authorLabel to item 4 of argv
    tell application "Microsoft Word"
        activate
        open (POSIX file origPath)
        set orig to active document
        compare orig path revPath author name authorLabel ¬
            detect format changes false ¬
            ignore all comparison warnings true
        set cmpDoc to active document
        save as cmpDoc file name outPath file format format document
        close orig saving no
    end tell
end run
