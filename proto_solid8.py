import math, pycatia
from pycatia.scripts.vba import vba_nothing
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object

def circle_pts(z, r, n=24, cx=0, cy=0):
    return [[cx + r*math.cos(2*math.pi*i/n), cy + r*math.sin(2*math.pi*i/n), z] for i in range(n)]

body = part.hybrid_bodies.add(); body.name = "T"
secs = []
for z in (0.0, 100.0):
    sp = hsf.add_new_spline()
    for p in hsf.add_new_point_coords(circle_pts(z, 30.0)): sp.add_point(p)
    sp.set_closing(1); body.append_hybrid_shape(sp); secs.append(sp)
loft = hsf.add_new_loft()
for s in secs: loft.add_section_to_loft(pr(s), 1, vba_nothing)
body.append_hybrid_shape(loft); part.update()
caps = []
for s in secs:
    f = hsf.add_new_fill(); f.add_bound(pr(s)); body.append_hybrid_shape(f); caps.append(f)
part.update()
j = hsf.add_new_join(pr(loft), pr(caps[0])); body.append_hybrid_shape(j); part.update()
j2 = hsf.add_new_join(pr(j), pr(caps[1])); body.append_hybrid_shape(j2); part.update()
print("圆柱壳体面积:", round(spa.get_measurable(pr(j2)).area, 6),
      " 理论:", round(2*math.pi*30*100/1e6 + 2*math.pi*900/1e6, 6), "m²")

raw = part.shape_factory.com_object
print("--- CloseSurface ---")
try:
    s = raw.AddNewCloseSurface(pr(j2).com_object); s.Name="圆柱实体"; part.update()
    print("✓ volume =", spa.get_measurable(part.create_reference_from_object(s)).volume,
          " 理论 =", round(math.pi*30*30*100/1e9, 8))
except Exception as exc:
    print("✗", str(exc)[:130])
    try: part.update()
    except Exception: pass
print("--- ThickSurface on 圆柱侧面 ---")
try:
    t = raw.AddNewThickSurface(pr(loft).com_object, 2.0, 0.0, 1); t.Name="厚曲面"; part.update()
    print("✓ volume =", spa.get_measurable(part.create_reference_from_object(t)).volume)
except Exception as exc:
    print("✗", str(exc)[:110])
doc.close()
