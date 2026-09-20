/* ============================ BladeForm UI ============================ */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const el = (t, a = {}, ...kids) => {
  const n = document.createElement(t);
  for (const [k, v] of Object.entries(a)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v != null) n.setAttribute(k, v);
  }
  kids.flat().forEach(c => n.append(c?.nodeType ? c : document.createTextNode(c)));
  return n;
};

/* ------------------------------ parameter schema ------------------------------ */
// dim drives unit conversion; every field carries a physical explanation.
const DIA = {
  beta: `<svg width="200" height="66" viewBox="0 0 200 66" fill="none">
    <path d="M12 54 H188" stroke="#8aa" stroke-width="1" stroke-dasharray="3 3"/>
    <path d="M40 54 C 78 54, 112 30, 150 12" stroke="#ffb020" stroke-width="2.5"/>
    <path d="M40 54 L96 54" stroke="#9cf" stroke-width="1.5"/>
    <path d="M40 54 C 60 54, 72 46, 84 40" stroke="#9cf" stroke-width="1.5" fill="none"/>
    <text x="90" y="48" fill="#cfe" font-size="11">\u03b2</text>
    <text x="150" y="62" fill="#9ab" font-size="9">meridional direction</text></svg>`,
  wrap: `<svg width="200" height="76" viewBox="0 0 200 76" fill="none">
    <circle cx="100" cy="40" r="28" stroke="#8aa" stroke-width="1" stroke-dasharray="3 3"/>
    <path d="M100 12 A28 28 0 0 1 124 54" stroke="#ffb020" stroke-width="3"/>
    <line x1="100" y1="40" x2="100" y2="12" stroke="#9cf" stroke-width="1.2"/>
    <line x1="100" y1="40" x2="124" y2="54" stroke="#9cf" stroke-width="1.2"/>
    <text x="106" y="34" fill="#cfe" font-size="11">\u03b8</text>
    <text x="16" y="70" fill="#9ab" font-size="9">total turning seen from the front</text></svg>`,
  merid: `<svg width="200" height="76" viewBox="0 0 200 76" fill="none">
    <path d="M24 64 C 84 64, 116 50, 132 14" stroke="#c8a" stroke-width="2.5"/>
    <path d="M24 30 C 64 30, 88 24, 104 14" stroke="#7bd" stroke-width="2.5"/>
    <line x1="24" y1="30" x2="24" y2="64" stroke="#9ab" stroke-dasharray="2 2"/>
    <line x1="104" y1="14" x2="132" y2="14" stroke="#9ab" stroke-dasharray="2 2"/>
    <text x="30" y="26" fill="#7bd" font-size="9">shroud</text>
    <text x="34" y="74" fill="#c8a" font-size="9">hub</text>
    <text x="108" y="10" fill="#cfe" font-size="9">b\u2082</text></svg>`,
};

const GROUPS = [
  { id: "op", name: "Operating conditions", open: true, fields: [
    { k: "rpm", l: "Shaft speed", dim: "rpm", min: 500, max: 200000, step: 100,
      tip: "How fast the wheel turns. Everything scales from this: blade speed goes up linearly with it, and the work you get goes up with the square." },
    { k: "mdot", l: "Mass flow", dim: "massflow", min: 0.01, max: 50, step: 0.01,
      tip: "How much fluid passes through each second. Too much for the inlet area and the flow chokes; too little and it stalls." },
    { k: "p01", l: "Inlet total pressure", dim: "pressure_pa", min: 1000, max: 2e6, step: 1000,
      tip: "Stagnation pressure entering the inducer. Sets the inlet density, and for a pump it sets how much margin you have before cavitation." },
    { k: "T01", l: "Inlet total temperature", dim: "temperature", min: 200, max: 600, step: 1,
      tip: "Stagnation temperature entering the machine. Hotter air is less dense, so the same mass flow needs more velocity." },
  ]},
  { id: "mer", name: "Meridional geometry", open: true, dia: "merid", fields: [
    { k: "r1_hub", l: "Inlet hub radius", dim: "length_mm", scale: 1000, min: 1, max: 300, step: .1,
      tip: "Radius of the shaft boss where the blades start. Larger blocks more of the inlet area." },
    { k: "r1_shroud", l: "Inlet shroud radius", dim: "length_mm", scale: 1000, min: 2, max: 400, step: .1,
      tip: "Outer radius of the inducer eye. This is where relative velocity is highest, so it governs the inlet Mach number." },
    { k: "r2", l: "Exit radius", dim: "length_mm", scale: 1000, min: 5, max: 600, step: .1,
      tip: "Tip radius where flow leaves the wheel. Blade speed at this radius sets almost all the work the stage can do." },
    { k: "b2", l: "Exit blade height", dim: "length_mm", scale: 1000, min: .2, max: 120, step: .1,
      tip: "Passage height at the exit. Narrower means faster through-flow, which costs efficiency in the diffuser." },
    { k: "axial_length", l: "Axial length", dim: "length_mm", scale: 1000, min: 2, max: 400, step: .1,
      tip: "How far the wheel extends along the shaft. Longer gives the flow a gentler turn from axial to radial." },
    { k: "exit_pitch_deg", l: "Exit pitch angle", dim: "angle", min: 0, max: 70, step: 1,
      tip: "0\u00b0 means the flow leaves purely radially, as in a centrifugal compressor. Raise it to lean the exit axially for a mixed-flow machine." },
    { k: "hub_fillet", l: "Hub fillet radius", dim: "length_mm", scale: 1000, min: 0, max: 20, step: .01,
      tip: "Blend radius where the blade meets the hub, for stress relief. Modelled into the blade surface, so it shows up here and in the exported solid alike. Watch the blockage warning: a big fillet eats the blade pitch." },
  ]},
  { id: "bl", name: "Blade definition", open: true, dia: "beta", fields: [
    { k: "n_main", l: "Main blades", dim: "ratio", int: true, min: 1, max: 40, step: 1,
      tip: "Full-length blades. More blades guide the flow better and raise the slip factor, but block the inlet and add friction." },
    { k: "n_splitter", l: "Splitter blades", dim: "ratio", int: true, min: 0, max: 40, step: 1,
      tip: "Short blades starting partway along the passage. They add guidance near the exit without blocking the inducer throat." },
    { k: "splitter_start_frac", l: "Splitter start", dim: "ratio", min: .05, max: .9, step: .01,
      tip: "Where splitters begin, as a fraction along the blade path. Later start means less blockage but less benefit." },
    { k: "beta1_hub_deg", l: "\u03b2\u2081 at hub", dim: "angle", min: 0, max: 85, step: .5,
      tip: "Inlet blade angle at the hub, measured from the flow direction. Match it to the incoming relative flow to avoid incidence loss \u2014 the zero-incidence value is shown under Derived." },
    { k: "beta1_shroud_deg", l: "\u03b2\u2081 at shroud", dim: "angle", min: 0, max: 85, step: .5,
      tip: "Inlet blade angle at the tip. Larger than the hub value because the blade is moving faster out there \u2014 that difference is the inducer twist." },
    { k: "beta2_hub_deg", l: "Backsweep \u03b2\u2082", dim: "angle", min: 0, max: 70, step: .5,
      tip: "How far the blade leans back at exit. More backsweep trades peak pressure rise for a wider, more stable operating range." },
    { k: "beta_exponent", l: "\u03b2 distribution", dim: "ratio", min: .15, max: 6, step: .05,
      tip: "Shapes how the blade angle changes between inlet and exit. Above 1 holds the inlet angle longer and turns late; below 1 turns early. The endpoints never move." },
    { k: "inlet_sweep_deg", l: "Inlet sweep", dim: "angle", min: -40, max: 40, step: 1,
      tip: "Leans the leading edge forward or back across the span, so the tip meets the flow before or after the hub." },
    { k: "exit_rake_deg", l: "Exit rake", dim: "angle", min: -30, max: 30, step: 1,
      tip: "Leans the trailing edge across the span. Used to trim the exit flow profile." },
    { k: "lean_deg", l: "Stacking lean", dim: "angle", min: -40, max: 40, step: 1,
      tip: "Tilts the blade sideways from hub to tip. Shifts load spanwise and changes the bending stress the blade carries." },
    { k: "t_le", l: "LE thickness", dim: "length_mm", scale: 1000, min: .05, max: 12, step: .01,
      tip: "Blade thickness at the leading edge. Thin is aerodynamically better but blocks the throat less forgivingly and is harder to cast." },
    { k: "t_max", l: "Max thickness", dim: "length_mm", scale: 1000, min: .05, max: 20, step: .01,
      tip: "Peak thickness along the blade, which carries the bending load." },
    { k: "t_te", l: "TE thickness", dim: "length_mm", scale: 1000, min: .05, max: 15, step: .01,
      tip: "Thickness at the trailing edge. Thicker leaves a bigger wake and more mixing loss downstream." },
    { k: "t_peak_frac", l: "Thickness peak at", dim: "ratio", min: .1, max: .9, step: .01,
      tip: "Where along the blade the maximum thickness sits, as a fraction of the path." },
  ]},
  { id: "ds", name: "Downstream", open: false, fields: [
    { k: "diffuser_ratio", l: "Diffuser radius ratio", dim: "ratio", min: 1.05, max: 2.5, step: .01,
      tip: "How far the diffuser extends past the impeller exit, as a multiple of exit radius." },
    { k: "diffuser_vanes", l: "Diffuser vanes", dim: "ratio", int: true, min: 0, max: 40, step: 1,
      tip: "Vaned diffusers recover more pressure than a plain vaneless space, but only over a narrower flow range." },
    { k: "diffuser_turn_deg", l: "Vane turning", dim: "angle", min: 0, max: 35, step: 1,
      tip: "How much the vanes turn the flow toward radial. The vane leading edge is set to the swirl the impeller actually delivers, so this is turning on top of that, not an absolute stagger." },
    { k: "volute_exit_d", l: "Volute exit diameter", dim: "length_mm", scale: 1000, min: 5, max: 400, step: 1,
      tip: "Throat diameter where the collecting scroll discharges. The scroll's cross-section is sized to match it, so the two stay consistent." },
    { k: "volute_area_exponent", l: "Volute area growth", dim: "ratio", min: 0.4, max: 2.5, step: .05,
      tip: "Shapes how the scroll cross-section grows around the wheel: A(\u03b8) = A_exit \u00d7 (\u03b8/2\u03c0)^n. 1.0 grows the area linearly with angle, which is the usual starting point." },
  ]},
];

