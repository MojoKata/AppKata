#!/bin/bash
# Part of scripts/test-sandbox.sh "launcher-vm" and "launcher-vm26". Runs inside a real Ubuntu 24.04 or 26.04 KVM VM (its own kernel,
# AppArmor userns restriction, systemd-resolved with /etc/resolv.conf a symlink into /run): applies
# AppKata's AppArmor profile as the one-time setup would, then runs tests/test_sandbox_run.py,
# test_sandbox_exposure.py, test_sandbox_one_fact.py and test_sandbox_user_shaped.py as the
# unprivileged 'ubuntu' user against the launchers AppKata generates. Source arrives over HTTP from the host side (10.0.2.2:8000/src.tgz).
exec > /dev/ttyS0 2>&1
echo "=====VMTEST BEGIN====="
echo "Ubuntu $(. /etc/os-release; echo $VERSION_ID), kernel $(uname -r), bwrap $(bwrap --version 2>&1)"
echo "resolv.conf -> $(readlink -f /etc/resolv.conf)"
mkdir -p /opt/src && curl -sSf http://10.0.2.2:8000/src.tgz | tar -xz -C /opt/src
# AppKata's code and the tests run on the Python the release carries (requirement 1.2); what the
# launchers run on the host stays on the system's python3
mkdir -p /opt/py && curl -sSf http://10.0.2.2:8000/py.tgz | tar -xz -C /opt/py && chmod -R a+rX /opt/py
PY=/opt/py/python/bin/python3
# As the one-time setup would: AppKata's profile only where the system has none of its own for bwrap
# (Ubuntu 25.04+ ship bwrap-userns-restrict, and AppKata's beside it breaks bwrap, 17.10.2).
others=$(PYTHONPATH=/opt/src/src $PY -c 'from appkata_core import sandbox; print(" ".join(sandbox.other_bwrap_profiles()))')
if [ -z "$others" ]; then
  PYTHONPATH=/opt/src/src $PY -c 'from appkata_core import sandbox; print(sandbox.profile_text(), end="")' \
    > /etc/apparmor.d/appkata-sandbox && apparmor_parser -r /etc/apparmor.d/appkata-sandbox && echo "AppArmor profile loaded"
else
  echo "the system's own bwrap profile is present ($others): AppKata's is not loaded"
fi
sudo -u ubuntu -H bash -lc "PYTHONPATH=/opt/src/src $PY -c 'from appkata_core import sandbox as s; print(\"support:\", s.support_status()[\"status\"], \"inner sandbox:\", s.nested_userns_works())'"
sh /opt/src/scripts/sandbox/register-test-handler.sh && echo "test handler registered"
cp -r /opt/src /home/ubuntu/src && chown -R ubuntu: /home/ubuntu/src
sudo -u ubuntu -H bash -lc "cd /home/ubuntu && XDG_RUNTIME_DIR=/run/user/\$(id -u) PYTHONPATH=src/src APPKATA_PYTHON=$PY APPKATA_BOOTED=1 \
  $PY -m pytest -q -rfEs -p no:cacheprovider src/tests/test_sandbox_run.py src/tests/test_sandbox_exposure.py src/tests/test_sandbox_one_fact.py src/tests/test_sandbox_user_shaped.py src/tests/test_booted.py ${PYTEST_ARGS:-} 2>&1 | tail -40"
echo "=====VMTEST END====="
poweroff
