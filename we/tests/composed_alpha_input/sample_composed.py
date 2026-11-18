
from pathlib import Path
import json,time
from Xlib import X,display
from Xlib.ext import shape
from PIL import Image
D=display.Display();root=D.screen().root;deadline=time.monotonic()+20;w=None
while time.monotonic()<deadline:
 for candidate in root.query_tree().children:
  if candidate.get_wm_name()=='Felix composed input parent' and candidate.get_attributes().map_state==2:w=candidate;break
 if w:break
 time.sleep(.1)
assert w,'No owned parent window';time.sleep(3)
ready=json.loads(Path('/opt/felix-case/composed-ready.json').read_text());assert ready['hr']==0,ready
g=w.get_geometry();r=w.shape_get_rectangles(shape.SK.Input).rectangles
points=[(100,16),(100,80),(100,g.height-40),(300,250)]
raw=w.get_image(0,0,g.width,g.height,X.ZPixmap,0xffffffff).data
im=Image.frombytes('RGBA',(g.width,g.height),raw,'raw','BGRA');im.save('/opt/felix-case/screens/composed-parent.png')
rows=[{'point':[x,y],'inside':any(v.x<=x<v.x+v.width and v.y<=y<v.y+v.height for v in r),'rgba':im.getpixel((x,y))} for x,y in points]
result={'size':[g.width,g.height],'depth':g.depth,'input_rectangles':[[v.x,v.y,v.width,v.height] for v in r],'points':rows,'ready':ready}
Path('/opt/felix-case/composed-input.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));D.close()