const TARGET_FIELD = { k: "target_pressure_ratio", l: "Target pressure ratio", dim: "ratio", min: 1, max: 12, step: .01,
  tip: "What you are aiming for. The bar under the viewport compares this against what the current geometry actually delivers." };
const TARGET_HEAD = { k: "target_head_m", l: "Target head", dim: "head", min: 1, max: 500, step: 1,
  tip: "Target rise in metres of liquid column. The bar under the viewport tracks it live." };

/* ------------------------ per-viewer persistence ------------------------
   localStorage only, for conveniences: restoring your last session and a
   recent-designs list. Every access is wrapped — storage can be absent,
   full, or disabled, and the page must still render. Nothing here is shared
   between viewers and nothing here is authoritative: the project file is.
   ----------------------------------------------------------------------- */
const SESSION_KEY = "bladeform.session.v1", RECENT_KEY = "bladeform.recent.v1";
const store = {
  get(k) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : null; }
           catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; }
              catch { return false; } },
};

// flat lookup of every declared field, for labels/units in the diff table
const FIELD_INDEX = (() => {
  const m = {};
  for (const g of GROUPS) for (const f of g.fields) m[f.k] = f;
  m[TARGET_FIELD.k] = TARGET_FIELD; m[TARGET_HEAD.k] = TARGET_HEAD;
  m.target_wrap_deg = { l: "Target wrap \u03b8", dim: "angle" };
  return m;
})();

/* ------------------------------ state ------------------------------ */
const S = {
  key: "turbocharger",
  d: null,
  sys: "SI",
  shade: "solid",
  lod: 1,
  tab: "merid",
  snaps: [],
  undo: [], redo: [],
  surfCol: "#4d7fb3",
  cmpSel: [],
  bgCol: null,
  lastMap: null,
};
const clone = o => JSON.parse(JSON.stringify(o));

function pushHistory() {
  S.undo.push(clone(S.d));
  if (S.undo.length > 60) S.undo.shift();
  S.redo.length = 0;
  syncHistoryButtons();
}
function syncHistoryButtons() {
  $("#undo").disabled = !S.undo.length;
  $("#redo").disabled = !S.redo.length;
}
function undo() { if (!S.undo.length) return; S.redo.push(clone(S.d)); S.d = S.undo.pop(); syncHistoryButtons(); renderAll(true); }
function redo() { if (!S.redo.length) return; S.undo.push(clone(S.d)); S.d = S.redo.pop(); syncHistoryButtons(); renderAll(true); }

function loadPreset(key) {
  S.key = key;
  S.d = clone(REF[key].params);
  S.undo.length = 0; S.redo.length = 0;
  syncHistoryButtons();
  $("#fluid").value = S.d.fluid_kind;
  renderAll(true, true);
}

/* ------------------------------ 3D viewer ------------------------------ */
const V = { renderer: null, scene: null, camera: null, group: null,
            rot: { th: -0.85, ph: 1.05 }, dist: 1, target: null, dirty: true };

function initViewer() {
  const host = $("#viewport");
  V.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  V.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  host.append(V.renderer.domElement);
  V.scene = new THREE.Scene();
  V.camera = new THREE.PerspectiveCamera(38, 1, 0.001, 100);
  V.target = new THREE.Vector3();

  V.scene.add(new THREE.HemisphereLight(0xdce8f4, 0x2a3038, 0.85));
  const key = new THREE.DirectionalLight(0xffffff, 0.85); key.position.set(2.2, 3.4, 2.6);
  const rim = new THREE.DirectionalLight(0x9fc4e8, 0.35); rim.position.set(-2.4, -1.2, -2.0);
  V.scene.add(key, rim);
  V.group = new THREE.Group(); V.scene.add(V.group);

  let drag = null;
  const dom = V.renderer.domElement;
  dom.style.touchAction = "none";
  dom.addEventListener("pointerdown", e => {
    drag = { x: e.clientX, y: e.clientY, btn: e.button, pan: e.button === 2 || e.shiftKey };
    dom.setPointerCapture(e.pointerId);
  });
  dom.addEventListener("pointermove", e => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.pan) {
      const s = V.dist * 0.0016;
      const right = new THREE.Vector3().setFromMatrixColumn(V.camera.matrix, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(V.camera.matrix, 1);
      V.target.addScaledVector(right, -dx * s).addScaledVector(up, dy * s);
    } else {
      V.rot.th -= dx * 0.008;
      V.rot.ph = Math.max(0.06, Math.min(Math.PI - 0.06, V.rot.ph - dy * 0.008));
    }
    V.dirty = true;
  });
  const end = e => { if (drag) { try { dom.releasePointerCapture(e.pointerId); } catch {} drag = null; } };
  dom.addEventListener("pointerup", end); dom.addEventListener("pointercancel", end);
  dom.addEventListener("contextmenu", e => e.preventDefault());
  dom.addEventListener("wheel", e => {
    e.preventDefault();
    V.dist *= Math.exp(Math.sign(e.deltaY) * 0.12);
    V.dist = Math.max(0.05, Math.min(60, V.dist)); V.dirty = true;
  }, { passive: false });

  new ResizeObserver(() => { sizeViewer(); V.dirty = true; }).observe(host);
  sizeViewer();
  (function loop() {
    requestAnimationFrame(loop);
    if (!V.dirty) return;
    V.dirty = false;
    const { th, ph } = V.rot, r = V.dist;
    V.camera.position.set(
      V.target.x + r * Math.sin(ph) * Math.cos(th),
      V.target.y + r * Math.cos(ph),
      V.target.z + r * Math.sin(ph) * Math.sin(th));
    V.camera.lookAt(V.target);
    V.renderer.render(V.scene, V.camera);
  })();
}

function sizeViewer() {
  const host = $("#viewport");
  const w = host.clientWidth || 640, h = host.clientHeight || 420;
  V.renderer.setSize(w, h, false);
  V.camera.aspect = w / h; V.camera.updateProjectionMatrix();
}

/* -------- tessellation (preview only; STEP export never sees this) -------- */
function gridIndices(ni, nj, off, flip, out) {
  for (let i = 0; i < ni - 1; i++) for (let j = 0; j < nj - 1; j++) {
    const a = off + i * nj + j, b = a + 1, c = a + nj, d = c + 1;
    if (flip) out.push(a, b, c, b, d, c); else out.push(a, c, b, b, c, d);
  }
}

/* Make a closed shell wind consistently outward. The hand-written patch
   orientations left ~9% of edges wound the same way on both sides: harmless
   under a double-sided material, which is why it hid here, but it flips those
   STL facet normals and makes any volume integral wrong. */
function orientFaces(pos, idx) {
  const n = idx.length / 3, edge = new Map();
  const key = (a, b) => (a < b ? a + ":" + b : b + ":" + a);
  for (let t = 0; t < n; t++)
    for (let e = 0; e < 3; e++) {
      const a = idx[t * 3 + e], b = idx[t * 3 + (e + 1) % 3], k = key(a, b);
      (edge.get(k) || edge.set(k, []).get(k)).push(t);
    }
  const seen = new Uint8Array(n);
  for (let seed = 0; seed < n; seed++) {
    if (seen[seed]) continue;
    seen[seed] = 1;
    const q = [seed];
    while (q.length) {
      const t = q.pop();
      const tv = [idx[t * 3], idx[t * 3 + 1], idx[t * 3 + 2]];
      for (let e = 0; e < 3; e++) {
        const a = tv[e], b = tv[(e + 1) % 3];
        for (const u2 of edge.get(key(a, b)) || []) {
          if (u2 === t || seen[u2]) continue;
          const nv = [idx[u2 * 3], idx[u2 * 3 + 1], idx[u2 * 3 + 2]];
          const same = (nv[0] === a && nv[1] === b) || (nv[1] === a && nv[2] === b)
                    || (nv[2] === a && nv[0] === b);
          if (same) { idx[u2 * 3 + 1] = nv[2]; idx[u2 * 3 + 2] = nv[1]; }
          seen[u2] = 1; q.push(u2);
        }
      }
    }
  }
  let vol = 0;
  for (let t = 0; t < n; t++) {
    const a = idx[t * 3] * 3, b = idx[t * 3 + 1] * 3, c = idx[t * 3 + 2] * 3;
    vol += (pos[a] * (pos[b + 1] * pos[c + 2] - pos[b + 2] * pos[c + 1])
          + pos[a + 1] * (pos[b + 2] * pos[c] - pos[b] * pos[c + 2])
          + pos[a + 2] * (pos[b] * pos[c + 1] - pos[b + 1] * pos[c])) / 6;
  }
  if (vol < 0) for (let t = 0; t < n; t++) {
    const s2 = idx[t * 3 + 1]; idx[t * 3 + 1] = idx[t * 3 + 2]; idx[t * 3 + 2] = s2;
  }
  return idx;
}

