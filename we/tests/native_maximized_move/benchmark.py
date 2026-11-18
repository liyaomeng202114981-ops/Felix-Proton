# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Real pointer drags against owned fixtures on a verified private GNOME bus."""
from pathlib import Path
import json,os,subprocess,sys,time
from gi.repository import Gio,GLib
case,backend,runner,runtime,rounds,fixture=sys.argv[1:];case=Path(case)
assert backend=='x11' and Path(os.environ['XDG_RUNTIME_DIR'])==case/'runtime'
assert Path(os.environ['HOME'])==case/'home'
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None);remote='org.gnome.Mutter.RemoteDesktop';path='/org/gnome/Mutter/RemoteDesktop'
def dbus(obj,iface,method,sig='()',args=()):
 return bus.call_sync(remote,obj,iface,method,GLib.Variant(sig,args),None,Gio.DBusCallFlags.NONE,3500,None).unpack()
owner=bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner',GLib.Variant('(s)',(remote,)),None,Gio.DBusCallFlags.NONE,3000,None).unpack()[0]
pid=bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID',GLib.Variant('(s)',(owner,)),None,Gio.DBusCallFlags.NONE,3000,None).unpack()[0]
p=Path('/proc')/str(pid);cmd=(p/'cmdline').read_bytes().split(b'\0');env=dict(x.split(b'=',1) for x in (p/'environ').read_bytes().split(b'\0') if b'=' in x)
assert p.stat().st_uid==os.getuid() and b'--headless' in cmd and b'--wayland-display=felix-ui-benchmark' in cmd
assert env[b'HOME'].decode()==str(case/'home') and env[b'XDG_RUNTIME_DIR'].decode()==str(case/'runtime')
session,=dbus(path,remote,'CreateSession');iface=remote+'.Session';dbus(session,iface,'Start')
snapshot=Path(os.environ['FELIX_UI_BENCH_SNAPSHOT'])
def state():
 try:return json.loads(snapshot.read_text())
 except (OSError,ValueError):return {'windows':[],'pointer':[]}
def wait(pred,seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  s=state()
  if pred(s):return s
  time.sleep(.05)
 raise RuntimeError('Private compositor state timeout: '+json.dumps(state()))
def pointer(dx,dy):dbus(session,iface,'NotifyPointerMotionRelative','(dd)',(float(dx),float(dy)))
def button(down):dbus(session,iface,'NotifyPointerButton','(ib)',(272,down))
def control(p,cmd):p.write_text(cmd+'\n')
def dos(p):return 'Z:'+str(p).replace('/','\\')
def drag(win,kind='caption'):
 x,y,w,h=win['frame'];target=[x+w-4,y+h-4] if kind=='edge' else [x+w//2,y+22]
 assert 0<=target[0]<1280 and 0<=target[1]<800
 pointer(-3000,-3000);time.sleep(.1);entry=[target[0]-20,target[1]+2];pointer(*entry);wait(lambda s:s['pointer']==entry,2);pointer(20,-2);wait(lambda s:s['pointer']==target,2);time.sleep(.12)
 button(True)
 try:
  time.sleep(.12)
  for i in range(12):
   if kind=='edge':pointer(-3,-12)
   elif kind=='tile':pointer((1-target[0])/12,(400-target[1])/12)
   else:pointer(3,12)
   time.sleep(.06)
 finally:button(False)
 time.sleep(.45);after=state();return {'before':win,'after':after['windows'][0],'pointer_after':after['pointer']}
results=[]
try:
 for mode in ['plain','corrected']:
  trace=case/(mode+'.tsv');ready=case/(mode+'.ready');trigger=case/(mode+'.control');log=case/(mode+'.log')
  with log.open('w') as stream:
   process=subprocess.Popen([runtime,'--verb=run','--',runner,'run',fixture,'--mode',mode,'--output',dos(trace),'--ready',dos(ready),'--trigger',dos(trigger),'--duration-ms','60000'],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
   try:
    s=wait(lambda s:ready.exists() and len(s['windows'])==1 and s['windows'][0]['name']=='FelixEdgeFixture-'+mode,35)
    assert s['windows'][0]['client']==1;time.sleep(1.2);s=state();normal=drag(s['windows'][0]);control(trigger,'maximize');s=wait(lambda s:len(s['windows'])==1 and s['windows'][0]['maximized'],4);time.sleep(.3);maximized=drag(s['windows'][0]);row={'mode':mode,'normal_drag':normal,'maximized_drag':maximized,'restored':not maximized['after']['maximized']}
    if mode=='corrected':
     control(trigger,'maximize');s=wait(lambda s:len(s['windows'])==1 and s['windows'][0]['maximized'],4);time.sleep(.35);row['maximized_edge_drag']=drag(s['windows'][0],'edge')
     control(trigger,'restore');wait(lambda s:len(s['windows'])==1 and not s['windows'][0]['maximized'],4);time.sleep(.65);row['tile_to_edge']=drag(state()['windows'][0],'tile');time.sleep(.45);row['tile_drag_out']=drag(state()['windows'][0]);row['tile_restored_size']=row['tile_drag_out']['after']['frame'][2:]==[640,420]
    results.append(row);print(json.dumps(row),flush=True)
   finally:
    control(trigger,'quit')
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=4)
   wait(lambda s:not s['windows'],4)
finally:
 dbus(session,iface,'Stop')
(case/'restore-results.json').write_text(json.dumps({'private_bus_owner_pid':pid,'verified_private_compositor':True,'host_pointer_not_used':True,'results':results},indent=2)+'\n')
print('RESULT_DIRECTORY='+str(case),flush=True)
