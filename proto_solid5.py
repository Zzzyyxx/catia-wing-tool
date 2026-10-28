import math, pycatia
from pycatia.scripts.vba import vba_nothing
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object

def loop(y, chord, thick, n=16):
    return [[chord*(0.5-0.5*math.cos(2*math.pi*i/n)), y, thick*0.5*math.sin(2*math.pi*i/n)]
            for i in range(n)]

body = part.hybrid_bodies.add(); body.name = "T"
secs = []
for y, c in ((0.0, 100.0), (250.0, 45.0)):
    sp = hsf.add_new_spline()
    for p in hsf.add_new_point_coords(loop(y, c, 0.18*c)): sp.add_point(p)
    sp.set_closing(1)
    body.append_hybrid_shape(sp); secs.append(sp)
loft = hsf.add_new_loft()
for s in secs: loft.add_section_to_loft(pr(s), 1, vba_nothing)
body.append_hybrid_shape(loft); part.update()
print("翼面面积:", round(spa.get_measurable(pr(loft)).area, 6), "m²")

# 两个端面封口
caps = []
for i, s in enumerate(secs):
    f = hsf.add_new_fill()
    f.name = f"端封_{i}"
    try:
        f.add_bound(pr(s))
    except Exception as exc:
        print("  add_bound 失败:", str(exc)[:80])
    body.append_hybrid_shape(f)
    caps.append(f)
try:
    part.update()
    for i, f in enumerate(caps):
        print(f"  端封_{i} 面积:", round(spa.get_measurable(pr(f)).area, 6), "m²")
except Exception as exc:
    print("封口 update 失败:", str(exc)[:110])

# Join 成闭合外壳
try:
    j1 = hsf.add_new_join(pr(loft), pr(caps[0])); j1.name = "接合_1"; body.append_hybrid_shape(j1)
    part.update()
    j2 = hsf.add_new_join(pr(j1), pr(caps[1])); j2.name = "接合_2"; body.append_hybrid_shape(j2)
    part.update()
    print("Join 成壳体 OK，面积:", round(spa.get_measurable(pr(j2)).area, 6), "m²")
    raw = part.shape_factory.com_object
    solid = raw.AddNewCloseSurface(pr(j2).com_object)
    solid.Name = "封闭实体"
    part.update()
    m = spa.get_measurable(part.create_reference_from_object(solid))
    print(f"✓ 封闭曲面成实体: volume={m.volume:.8f} m³  area={m.area:.6f} m²")
except Exception as exc:
    print("实体化失败:", str(exc)[:150])
doc.close()
