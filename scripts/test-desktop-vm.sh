#!/bin/sh
# Linux Mint 22.3 and LMDE 7 as their ISOs install them, in KVM VMs (docs/testing.md, tier 3): the
# distribution's own kernel, a real Cinnamon session on X11 with its display manager, D-Bus, portals,
# keyring, polkit agent and default apps -- what no container shows.
#
#   build NAME  once: the installed system from the ISO (the squashfs its installer
#               copies, the live-only packages removed as the installer removes them), a user
#               "kata" logged in automatically, GRUB, and an autostart entry that runs the test
#               script the host serves. The result is build/desktop-vm/NAME/base.qcow2 (~10 GB).
#   run NAME    a throwaway overlay of it: boots, logs in, and in the session reports the stock
#               system (what it carries of what AppKata needs), starts the AppImage as a user would,
#               runs the launcher tests as that user (the setup applied as AppKata's would), and the
#               field test (scripts/sandbox/field-test.sh --non-interactive). Results between
#               =====VMTEST markers; screenshots of the session into build/desktop-vm/NAME/shots/.
#   release NAME  AppKata no longer needs the ISO: removes its claim, and the ISO with its
#               checksum only where no other project's claim is left.
# NAME: mint22.3 or lmde7. Needs /dev/kvm, Docker, and --privileged (loop devices) for build.
#
# The ISOs are shared with the machine's other projects (coworker/iso): they live in $ISO_DIR
# (default ~/iso; local.env can set it) beside their SHA-256 (<iso>.sha256). Fetch one with
# coworker/iso/download.sh (it resumes, checks the SHA-256 and claims it); this script claims its
# ISO for "appkata" each time, and release gives it up, which removes the ISO only with the last
# claim (docs/testing.md, "Downloaded ISOs").
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
CMD=${1:?usage: scripts/test-desktop-vm.sh build|run|release mint22.3|lmde7}
NAME=${2:?usage: scripts/test-desktop-vm.sh build|run|release mint22.3|lmde7}
[ ! -f "$HERE/local.env" ] || . "$HERE/local.env"     # this machine's settings (coworker/README.md)
ISODIR=${ISO_DIR:-$HOME/iso}
export ISO_DIR="$ISODIR"
case $NAME in
    mint22.3) ISO=linuxmint-22.3-cinnamon-64bit.iso LIVE=casper ;;
    lmde7)    ISO=lmde-7-cinnamon-64bit.iso LIVE=live ;;
    *) echo "unknown: $NAME" >&2; exit 2 ;;
esac
VM=$HERE/build/desktop-vm/$NAME

if [ "$CMD" = release ]; then
    "$HERE/coworker/iso/release.sh" "$ISO" appkata
    exit 0
fi
mkdir -p "$VM"
"$HERE/coworker/iso/claim.sh" "$ISO" appkata >/dev/null       # AppKata needs this ISO
ISODIR=$(cd "$ISODIR" && pwd -P)                              # for docker's -v
[ -e /dev/kvm ] || { echo "no /dev/kvm" >&2; exit 1; }

if ! docker image inspect appkata-vmtools >/dev/null 2>&1; then
    printf 'FROM ubuntu:24.04\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq qemu-system-x86 qemu-utils squashfs-tools parted e2fsprogs grub-pc-bin grub2-common util-linux socat python3 curl >/dev/null\n' \
        | docker build -q -t appkata-vmtools - >/dev/null
fi

if [ "$CMD" = build ]; then
    [ -f "$ISODIR/$ISO" ] || { echo "no $ISODIR/$ISO: fetch it with coworker/iso/download.sh (docs/testing.md)" >&2; exit 1; }
    (cd "$ISODIR" && sha256sum -c --status "$ISO.sha256") || { echo "$ISO: SHA-256 doesn't match $ISO.sha256" >&2; exit 1; }
    # the guest's side: what the installer does after copying the files, run in a chroot
    cat > "$VM/configure.sh" <<'EOF'
