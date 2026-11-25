# R3. App metadata

R3.1. For each app, AppKata reads the following from the project and caches it (R1.8):

- An icon (small, 32–128 px).
- A high-resolution hero image (about 1280 × 640).
- The README.
- The latest release's notes.

R3.1.1. **Where an image is fetched from.** The icon and the hero image come from addresses the
project or its forge names: its metainfo's icon and screenshot, its README's images, the owner's
avatar. Only http and https addresses are asked for, and none with a user part before its host
(`user@` or `10.0.0.5%2f@`, the Source's own host's too), which is sent along with the host, and
which a proxy may read as the host. None is asked for whose host stands for a
loopback, private or link-local address, or another address that isn't public, unless it is the
Source's own host (a forge on the user's own network), on the Source's own port. The Source's own
port is the one its host names, or https's 443 where it names none; an address is on the port it is
asked on, whatever its scheme, so one in plain `http://` with the Source's name and no port is on
port 80, and isn't the Source's. A redirect is held to the same rule. A host is read as it is sent,
with its escapes decoded: `%31%30.0.0.5` is `10.0.0.5`. Behind a proxy, the proxy looks a host's
name up: a name this computer can't look up is asked for through the proxy, and one this computer
finds to be such an address, or `localhost`, is still refused. Of the hosts this computer can't look
up, only a plain name is left to the proxy: ASCII letters, digits, `-`, `_` and dots, whose last
part isn't a number. Any other is refused, such as an address with a trailing dot, an IPv6 zone or a
port inside the host. An image that is refused is passed over for the next one in R3.2's or R3.3's
list.

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
