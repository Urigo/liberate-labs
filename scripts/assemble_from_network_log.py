#!/usr/bin/env python3
"""
Reassemble data that was smuggled out of a browser tab via URL-encoded fetch
requests (the "network-log channel" in maccabi_extract.js, STEP 3 option B).

Input: a text/JSON dump of the tab's network requests (whatever your agent's
network-log tool produced). Any line containing
    .../__E__/<idx>-<total>?d=<urlencoded chunk>
is picked up; chunks are ordered by <idx> and concatenated.

Usage:
    python assemble_from_network_log.py network_dump.txt > maccabi_all.tsv
"""
import re
import sys
import urllib.parse

PATTERN = re.compile(r"/__E__/(\d+)-(\d+)\?d=([^\s\"'\\]+)")


def main(path: str) -> None:
    text = open(path, encoding="utf-8", errors="replace").read()
    chunks: dict[int, str] = {}
    total = None
    for idx, tot, enc in PATTERN.findall(text):
        chunks[int(idx)] = urllib.parse.unquote(enc)
        total = int(tot)
    if not chunks:
        sys.exit("no __E__ chunks found")
    missing = [i for i in range(total or 0) if i not in chunks]
    if missing:
        sys.exit(f"missing chunks: {missing} — re-fire those indices")
    sys.stdout.write("".join(chunks[i] for i in range(len(chunks))))


if __name__ == "__main__":
    main(sys.argv[1])
