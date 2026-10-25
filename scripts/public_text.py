"""Names that must not appear in the public repository: the other projects that share the machine it
is developed on, their folders and accounts, and private accounts and domains (coworker/README.md).
They are kept as SHA-256 hashes, so this file names none of them itself.

    python3 scripts/public_text.py hash NAME...      the hash to add for a new name
    python3 scripts/public_text.py check FILE...     report any of FILE's words that are listed

A word is a run of letters and digits, alone or joined to the next by -, _ or . ("lab-vm2" is
checked whole and as "lab" and "vm2"); case doesn't matter. tests/test_public_text.py checks every
file git tracks or would add, and scripts/test-screenshot-text.sh the text read from every
screenshot. PLACEHOLDER is the address AppKata's repository had before it was published, which both
also look for.
"""

import hashlib
import re
import sys

PRIVATE = {
    "026d537ae25d53cf76ef4b027702c86f1529ea4111711639d4a844635ea01b59",
    "040929ae5406e450553877bd2c0b0758ce81df05a47c8677ff19ccdb3fa53591",
    "4727d31a3aa6b3a3f0dc2666cd6db98dd7f0af874296e9beee1cb66aaab564ed",
    "6448f7770a1e1793b8a3a6907ae5cec898173b95e90df4f043f92825fba07ae4",
    "89e38c119257ffd6d880ec4a32e2be8d6db5eb81e45ad57d67e28bfbb6d1d276",
    "8abd711040801c4597ad1fdc5cbc9d24c4ab5c62000d98288949e158311fa308",
    "8b8880db4d0d200a0923443bafde427ed0a4b28b52ff7f1460821bdda1f46603",
    "8e6cb6189e3a025fe581b5a25f540d796632e6a14c3319fd29e21fcc27aa1581",
    "a5f175a5977de6ab167b6f4137837d322638113937d24a41dd3a64720ac0871c",
    "abe8766197acd523426a9eaa2171f1845e4709e6a21788647d2313065ebcd324",
    "ba6acaca32fb4af7294a8c86ab85e175a06d3a4a881fabf805fe58a9fc991f9c",
    "c00ea19495a928bc669da0869cffa8359e4348e16bb153870f8b5b72b757b459",
    "d23a977543b02dd726f755c85461def74fe34b31aba4d0a2ea7a39a529d0448c",
    "d3e985437e10fd2fca2dc78b287c3820a9f768dd67fcc48550d00b46e5ceec34",
    "f2961e4e9a9829f8b9999136db7158e946160f737075f3a2a1e2cdf7500b7bce",
    "fe1517b74a3952aa6df0494ec75d2bf8fae306ed993658d8385ba8378cbc5567",
}

# written in two parts, so that this file doesn't name it
PLACEHOLDER = re.compile(r"(?<![\w/])appkata/" r"appkata(?![\w.])")

PART = re.compile(r"[a-z0-9]+")
WORD = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")


def digest(word):
    return hashlib.sha256(word.lower().encode()).hexdigest()


def words(text):
    """Every word of text, and every run of the parts each joined word is made of."""
    seen = set()
    for m in WORD.finditer(text.lower()):
        w = m.group()
        parts = PART.findall(w)
        seps = re.findall(r"[-_.]", w)
        for i in range(len(parts)):
            run = parts[i]
            seen.add(run)
            for j in range(i + 1, len(parts)):
                run += seps[j - 1] + parts[j]
                seen.add(run)
    return seen


def found(text):
    """The words of text that are listed, as they appear."""
    return sorted(w for w in words(text) if digest(w) in PRIVATE)


def main(argv):
    if len(argv) >= 2 and argv[0] == "hash":
        for name in argv[1:]:
            print(digest(name), name)
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        bad = 0
        for path in argv[1:]:
            with open(path, encoding="utf-8", errors="replace") as f:
                hits = found(f.read())
            if hits:
                bad = 1
                print(f"{path}: {', '.join(hits)}")
        return bad
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