set -eu
export DEBIAN_FRONTEND=noninteractive
echo "LABEL=root / ext4 errors=remount-ro 0 1" > /etc/fstab
echo appkata-vm > /etc/hostname
rm -f /etc/machine-id /var/lib/dbus/machine-id; systemd-machine-id-setup >/dev/null
# the live-only packages, as the installer removes them
if [ -s /tmp/remove.list ]; then
    dpkg-query -W -f '${Package}\n' $(cat /tmp/remove.list) 2>/dev/null | xargs -r apt-get purge -y -qq >/dev/null 2>&1 || true
fi
useradd -m -s /bin/bash -G sudo,dialout kata
echo kata:kata | chpasswd
echo "kata ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/kata && chmod 440 /etc/sudoers.d/kata
mkdir -p /etc/lightdm/lightdm.conf.d
printf '[Seat:*]\nautologin-user=kata\nautologin-session=cinnamon\n' > /etc/lightdm/lightdm.conf.d/70-appkata-test.conf
# no welcome window over the session's screenshots
mkdir -p /home/kata/.linuxmint/mintwelcome && touch /home/kata/.linuxmint/mintwelcome/norun.flag
mkdir -p /home/kata/.config/autostart
cat > /home/kata/.config/autostart/appkata-vmtest.desktop <<'DESK'
[Desktop Entry]
Type=Application
Name=AppKata VM test
Exec=sh -c 'sleep 15; curl -sSf http://10.0.2.2:8000/run.sh -o /tmp/run.sh && bash /tmp/run.sh'
X-GNOME-Autostart-enabled=true
DESK
chown -R kata:kata /home/kata
k=$(ls /lib/modules | sort -V | tail -1)
update-initramfs -c -k "$k" >/dev/null 2>&1 || update-initramfs -u -k "$k" >/dev/null 2>&1
EOF
    docker run --rm --privileged -v /dev:/dev -v "$ISODIR:/iso:ro" -v "$VM:/vm" -e ISO="$ISO" -e LIVE="$LIVE" appkata-vmtools bash -c '
        set -eu
        mkdir -p /mnt/iso /mnt/root
        mount -o loop,ro /iso/$ISO /mnt/iso
        rm -f /vm/disk.raw; truncate -s 30G /vm/disk.raw
        parted -s /vm/disk.raw mklabel msdos mkpart primary ext4 1MiB 100% set 1 boot on
        dev=$(losetup -fP --show /vm/disk.raw)
        trap "umount -R /mnt/root 2>/dev/null; losetup -d $dev; umount /mnt/iso" EXIT
        for i in $(seq 20); do [ -e ${dev}p1 ] && break; sleep 0.5; done
        mkfs.ext4 -q -L root ${dev}p1
        mount ${dev}p1 /mnt/root
        echo "== unpacking $(du -h /mnt/iso/$LIVE/filesystem.squashfs | cut -f1) of $ISO"
        unsquashfs -q -f -d /mnt/root /mnt/iso/$LIVE/filesystem.squashfs >/dev/null
        # the kernel the live system boots, where the squashfs has none of its own
        ls /mnt/root/boot/vmlinuz-* >/dev/null 2>&1 || cp /mnt/iso/$LIVE/vmlinuz /mnt/root/boot/vmlinuz-$(ls /mnt/root/lib/modules | head -1)
        for f in filesystem.manifest-remove filesystem.packages-remove; do [ -f /mnt/iso/$LIVE/$f ] && cut -d" " -f1 /mnt/iso/$LIVE/$f > /mnt/root/tmp/remove.list; done
        cp /vm/configure.sh /mnt/root/tmp/configure.sh
        for d in dev proc sys; do mount --bind /$d /mnt/root/$d; done
        cp /etc/resolv.conf /mnt/root/etc/resolv.conf 2>/dev/null || true
        chroot /mnt/root bash /tmp/configure.sh
        # GRUB from this container (the ISO keeps its BIOS GRUB in its package pool), with a menu of one
        grub-install --target=i386-pc --boot-directory=/mnt/root/boot $dev >/dev/null
        k=$(ls /mnt/root/lib/modules | sort -V | tail -1)
        printf "set timeout=1\ninsmod part_msdos\ninsmod ext2\nsearch --no-floppy --label --set=root root\nmenuentry \"%s\" {\n  linux /boot/vmlinuz-%s root=LABEL=root ro quiet console=tty0 console=ttyS0,115200\n  initrd /boot/initrd.img-%s\n}\n" "$ISO" "$k" "$k" > /mnt/root/boot/grub/grub.cfg
        ls -la /mnt/root/boot/vmlinuz-$k /mnt/root/boot/initrd.img-$k
        rm -f /mnt/root/tmp/configure.sh /mnt/root/tmp/remove.list
        umount -R /mnt/root; losetup -d $dev; umount /mnt/iso; trap - EXIT
        qemu-img convert -O qcow2 /vm/disk.raw /vm/base.qcow2 && rm -f /vm/disk.raw
        echo "== built $(du -h /vm/base.qcow2 | cut -f1)"'
    exit 0
