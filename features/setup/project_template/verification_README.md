# Verification results

Each verification stream's results file goes in this folder as `<stream>.json`. The verification procedures write these files, and the scholar approves or holds each result.

The build reads this folder. A product with no current approved results for a stream is marked unverified for that stream, and the build still goes on.
