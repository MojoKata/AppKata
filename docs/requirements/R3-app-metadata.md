# R3. App metadata

R3.1. For each app, AppKata reads the following from the project and caches it (R1.8):

- An icon (small, 32–128 px).
- A high-resolution hero image (about 1280 × 640).
- The README.
- The latest release's notes.

R3.1.1. **Where an image is fetched from.** The icon and the hero image come from addresses the
project or its forge names: its metainfo's icon and screenshot, its README's images, the owner's
avatar. Only http and https addresses are asked for, and only those whose host part, all that
comes between the `//` and the first `/` after it, is a host and its port and nothing else, the
Source's own host's too: a name, with its escapes decoded, whose IDNA form, the one its lookup and a
proxy are sent, is ASCII letters, digits, `-`, `_` and dots, and doesn't change when the name is
written in lower case, so a name in any script is asked for, and one with no IDNA form (an empty
part, as in `a..b`, or a part of more than 63 characters), or whose IDNA form has an empty part
(`a‥b`'s is `a..b`), isn't, though a name's one final dot is its own; or an IPv6 address in brackets, as
they are written and not escaped; then a `:` and the port where it names one; all of it at most 300
characters, its escapes decoded, which no host and its port is more than. So none with a user part
before its host (`user@` or `10.0.0.5%2f@`), a `\` in its host, escaped brackets
(`%5b127.0.0.1%5d`), or a `?` or `#` right after its host with no path
(`images.example.com?@10.0.0.5`) is asked for: a proxy is sent all of a host part, and may read
another host out of it. Nor is one with a tab or a line break in its `//` or its host part, which one
reading of an address drops and another keeps. Nor is a name that holds, in lower case, `ß`, `ς`, a
zero-width non-joiner (U+200C) or a zero-width joiner (U+200D), the four characters that IDNA 2003,
by which AppKata writes a name in its IDNA form, and IDNA 2008, by which registries and browsers
write it, read apart: such a name is two hosts, and `straße.example` is `strasse.example` by IDNA
2003 and `xn--strae-oqa.example` by IDNA 2008. It is refused, with a message that says so, wherever
a host is judged: an address, a redirect, the Source's own host, and the host a token is typed for (R11.1.6).
Written in its IDNA 2008 form, which is ASCII, it is asked for. None is asked for whose host stands for a
loopback, private or link-local address, or another address that isn't public, unless it is the
Source's own host (a forge on the user's own network), on the Source's own port. The Source's own
port is the one its host names, or https's 443 where it names none; an address is on the port it is
asked on, whatever its scheme, so one in plain `http://` with the Source's name and no port is on
port 80, and isn't the Source's. A redirect is held to the same rule. A host is read as it is sent,
and sent as it is read, wherever it is sent (its lookup, the Host header, a proxy's CONNECT and the
address a proxy is sent over http): with its escapes decoded, in lower case, and a name in its IDNA
form. So `%31%30.0.0.5` is `10.0.0.5`, and `गिट.example` is sent in its IDNA form,
`xn--31bq9g.example`. The Source's own host is read so too: an address, or a redirect, is the
Source's own host in whichever form it is written, in its IDNA form or its script, escaped, or in
either case, so `xn--bung-zra.lan` and `übung.lan` are one host, and so are `git.example` and
`%67it.example`. Behind a proxy, the proxy looks a host's
name up: a name this computer can't look up is asked for through the proxy, and one this computer
finds to be such an address, or `localhost`, is still refused. Of the hosts this computer can't look
up, only a plain name is left to the proxy: ASCII letters, digits, `-`, `_` and dots, whose last
part isn't a number, in the form it is sent, so a name in any script is one (`übung.example.org`,
sent as `xn--bung-zra.example.org`). Any other is refused, such as an address with a trailing dot,
an IPv6 zone or a port inside the host. An image that is refused is passed over for the next one in
R3.2's or R3.3's list.

R3.2. **Icon.** AppKata uses the first one it finds:

1. The manifest (R2.7).
2. AppStream `*.metainfo.xml` (`<icon>`).
3. Fastlane metadata (`fastlane/metadata/**/images/icon.png`).
4. An icon file at the repo root or in `assets/`, `icons/`, `data/` (`icon.svg`, `icon.png`,
   `logo.*`).
5. The owner's avatar.
6. A generated tile: the app's initial on a gradient chosen from a hash of its Source URL.

R3.3. **Hero image.** AppKata uses the first one it finds:

1. The manifest.
2. The first AppStream screenshot.
3. Fastlane `featureGraphic.png`.
4. The forge's social-preview image.
5. The first non-badge image in the README.
6. A generated banner from the icon's colours.

R3.4. **README.**

- The README is rendered as Markdown.
- Relative links and images are resolved against the repository's raw-file URL at the default
  branch.
- Raw HTML is reduced to a safe subset; scripts, iframes and forms are removed.

R3.4.1. The **summary** is the README's first prose paragraph. Headings, badge-only lines,
images and HTML-only blocks are skipped. If there isn't one, the summary is the forge's
project description.
