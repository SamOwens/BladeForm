# Human made README

This tool was made because I had difficulty finding a free impeller design
tool that was both free and had a user friendly GUI. It is admittedly AI generated
so there's a very real possibility nothing here is accurate in the slightest but I 
figured it'd be worth a shot. Don't be irresponsible. Don't act as if exports are
100% accurate, this is for mean-line at best. Also this is meant for Windows.

After unzipping you're gonna need to
1. Open a terminal in the folder containing start_bladeform.bat 
2. Run pip install -r requirements.txt
3. Run pip install cadquery-ocp
4. Double click start_bladeform.bat 
(or run python helper.py and open http://127.0.0.1:8765/ in a browser)
5. Design your impeller
6. Export to steps folder

I hope this can be of use to somebody, a more detailed (but less personal)
README sits below. You've got BladeForm, all is right with the world. 😎😎😎



# BladeForm

Parametric design tool for turbomachinery impellers — centrifugal compressors,
turbochargers, pumps and mixed-flow fans. Adjust engineering parameters, watch
the geometry and performance update live, and export a real B-rep solid for CAD
and CFD.

Two pieces, sharing one set of physics:

| | what it is | needs |
|---|---|---|
| **Viewer** | `bladeform-viewer.html` — the whole GUI in one file | a browser |
| **Engine** | `bladeform/` — Python package, and the only thing that writes STEP | Python 3.10+ |
| **Helper** | `helper.py` + `start_bladeform.bat` — local server on 127.0.0.1 | Python 3.10+ |

Read `STATUS.md` before trusting any number. It lists exactly what is verified,
what is approximate, and what does not work.

---

## Quick start — the viewer

**Recommended:** double-click `start_bladeform.bat`. That starts the local helper
(bound to `127.0.0.1` only) and opens the viewer at `http://127.0.0.1:8765/`.
Project files land in `projects/`, verified STEP solids in `steps/`.

You can still open `bladeform-viewer.html` directly in any modern browser for
preview work. Mesh and performance-map downloads work without the helper; project
save falls back to a normal browser download; STEP export needs the helper.

Check the badge in the top right. It should read **"engine verified"**. That
means the browser's copy of the physics was just re-checked against reference
values from the Python engine and agrees to about 1e-15. If it ever reads
"engine mismatch", hover it — it names the quantity that drifted.

### Finding your way around

- **Left** — every parameter, grouped. Hover any label for what it physically
  means; several have a diagram.
- **Centre** — the 3D wheel, the target-vs-actual bar, and the plots.
- **Right** — derived values, warnings, and your snapshots.

### A first pass

1. Pick a machine from the **Machine** menu. Each preset is sized from its duty
   using standard preliminary-design rules, not typed in by hand.
2. Set a **target pressure ratio** (or target head, for liquids) at the top of
   the Operating conditions group. Every preset starts on its target to within
   0.2%, so you can see immediately what your change costs.
3. Drag **Shaft speed** and watch the bar under the viewport. Green means you
   are near target; amber means you are off it; red means you have crossed an
   estimated surge or choke limit.
4. Open the **Performance map** tab to see where the design point sits against
   the speed lines.
5. **Save snapshot**, change something, save another, then tick both and open
   the **Compare** tab for overlaid profiles and a table of what changed.

### Things worth knowing

**Wrap angle has two modes**, and the UI tells you which is active.
*Derived* means wrap is the integral of tan β / r along the blade — it follows
from your blade angles and is read-only. *Target* holds β₁ and β₂ exactly at
what you typed and solves only the distribution between them to reach your
wrap. If your target is unreachable it says so instead of quietly clamping.

**The fluid selector changes the physics, not a label.** With Water selected the
solver reports head and NPSH and never evaluates a Mach number; the liquid model
raises an error if anything tries to ask it for a specific heat ratio.

**Units convert.** Switching to Imperial re-derives every displayed and exported
number, including the affine K → °F conversion.

**Choke margin is watched.** Near Mach 1 the inducer has very little flow left
before it chokes — at M₁rel = 0.7 only about 9% more. That is normal for a fast
wheel, so the checks panel warns below 6% margin and errors past the limit
rather than letting a design sit silently on its choke line.

**The hub fillet is modelled into the blade surface.** It widens the root and
tapers to nothing over a height equal to its radius. It shows up in the preview
and in the exported solid alike — and it eats blade pitch, so watch the blockage
warning if you make it large.

Undo/redo is Ctrl+Z / Ctrl+Shift+Z. Your session autosaves in the browser;
**Open** loads a `.bfproj` file back.

### Exporting from the viewer

**Export** gives you a project file, an STL of the preview mesh, and the map as
CSV. STEP needs a CAD kernel, which does not run in a browser — use the Python
package below.

---

## The Python engine

```bash
pip install numpy scipy matplotlib
pip install cadquery-ocp          # OpenCASCADE — only needed for STEP export
```

`cadquery-ocp` is a large download. Everything except STEP works without it.

Auto-size a machine from duty rather than starting from a preset:

```python
from bladeform import air
from bladeform.performance import size_converged

d, op = size_converged(
    air(),
    template=dict(name="My wheel", archetype="baseline_compressor",
                  n_main=9, n_splitter=9, fluid_kind="air",
                  p01=101325.0, T01=288.15, mdot=2.0, rpm=25000,
                  target_pressure_ratio=2.6, target_head_m=40.0),
    target_pressure_ratio=2.6,
    mdot=2.0, rpm=25000, psi=0.62, beta2=32, htr=0.30, beta1s_target=50,
)
print(f"r2 {d.r2*1000:.1f} mm, PR {op.pressure_ratio:.3f}, eta {op.eta_tt:.3f}")
```

It iterates on the efficiency the loss model predicts and then on blade speed,
so the machine meets the duty you asked for instead of missing it by whatever
the initial efficiency guess was wrong by. It raises rather than returning a
machine that quietly misses its target.

```python
from bladeform.params import make_preset, validate
from bladeform.fluids import air
from bladeform.performance import evaluate, choke_mass_flow

d = make_preset("turbocharger")
d.rpm = 120_000
d.beta2_hub_deg = 38

op = evaluate(d, air())
print(f"PR {op.pressure_ratio:.3f}  eta {op.eta_tt:.3f}  {op.power_W/1000:.1f} kW")
print(f"inducer tip Mach {op.M1_rel:.2f}, choke at {choke_mass_flow(d, air()):.3f} kg/s")

for issue in validate(d):
    print(issue.level, issue.field, issue.message)
```

Presets: `baseline_compressor`, `turbocharger`, `pump`, `mixed_flow_fan`.

### Exporting a solid

```python
from bladeform.step_export import export_step
from bladeform.step_verify import verify

d.diffuser_on = True          # vanes are included when enabled
d.volute_on = True

print(export_step(d, "wheel.step")["notes"])
print(verify("wheel.step"))   # independent check — see below
```

`export_step` defaults to `mode="compound"`: the hub, every blade, the diffuser
vanes and the volute as separate validated solids in one STEP assembly. Unite
them in your CAD system if you want a single body.

`mode="fused"` runs a boolean to produce one solid. It is slow (about 19 s per
blade on one core) and produces an invalid solid on three of the four presets,
so it is not the default. It validates its own output and raises rather than
writing a bad file.

### Checking the export yourself

`step_verify` is a plain text parser over the STEP entity list. It does not use
OpenCASCADE, so it cannot be fooled by the same bug that wrote the file. It
reports the surface types present and fails loudly on triangle-soup markers —
the signature of a mesh dressed up as a solid.

A useful check of your own: raise the viewer's detail setting and export again.
The STEP face count must not change. It is determined by the surface
definition, never by tessellation.

### Other outputs

```python
from bladeform.exporters import export_stl, export_report, save_project, load_project
from bladeform.cmap import generate_map, plot_map, map_to_csv
from bladeform.fluids import water, custom

export_stl(d, "wheel.stl", lod=2)          # STL IS a mesh, so lod applies here
export_report(d, "report.html")            # parameters, derived values, plots
save_project(d, "design.bfproj")           # reopens in the viewer

m = generate_map(d, air())
plot_map(m, "map.png")                     # also writes map.svg
open("map.csv", "w").write(map_to_csv(m))

oil = custom("Oil", compressible=False, density=870, viscosity=0.08,
             vapour_pressure=50)
```

---

## Running the tests

```bash
python3 tests/test_all.py        # 42 tests, fast
python3 tests/test_step.py       # 14 tests, needs cadquery-ocp, ~20 s
cd viewer && npm install jsdom && node uitest.js    # drives the whole GUI
```

---

## What the numbers are

The performance model is a 1D mean-line calculation: Euler work, Wiesner slip,
and a loss set following Oh, Yoon & Chung (1997). Every empirical constant
carries its source in a comment, and the two limits that are engineering
judgement rather than published correlation say so.

**These are first-order estimates.** Surge and choke lines come from simple
correlations, not CFD or test data. The plots, the CSV and the HTML report all
say so. Use them to navigate the design space, not to predict a machine.

Known limitations are in `STATUS.md`, including the skin-friction term reading
low against literature (left at the published correlation rather than scaled to
look right) and the fillet being a modelled blend rather than a kernel fillet.

---

## Layout

```
bladeform/
  units.py         SI/Imperial, stored SI, converted at the edges
  fluids.py        air, water, custom — liquids refuse gas properties
  geometry.py      meridional channel, camber, thickness, root fillet
  params.py        parameter set, presets, validation
  performance.py   mean-line model, choke, duty-based sizing
  cmap.py          performance map
  mesh.py          preview tessellation
  step_export.py   B-rep solids via OpenCASCADE
  step_verify.py   independent STEP checker
  exporters.py     STL, project JSON, HTML report
viewer/            viewer sources and the jsdom test
tests/
STATUS.md          verified / approximate / broken
```