function bladeGeometry(P, S_, betaGrid, loadMode, betaRange) {
  const ni = P.length, nj = P[0].length, n = ni * nj;
  const pos = new Float32Array(n * 2 * 3);
  const col = loadMode ? new Float32Array(n * 2 * 3) : null;
  const put = (base, grid) => {
    for (let i = 0; i < ni; i++) for (let j = 0; j < nj; j++) {
      const k = (base + i * nj + j) * 3, p = grid[i][j];
      pos[k] = p[0]; pos[k + 1] = p[1]; pos[k + 2] = p[2];
      if (col) {
        const t = (betaGrid[i][j] - betaRange[0]) / Math.max(betaRange[1] - betaRange[0], 1e-9);
        const c = ramp(clamp(t, 0, 1));
        col[k] = c[0]; col[k + 1] = c[1]; col[k + 2] = c[2];
      }
    }
  };
  put(0, P); put(n, S_);
  const idx = [];
  gridIndices(ni, nj, 0, false, idx);
  gridIndices(ni, nj, n, true, idx);
  for (const [j, flip] of [[0, true], [nj - 1, false]])
    for (let i = 0; i < ni - 1; i++) {
      const a = i * nj + j, b = (i + 1) * nj + j, c = n + a, d = n + b;
      if (flip) idx.push(a, b, c, b, d, c); else idx.push(a, c, b, b, c, d);
    }
  for (const [i, flip] of [[0, false], [ni - 1, true]])
    for (let j = 0; j < nj - 1; j++) {
      const a = i * nj + j, b = a + 1, c = n + a, d = n + b;
      if (flip) idx.push(a, b, c, b, d, c); else idx.push(a, c, b, b, c, d);
    }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  if (col) g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.setIndex(orientFaces(pos, idx)); g.computeVertexNormals();
  return g;
}

// blue -> cyan -> amber ramp for blade loading
function ramp(t) {
  const stops = [[0.18, 0.36, 0.66], [0.22, 0.66, 0.72], [0.55, 0.78, 0.45],
                 [0.94, 0.76, 0.24], [0.86, 0.36, 0.20]];
  const x = clamp(t, 0, 1) * (stops.length - 1);
  const i = Math.min(Math.floor(x), stops.length - 2), f = x - i;
  return stops[i].map((v, k) => v + (stops[i + 1][k] - v) * f);
}

function hubGeometry(d, nStream, nTheta) {
  const st = streamline(d, 0, nStream);
  const pos = new Float32Array(nStream * nTheta * 3);
  for (let i = 0; i < nStream; i++) for (let j = 0; j < nTheta; j++) {
    const th = TAU * j / (nTheta - 1), k = (i * nTheta + j) * 3;
    pos[k] = st.r[i] * Math.cos(th); pos[k + 1] = st.r[i] * Math.sin(th); pos[k + 2] = st.z[i];
  }
  const idx = []; gridIndices(nStream, nTheta, 0, false, idx);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}

function rebuildScene(quick) {
  const d = S.d;
  while (V.group.children.length) {
    const c = V.group.children.pop();
    c.geometry?.dispose(); c.material?.dispose();
  }
  const lod = quick ? 0 : S.lod;
  const nSpan = [5, 9, 14][lod], nStream = [22, 40, 64][lod], nTheta = [40, 72, 120][lod];
  const loadMode = S.shade === "load";
  const wire = S.shade === "wire";

  // spanwise beta range across the whole blade, for a stable colour scale
  let bLo = 1e9, bHi = -1e9;
  if (loadMode) {
    const probe = buildBlade(d, 5, 18, 0, 0);
    probe.beta.forEach(r => r.forEach(v => { const x = deg(v); if (x < bLo) bLo = x; if (x > bHi) bHi = x; }));
  }

  const matBlade = new THREE.MeshStandardMaterial({
    color: loadMode ? 0xffffff : new THREE.Color(S.surfCol),
    vertexColors: loadMode, roughness: .55, metalness: .18,
    side: THREE.DoubleSide, wireframe: wire, flatShading: false });
  const matSplit = new THREE.MeshStandardMaterial({
    color: loadMode ? 0xffffff : new THREE.Color(S.surfCol).offsetHSL(0, -0.05, 0.10),
    vertexColors: loadMode, roughness: .55, metalness: .18,
    side: THREE.DoubleSide, wireframe: wire });
  const matHub = new THREE.MeshStandardMaterial({
    color: 0xb9b2a4, roughness: .78, metalness: .1,
    side: THREE.DoubleSide, wireframe: wire });

  const perPassage = d.n_main ? Math.floor(d.n_splitter / d.n_main) : 0;
  let tris = 0;
  for (let k = 0; k < d.n_main; k++) {
    const th0 = TAU * k / Math.max(d.n_main, 1);
    const b = buildBlade(d, nSpan, nStream, th0, 0);
    const bg = loadMode ? b.beta.map(r => r.map(deg)) : null;
    const g = bladeGeometry(b.P, b.S, bg, loadMode, [bLo, bHi]);
    tris += g.index.count / 3;
    V.group.add(new THREE.Mesh(g, matBlade));
    for (let s = 0; s < perPassage; s++) {
      const f = (s + 1) / (perPassage + 1);
      const sb = buildBlade(d, nSpan, nStream, th0 + TAU * f / d.n_main, d.splitter_start_frac);
      const sbg = loadMode ? sb.beta.map(r => r.map(deg)) : null;
      const sg = bladeGeometry(sb.P, sb.S, sbg, loadMode, [bLo, bHi]);
      tris += sg.index.count / 3;
      V.group.add(new THREE.Mesh(sg, matSplit));
    }
  }
  const hg = hubGeometry(d, nStream, nTheta);
  tris += hg.index.count / 3;
  V.group.add(new THREE.Mesh(hg, matHub));

  if (d.diffuser_on) addDiffuser(d, wire);
  if (d.volute_on) addVolute(d, wire);

  if (loadMode) {
    $("#legend").style.display = "block";
    $("#legendTitle").textContent = "Blade angle \u03b2";
    $("#legendLo").textContent = bLo.toFixed(0) + "\u00b0";
    $("#legendHi").textContent = bHi.toFixed(0) + "\u00b0";
    $("#legendBar").style.background = "linear-gradient(90deg," +
      [0, .25, .5, .75, 1].map(t => `rgb(${ramp(t).map(v => Math.round(v * 255)).join(",")})`).join(",") + ")";
  } else $("#legend").style.display = "none";

  V.tris = tris;
  V.dirty = true;
}

function addDiffuser(d, wire) {
  const ri = d.r2 * 1.04, ro = d.r2 * d.diffuser_ratio;
  const zc = d.axial_length - d.b2 * 0.5, h = d.b2;
  const mat = new THREE.MeshStandardMaterial({ color: 0x8d97a4, roughness: .7,
    metalness: .1, side: THREE.DoubleSide, transparent: true, opacity: .34, wireframe: wire });
  const ring = new THREE.Mesh(new THREE.RingGeometry(ri, ro, 96), mat);
  ring.position.z = zc + h / 2; V.group.add(ring);
  const ring2 = new THREE.Mesh(new THREE.RingGeometry(ri, ro, 96), mat);
  ring2.position.z = zc - h / 2; V.group.add(ring2);
  if (d.diffuser_vanes > 0) {
    const vmat = new THREE.MeshStandardMaterial({ color: 0x9aa6b4, roughness: .65,
      metalness: .12, side: THREE.DoubleSide, wireframe: wire });
    const len = ro - ri, t = Math.max(len * 0.045, d.t_te * 0.8);
    for (let i = 0; i < d.diffuser_vanes; i++) {
      const a = TAU * i / d.diffuser_vanes;
      const g = new THREE.BoxGeometry(len * 0.92, t, h * 0.9);
      const m = new THREE.Mesh(g, vmat);
      const rm = (ri + ro) / 2;
      m.position.set(rm * Math.cos(a), rm * Math.sin(a), zc);
      m.rotation.z = a + 1.15;   // vanes set at a swirl-matching stagger
      V.group.add(m);
    }
  }
}

function addVolute(d, wire) {
  const ro = d.r2 * (d.diffuser_on ? d.diffuser_ratio : 1.08);
  const zc = d.axial_length - d.b2 * 0.5;
  // Same area law the STEP export uses: A(theta) = A_exit * (theta/2pi)^n,
  // so the drawn scroll and the exported one agree.
  const Aexit = Math.PI * Math.pow(d.volute_exit_d / 2, 2);
  const n = Math.max(d.volute_area_exponent || 1, 0.2);
  const radAt = f => Math.sqrt(Aexit * Math.pow(Math.max(f, 1e-4), n) / Math.PI);
  const pts = [], N = 120;
  for (let i = 0; i <= N; i++) {
    const f = 0.04 + 0.96 * i / N, a = TAU * f;
    const Rc = ro + radAt(f);
    pts.push(new THREE.Vector3(Rc * Math.cos(a), Rc * Math.sin(a), zc));
  }
  const curve = new THREE.CatmullRomCurve3(pts, false);
  const g = new THREE.TubeGeometry(curve, 160, Math.max(radAt(0.5), d.r2 * 0.02), 18, false);
  V.group.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({
    color: 0x77828f, roughness: .75, metalness: .08, transparent: true,
    opacity: .30, side: THREE.DoubleSide, wireframe: wire })));
}

function fitView() {
  const box = new THREE.Box3().setFromObject(V.group);
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  V.target.copy(c);
  V.dist = Math.max(size.x, size.y, size.z) * 1.85;
  V.dirty = true;
}

