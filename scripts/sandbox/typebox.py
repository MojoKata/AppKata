# The user's other app: a text box that saves what's typed into it to /tmp/typed-<display>.txt
import os, sys, gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
out = f"/tmp/typed-{sys.argv[1]}.txt"
w = Gtk.Window(title="Password"); e = Gtk.Entry(); w.add(e)
e.connect("changed", lambda x: open(out, "w").write(x.get_text()))
w.connect("destroy", Gtk.main_quit); w.set_default_size(400, 60); w.show_all(); w.present(); Gtk.main()
