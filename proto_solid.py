import math, pycatia
from pycatia.scripts.vba import vba_nothing
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object

def loop(x0, y, chord, thick, n=16):
    pts = []
    for i in range(n):
        t = 2*math.pi*i/n
        # 用椭圆近似翼型截面，够验证加厚
        pts.append([x0 + chord*(0.5 - 0.5*math.cos(t)), y, thick*0.5*math.sin(t)])
    return pts

body = part.hybrid_bodies.add(); body.name="T"
secs = []
for y, c in ((0.0, 100.0), (250.0, 45.0)):
    sp = hsf.add_new_spline()
    for p in hsf.add_new_point_coords(loop(0, y, c, 0.18*c)): sp.add_point(p)
    sp.set_closing(1); body.append_hybrid_shape(sp); secs.append(sp)
loft = hsf.add_new_loft()
for s in secs: loft.add_section_to_loft(pr(s), 1, vba_nothing)
body.append_hybrid_shape(loft); part.update()
print("翼面面积:", round(spa.get_measurable(pr(loft)).area, 6), "m²")

raw = part.shape_factory.com_object
for name, args in (("AddNewThickSurface", None), ("AddNewCloseSurface", None)):
    try:
        if name == "AddNewThickSurface":
            th = raw.AddNewThickSurface(pr(loft), 0.0, -2.0)
        else:
            th = raw.AddNewCloseSurface(pr(loft))
        th.Name = name
        part.update()
        m = spa.get_measurable(pr(th))
        print(f"{name}: OK, volume={m.volume:.6f} m³  area={m.area:.6f}")
    except Exception as exc:
        print(f"{name} 失败: {str(exc)[:130]}")
        try: part.update()
        except Exception: pass
doc.close()