/* ------------------------------ parameter panel ------------------------------ */
let tipNode = null;
function showTip(row, f) {
  hideTip();
  tipNode = el("div", { class: "tip" });
  tipNode.append(el("div", {}, f.tip));
  const g = GROUPS.find(g => g.fields.includes(f));
  const dia = f.k.startsWith("beta1") || f.k.startsWith("beta2") ? DIA.beta
    : f.k === "beta_exponent" ? DIA.wrap : (g && g.dia ? DIA[g.dia] : null);
  if (dia) tipNode.insertAdjacentHTML("beforeend", dia);
  row.append(tipNode);
}
const hideTip = () => { tipNode?.remove(); tipNode = null; };

function fieldRow(f, issues) {
  const scale = f.scale || 1;
  const si = S.d[f.k] * scale;
  const shown = toDisp(si, f.dim, S.sys);
  const iss = issues.find(i => i.field === f.k);
  const row = el("div", { class: "row" + (iss ? " " + iss.level : "") });
  const lab = el("label", { for: "f_" + f.k }, f.l);
  const inp = el("input", { type: "number", id: "f_" + f.k, class: "num",
    step: f.int ? 1 : "any", value: fmtNum(shown) });
  const unit = uLabel(f.dim, S.sys);
  const commit = v => {
    let siVal = fromDisp(v, f.dim, S.sys) / scale;
    if (f.int) siVal = Math.round(siVal);
    if (!isFinite(siVal)) return;
    pushHistory();
    S.d[f.k] = siVal;
    renderAll();
  };
  inp.addEventListener("change", () => commit(parseFloat(inp.value)));
  lab.addEventListener("pointerenter", () => showTip(row, f));
  lab.addEventListener("pointerleave", hideTip);
  lab.addEventListener("focus", () => showTip(row, f));
  lab.addEventListener("blur", hideTip);
  lab.tabIndex = 0;

  const lo = toDisp(f.min * (f.dim === "length_mm" ? 1 : 1), f.dim, S.sys);
  const hi = toDisp(f.max, f.dim, S.sys);
  const rng = el("input", { type: "range", class: "rng",
    min: Math.min(lo, hi), max: Math.max(lo, hi),
    step: f.int ? 1 : (Math.abs(hi - lo) / 400), value: clamp(shown, Math.min(lo, hi), Math.max(lo, hi)) });
  let dragging = false;
  rng.addEventListener("pointerdown", () => { dragging = true; pushHistory(); });
  rng.addEventListener("input", () => {
    let v = parseFloat(rng.value);
    let siVal = fromDisp(v, f.dim, S.sys) / scale;
    if (f.int) siVal = Math.round(siVal);
    S.d[f.k] = siVal;
    inp.value = fmtNum(toDisp(siVal * scale, f.dim, S.sys));
    // Coarse mesh while dragging keeps this responsive at 40 blades and high
    // detail; the full-resolution rebuild lands on release.
    renderLive(true);
  });
  const release = () => { if (dragging) { dragging = false; renderAll(); } };
  rng.addEventListener("pointerup", release);
  rng.addEventListener("change", release);

  row.append(lab, inp, el("span", { class: "u" }, unit), rng);
  return row;
}

function fmtNum(v) {
  if (v == null || !isFinite(v)) return "";
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 100) return v.toFixed(1);
  if (a >= 1) return v.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  return v.toPrecision(3);
}

function renderParams() {
  const host = $("#params"); host.textContent = "";
  const issues = validate(S.d);
  const isLiquid = S.d.fluid_kind === "water" ||
    (S.d.fluid_kind === "custom" && !S.d.custom_fluid?.compressible);

  for (const g of GROUPS) {
    const det = el("details", { class: "grp", open: g.open ? "" : null });
    det.append(el("summary", {}, g.name));
    const body = el("div", { class: "fields" });

    if (g.id === "op") body.append(fieldRow(isLiquid ? TARGET_HEAD : TARGET_FIELD, issues));
    for (const f of g.fields) body.append(fieldRow(f, issues));

    if (g.id === "bl") {
      // wrap-angle mode: the spec requires the active mode be visible
      const modeRow = el("div", { class: "row" });
      const sel = el("select", { class: "num" },
        el("option", { value: "derived" }, "Wrap: derived from \u03b2"),
        el("option", { value: "target" }, "Wrap: target value"));
      sel.value = S.d.wrap_mode;
      sel.addEventListener("change", () => { pushHistory(); S.d.wrap_mode = sel.value; renderAll(); });
      modeRow.append(el("label", {}, "Wrap angle"), sel);
      body.append(modeRow);
      if (S.d.wrap_mode === "target")
        body.append(fieldRow({ k: "target_wrap_deg", l: "Target wrap \u03b8", dim: "angle",
          min: 10, max: 320, step: 1,
          tip: "\u03b2\u2081 and \u03b2\u2082 are held exactly at what you typed; only the distribution between them is solved to reach this wrap. If the target cannot be reached it is reported, never quietly clamped." }, issues));

      const lawRow = el("div", { class: "row" });
      const law = el("select", { class: "num" },
        el("option", { value: "parabolic" }, "Parabolic"),
        el("option", { value: "linear" }, "Linear"),
        el("option", { value: "elliptic" }, "Elliptic"));
      law.value = S.d.thickness_law;
      law.addEventListener("change", () => { pushHistory(); S.d.thickness_law = law.value; renderAll(); });
      lawRow.append(el("label", {}, "Thickness law"), law);
      body.append(lawRow);
    }
    det.append(body);
    host.append(det);
  }
}

/* ------------------------------ derived panel ------------------------------ */
function kvRow(host, k, v, dim, cls, places) {
  const disp = dim ? toDisp(v, dim, S.sys) : v;
  host.append(el("div", { class: "k" }, k),
    el("div", { class: "v num" + (cls ? " " + cls : "") },
      v == null ? "\u2014" : (typeof disp === "number" ? fmtSig(disp, places) : disp)),
    el("div", { class: "u" }, dim ? uLabel(dim, S.sys) : ""));
}
const fmtSig = (v, p = 4) => !isFinite(v) ? "\u2014" :
  (Math.abs(v) >= 1e5 ? v.toExponential(2) : Number(v.toPrecision(p)).toString());

function renderDerived(op, fl) {
  const host = $("#derived"); host.textContent = "";
  const [b1h, b1s] = optimalBeta1(S.d, fl);
  kvRow(host, "Blade tip speed U\u2082", op.U2, "speed");
  kvRow(host, "Shaft power", op.power_W / 1000, "power");
  kvRow(host, "Euler work", op.euler_work / 1000, "energy");
  host.append(el("div", { class: "sep" }));
  kvRow(host, "Stage efficiency", op.eta_tt, "ratio", op.eta_tt > .72 ? "ok" : "warn", 3);
  kvRow(host, "Impeller efficiency", op.eta_impeller, "ratio", null, 3);
  kvRow(host, "Slip factor", op.slip, "ratio", null, 3);
  host.append(el("div", { class: "sep" }));
  kvRow(host, "Flow coefficient \u03c6", op.flow_coeff, "ratio", null, 3);
  kvRow(host, "Work coefficient \u03c8", op.work_coeff, "ratio", null, 3);
  kvRow(host, "Specific speed", op.specific_speed, "ratio", null, 3);
  host.append(el("div", { class: "sep" }));
  if (fl.compressible) {
    const m = op.M1_rel;
    kvRow(host, "Inducer tip Mach", m, "ratio", m > 1 ? "hot" : m > 0.9 ? "warn" : "ok", 3);
    const mc = chokeMassFlow(S.d, fl);
    kvRow(host, "Choke mass flow", mc, "massflow");
    if (mc) kvRow(host, "Choke margin", mc / S.d.mdot, "ratio",
      mc / S.d.mdot < 1.05 ? "hot" : mc / S.d.mdot < 1.15 ? "warn" : "ok", 3);
  } else {
    kvRow(host, "NPSH required", op.npsh_required, "head");
    kvRow(host, "NPSH available", op.npsh_available, "head",
      op.cavitating ? "hot" : "ok");
  }
  kvRow(host, "Diffusion ratio w\u2081/w\u2082", op.diffusion_ratio, "ratio",
    op.surge_risk ? "warn" : "ok", 3);
  host.append(el("div", { class: "sep" }));
  const wrapProbe = solveCamber(streamline(S.d, 0, 120), S.d.beta1_hub_deg,
    S.d.beta2_hub_deg, S.d.wrap_mode, S.d.beta_exponent, S.d.target_wrap_deg);
  kvRow(host, `Wrap \u03b8 at hub (${S.d.wrap_mode})`, wrapProbe.wrapDeg, "angle", null, 4);
  kvRow(host, "Zero-incidence \u03b2\u2081 hub", b1h, "angle", null, 3);
  kvRow(host, "Zero-incidence \u03b2\u2081 shroud", b1s, "angle", null, 3);
  kvRow(host, "Preview triangles", V.tris || 0, null);
  return wrapProbe;
}

function renderIssues(op, wrapProbe) {
  const host = $("#issues"); host.textContent = "";
  const list = validate(S.d).map(i => ({ ...i }));
  op.messages.forEach(m => list.push({ level: "warn", field: "model", message: m }));
  if (wrapProbe && !wrapProbe.targetMet)
    list.push({ level: "warn", field: "wrap angle", message: wrapProbe.note });
  if (!list.length) {
    host.append(el("div", { class: "issue ok" }, el("span", { class: "dot" }),
      el("div", {}, "Nothing flagged. Values sit inside normal design ranges.")));
    return;
  }
  for (const i of list)
    host.append(el("div", { class: "issue " + i.level }, el("span", { class: "dot" }),
      el("div", {}, el("b", {}, i.field), " " + i.message)));
}

