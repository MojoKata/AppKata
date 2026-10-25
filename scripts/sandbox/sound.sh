#!/bin/bash
# Part of scripts/test-sandbox.sh "session" (docs/app-sandboxing.md round 2). Runs inside the Mint 22.1 Wayland container.
# Sound: what the PipeWire and PulseAudio sockets give a sandboxed app, besides playing sound.
. /x/session.sh; . /x/lib.sh
H=$HOME/.local/share/appkata/sandboxes/snd
mkdir -p $H; sox -n $H/tone.wav synth 3 sine 440 2>/dev/null
streams() { pactl list short sink-inputs | wc -l; }
SBX_SOUND=1 sbx snd pw-play $HOME/tone.wav > /tmp/pwplay.log 2>&1 & sleep 1.2; n=$(streams); wait
[ "$n" -gt 0 ] && say WORKS "play sound through PipeWire (pw-play)" "$n stream seen by the server" || say FAILS "play sound through PipeWire" "$(head -1 /tmp/pwplay.log)"
SBX_SOUND=1 sbx snd paplay $HOME/tone.wav > /tmp/paplay.log 2>&1 & sleep 1.2; n=$(streams); wait
[ "$n" -gt 0 ] && say WORKS "play sound through PulseAudio (paplay)" "$n stream seen by the server" || say FAILS "play sound through PulseAudio" "$(head -1 /tmp/paplay.log)"
sbx snd paplay $HOME/tone.wav > /tmp/nosound.log 2>&1 && say LEAKED "play sound without the sound grant" || say BLOCKED "play sound without the sound grant" "$(head -1 /tmp/nosound.log)"
# another app plays; the sandboxed one records the default source and the output's monitor
src=$(pactl get-default-source)
( for i in 1 2 3; do paplay $H/tone.wav; done ) & PL=$!; sleep 0.5
SBX_SOUND=1 sbx snd timeout 2 parecord --file-format=wav $HOME/rec-default.wav 2>/dev/null
SBX_SOUND=1 sbx snd timeout 2 parecord -d auto_null.monitor --file-format=wav $HOME/rec-monitor.wav 2>/dev/null
SBX_SOUND=1 sbx snd timeout 2 pw-record $HOME/rec-pw.wav 2>/dev/null
kill $PL 2>/dev/null; wait 2>/dev/null
rms() { sox "$1" -n stat 2>&1 | awk '/RMS +amplitude/ {print $3}'; }
for f in rec-default:"record the default source ($src) (parecord)" rec-monitor:"record what other apps play (parecord, monitor)" rec-pw:"record the default source (pw-record)"; do
  file=$H/${f%%:*}.wav what=${f#*:} r=$(rms $H/${f%%:*}.wav 2>/dev/null)
  if [ -s $file ] && awk "BEGIN{exit !(${r:-0} > 0.01)}"; then say LEAKED "$what" "RMS $r: the other app's tone"
  elif [ -s $file ]; then say LEAKED "$what" "recorded (silence: nothing playing there)"
  else say BLOCKED "$what"; fi
done
# PulseAudio modules run inside the sound server, outside the sandbox
out=$(SBX_SOUND=1 sbx snd pactl load-module module-pipe-sink file=$HOME/../../../../../home/kata/pwned.fifo sink_name=evil 2>&1)
[ -e /home/kata/pwned.fifo ] && say LEAKED "load a module that writes a file outside (module-pipe-sink)" "created /home/kata/pwned.fifo ($out)" || say BLOCKED "load a module that writes a file outside (module-pipe-sink)" "$out"
out=$(SBX_SOUND=1 sbx snd pactl load-module module-native-protocol-tcp port=4713 auth-anonymous=1 2>&1)
[ -n "$out" ] && pactl list short modules | grep -q protocol-tcp && say LEAKED "load a module that opens a network port (native-protocol-tcp)" "module $out" || say BLOCKED "load a module that opens a network port" "$out"
pactl list short modules | grep -E "pipe-sink|protocol-tcp" | awk '{print $1}' | xargs -r -n1 pactl unload-module 2>/dev/null; rm -f /home/kata/pwned.fifo
