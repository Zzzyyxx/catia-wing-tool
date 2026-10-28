import pycatia, time
from pycatia import CatCaptureFormat
catia = pycatia.catia(); catia.display_file_alerts = False
w = None
for win in catia.windows:
    if "example_solid" in str(win.caption): w = win; break
if w: w.activate(); time.sleep(0.6)
doc = catia.active_document; part = doc.part; spa = doc.spa_workbench()
print("文档:", doc.name)

def find(name_prefix):
    for b in part.hybrid_bodies:
        for sh in b.hybrid_shapes:
            if sh.name.startswith(name_prefix):
                return b.name, sh
    return None, None

for nm in ("多截面曲面", "水密壳体", "端封_根", "端封_梢"):
    b, sh = find(nm)
    if sh is None:
        print(f"  {nm}: 未找到"); continue
    m = spa.get_measurable(part.create_reference_from_object(sh))
    extra = ""
    try:
        if m.volume: extra = f" volume={m.volume:.6f} m³"
    except Exception: pass
    print(f"  [{b}] {sh.name}: area={m.area:.6f} m²{extra}")

if w:
    v = w.active_viewer; v.reframe(); time.sleep(1.2)
    out = r"C:\Users\lenovo\Desktop\dsh\work\c_stimulating flying\CATIA_Wing_Tool\output\solid_tree.jpg"
    v.capture_to_file(int(CatCaptureFormat.catCaptureFormatJPEG), out)
    print("截图:", out)
