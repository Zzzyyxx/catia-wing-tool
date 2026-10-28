import math, pycatia
from pycatia.scripts.vba import vba_nothing
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object

body = part.hybrid_bodies.add(); body.name = "T"
# 简单平面曲片：100x100 的方形（用样条闭合），法向 Z
pts = [[0,0,0],[100,0,0],[100,100,0],[0,100,0]]
sq = hsf.add_new_spline()
for p in hsf.add_new_point_coords(pts): sq.add_point(p)
sq.set_closing(1); body.append_hybrid_shape(sq)
fill = hsf.add_new_fill()
try:
    fill.add_boundary(pr(sq))   # 若有此方法
except Exception:
    pass
body.append_hybrid_shape(fill)
try:
    part.update()
    print("填充面面积:", round(spa.get_measurable(pr(fill)).area, 6), "m²")
except Exception as exc:
    print("填充失败:", str(exc)[:100])

raw = part.shape_factory.com_object
zref = None
a = hsf.add_new_point_coords([[0,0,0]])[0]; b = hsf.add_new_point_coords([[0,0,100]])[0]
zline = hsf.add_new_line_pt_pt(pr(a), pr(b)); body.append_hybrid_shape(zline); part.update()
zref = pr(zline).com_object
sref = pr(fill).com_object

cases = [
    ("4: (ref,2,0,1)",      (sref, 2.0, 0.0, 1)),
    ("4: (ref,2,0,True)",   (sref, 2.0, 0.0, True)),
    ("4: (ref,2,0,0)",      (sref, 2.0, 0.0, 0)),
    ("4: (ref,0,-2,False)", (sref, 0.0, -2.0, False)),
    ("4: (ref,2,0,Ref)",    (sref, 2.0, 0.0, zref)),
]
for label, args in cases:
    try:
        got = raw.AddNewThickSurface(*args)
        got.Name = "TH_" + label.split(":")[0].replace(" ", "")
        part.update()
        m = spa.get_measurable(part.create_reference_from_object(got))
        print(f"✓ {label}: volume={m.volume:.8f} m³")
        break
    except Exception as exc:
        print(f"✗ {label}: {str(exc)[:80]}")
        try: part.update()
        except Exception: pass
doc.close()
