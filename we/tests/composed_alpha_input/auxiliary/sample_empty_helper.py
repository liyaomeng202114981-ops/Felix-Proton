
from pathlib import Path
import json,time,collections
from Xlib import display,X
from Xlib.ext import shape
D=display.Display();deadline=time.monotonic()+25;w=None
while time.monotonic()<deadline:
 for c in D.screen().root.query_tree().children:
  if c.get_wm_class() and 'electron.exe' in c.get_wm_class() and [c.get_geometry().width,c.get_geometry().height]==[300,240] and c.get_attributes().map_state==2:w=c;break
 if w:break
 time.sleep(.1)
inventory=[{'xid':hex(c.id),'class':c.get_wm_class(),'title':c.get_wm_name(),'size':[c.get_geometry().width,c.get_geometry().height],'mapped':c.get_attributes().map_state} for c in D.screen().root.query_tree().children];Path('/opt/felix-case/window-inventory.json').write_text(json.dumps(inventory,indent=2)+'\n');assert w,inventory;time.sleep(6);g=w.get_geometry();raw=w.get_image(0,0,g.width,g.height,X.ZPixmap,0xffffffff).data
r=w.shape_get_rectangles(shape.SK.Input).rectangles
result={'size':[g.width,g.height],'alpha_histogram':dict(collections.Counter(raw[3::4])),'input_rectangles':[[v.x,v.y,v.width,v.height] for v in r]}
Path('/opt/felix-case/empty-helper.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));D.close()
