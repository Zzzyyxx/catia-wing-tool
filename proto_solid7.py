import pycatia
catia = pycatia.catia(); catia.display_file_alerts = False
doc = catia.documents.add("Part"); part = doc.part; spa = doc.spa_workbench()
hsf = part.hybrid_shape_factory; pr = part.create_reference_from_object

body = part.hybrid_bodies.add(); body.name = "T"
pts = [[0,0,0],[100,0,0],[100,80,0],[0,80,0]]
sq = hsf.add_new_spline()
for p in hsf.add_new_point_coords(pts): sq.add_point(p)
sq.set_closing(1); body.append_hybrid_shape(sq)
fill = hsf.add_new_fill(); fill.add_bound(pr(sq)); body.append_hybrid_shape(fill)
part.update()
print("平面片面积:", round(spa.get_measurable(pr(fill)).area, 6), "m²")

a = hsf.add_new_point_coords([[0,0,0]])[0]; b = hsf.add_new_point_coords([[0,0,100]])[0]
zline = hsf.add_new_line_pt_pt(pr(a), pr(b)); body.append_hybrid_shape(zline); part.update()
zref = pr(zline).com_object
raw = part.shape_factory.com_object
fref = pr(fill).com_object

cases = [
    ("4 参: 2,0,0",   (fref, 2.0, 0.0, 0)),
    ("4 参: 2,0,1",   (fref, 2.0, 0.0, 1)),
    ("4 参: 2,0,True",(fref, 2.0, 0.0, True)),
    ("4 参: 2,0,False",(fref, 2.0, 0.0, False)),
    ("4 参: 2,0,Zref",(fref, 2.0, 0.0, zref)),
]
ok = None
for label, args in cases:
    try:
        got = raw.AddNewThickSurface(*args)
        got.Name = "TH"
        part.update()
        v = spa.get_measurable(part.create_reference_from_object(got)).volume
        print(f"✓ {label}: volume={v:.8f} m³")
        ok = label; break
    except Exception as exc:
        print(f"✗ {label}: {str(exc)[:70]}")
        try: part.update()
        except Exception: pass

print("\n--- VolumeCloseSurface 测试 ---")
for label, args in (("1 参", (fref,)), ("2 参", (fref, 1))):
    try:
        got = raw.AddNewVolumeCloseSurface(*args)
        got.Name = "VC"
        part.update()
        print(f"✓ {label}: volume={spa.get_measurable(part.create_reference_from_object(got)).volume:.8f}")
        break
    except Exception as exc:
        print(f"✗ {label}: {str(exc)[:80]}")
        try: part.update()
        except Exception: pass
doc.close()
