# NEMA Four-Way Reference

Single-intersection reference built with SUMO plain XML source files.

- source files: `.nod.xml`, `.edg.xml`, `.con.xml`
- signal groups: `.tll.xml` loaded by `netconvert`
- generated network: `.net.xml` from `netconvert`
- NEMA controller: embedded by `.tll.xml`; `.add.xml` is written as a reusable template
- no direct hand-editing of `.net.xml` traffic-light logic

NEMA settings: `total-cycle-length=90`, `ring1=1,2,3,4`, `ring2=5,6,7,8`, `barrierPhases=2,6`, `barrier2Phases=4,8`, `minRecall=2,6`, empty `maxRecall`, `yellow=3`, `red=1`, `minDur=5`, left `maxDur=20`, through `maxDur=35`.

Audit: `intersection_scene_nema_audit.json`

`diagnostic-demo`: this is a calibration/reference network, not a calibrated field signal plan.
