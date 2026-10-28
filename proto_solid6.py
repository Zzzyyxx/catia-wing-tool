import math, pycatia
from pycatia.scripts.vba import vba_nothing
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object
print("main_body:", part.main_body.name)

def loop(y, chord, thick, n=16):
    return [[chord*(0.5-0.5*math.cos(2*math.pi*i/n)), y, thick*0.5*math.sin(2*math.pi*i/n)]
            for i in range(n)]
body = part.hybrid_bodies.add(); body.name = "T"
secs = []
for y, c in ((0.0, 100.0), (250.0, 45.0)):
    sp = hsf.add_new_spline()
    for p in hsf.add_new_point_coords(loop(y, c, 0.18*c)): sp.add_point(p)
    sp.set_closing(1); body.append_hybrid_shape(sp); secs.append(sp)
loft = hsf.add_new_loft()
for s in secs: loft.add_section_to_loft(pr(s), 1, vba_nothing)
body.append_hybrid_shape(loft); part.update()

caps = []
for s in secs:
    f = hsf.add_new_fill(); f.add_bound(pr(s)); body.append_hybrid_shape(f); caps.append(f)
part.update()
j1 = hsf.add_new_join(pr(loft), pr(caps[0])); body.append_hybrid_shape(j1); part.update()
j2 = hsf.add_new_join(pr(j1), pr(caps[1])); body.append_hybrid_shape(j2); part.update()
shell = j2
print("壳体面积:", round(spa.get_measurable(pr(shell)).area, 6))

raw = part.shape_factory.com_object
print("\n--- 尝试 1: 直接封闭曲面 ---")
try:
    s = raw.AddNewCloseSurface(pr(shell).com_object); s.Name = "实体_1"; part.update()
    print("  ✓ volume =", spa.get_measurable(part.create_reference_from_object(s)).volume)
except Exception as exc:
    print("  ✗", str(exc)[:90])
    try: part.update()
    except Exception: pass

print("\n--- 尝试 2: 先设 in_work_object = 零件几何体 ---")
try:
    part.in_work_object = part.main_body
    s = raw.AddNewCloseSurface(pr(shell).com_object); s.Name = "实体_2"; part.update()
    print("  ✓ volume =", spa.get_measurable(part.create_reference_from_object(s)).volume)
except Exception as exc:
    print("  ✗", str(exc)[:90])
    try: part.update()
    except Exception: pass
doc.close()
