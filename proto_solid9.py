import math, pycatia
from pycatia.scripts.vba import vba_nothing
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object

def circle_pts(z, r, n=24):
    return [[r*math.cos(2*math.pi*i/n), r*math.sin(2*math.pi*i/n), z] for i in range(n)]
body = part.hybrid_bodies.add(); body.name="T"
secs=[]
for z in (0.0, 100.0):
    sp = hsf.add_new_spline()
    for p in hsf.add_new_point_coords(circle_pts(z,30.0)): sp.add_point(p)
    sp.set_closing(1); body.append_hybrid_shape(sp); secs.append(sp)
loft = hsf.add_new_loft()
for s in secs: loft.add_section_to_loft(pr(s), 1, vba_nothing)
body.append_hybrid_shape(loft); part.update()
for s in secs:
    f = hsf.add_new_fill(); f.add_bound(pr(s)); body.append_hybrid_shape(f)
part.update()
fills = [sh for b in part.hybrid_bodies for sh in b.hybrid_shapes if sh.name.startswith("填充")]
j = hsf.add_new_join(pr(loft), pr(fills[0])); body.append_hybrid_shape(j); part.update()
j2 = hsf.add_new_join(pr(j), pr(fills[1])); body.append_hybrid_shape(j2); part.update()

print("尝试切换工作台...")
for wb in ("PartDesign", "GenerativeShapeDesign"):
    try:
        catia.start_workbench(wb)
        print(f"  start_workbench({wb}) OK, 当前: {catia.active_workbench.name if hasattr(catia,'active_workbench') else '?'}")
        break
    except Exception as exc:
        print(f"  {wb} 失败: {str(exc)[:70]}")

raw = part.shape_factory.com_object
try:
    s = raw.AddNewCloseSurface(pr(j2).com_object); s.Name="实体"; part.update()
    print("✓ 切换后 CloseSurface 成功 volume =", spa.get_measurable(part.create_reference_from_object(s)).volume)
except Exception as exc:
    print("✗ 切换后仍失败:", str(exc)[:100])
doc.close()
