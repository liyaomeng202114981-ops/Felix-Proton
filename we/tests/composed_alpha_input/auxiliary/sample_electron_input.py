
import collections,json,time
from pathlib import Path
from Xlib import X,display
from Xlib.ext import shape
D=display.Display();root=D.screen().root;deadline=time.monotonic()+25
while True:
 ws=[]
 for w in root.query_tree().children:
  try:
   c=w.get_full_property(D.intern_atom('WM_CLASS'),X.AnyPropertyType)
   if c and b'electron.exe' in c.value.lower() and w.get_attributes().map_state==2:ws.append(w)
  except Exception:pass
 if len(ws)>=4 or time.monotonic()>deadline:break
 time.sleep(.1)
assert len(ws)==4,len(ws)
time.sleep(2)
rows=[]
for w in ws:
 g=w.get_geometry();raw=w.get_image(0,0,g.width,g.height,X.ZPixmap,0xffffffff).data;rects=w.shape_get_rectangles(shape.SK.Input).rectangles
 inside=lambda x,y:any(r.x<=x<r.x+r.width and r.y<=y<r.y+r.height for r in rects)
 pixel=lambda x,y:list(raw[(y*g.width+x)*4:(y*g.width+x)*4+4])
 rows.append({'title':w.get_wm_name(),'depth':g.depth,'size':[g.width,g.height],'input_rectangles':len(rects),'caption_input':inside(min(300,g.width-10),20),'tail_input':inside(g.width-10,g.height-10),'tail_bgra':pixel(g.width-10,g.height-10),'panel_bgra':pixel(30,30),'black_bgra':pixel(30,220)})
Path('/opt/felix-case/input-probe.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows));D.close()