/* ------------------------------ comparison bar ------------------------------ */
function renderCompare(op, fl) {
  const liquid = !fl.compressible;
  const cur = liquid ? op.head_m : op.pressure_ratio;
  const tgt = liquid ? S.d.target_head_m : S.d.target_pressure_ratio;
  const dim = liquid ? "head" : "ratio";
  $("#cmpLabel").textContent = liquid ? "Head delivered" : "Pressure ratio delivered";
  $("#cmpUnit").textContent = liquid ? " " + uLabel("head", S.sys) : "";
  $("#cmpVal").textContent = cur == null ? "\u2014" : fmtSig(toDisp(cur, dim, S.sys), 4);

  const base = liquid ? 0 : 1;
  const hi = Math.max(tgt * 1.35, (cur ?? 0) * 1.12, base + 1e-6);
  const frac = x => clamp((x - base) / Math.max(hi - base, 1e-9), 0, 1);
  const f = cur == null ? 0 : frac(cur);
  $("#fill").style.width = (f * 100).toFixed(2) + "%";
  $("#targetMark").style.left = (frac(tgt) * 100).toFixed(2) + "%";
  $("#targetMark").dataset.l = "target " + fmtSig(toDisp(tgt, dim, S.sys), 4);

  const rel = cur == null ? null : (cur - base) / Math.max(tgt - base, 1e-9);
  const blocked = op.surge_risk || (op.M1_rel != null && op.M1_rel > 1) || !op.ok;
  let col = "var(--good)";
  if (blocked) col = "var(--bad)";
  else if (rel == null || rel < 0.9 || rel > 1.15) col = "var(--signal)";
  $("#fill").style.background = col;

  const pct = rel == null ? "\u2014" : ((rel - 1) * 100).toFixed(1);
  $("#cmpDelta").textContent = rel == null ? "" :
    (rel >= 1 ? "+" : "") + pct + "% vs target";
  $("#cmpFoot").textContent = !op.ok ? "Model did not converge at this point"
    : op.surge_risk ? "Beyond the estimated surge limit"
    : (op.M1_rel != null && op.M1_rel > 1) ? "Inducer tip is supersonic"
    : "Within estimated operating limits";
}

/* ------------------------------ plots ------------------------------ */
const SVGNS = "http://www.w3.org/2000/svg";
function svg(w, h) {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("viewBox", `0 0 ${w} ${h}`);
  s.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return s;
}
function sEl(t, a) {
  const n = document.createElementNS(SVGNS, t);
  for (const [k, v] of Object.entries(a)) n.setAttribute(k, v);
  return n;
}
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

function plotMeridional() {
  const W = 560, H = 300, PAD = 40;
  const d = S.d, s = svg(W, H);
  const hub = streamline(d, 0, 160), shr = streamline(d, 1, 160);
  const xs = [...hub.z, ...shr.z], ys = [...hub.r, ...shr.r];
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = 0, y1 = Math.max(...ys) * 1.06;
  const sc = Math.min((W - 2 * PAD) / Math.max(x1 - x0, 1e-9), (H - 2 * PAD) / Math.max(y1 - y0, 1e-9));
  const X = v => PAD + (v - x0) * sc, Y = v => H - PAD - (v - y0) * sc;
  const path = st => st.z.reduce((a, z, i) => a + (i ? "L" : "M") + X(z).toFixed(1) + " " + Y(st.r[i]).toFixed(1), "");

  s.append(sEl("rect", { x: 0, y: 0, width: W, height: H, fill: "transparent" }));
  for (let i = 1; i < 4; i++) {
    const st = streamline(d, i / 4, 160);
    s.append(sEl("path", { d: path(st), fill: "none", stroke: css("--line"), "stroke-width": 1 }));
  }
  s.append(sEl("path", { d: path(hub), fill: "none", stroke: "#a98a5c", "stroke-width": 2.4 }));
  s.append(sEl("path", { d: path(shr), fill: "none", stroke: "#4d7fb3", "stroke-width": 2.4 }));
  const dash = (a, b, c, e) => s.append(sEl("line", { x1: X(a), y1: Y(b), x2: X(c), y2: Y(e),
    stroke: css("--dim"), "stroke-width": 1.2, "stroke-dasharray": "4 3" }));
  dash(hub.z[0], hub.r[0], shr.z[0], shr.r[0]);
  const n = 159; dash(hub.z[n], hub.r[n], shr.z[n], shr.r[n]);
  const lab = (x, y, t, anchor = "start", fill = css("--dim")) =>
    s.append(Object.assign(sEl("text", { x, y, fill, "font-size": 11, "text-anchor": anchor }),
      { textContent: t }));
  lab(X(shr.z[40]), Y(shr.r[40]) - 7, "shroud", "middle", "#4d7fb3");
  lab(X(hub.z[40]), Y(hub.r[40]) + 15, "hub", "middle", "#a98a5c");
  lab(PAD, H - 12, `axial (${uLabel("length_mm", S.sys)})`);
  lab(PAD - 8, PAD - 12, `radius (${uLabel("length_mm", S.sys)})`, "start");
  // scale ticks
  for (const frac of [0, .5, 1]) {
    const zv = x0 + (x1 - x0) * frac, rv = y0 + (y1 - y0) * frac;
    lab(X(zv), H - PAD + 14, fmtSig(toDisp(zv * 1000, "length_mm", S.sys), 3), "middle", css("--faint"));
    lab(PAD - 6, Y(rv) + 4, fmtSig(toDisp(rv * 1000, "length_mm", S.sys), 3), "end", css("--faint"));
  }
  return { node: s, note: "Hub and shroud contours with three intermediate streamlines. Dashed lines mark the inlet and exit planes." };
}

function plotMap(fl) {
  const W = 560, H = 300, L = 54, R = 16, T = 14, B = 38;
  const m = generateMap(S.d, fl);
  S.lastMap = m;
  const s = svg(W, H);
  if (!m.lines.length) {
    const t = sEl("text", { x: W / 2, y: H / 2, fill: css("--dim"), "font-size": 13, "text-anchor": "middle" });
    t.textContent = "No converged operating points at this geometry.";
    s.append(t);
    return { node: s, note: "Adjust the geometry or duty until the model converges." };
  }
  const all = m.lines.flatMap(l => l.pts);
  const xs = all.map(p => p.x), ys = all.map(p => p.y);
  const x0 = Math.min(...xs, m.design.x) * .96, x1 = Math.max(...xs, m.design.x) * 1.04;
  const y0 = Math.min(...ys, m.design.y) * .97, y1 = Math.max(...ys, m.design.y) * 1.03;
  const X = v => L + (v - x0) / (x1 - x0) * (W - L - R);
  const Y = v => H - B - (v - y0) / (y1 - y0) * (H - T - B);

  s.append(sEl("rect", { x: L, y: T, width: W - L - R, height: H - T - B,
    fill: "none", stroke: css("--line-soft") }));
  for (let i = 0; i <= 4; i++) {
    const yv = y0 + (y1 - y0) * i / 4, xv = x0 + (x1 - x0) * i / 4;
    s.append(sEl("line", { x1: L, y1: Y(yv), x2: W - R, y2: Y(yv), stroke: css("--line-soft") }));
    const ty = sEl("text", { x: L - 7, y: Y(yv) + 4, fill: css("--faint"), "font-size": 10, "text-anchor": "end" });
    ty.textContent = fmtSig(yv, 3); s.append(ty);
    const tx = sEl("text", { x: X(xv), y: H - B + 14, fill: css("--faint"), "font-size": 10, "text-anchor": "middle" });
    tx.textContent = fmtSig(xv, 3); s.append(tx);
  }
  m.lines.forEach((ln, i) => {
    const t = i / Math.max(m.lines.length - 1, 1);
    const c = `rgb(${ramp(t).map(v => Math.round(v * 255)).join(",")})`;
    const dpath = ln.pts.reduce((a, p, j) => a + (j ? "L" : "M") + X(p.x).toFixed(1) + " " + Y(p.y).toFixed(1), "");
    s.append(sEl("path", { d: dpath, fill: "none", stroke: c, "stroke-width": 1.8 }));
    const last = ln.pts[ln.pts.length - 1];
    const tt = sEl("text", { x: X(last.x) + 4, y: Y(last.y) + 3, fill: c, "font-size": 9.5 });
    tt.textContent = (ln.sf * 100).toFixed(0) + "%"; s.append(tt);
  });
  const poly = (pts, stroke, dash) => {
    if (pts.length < 2) return;
    const sorted = [...pts].sort((a, b) => a[0] - b[0]);
    s.append(sEl("path", { d: sorted.reduce((a, p, j) => a + (j ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1), ""),
      fill: "none", stroke, "stroke-width": 1.5, "stroke-dasharray": dash }));
  };
  poly(m.surge, "#b5342a", "5 4");
  poly(m.choke, css("--dim"), "2 3");
  s.append(sEl("circle", { cx: X(m.design.x), cy: Y(m.design.y), r: 5.5,
    fill: css("--signal"), stroke: css("--text"), "stroke-width": 1.2 }));
  const yl = sEl("text", { x: 12, y: H / 2, fill: css("--dim"), "font-size": 11,
    transform: `rotate(-90 12 ${H / 2})`, "text-anchor": "middle" });
  yl.textContent = m.yLabel; s.append(yl);
  const xl = sEl("text", { x: (L + W - R) / 2, y: H - 6, fill: css("--dim"), "font-size": 11, "text-anchor": "middle" });
  xl.textContent = "Corrected mass flow (kg/s)"; s.append(xl);
  return { node: s, note: "Speed lines from 60% to 110% of design. The dashed red line is an estimated surge limit and the dotted line an estimated choke limit \u2014 both come from simple correlations, not CFD or test data. The amber dot is the current design point." };
}

