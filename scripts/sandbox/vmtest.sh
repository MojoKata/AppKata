#!/bin/bash
# Part of scripts/test-sandbox.sh "apparmor" (docs/app-sandboxing.md). Runs inside the Ubuntu 24.04 KVM VM.
# Question: can AppKata (a plain-user AppImage, no root) satisfy the userns requirement on first need,
# and what needs privilege? Runs each check as the unprivileged 'ubuntu' user unless noted.
exec > /dev/ttyS0 2>&1
echo "=====VMTEST BEGIN====="
echo "Ubuntu $(. /etc/os-release; echo $VERSION_ID), kernel $(uname -r), restrict=$(sysctl -n kernel.apparmor_restrict_unprivileged_userns)"
U(){ sudo -u ubuntu bash -lc "$1"; }
echo "pkexec present: $(command -v pkexec || echo NO)   polkit: $(systemctl is-active polkit 2>/dev/null || echo n/a)"
echo
echo "-- Can an UNPRIVILEGED user apply the fixes themselves? (all should fail)"
U 'echo "profile appkata /usr/bin/bwrap flags=(unconfined){userns,}" > /etc/apparmor.d/zz-appkata 2>&1' | sed 's#^#   write apparmor.d: #'
U 'apparmor_parser -r /etc/apparmor.d/*bwrap* 2>&1 | head -1' | sed 's/^/   apparmor_parser -r: /'
U 'sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 2>&1 | head -1' | sed 's/^/   sysctl -w: /'
U 'command -v aa-exec >/dev/null && echo yes || echo no' | sed 's/^/   (aa-exec available): /'
echo
echo "-- A ONE-TIME privileged step (what AppKata would run behind a single pkexec prompt):"
cat > /etc/apparmor.d/appkata-sandbox <<'AA'
abi <abi/4.0>,
include <tunables/global>
profile appkata-sandbox /usr/bin/bwrap flags=(unconfined) { userns, include if exists <local/appkata-sandbox> }
AA
apparmor_parser -r /etc/apparmor.d/appkata-sandbox && echo "   root: profile written + loaded"
echo "-- Does it then work for the unprivileged user, no further prompt?"
U 'bwrap --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin --proc /proc --dev /dev --unshare-user --share-net -- /bin/echo "   sandbox: WORKS (no root)"'; echo "   rc=$?"
echo "-- Does the profile persist across a reboot? (apparmor.service auto-loads /etc/apparmor.d/ at boot)"
systemctl is-enabled apparmor 2>/dev/null | sed 's/^/   apparmor.service enabled: /'
aa-status 2>/dev/null | grep -q appkata-sandbox && echo "   loaded now: yes (and will reload at boot from the file)"
echo
echo "-- No-root fallback: is Landlock available? (restricts files without userns or root)"
grep -o 'landlock' /sys/kernel/security/lsm 2>/dev/null | head -1 | sed 's/^/   LSM lists: /'
U 'python3 - <<PY 2>&1 | sed "s/^/   /"
import ctypes,struct
LANDLOCK_CREATE_RULESET_VERSION=1<<0
libc=ctypes.CDLL("libc.so.6",use_errno=True)
# landlock_create_ruleset(NULL,0,LANDLOCK_CREATE_RULESET_VERSION) -> ABI version, no privilege needed
abi=libc.syscall(444,0,0,LANDLOCK_CREATE_RULESET_VERSION)
print("Landlock ABI:",abi,"(>=1 means usable unprivileged)" if abi>0 else "(unavailable)")
PY'
echo "=====VMTEST END====="
poweroff
