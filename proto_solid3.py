import math, pycatia
from pycatia.scripts.vba import vba_nothing
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object

def loop(y, chord, thick, n=16):
    return [[chord*(0.5-0.5*math.cos(2*math.pi*i/n)), y, thick*0.5*math.sin(2*math.pi*i/n)]
            for i in range(n)]
body = part.hybrid_bodies.add(); body.name="T"
secs=[]
for y,c in ((0.0,100.0),(250.0,45.0)):
    sp = hsf.add_new_spline()
    for p in hsf.add_new_point_coords(loop(y,c,0.18*c)): sp.add_point(p)
    sp.set_closing(1); body.append_hybrid_shape(sp); secs.append(sp)
loft = hsf.add_new_loft()
for s in secs: loft.add_section_to_loft(pr(s), 1, vba_nothing)
body.append_hybrid_shape(loft); part.update()
ref = pr(loft).com_object
raw = part.shape_factory.com_object

trials = [
    ("2 参数 (ref,2)",        lambda: raw.AddNewThickSurface(ref, 2.0)),
    ("3 参数 (ref,0,-2)",     lambda: raw.AddNewThickSurface(ref, 0.0, -2.0)),
    ("4 参数 (+1)",           lambda: raw.AddNewThickSurface(ref, 0.0, -2.0, 1)),
    ("4 参数 (+0)",           lambda: raw.AddNewThickSurface(ref, 0.0, -2.0, 0)),
    ("3 参数 (ref,2,0)",      lambda: raw.AddNewThickSurface(ref, 2.0, 0.0)),
]
for label, fn in trials:
    try:
        got = fn()
        got.Name = "TH_" + label.replace(" ", "")
        part.update()
        m = spa.get_measurable(part.create_reference_from_object(got))
        print(f"✓ {label}: volume={m.volume:.8f} m³")
        break
    except Exception as exc:
        print(f"✗ {label}: {str(exc)[:70]}")
        try: part.update()
        except Exception: pass
doc.close()