function plotBeta() {
  const W = 560, H = 300, L = 52, R = 14, T = 14, B = 40;
  const d = S.d, s = svg(W, H);
  const spans = [0, .5, 1];
  const series = spans.map(sp => {
    const st = streamline(d, sp, 140);
    const b1 = d.beta1_hub_deg + sp * (d.beta1_shroud_deg - d.beta1_hub_deg);
    const b2 = d.beta2_hub_deg + sp * (d.beta2_shroud_deg - d.beta2_hub_deg);
    const cam = solveCamber(st, b1, b2, d.wrap_mode, d.beta_exponent, d.target_wrap_deg);
    return { sp, st, cam };
  });
  const yAll = series.flatMap(x => [...x.cam.beta].map(deg));
  const y0 = Math.min(...yAll) - 3, y1 = Math.max(...yAll) + 3;
  const X = v => L + v * (W - L - R), Y = v => H - B - (v - y0) / (y1 - y0) * (H - T - B);
  s.append(sEl("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "none", stroke: css("--line-soft") }));
  for (let i = 0; i <= 4; i++) {
    const yv = y0 + (y1 - y0) * i / 4;
    s.append(sEl("line", { x1: L, y1: Y(yv), x2: W - R, y2: Y(yv), stroke: css("--line-soft") }));
    const t = sEl("text", { x: L - 7, y: Y(yv) + 4, fill: css("--faint"), "font-size": 10, "text-anchor": "end" });
    t.textContent = yv.toFixed(0) + "\u00b0"; s.append(t);
  }
  const cols = ["#a98a5c", "#6f9b6a", "#4d7fb3"];
  series.forEach((x, i) => {
    const n = x.cam.beta.length;
    const dpath = [...x.cam.beta].reduce((a, b, j) =>
      a + (j ? "L" : "M") + X(j / (n - 1)).toFixed(1) + " " + Y(deg(b)).toFixed(1), "");
    s.append(sEl("path", { d: dpath, fill: "none", stroke: cols[i], "stroke-width": 2.2 }));
    const t = sEl("text", { x: W - R - 4, y: Y(deg(x.cam.beta[n - 1])) - 5, fill: cols[i],
      "font-size": 10, "text-anchor": "end" });
    t.textContent = ["hub", "mid-span", "shroud"][i] + ` \u00b7 wrap ${x.cam.wrapDeg.toFixed(0)}\u00b0`;
    s.append(t);
  });
  const xl = sEl("text", { x: (L + W - R) / 2, y: H - 8, fill: css("--dim"), "font-size": 11, "text-anchor": "middle" });
  xl.textContent = "fraction along the blade path (leading edge \u2192 trailing edge)"; s.append(xl);
  const yl = sEl("text", { x: 12, y: H / 2, fill: css("--dim"), "font-size": 11,
    transform: `rotate(-90 12 ${H / 2})`, "text-anchor": "middle" });
  yl.textContent = "blade angle \u03b2"; s.append(yl);
  const note = d.wrap_mode === "target"
    ? "Wrap angle is a target: the endpoints you typed are held exactly and only the curve between them is solved. " + series[0].cam.note
    : "Wrap angle is derived: it is the integral of tan\u03b2/r along the blade, so it follows from these curves rather than being set independently.";
  return { node: s, note };
}

function plotCompare() {
  const W = 560, H = 300, PAD = 40;
  const s = svg(W, H);
  const picks = S.cmpSel.map(i => S.snaps[i]).filter(Boolean);
  if (picks.length !== 2) {
    const t = sEl("text", { x: W / 2, y: H / 2 - 6, fill: css("--dim"),
      "font-size": 13, "text-anchor": "middle" });
    t.textContent = "Tick two snapshots to compare them.";
    const t2 = sEl("text", { x: W / 2, y: H / 2 + 14, fill: css("--faint"),
      "font-size": 11, "text-anchor": "middle" });
    t2.textContent = S.snaps.length < 2
      ? "Save at least two with the Save snapshot button."
      : `${S.cmpSel.length} of 2 selected.`;
    s.append(t, t2);
    return { node: s, note: "Overlays the two meridional profiles and lists every parameter that differs." };
  }
  const [A, B] = picks;
  const cols = ["#4d7fb3", "#c77700"];
  const sets = [A, B].map(x => ({ hub: streamline(x.d, 0, 160), shr: streamline(x.d, 1, 160) }));
  const xs = sets.flatMap(o => [...o.hub.z, ...o.shr.z]);
  const ys = sets.flatMap(o => [...o.hub.r, ...o.shr.r]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = 0, y1 = Math.max(...ys) * 1.06;
  const sc = Math.min((W - 2 * PAD) / Math.max(x1 - x0, 1e-9), (H - 2 * PAD) / Math.max(y1 - y0, 1e-9));
  const X = v => PAD + (v - x0) * sc, Y = v => H - PAD - (v - y0) * sc;
  const path = st => st.z.reduce((a, z, i) => a + (i ? "L" : "M") + X(z).toFixed(1) + " " + Y(st.r[i]).toFixed(1), "");
  sets.forEach((o, i) => {
    s.append(sEl("path", { d: path(o.hub), fill: "none", stroke: cols[i], "stroke-width": 2.2 }));
    s.append(sEl("path", { d: path(o.shr), fill: "none", stroke: cols[i],
      "stroke-width": 2.2, "stroke-dasharray": "6 3" }));
  });
  [A, B].forEach((x, i) => {
    const t = sEl("text", { x: PAD, y: PAD + 2 + i * 15, fill: cols[i], "font-size": 11 });
    t.textContent = x.name; s.append(t);
  });
  const lg = sEl("text", { x: W - 12, y: H - 14, fill: css("--faint"), "font-size": 10, "text-anchor": "end" });
  lg.textContent = "solid = hub, dashed = shroud"; s.append(lg);
  return { node: s, note: null, diff: buildDiff(A, B) };
}

function buildDiff(A, B) {
  const keys = [...new Set([...Object.keys(A.d), ...Object.keys(B.d)])].sort();
  const rows = [];
  for (const k of keys) {
    const a = A.d[k], b = B.d[k];
    if (typeof a === "number" && typeof b === "number") {
      if (Math.abs(a - b) <= 1e-12 * Math.max(1, Math.abs(a))) continue;
      const f = FIELD_INDEX[k];
      const sc2 = f?.scale || 1, dim = f?.dim || "ratio";
      rows.push({ label: f?.l || k, dim,
        a: toDisp(a * sc2, dim, S.sys), b: toDisp(b * sc2, dim, S.sys),
        pct: a === 0 ? null : (b - a) / Math.abs(a) * 100 });
    } else if (a !== b && (typeof a === "string" || typeof b === "string")) {
      rows.push({ label: FIELD_INDEX[k]?.l || k, dim: null, a, b, pct: null });
    }
  }
  const tab = el("table", { class: "difftab" });
  const head = el("tr", {}, el("th", {}, "Parameter"), el("th", {}, A.name),
    el("th", {}, B.name), el("th", {}, "change"));
  head.children[1].style.textAlign = "right"; head.children[2].style.textAlign = "right";
  head.children[3].style.textAlign = "right";
  tab.append(head);
  if (!rows.length)
    tab.append(el("tr", {}, el("td", { colspan: 4, style: "color:var(--dim)" },
      "These two designs are identical.")));
  for (const r of rows) {
    const unit = r.dim ? " " + uLabel(r.dim, S.sys) : "";
    tab.append(el("tr", {},
      el("td", {}, r.label),
      el("td", { class: "n" }, (typeof r.a === "number" ? fmtSig(r.a, 4) : String(r.a)) + unit),
      el("td", { class: "n" }, (typeof r.b === "number" ? fmtSig(r.b, 4) : String(r.b)) + unit),
      el("td", { class: "d " + (r.pct == null ? "" : r.pct >= 0 ? "up" : "dn") },
        r.pct == null ? "\u2014" : (r.pct >= 0 ? "+" : "") + r.pct.toFixed(1) + "%")));
  }
  return tab;
}

function renderPlot(fl) {
  const host = $("#plot"); host.textContent = "";
  const r = S.tab === "map" ? plotMap(fl)
          : S.tab === "beta" ? plotBeta()
          : S.tab === "compare" ? plotCompare()
          : plotMeridional();
  host.append(r.node);
  if (r.diff) host.append(r.diff);
  if (r.note) host.append(el("div", { class: "note" }, r.note));
}

/* ------------------------------ snapshots ------------------------------ */
function renderSnaps() {
  const host = $("#snaps"); host.textContent = "";
  if (!S.snaps.length) {
    host.append(el("div", { class: "empty" }, "No snapshots yet. Save one to compare design iterations."));
    return;
  }
  const wrap = el("div", { class: "snaps" });
  S.snaps.forEach((sn, i) => {
    const name = el("span", { class: "name", contenteditable: "true",
      spellcheck: "false", title: "Click to rename" }, sn.name);
    name.addEventListener("blur", () => { sn.name = name.textContent.trim() || sn.name; });
    name.addEventListener("keydown", ev => {
      if (ev.key === "Enter") { ev.preventDefault(); name.blur(); }
    });
    const box = el("input", { type: "checkbox", title: "Select for comparison" });
    box.checked = S.cmpSel.includes(i);
    box.addEventListener("change", () => {
      if (box.checked) { S.cmpSel.push(i); if (S.cmpSel.length > 2) S.cmpSel.shift(); }
      else S.cmpSel = S.cmpSel.filter(x => x !== i);
      renderSnaps();
      if (S.tab === "compare") renderPlot(makeFluid(S.d));
    });
    const chip = el("div", { class: "snap" + (box.checked ? " sel" : "") }, box,
      el("button", { class: "restore", title: "Restore this design",
        onclick: () => { pushHistory(); S.d = clone(sn.d); renderAll(true); } }, "\u21a9"),
      name,
      el("button", { title: "Delete", onclick: () => {
        S.snaps.splice(i, 1);
        S.cmpSel = S.cmpSel.filter(x => x !== i).map(x => x > i ? x - 1 : x);
        renderSnaps(); if (S.tab === "compare") renderPlot(makeFluid(S.d));
      } }, "\u00d7"));
    wrap.append(chip);
  });
  host.append(wrap);
  $("#cmpHint").textContent = S.snaps.length >= 2
    ? `${S.cmpSel.length}/2 to compare` : "";
}

/* ------------------------------ export ------------------------------ */
const HELPER_BASE = (location.protocol === "http:" || location.protocol === "https:")
  ? `${location.protocol}//${location.hostname}:${location.port || "8765"}`
  : "http://127.0.0.1:8765";

function download(name, data, mime) {
  const blob = data instanceof Blob ? data : new Blob([data], { type: mime || "text/plain" });
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

function projectPayload() {
  return {
    format: "bladeform-project", version: 1,
    saved: new Date().toISOString(),
    design: S.d,
    snapshots: S.snaps.map(s => ({ name: s.name, design: s.d })),
  };
}

function designName() {
  const inp = $("#exportName");
  return (inp && inp.value ? inp.value : "").trim();
}

function requireDesignName() {
  const name = designName();
  if (!name) {
    setExportStatus("Enter a design name before saving a project or exporting STEP.", true);
    const inp = $("#exportName");
    if (inp) inp.focus();
    return null;
  }
  return name;
}

function setExportStatus(msg, isError) {
  const box = $("#exportStatus");
  if (!box) return;
  box.style.display = msg ? "block" : "none";
  box.textContent = msg || "";
  box.style.borderColor = isError ? "var(--bad)" : "var(--line)";
  box.style.color = isError ? "var(--bad)" : "var(--dim)";
}

async function helperPing() {
  try {
    const r = await fetch(`${HELPER_BASE}/api/ping`, { method: "GET", cache: "no-store" });
    if (!r.ok) return false;
    const j = await r.json();
    return !!(j && j.ok && j.helper);
  } catch {
    return false;
  }
}

async function helperPost(path, body) {
  const r = await fetch(`${HELPER_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let j = null;
  try { j = await r.json(); } catch { j = { ok: false, message: `HTTP ${r.status}` }; }
  j._http = r.status;
  return j;
}

function exportStl() {
  const d = S.d, nSpan = [5, 9, 14][S.lod], nStream = [22, 40, 64][S.lod], nTheta = [40, 72, 120][S.lod];
  const tris = [];
  const addGrid = g => {
    const pos = g.attributes.position.array, idx = g.index.array;
    for (let i = 0; i < idx.length; i += 3) {
      const t = [0, 1, 2].map(k => {
        const b = idx[i + k] * 3; return [pos[b], pos[b + 1], pos[b + 2]];
      });
      tris.push(t);
    }
  };
  const perPassage = d.n_main ? Math.floor(d.n_splitter / d.n_main) : 0;
  for (let k = 0; k < d.n_main; k++) {
    const th0 = TAU * k / Math.max(d.n_main, 1);
    const mb = buildBlade(d, nSpan, nStream, th0, 0);
    addGrid(bladeGeometry(mb.P, mb.S, null, false, [0, 1]));
    for (let s2 = 0; s2 < perPassage; s2++) {
      const f = (s2 + 1) / (perPassage + 1);
      const sb = buildBlade(d, nSpan, nStream, th0 + TAU * f / d.n_main, d.splitter_start_frac);
      addGrid(bladeGeometry(sb.P, sb.S, null, false, [0, 1]));
    }
  }
  addGrid(hubGeometry(d, nStream, nTheta));

  const buf = new ArrayBuffer(84 + tris.length * 50);
  const dv = new DataView(buf);
  const header = "BladeForm STL - preview tessellation, not a CAD solid";
  for (let i = 0; i < 80; i++) dv.setUint8(i, i < header.length ? header.charCodeAt(i) : 0);
  dv.setUint32(80, tris.length, true);
  let o = 84;
  for (const t of tris) {
    const u = t[1].map((v, i) => v - t[0][i]), v2 = t[2].map((v, i) => v - t[0][i]);
    let n = [u[1] * v2[2] - u[2] * v2[1], u[2] * v2[0] - u[0] * v2[2], u[0] * v2[1] - u[1] * v2[0]];
    const L2 = Math.hypot(...n) || 1; n = n.map(x => x / L2);
    n.forEach(x => { dv.setFloat32(o, x, true); o += 4; });
    t.forEach(p => p.forEach(x => { dv.setFloat32(o, x, true); o += 4; }));
    dv.setUint16(o, 0, true); o += 2;
  }
  download(`${S.key}_lod${S.lod}.stl`, new Blob([buf], { type: "model/stl" }));
}

/** Browser-only fallback download of the project JSON. */
function exportProjectDownload(name) {
  const n = name || S.key || "design";
  download(`${n}.bfproj`, JSON.stringify(projectPayload(), null, 2), "application/json");
}

async function exportProjectViaHelper(overwrite) {
  const name = requireDesignName();
  if (!name) return;
  setExportStatus("Saving project…", false);
  const alive = await helperPing();
  if (!alive) {
    setExportStatus("Helper not running — downloading project file in the browser instead.", false);
    exportProjectDownload(name);
    pushRecent(name);
    return;
  }
  const body = { ...projectPayload(), name, overwrite: !!overwrite };
  const res = await helperPost("/api/save-project", body);
  if (res.exists && !overwrite) {
    if (confirm(`Project "${name}.bfproj" already exists in the projects folder.\nOverwrite it?`)) {
      return exportProjectViaHelper(true);
    }
    setExportStatus("Save cancelled — existing project kept.", false);
    return;
  }
  if (!res.ok) {
    setExportStatus(res.message || "Failed to save project.", true);
    return;
  }
  setExportStatus(res.message || `Saved projects/${name}.bfproj`, false);
  pushRecent(name);
}

async function exportStepViaHelper(overwrite) {
  const name = requireDesignName();
  if (!name) return;
  setExportStatus("Exporting STEP (OpenCASCADE)… this can take a while.", false);
  const alive = await helperPing();
  if (!alive) {
    setExportStatus(
      "Local helper is not running. Start BladeForm with start_bladeform.bat so the helper can build STEP files.",
      true);
    return;
  }
  const body = { ...projectPayload(), name, overwrite: !!overwrite };
  let res;
  try {
    res = await helperPost("/api/export-step", body);
  } catch (e) {
    setExportStatus("STEP request failed: " + (e && e.message ? e.message : e), true);
    return;
  }
  if (res.exists && !overwrite) {
    if (confirm(`STEP file "${name}.step" already exists in the steps folder.\nOverwrite it?`)) {
      return exportStepViaHelper(true);
    }
    setExportStatus("STEP export cancelled — existing file kept.", false);
    return;
  }
  if (!res.ok) {
    let msg = res.message || "STEP export failed.";
    if (res.temp_bfproj) msg += ` Temp project kept at ${res.temp_bfproj}.`;
    setExportStatus(msg, true);
    return;
  }
  setExportStatus(res.message || `Wrote steps/${name}.step`, false);
}

function exportCsv(fl) {
  const m = S.lastMap || generateMap(S.d, fl);
  download(`${S.key}_map.csv`, mapToCsv(m), "text/csv");
}

function downloadPlotSvg() {
  const node = $("#plot svg");
  if (!node) return;
  const c = node.cloneNode(true);
  c.setAttribute("xmlns", SVGNS);
  c.setAttribute("style", "background:" + css("--panel"));
  download(`${S.key}_${S.tab}.svg`,
    '<?xml version="1.0" encoding="UTF-8"?>\n' + c.outerHTML, "image/svg+xml");
}

/* ------------------------------ session ------------------------------ */
let autosaveTimer = null;
function autosave() {
  clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(() => {
    store.set(SESSION_KEY, { key: S.key, design: S.d, snaps: S.snaps,
                             sys: S.sys, at: Date.now() });
  }, 700);
}

function pushRecent(name) {
  const list = (store.get(RECENT_KEY) || []).filter(r => r.name !== name);
  list.unshift({ name, at: Date.now(), key: S.key, design: clone(S.d) });
  store.set(RECENT_KEY, list.slice(0, 8));
  renderRecents();
}

function renderRecents() {
  const host = $("#recents"); host.textContent = "";
  const list = store.get(RECENT_KEY) || [];
  if (!list.length) {
    host.append(el("div", { class: "empty" },
      "Designs you open or export appear here, on this browser only."));
    return;
  }
  const wrap = el("div", { class: "snaps" });
  list.forEach(r => wrap.append(el("div", { class: "snap" },
    el("span", { class: "name", style: "cursor:pointer",
      title: new Date(r.at).toLocaleString(),
      onclick: () => { pushHistory(); S.key = r.key || S.key; S.d = clone(r.design); renderAll(true, true); } },
      r.name))));
  host.append(wrap);
}

function openProjectFile(file) {
  const fr = new FileReader();
  fr.onload = () => {
    let p;
    try { p = JSON.parse(fr.result); }
    catch { return flashOpenError("That file is not valid JSON."); }
    if (p.format !== "bladeform-project")
      return flashOpenError("That is not a BladeForm project file.");
    if ((p.version || 0) > 1)
      return flashOpenError(`Project version ${p.version} is newer than this build understands.`);
    if (!p.design || typeof p.design.r2 !== "number")
      return flashOpenError("The project file has no usable design in it.");
    pushHistory();
    S.d = { ...clone(REF[S.key].params), ...clone(p.design) };   // fill any missing keys
    S.snaps = (p.snapshots || []).map(sn => ({ name: sn.name || "snapshot", d: clone(sn.design || sn.d) }));
    S.cmpSel = [];
    renderAll(true, true); renderSnaps();
    pushRecent(file.name.replace(/\.[^.]+$/, ""));
  };
  fr.onerror = () => flashOpenError("The file could not be read.");
  fr.readAsText(file);
}

function flashOpenError(msg) {
  const host = $("#issues");
  host.prepend(el("div", { class: "issue error" }, el("span", { class: "dot" }),
    el("div", {}, el("b", {}, "open"), " " + msg)));
}

/* ------------------------------ render ------------------------------ */
let liveTimer = null;
function renderLive(quick) {
  rebuildScene(quick);
  const fl = makeFluid(S.d);
  let op;
  try { op = evaluate(S.d, fl); }
  catch (e) { op = { ok: false, messages: [String(e.message || e)], losses: {} }; }
  renderCompare(op, fl);
  const wrapProbe = renderDerived(op, fl);
  renderIssues(op, wrapProbe);
}

function renderAll(rebuildParams, refit) {
  const fl = makeFluid(S.d);
  let op;
  try { op = evaluate(S.d, fl); }
  catch (e) {
    op = { ok: false, messages: ["Solver error: " + (e.message || e)], losses: {},
           U2: 0, euler_work: 0, eta_tt: 0, eta_impeller: 0, slip: 0,
           flow_coeff: 0, work_coeff: 0, specific_speed: 0, diffusion_ratio: 0,
           power_W: 0, pressure_ratio: null, head_m: null, M1_rel: null };
  }
  rebuildScene(false);
  $("#tglDiff").setAttribute("aria-pressed", String(!!S.d.diffuser_on));
  $("#tglVol").setAttribute("aria-pressed", String(!!S.d.volute_on));
  if (refit) fitView();
  renderCompare(op, fl);
  const wrapProbe = renderDerived(op, fl);
  renderIssues(op, wrapProbe);
  if (rebuildParams !== false) renderParams();
  renderPlot(fl);
  autosave();
}

/* ------------------------------ wiring ------------------------------ */
function wire() {
  const psel = $("#preset");
  const NAMES = { baseline_compressor: "Baseline compressor", turbocharger: "Turbocharger",
                  pump: "Centrifugal pump", mixed_flow_fan: "Mixed-flow fan" };
  for (const k of Object.keys(REF)) psel.append(el("option", { value: k }, NAMES[k] || k));
  psel.value = S.key;
  psel.addEventListener("change", () => loadPreset(psel.value));
  $("#resetPreset").addEventListener("click", () => loadPreset(S.key));

  $("#fluid").addEventListener("change", e => {
    pushHistory();
    const v = e.target.value;
    S.d.fluid_kind = v;
    if (v === "custom" && !S.d.custom_fluid?.gasConstant) {
      S.d.custom_fluid = { compressible: true, density: 1.2, viscosity: 1.8e-5,
                           gamma: 1.4, gasConstant: 287.05, vapourPressure: 2339 };
    }
    if (v === "water") { S.d.p01 = Math.max(S.d.p01, 150000); S.d.T01 = 293.15; }
    renderAll();
  });

  $$("#units button").forEach(b => b.addEventListener("click", () => {
    S.sys = b.dataset.u;
    $$("#units button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    renderAll();     // every displayed and exported number is re-converted
  }));

  $$("#shade button").forEach(b => b.addEventListener("click", () => {
    S.shade = b.dataset.s;
    $$("#shade button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    rebuildScene(false);
  }));

  $("#tglDiff").addEventListener("click", e => {
    pushHistory(); S.d.diffuser_on = !S.d.diffuser_on;
    e.currentTarget.setAttribute("aria-pressed", String(S.d.diffuser_on));
    renderAll();
  });
  $("#tglVol").addEventListener("click", e => {
    pushHistory(); S.d.volute_on = !S.d.volute_on;
    e.currentTarget.setAttribute("aria-pressed", String(S.d.volute_on));
    renderAll();
  });
  $("#colSurf").addEventListener("input", e => { S.surfCol = e.target.value; rebuildScene(false); });
  $("#colBg").addEventListener("input", e => {
    S.bgCol = e.target.value;
    $("#viewport").style.background = e.target.value;
  });
  $("#fit").addEventListener("click", fitView);

  $$("#tabs button").forEach(b => b.addEventListener("click", () => {
    S.tab = b.dataset.t;
    $$("#tabs button").forEach(x => x.setAttribute("aria-selected", String(x === b)));
    renderPlot(makeFluid(S.d));
  }));
  $("#dlPlot").addEventListener("click", downloadPlotSvg);

  $("#undo").addEventListener("click", undo);
  $("#redo").addEventListener("click", redo);
  $("#snap").addEventListener("click", () => {
    // No prompt() here: it is blocked in a sandboxed frame. The chip name is
    // editable in place instead.
    S.snaps.push({ name: `${NAMES[S.key] || S.key} ${S.snaps.length + 1}`, d: clone(S.d) });
    renderSnaps();
    const last = $("#snaps .snap:last-child .name");
    if (last) { last.focus();
      const r = document.createRange(); r.selectNodeContents(last);
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); }
  });
  $("#clearSnaps").addEventListener("click", () => {
    S.snaps.length = 0; S.cmpSel = [];
    renderSnaps(); if (S.tab === "compare") renderPlot(makeFluid(S.d));
  });

  $("#openBtn").addEventListener("click", () => $("#openFile").click());
  $("#openFile").addEventListener("change", e => {
    const f = e.target.files?.[0];
    if (f) openProjectFile(f);
    e.target.value = "";
  });

  // <dialog> support varies: a sandboxed frame can refuse modals, and older
  // engines lack the element entirely. Degrade to a plainly-positioned panel
  // rather than leaving the Export button dead.
  const openDlg = () => {
    const dlg = $("#exportDlg");
    try { dlg.showModal(); return; } catch {}
    try { dlg.show(); return; } catch {}
    dlg.setAttribute("open", "");
    Object.assign(dlg.style, { display: "block", position: "fixed", zIndex: 50,
      top: "50%", left: "50%", transform: "translate(-50%,-50%)" });
  };
  const closeDlg = () => {
    const dlg = $("#exportDlg");
    try { dlg.close(); } catch {}
    dlg.removeAttribute("open"); dlg.style.display = "";
  };
  $("#exportBtn").addEventListener("click", () => {
    const inp = $("#exportName");
    if (inp && !inp.value) {
      // Prefer the design's own name, then the preset key.
      const n = (S.d && S.d.name) ? String(S.d.name).replace(/\s+/g, "_") : S.key;
      inp.value = n || "";
    }
    setExportStatus("", false);
    openDlg();
  });
  $("#closeDlg").addEventListener("click", closeDlg);
  $$("#exportDlg [data-x]").forEach(b => b.addEventListener("click", () => {
    const fl = makeFluid(S.d);
    if (b.dataset.x === "stl") exportStl();
    if (b.dataset.x === "proj") exportProjectViaHelper(false);
    if (b.dataset.x === "csv") exportCsv(fl);
    if (b.dataset.x === "step") exportStepViaHelper(false);
  }));
  $("#stepNote").textContent =
    "Project and STEP exports need the local helper (start_bladeform.bat). " +
    "The helper binds to 127.0.0.1 only, saves projects/*.bfproj and steps/*.step, " +
    "and verifies STEP size, curved surfaces and solid count before keeping the file. " +
    "Mesh and performance-map downloads still work entirely in the browser. " +
    "The hub fillet is a blend modelled into the blade surface, not a kernel fillet — see STATUS.md.";

  addEventListener("keydown", e => {
    if (!(e.ctrlKey || e.metaKey)) return;
    if (e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  });
}

/* ------------------------------ boot ------------------------------ */
function boot() {
  const r = selfTest();
  const badge = $("#selftest");
  badge.className = r.pass ? "pass" : "fail";
  badge.textContent = r.pass
    ? `engine verified \u00b7 ${r.worst.toExponential(0)} vs Python`
    : `engine mismatch \u00b7 ${r.total} value${r.total === 1 ? "" : "s"}`;
  badge.title = r.pass
    ? `This browser engine is a port of the Python engine. Every quantity it computes was re-checked against reference values from Python: worst relative difference ${r.worst.toExponential(2)}.`
    : "The browser engine disagrees with the Python reference:\n" + r.failures.join("\n");

  initViewer();
  wire();

  const sess = store.get(SESSION_KEY);
  if (sess?.design && typeof sess.design.r2 === "number") {
    S.key = sess.key in REF ? sess.key : "turbocharger";
    S.d = { ...clone(REF[S.key].params), ...clone(sess.design) };
    S.snaps = (sess.snaps || []).map(x => ({ name: x.name, d: clone(x.d) }));
    S.sys = sess.sys === "Imperial" ? "Imperial" : "SI";
    $("#preset").value = S.key;
    $("#fluid").value = S.d.fluid_kind;
    $$("#units button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.u === S.sys)));
    syncHistoryButtons();
    renderAll(true, true);
  } else {
    loadPreset("turbocharger");
  }
  renderSnaps();
  renderRecents();
  fitView();
}

if (document.readyState === "loading") addEventListener("DOMContentLoaded", boot);
else boot();