fi

# run: what the VM fetches from 10.0.2.2:8000 (the host side, this container)
PYT=$(sh "$HERE/scripts/python-standalone.sh")
git -C "$HERE" ls-files -co --exclude-standard src tests docs scripts/sandbox | tar -C "$HERE" -czf "$VM/src.tgz" -T -
tar -C "$(dirname "$(dirname "$(dirname "$PYT")")")" -czf "$VM/py.tgz" python
# VMTEST_SCRIPT: another script, to probe; VM_NAME tells it which VM it runs in (its skip list's name)
sed "1a VM_NAME=$NAME" "${VMTEST_SCRIPT:-$HERE/scripts/sandbox/vm-desktop.sh}" > "$VM/run.sh"
cp "$HERE/releases/AppKata-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/appkata_core/__init__.py")-x86_64.AppImage" "$VM/AppKata.AppImage"
rm -rf "$VM/shots"; mkdir -p "$VM/shots"
docker run --rm --device /dev/kvm -v "$VM:/vm" appkata-vmtools bash -c '
    set -e; cd /vm
    rm -f run.qcow2 serial.log; qemu-img create -f qcow2 -b base.qcow2 -F qcow2 run.qcow2 >/dev/null
    (python3 -m http.server 8000 --bind 0.0.0.0 >/dev/null 2>&1 &)
    qemu-system-x86_64 -enable-kvm -cpu host -m 4096 -smp 4 -device virtio-vga -display none \
        -drive file=run.qcow2,if=virtio -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
        -serial file:serial.log -monitor unix:/vm/mon.sock,server,nowait &
    qpid=$!
    # the guest asks for a screenshot with a "VMSHOT name" line; QEMU takes it from the screen itself
    seen=""
    for i in $(seq 1 900); do
        kill -0 $qpid 2>/dev/null || break
        for s in $(tr -d "\r" < serial.log 2>/dev/null | sed -n "s/^VMSHOT \([A-Za-z0-9_-]*\).*/\1/p"); do
            case " $seen " in *" $s "*) ;; *) echo "screendump /vm/shots/$s.ppm" | socat - UNIX-CONNECT:/vm/mon.sock >/dev/null; seen="$seen $s" ;; esac
        done
        grep -q "=====VMTEST END" serial.log 2>/dev/null && { sleep 5; break; }
        sleep 2
    done
    echo quit | socat - UNIX-CONNECT:/vm/mon.sock >/dev/null 2>&1 || kill $qpid 2>/dev/null || true
    sed -n "/=====VMTEST BEGIN/,/=====VMTEST END/p" serial.log | tr -d "\r"
    rm -f run.qcow2'
