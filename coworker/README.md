# Coworker protocols

How projects that share one machine share its big, slow-to-make things without stepping on each
other. Each project's repository carries the same copy of this folder; the shared thing itself (a
folder of ISOs, a VM) records who uses it, so no project's documents need to name another.

| Protocol | What's shared | Where (default) |
|---|---|---|
| [`iso/`](iso/README.md) | installer ISOs: downloaded once, checked once, kept while any project needs them | `$ISO_DIR` (`~/iso`) |
| [`vm/`](vm/README.md) | virtual machines: kept while any project needs them, used by one project at a time | `$VM_DIR` (`~/vm`) |

**Version 1, 2026-10-25.** A change to a protocol changes every copy: bump the version here and
copy the folder into each project that carries it, unchanged.

## In a project

- **Its name.** A project claims things under one name: letters, digits, `-` and `_`. This project's
  is `appkata`.
- **This machine's settings.** A project's scripts read `local.env` at the top of its repository
  when there is one (git ignores it), so a machine can put the shared folders elsewhere:

      ISO_DIR=/srv/iso
      VM_DIR=/srv/vm

  How to reach a VM (its container, SSH port, account and key) isn't here: it's the VM's own
  `vm.env`, in its folder, the same for every project ([`vm/`](vm/README.md)).
- **Where it's written down.** The project's own documents say which ISOs and VMs it claims and
  why (here: [`docs/testing.md`](../docs/testing.md), "Downloaded ISOs", and
  [`docs/build.md`](../docs/build.md), "Shared Windows test VM").
