# SPDX-License-Identifier: BSD-3-Clause; Copyright 2026 Felix Li
import json,time,pathlib,collections
from Xlib import display,X
from PIL import Image
D=display.Display();root=D.screen().root;deadline=time.monotonic()+30
while True:
 windows=[]
 for w in root.query_tree().children:
  try:
   cl=w.get_full_property(D.intern_atom('WM_CLASS'),X.AnyPropertyType)
   if cl and b'electron.exe' in cl.value.lower() and w.get_attributes().map_state==2:windows.append(w)
  except Exception:pass
 if len(windows)>=3 or time.monotonic()>deadline:break
 time.sleep(.1)
records=[]
for w in windows:
 g=w.get_geometry();raw=w.get_image(0,0,g.width,g.height,X.ZPixmap,0xffffffff).data;name=w.get_wm_name();pixels=Image.frombytes('RGBA',(g.width,g.height),raw,'raw','BGRA')
 records.append({'xid':hex(w.id),'title':name,'size':[g.width,g.height],'depth':g.depth,'alpha_histogram':dict(collections.Counter(raw[3::4])),'tail_rgba':pixels.getpixel((g.width-10,g.height-10)),'panel_rgba':pixels.getpixel((30,30)),'black_rgba':pixels.getpixel((30,220))});pixels.save('/opt/felix-case/screens/electron-'+hex(w.id)+'.png')
pathlib.Path('/opt/felix-case/electron-window-samples.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n');print(json.dumps(records));D.close()
