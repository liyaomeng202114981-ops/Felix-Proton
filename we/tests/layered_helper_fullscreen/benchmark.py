# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Observe only synthetic EWMH windows on a verified private GNOME bus."""
from pathlib import Path
import json,os,subprocess,sys,time
from gi.repository import Gio,GLib
from Xlib import X,display
case,backend,runner,runtime,rounds,fixture=sys.argv[1:];case=Path(case)
assert backend=='x11' and Path(os.environ['XDG_RUNTIME_DIR'])==case/'runtime'
assert Path(os.environ['HOME'])==case/'home' and os.environ['WAYLAND_DISPLAY']=='felix-ui-benchmark'
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
reply=bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID',GLib.Variant('(s)',('org.gnome.Mutter.DisplayConfig',)),None,Gio.DBusCallFlags.NONE,3000,None).unpack();pid=reply[0]
p=Path('/proc')/str(pid);cmd=(p/'cmdline').read_bytes().split(b'\0');env=dict(v.split(b'=',1) for v in (p/'environ').read_bytes().split(b'\0') if b'=' in v)
assert p.stat().st_uid==os.getuid() and b'--headless' in cmd and b'--wayland-display=felix-ui-benchmark' in cmd
assert env[b'XDG_RUNTIME_DIR'].decode()==str(case/'runtime')
def dos(p):return 'Z:'+str(p).replace('/','\\')
ready=case/'fixture-ready.json';quit=case/'fixture-quit';trigger=case/'provided-hint-ready';log=case/'fixture.log';D=display.Display()
with log.open('w') as stream:
 proc=subprocess.Popen([runtime,'--verb=run','--',runner,'run',fixture,dos(ready),dos(quit),dos(trigger)],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
 try:
  deadline=time.monotonic()+40
  while not ready.exists() and time.monotonic()<deadline:
   assert proc.poll() is None,proc.returncode;time.sleep(.05)
  source=json.loads(ready.read_text());time.sleep(1.2);records=[]
  for entry in source['windows']:
   result=dict(entry)
   for role in ['owner','helper']:
    w=D.create_resource_object('window',entry[role+'_xid']);prop=w.get_full_property(D.intern_atom('_NET_WM_STATE'),X.AnyPropertyType);g=w.get_geometry();pos=D.screen().root.translate_coords(w,0,0)
    result[role]={'states':sorted(D.get_atom_name(int(v)) for v in prop.value) if prop else [],'mapped':w.get_attributes().map_state,'geometry':[pos.x,pos.y,g.width,g.height]}
    gtk=w.get_full_property(D.intern_atom('_GTK_FRAME_EXTENTS'),X.AnyPropertyType);result[role]['gtk_frame_extents']=list(map(int,gtk.value)) if gtk else None
   records.append(result)
  candidate=D.create_resource_object('window',source['windows'][1]['helper_xid'])
  provided=[2,3,4,5];candidate.change_property(D.intern_atom('_GTK_FRAME_EXTENTS'),D.intern_atom('CARDINAL'),32,provided);D.sync();trigger.touch()
  deadline=time.monotonic()+5;done=Path(str(trigger)+'.done')
  while not done.exists() and time.monotonic()<deadline:time.sleep(.05)
  assert done.read_text().strip()=='ok';time.sleep(.7)
  gtk=candidate.get_full_property(D.intern_atom('_GTK_FRAME_EXTENTS'),X.AnyPropertyType);preserved=list(map(int,gtk.value)) if gtk else None
  assert preserved==provided,('Existing client frame hint overwritten',preserved)
  (case/'observed.json').write_text(json.dumps({'private_compositor_pid':pid,'verified_private':True,'no_input_sent':True,'cases':records,'existing_hint_preserved_after_role_and_geometry_change':preserved},indent=2)+'\n')
  print('RESULT_DIRECTORY='+str(case),flush=True)
 finally:
  quit.touch();proc.wait(timeout=12)
assert proc.returncode==0,proc.returncode
remaining=[]
for w in D.screen().root.query_tree().children:
 if w.get_wm_class() and 'SyntheticLayeredFullscreen' in w.get_wm_class() and w.get_attributes().map_state==2:remaining.append(w.id)
assert not remaining,remaining
(case/'fixture-cleanup.json').write_text(json.dumps({'fixture_exit':proc.returncode,'mapped_fixture_windows':remaining},indent=2)+'\n');D.close()
