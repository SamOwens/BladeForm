/* =========================================================================
   BladeForm browser engine.

   This is a PORT of the Python engine (bladeform/*.py), not a second design.
   The spec's own architecture calls for it: the viewer needs a fast preview
   mesh, and the CAD kernel is reserved for export. That means the same physics
   exists twice, which is a real risk of silent divergence.

   So it is checked rather than assumed: REF below holds values computed by the
   Python engine, and selfTest() re-computes all of them here and reports the
   worst relative error in the header. If the two implementations drift, the
   badge turns red and says which quantity moved.
   ========================================================================= */
const G = 9.80665, PI = Math.PI, TAU = 2 * Math.PI;
const REF = /*REF_JSON*/{};
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
const rad = d => d * PI / 180, deg = r => r * 180 / PI;
const hypot = Math.hypot;

/* ---------------------------------------------------------------- units */
const UNITS = {
  length_mm:  ["mm", "in", 1 / 25.4, 0],
  length_m:   ["m", "ft", 3.280839895, 0],
  pressure:   ["kPa", "psi", 0.1450377377, 0],
  pressure_pa:["Pa", "psi", 1.450377e-4, 0],
  temperature:["K", "\u00b0F", 1.8, -459.67],
  massflow:   ["kg/s", "lbm/s", 2.204622622, 0],
  volflow:    ["m\u00b3/s", "gpm", 15850.32314, 0],
  power:      ["kW", "hp", 1.34102209, 0],
  speed:      ["m/s", "ft/s", 3.280839895, 0],
  density:    ["kg/m\u00b3", "lbm/ft\u00b3", 0.06242796, 0],
  head:       ["m", "ft", 3.280839895, 0],
  energy:     ["kJ/kg", "Btu/lbm", 0.429922614, 0],
  rpm:        ["rpm", "rpm", 1, 0],
  angle:      ["\u00b0", "\u00b0", 1, 0],
  ratio:      ["", "", 1, 0],
};
const uLabel = (dim, sys) => UNITS[dim][sys === "SI" ? 0 : 1];
const toDisp = (v, dim, sys) => v == null ? null :
  (sys === "Imperial" ? v * UNITS[dim][2] + UNITS[dim][3] : v);
const fromDisp = (v, dim, sys) => v == null ? null :
  (sys === "Imperial" ? (v - UNITS[dim][3]) / UNITS[dim][2] : v);

/* --------------------------------------------------------------- fluids */
class IncompressibleProperty extends Error {}

function airFluid() {
  return {
    name: "Air", compressible: true, R: 287.05,
    cp(T) { return 1002.5 + 1e-4 * Math.pow(T - 273.15, 2) * 0.275; },
    gamma(T) { const c = this.cp(T); return c / (c - this.R); },
    gasConstant() { return this.R; },
    soundSpeed(T) { return Math.sqrt(this.gamma(T) * this.R * T); },
    density(p, T) { return p / (this.R * T); },
    viscosity(T) {
      return 1.716e-5 * Math.pow(T / 273.15, 1.5) * (273.15 + 110.4) / (T + 110.4);
    },
    vapourPressure() { throw new IncompressibleProperty("gas has no NPSH"); },
  };
}

function waterFluid() {
  return {
    name: "Water", compressible: false, rhoRef: 998.0, TRef: 293.15, beta: 2.07e-4,
    density(p, T) { return this.rhoRef / (1 + this.beta * (T - this.TRef)); },
    viscosity(T) { return 2.414e-5 * Math.pow(10, 247.8 / Math.max(T - 140, 1)); },
    vapourPressure(T) {
      return Math.pow(10, 8.07131 - 1730.63 / (233.426 + (T - 273.15))) * 133.322;
    },
    cp() { return 4182.0; },
    /* Gas properties THROW for a liquid, exactly as in Python. If a
       compressible code path is ever reached with water selected it fails
       loudly instead of silently borrowing air's gamma. */
    gamma() { throw new IncompressibleProperty("Water is incompressible: gamma is undefined"); },
    gasConstant() { throw new IncompressibleProperty("Water is incompressible: no gas constant"); },
    soundSpeed() { throw new IncompressibleProperty("Water is incompressible: Mach not evaluated"); },
  };
}

function customFluid(c) {
  if (c.compressible) {
    const f = airFluid();
    f.name = "Custom gas"; f.R = c.gasConstant;
    f.cpConst = c.gamma * c.gasConstant / (c.gamma - 1);
    f.gammaConst = c.gamma; f.muConst = c.viscosity;
    f.cp = function () { return this.cpConst; };
    f.gamma = function () { return this.gammaConst; };
    f.viscosity = function () { return this.muConst; };
    return f;
  }
  const f = waterFluid();
  f.name = "Custom liquid"; f.rhoRef = c.density; f.beta = 0;
  f.muConst = c.viscosity; f.pvConst = c.vapourPressure;
  f.viscosity = function () { return this.muConst; };
  f.vapourPressure = function () { return this.pvConst; };
  return f;
}

function makeFluid(d) {
  if (d.fluid_kind === "water") return waterFluid();
  if (d.fluid_kind === "custom") return customFluid(d.custom_fluid);
  return airFluid();
}

/* ------------------------------------------------------------- geometry */
function controlPoints(d) {
  const phi = rad(d.exit_pitch_deg), sp = Math.sin(phi), cp = Math.cos(phi);
  const L = d.axial_length, w = 0.55;
  const h0 = [0, d.r1_hub], h3 = [L, d.r2];
  // Handles scale by each direction's own extent. Scaling both by the diagonal
  // chord pushed a hub control point past the exit plane and flattened the
  // channel into a disc — the defect that made the hub dwarf the blades.
  const dzh = Math.max(h3[0] - h0[0], 1e-6), drh = Math.max(h3[1] - h0[1], 1e-6);
  const h1 = [h0[0] + w * dzh, h0[1]];
  const h2 = [h3[0] - w * drh * sp, h3[1] - w * drh * cp];
  const s0 = [0, d.r1_shroud], s3 = [h3[0] - d.b2 * cp, h3[1] + d.b2 * sp];
  const dzs = Math.max(s3[0] - s0[0], 1e-6), drs = Math.max(s3[1] - s0[1], 1e-6);
  const s1 = [s0[0] + w * dzs, s0[1]];
  const s2 = [s3[0] - w * drs * sp, s3[1] - w * drs * cp];
  return [[h0, h1, h2, h3], [s0, s1, s2, s3]];
}

function streamline(d, span, n) {
  const [Ph, Ps] = controlPoints(d);
  const P = Ph.map((p, i) => [p[0] * (1 - span) + Ps[i][0] * span,
                              p[1] * (1 - span) + Ps[i][1] * span]);
  const z = new Float64Array(n), r = new Float64Array(n), m = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1), u = 1 - t;
    const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, e = t * t * t;
    z[i] = a * P[0][0] + b * P[1][0] + c * P[2][0] + e * P[3][0];
    r[i] = a * P[0][1] + b * P[1][1] + c * P[2][1] + e * P[3][1];
    m[i] = i ? m[i - 1] + hypot(z[i] - z[i - 1], r[i] - r[i - 1]) : 0;
  }
  return { z, r, m, M: m[n - 1] };
}

// Fraction of span the root section cluster covers. Fixed, so section layout
// never depends on the fillet radius — making it fillet-dependent meant
// filleted and unfilleted blades were built through different section counts.
const ROOT_CLUSTER = 0.12;

function spanPositions(nSpan, spanMin) {
  if (nSpan < 4) {
    const o = [];
    for (let i = 0; i < nSpan; i++) o.push(spanMin + (1 - spanMin) * i / Math.max(nSpan - 1, 1));
    return o;
  }
  const nRoot = Math.max(3, Math.round(nSpan * 0.45));
  const out = [];
  for (let i = 0; i < nRoot; i++) out.push(spanMin + (ROOT_CLUSTER - spanMin) * i / nRoot);
  const nRest = nSpan - nRoot;
  for (let i = 0; i < nRest; i++) out.push(ROOT_CLUSTER + (1 - ROOT_CLUSTER) * i / Math.max(nRest - 1, 1));
  return out.filter((v, i) => i === 0 || v - out[i - 1] > 1e-6);
}

/* Lateral half-width a circular root fillet adds at height h above the hub:
     w(h) = R - sqrt(R^2 - (R - h)^2),  0 <= h <= R,  else 0
   R wide at the hub, tapering to nothing at h = R.

   HONEST SCOPE: a MODELLED blend built into the blade's lofted surface and
   applied tangentially — not a kernel rolling-ball fillet. BRepFilletAPI could
   not fillet this junction at any radius tested (see STATUS.md), and a modelled
   blend has the advantage of appearing in the preview and the STEP export
   alike. */
function filletWidth(h, R) {
  if (!(R > 0)) return 0;
  h = Math.max(h, 0);
  if (h >= R) return 0;
  return R - Math.sqrt(Math.max(R * R - (R - h) * (R - h), 0));
}

const betaAt = (s, b1, b2, ex) => b1 + (b2 - b1) * Math.pow(clamp(s, 0, 1), ex);

function integrateWrap(m, r, beta) {
  const n = m.length, th = new Float64Array(n);
  for (let i = 1; i < n; i++) {
    const a = Math.tan(beta[i - 1]) / Math.max(r[i - 1], 1e-9);
    const b = Math.tan(beta[i]) / Math.max(r[i], 1e-9);
    th[i] = th[i - 1] + 0.5 * (a + b) * (m[i] - m[i - 1]);
  }
  return th;
}

/* Wrap angle: theta(m) = integral tan(beta)/r dm.
   DERIVED — wrap is an OUTPUT of the blade angles; nothing is rescaled.
   TARGET  — beta1 and beta2 are held EXACTLY; only the interior distribution
             exponent is solved. An unreachable target is reported, not clamped. */
function solveCamber(st, b1deg, b2deg, mode, exponent, targetDeg) {
  const { m, r, M } = st, n = m.length;
  const sHat = new Float64Array(n);
  for (let i = 0; i < n; i++) sHat[i] = m[i] / Math.max(M, 1e-12);
  const b1 = rad(b1deg), b2 = rad(b2deg);
  const build = ex => { const b = new Float64Array(n);
    for (let i = 0; i < n; i++) b[i] = betaAt(sHat[i], b1, b2, ex); return b; };
  const wrapFor = ex => integrateWrap(m, r, build(ex))[n - 1];

  if (mode !== "target" || targetDeg == null) {
    const beta = build(exponent), theta = integrateWrap(m, r, beta);
    return { theta, beta, wrapDeg: deg(theta[n - 1]), exponent,
             mode: "derived", targetMet: true,
             note: "Wrap angle is an output of the \u03b2 distribution." };
  }
  const tgt = rad(targetDeg), lo = 0.12, hi = 8.0;
  const wLo = wrapFor(lo), wHi = wrapFor(hi);
  if ((wLo - tgt) * (wHi - tgt) > 0) {
    const ex = Math.abs(wLo - tgt) < Math.abs(wHi - tgt) ? lo : hi;
    const beta = build(ex), theta = integrateWrap(m, r, beta);
    return { theta, beta, wrapDeg: deg(theta[n - 1]), exponent: ex, mode: "target",
      targetMet: false,
      note: `Target wrap ${targetDeg.toFixed(1)}\u00b0 is not reachable with ` +
            `\u03b2\u2081=${b1deg.toFixed(1)}\u00b0, \u03b2\u2082=${b2deg.toFixed(1)}\u00b0 ` +
            `(reachable ${deg(Math.min(wLo, wHi)).toFixed(1)}\u2013${deg(Math.max(wLo, wHi)).toFixed(1)}\u00b0). ` +
            `Showing ${deg(theta[n - 1]).toFixed(1)}\u00b0 \u2014 geometry is not rescaled.` };
  }
  let a = lo, b = hi, fa = wLo - tgt, ex = lo;
  for (let i = 0; i < 90; i++) {
    ex = 0.5 * (a + b); const fm = wrapFor(ex) - tgt;
    if (Math.abs(fm) < 1e-12 || (b - a) < 1e-10) break;
    if (fa * fm < 0) b = ex; else { a = ex; fa = fm; }
  }
  const beta = build(ex), theta = integrateWrap(m, r, beta);
  return { theta, beta, wrapDeg: deg(theta[n - 1]), exponent: ex, mode: "target",
    targetMet: true,
    note: `\u03b2\u2081/\u03b2\u2082 held exactly; interior exponent solved to ${ex.toFixed(3)}.` };
}

function thicknessAt(s, tle, tmax, tte, law, peak) {
  s = clamp(s, 0, 1);
  if (law === "linear") return tle + (tte - tle) * s;
  if (law === "elliptic") {
    return s < peak ? tle + (tmax - tle) * Math.sqrt(clamp(s / peak, 0, 1))
                    : tmax + (tte - tmax) * clamp((s - peak) / (1 - peak), 0, 1);
  }
  return s < peak
    ? tle + (tmax - tle) * (1 - Math.pow((peak - s) / peak, 2))
    : tte + (tmax - tte) * (1 - Math.pow((s - peak) / (1 - peak), 2));
}

function buildBlade(d, nSpan, nStream, thetaOffset, mStartFrac, spanMin = 0) {
  const stH = streamline(d, 0, nStream), stS = streamline(d, 1, nStream);
  const inletSpan = hypot(stS.z[0] - stH.z[0], stS.r[0] - stH.r[0]);
  const exitSpan = hypot(stS.z[nStream - 1] - stH.z[nStream - 1],
                         stS.r[nStream - 1] - stH.r[nStream - 1]);
  // Hub reference row for fillet height, always span 0.
  const mLE0 = clamp(mStartFrac * stH.M, 0, 0.85 * stH.M);
  const mTE0 = clamp(stH.M, mLE0 + 0.10 * stH.M, stH.M);
  const hubZ = [], hubR = [];
  for (let j = 0; j < nStream; j++) {
    const mb = mLE0 + (mTE0 - mLE0) * (nStream === 1 ? 0 : j / (nStream - 1));
    hubZ.push(interp(mb, stH.m, stH.z)); hubR.push(interp(mb, stH.m, stH.r));
  }
  const P = [], S = [], C = [], B = [], T = [], wraps = [];
  const spans = spanPositions(nSpan, spanMin);
  for (let i = 0; i < spans.length; i++) {
    const sp = spans[i];
    const st = streamline(d, sp, nStream), M = st.M;
    let mLE = mStartFrac * M + sp * inletSpan * Math.tan(rad(d.inlet_sweep_deg));
    let mTE = M - sp * exitSpan * Math.tan(rad(d.exit_rake_deg));
    mLE = clamp(mLE, 0, 0.85 * M);
    mTE = clamp(mTE, mLE + 0.10 * M, M);
    const b1 = d.beta1_hub_deg + sp * (d.beta1_shroud_deg - d.beta1_hub_deg);
    const b2 = d.beta2_hub_deg + sp * (d.beta2_shroud_deg - d.beta2_hub_deg);
    const cam = solveCamber(st, b1, b2, d.wrap_mode, d.beta_exponent, d.target_wrap_deg);
    wraps.push(cam.wrapDeg);
    const lean = Math.tan(rad(d.lean_deg)) * sp * exitSpan;
    const row = { p: [], s: [], c: [], b: [], t: [] };
    let th0 = null;
    for (let j = 0; j < nStream; j++) {
      const mb = mLE + (mTE - mLE) * (nStream === 1 ? 0 : j / (nStream - 1));
      const z = interp(mb, st.m, st.z), r = interp(mb, st.m, st.r);
      let th = interp(mb, st.m, cam.theta);
      const beta = interp(mb, st.m, cam.beta);
      if (th0 === null) th0 = th;
      th = th - th0 + thetaOffset + lean / Math.max(r, 1e-9);
      const sh = (mb - mLE) / Math.max(mTE - mLE, 1e-12);
      const t = thicknessAt(sh, d.t_le, d.t_max, d.t_te, d.thickness_law, d.t_peak_frac);
      // Root fillet height must be SIGNED: an unsigned distance made a buried
      // root read as "far from the hub", collapsing the blend there.
      const hAbove = sp === 0 ? 0
        : Math.sign(sp) * hypot(z - hubZ[j], r - hubR[j]);
      const half = t / 2 + filletWidth(hAbove, d.hub_fillet);
      // tangential half-angle for a width measured NORMAL to the camber
      const dth = half / (Math.max(r, 1e-9) * Math.max(Math.cos(beta), 0.15));
      row.p.push([r * Math.cos(th - dth), r * Math.sin(th - dth), z]);
      row.s.push([r * Math.cos(th + dth), r * Math.sin(th + dth), z]);
      row.c.push([r * Math.cos(th), r * Math.sin(th), z]);
      row.b.push(beta); row.t.push(t);
    }
    P.push(row.p); S.push(row.s); C.push(row.c); B.push(row.b); T.push(row.t);
  }
  return { P, S, C, beta: B, thick: T, wraps };
}

function interp(x, xs, ys) {
  const n = xs.length;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  const f = (x - xs[lo]) / Math.max(xs[hi] - xs[lo], 1e-15);
  return ys[lo] + f * (ys[hi] - ys[lo]);
}

/* ---------------------------------------------------------- performance */
/* Blade surface path length and mean passage hydraulic diameter, both from the
   geometry. Earlier stand-ins (1.2 x meridional length, and a hydraulic
   diameter from the exit alone) under-read the friction term. */
function passageGeometry(d, Zeff, beta2deg) {
  const st = streamline(d, 0.5, 120);
  const b1 = 0.5 * (d.beta1_hub_deg + d.beta1_shroud_deg);
  const cam = solveCamber(st, b1, beta2deg, d.wrap_mode, d.beta_exponent, d.target_wrap_deg);
  let Lb = 0;
  for (let i = 1; i < st.m.length; i++) {
    const a = 1 / Math.max(Math.cos(cam.beta[i - 1]), 0.15);
    const b = 1 / Math.max(Math.cos(cam.beta[i]), 0.15);
    Lb += 0.5 * (a + b) * (st.m[i] - st.m[i - 1]);
  }
  const r1rms = Math.sqrt(0.5 * (d.r1_shroud ** 2 + d.r1_hub ** 2));
  const Z = Math.max(Zeff, 1);
  const dh = (radius, height, betaDeg, thick) => {
    const w = Math.max(TAU * radius / Z * Math.cos(rad(betaDeg)) - thick, 1e-6);
    const h = Math.max(height, 1e-6);
    return 4 * (w * h) / (2 * (w + h));
  };
  return [Lb, 0.5 * (dh(r1rms, d.r1_shroud - d.r1_hub, b1, d.t_le)
                   + dh(d.r2, d.b2, beta2deg, d.t_te))];
}

function wiesnerSlip(beta2deg, Z, radiusRatio) {
  const b2 = rad(Math.abs(beta2deg)), cb = Math.max(Math.cos(b2), 1e-6);
  let sigma = 1 - Math.sqrt(cb) / Math.pow(Math.max(Z, 1), 0.7);
  const epsLim = Math.exp(-8.16 * cb / Math.max(Z, 1));
  if (radiusRatio > epsLim) {
    const f = (radiusRatio - epsLim) / Math.max(1 - epsLim, 1e-9);
    sigma *= (1 - Math.pow(f, 3));
  }
  return clamp(sigma, 0.05, 1.0);
}

function inletCompressible(fl, p01, T01, mdot, A1, blockage = 0.03) {
  const cp = fl.cp(T01), g = fl.gamma(T01), R = fl.gasConstant();
  let cm = mdot / Math.max((p01 / (R * T01)) * A1 * (1 - blockage), 1e-9);
  for (let i = 0; i < 60; i++) {
    const T1 = T01 - cm * cm / (2 * cp);
    if (T1 <= 1) return null;
    const p1 = p01 * Math.pow(T1 / T01, g / (g - 1));
    const rho1 = p1 / (R * T1);
    const cmNew = mdot / Math.max(rho1 * A1 * (1 - blockage), 1e-9);
    if (Math.abs(cmNew - cm) < 1e-8) { cm = cmNew; break; }
    cm = 0.5 * cm + 0.5 * cmNew;
  }
  const T1 = T01 - cm * cm / (2 * cp);
  // The in-loop guard does not cover this final evaluation; without it a
  // negative static temperature reached the power operation and yielded NaN.
  if (T1 <= 1) return null;
  const p1 = p01 * Math.pow(T1 / T01, g / (g - 1));
  return { cm, T1, rho: p1 / (R * T1) };
}

function evaluate(d, fl, mdotIn, rpmIn) {
  const op = { ok: true, messages: [], losses: {} };
  const mdot = mdotIn ?? d.mdot, rpm = rpmIn ?? d.rpm;
  const omega = rpm * TAU / 60, blockExit = 0.08;
  const r1s = d.r1_shroud, r1h = d.r1_hub, r2 = d.r2, b2 = d.b2;
  const A1 = PI * (r1s * r1s - r1h * r1h), A2 = TAU * r2 * b2;
  const r1rms = Math.sqrt(0.5 * (r1s * r1s + r1h * r1h));
  const Zeff = Math.max(d.n_main, 1) + d.n_splitter * (1 - d.splitter_start_frac);
  op.U2 = omega * r2; op.U1s = omega * r1s;

  let rhoIn;
  if (fl.compressible) {
    const inl = inletCompressible(fl, d.p01, d.T01, mdot, A1);
    if (!inl) { op.ok = false; op.messages.push("No inlet static solution — the inducer cannot pass this flow."); return op; }
    op.c_m1 = inl.cm; op.w1s = hypot(inl.cm, op.U1s);
    op.M1_rel = op.w1s / fl.soundSpeed(inl.T1); rhoIn = inl.rho;
  } else {
    rhoIn = fl.density(d.p01, d.T01);
    op.c_m1 = mdot / Math.max(rhoIn * A1, 1e-9);
    op.w1s = hypot(op.c_m1, op.U1s);
    op.M1_rel = null;                       // Mach not evaluated for a liquid
  }

  const beta2 = d.beta2_hub_deg;
  op.slip = wiesnerSlip(beta2, Math.round(Zeff), r1rms / r2);

  let rho2 = rhoIn, converged = true;
  const cp = fl.compressible ? fl.cp(d.T01) : fl.cp(d.T01);
  const g = fl.compressible ? fl.gamma(d.T01) : null;
  const R = fl.compressible ? fl.gasConstant() : null;
  let it = 0;
  for (; it < 80; it++) {
    op.c_m2 = mdot / Math.max(rho2 * A2 * (1 - blockExit), 1e-9);
    op.c_th2 = op.slip * op.U2 - op.c_m2 * Math.tan(rad(beta2));
    op.euler_work = op.U2 * op.c_th2;
    if (!fl.compressible) break;
    const T02 = d.T01 + op.euler_work / cp;
    const c2 = hypot(op.c_m2, op.c_th2);
    const T2 = T02 - c2 * c2 / (2 * cp);
    if (T2 <= 1 || T02 <= 1) { converged = false; break; }
    const p2 = d.p01 * Math.pow(Math.max(T2 / d.T01, 1e-6), g / (g - 1));
    // Bounded update: an unbounded fixed point ran away to rho2 -> 0 and gave
    // c_m2 of order 1e8 m/s before this clamp existed.
    const rn = clamp(p2 / (R * T2), 0.05 * rhoIn, 20 * rhoIn);
    if (Math.abs(rn - rho2) < 1e-9 * Math.max(rhoIn, 1e-9)) { rho2 = rn; break; }
    rho2 = 0.6 * rho2 + 0.4 * rn;
  }
  if (it >= 80) converged = false;
  if (!converged) { op.ok = false;
    op.messages.push("Exit state did not converge — geometry and duty are mutually inconsistent."); }
  if (op.euler_work <= 0) { op.ok = false;
    op.messages.push(`Euler work is non-positive (${op.euler_work.toFixed(0)} J/kg): backsweep and meridional velocity cancel the blade speed.`); }
  op.w2 = hypot(op.c_m2, op.U2 - op.c_th2);

  /* ---- losses. Every constant is sourced; see Python performance.py ---- */
  const L = op.losses;
  const beta1flow = deg(Math.atan2(op.U1s, Math.max(op.c_m1, 1e-9)));
  const wth1 = op.c_m1 * Math.abs(Math.tan(rad(beta1flow)) - Math.tan(rad(d.beta1_shroud_deg)));
  L.incidence = 0.6 * wth1 * wth1 / 2;                       // Conrad et al. (1980)

  const denom = (Zeff / PI) * (1 - r1s / r2) + 2 * r1s / r2;
  let Df = 1 - op.w2 / Math.max(op.w1s, 1e-9) + 0.75 * op.euler_work /
    Math.max(op.U2 * op.U2, 1e-9) * (op.w1s / Math.max(op.w2, 1e-9)) / Math.max(denom, 1e-9);
  Df = clamp(Df, 0, 0.95);
  L.blade_loading = 0.05 * Df * Df * op.U2 * op.U2;           // Coppage et al. (1956)

  const mu = fl.viscosity(d.T01);
  const [Lb, dHyd] = passageGeometry(d, Zeff, beta2);
  const wAvg = 0.5 * (op.w1s + op.w2);
  const Re = rhoIn * wAvg * Math.max(dHyd, 1e-6) / Math.max(mu, 1e-12);
  const cf = 0.0412 * Math.pow(Math.max(Re, 1e3), -0.1925);   // Jansen (1967)
  L.skin_friction = 2 * cf * (Lb / Math.max(dHyd, 1e-9)) * wAvg * wAvg;

  const epsCl = 0.02 * b2;                                    // Jansen (1967)
  const inner = (4 * PI / Math.max(b2 * Zeff, 1e-9)) *
    ((r1s * r1s - r1h * r1h) / Math.max((r2 - r1s) * (1 + rho2 / Math.max(rhoIn, 1e-9)), 1e-9)) *
    Math.abs(op.c_th2) * Math.abs(op.c_m1);
  L.clearance = 0.6 * (epsCl / Math.max(b2, 1e-9)) * Math.abs(op.c_th2) * Math.sqrt(Math.max(inner, 0));

  const rhoAvg = 0.5 * (rhoIn + rho2);
  const ReDf = Math.max(op.U2 * r2 * rhoAvg / Math.max(mu, 1e-12), 1e3);
  L.disk_friction = (0.0402 / Math.pow(ReDf, 0.2)) * rhoAvg *
    Math.pow(op.U2, 3) * r2 * r2 / (4 * Math.max(mdot, 1e-9));  // Daily & Nece (1960)

  const alpha2 = Math.atan2(Math.abs(op.c_th2), Math.max(op.c_m2, 1e-9));
  // Oh et al. fit the sinh form to ~75 deg; past that it grows without bound
  // (it once exceeded the whole Euler work for a low-flow pump). Both limits
  // below are engineering judgement, NOT part of the published correlation.
  const a2c = Math.min(alpha2, rad(75));
  L.recirculation = Math.min(8e-5 * Math.sinh(3.5 * Math.pow(a2c, 3)) * Df * Df * op.U2 * op.U2,
                             0.25 * Math.max(op.euler_work, 0));

  // Exit kinetic energy: mixing + downstream recovery. Omitting this gave a
  // physically impossible stage efficiency of ~0.95.
  op.c2 = hypot(op.c_m2, op.c_th2);
  const tanA2 = Math.abs(op.c_th2) / Math.max(op.c_m2, 1e-9);
  L.mixing = (1 / (1 + tanA2 * tanA2)) * Math.pow((1 - 0.20 - 0.10) / (1 - 0.20), 2)
             * op.c2 * op.c2 / 2;                             // Johnston & Dean (1966)
  let etaDiff = d.diffuser_on ? 0.78 : 0.60;
  const c3r = d.diffuser_on ? 0.30 : 0.50;
  if (d.volute_on) etaDiff -= 0.05;
  op.c3 = c3r * op.c2;
  L.diffuser = (1 - etaDiff) * (op.c2 * op.c2 - op.c3 * op.c3) / 2;

  const impInt = L.incidence + L.blade_loading + L.skin_friction + L.clearance;
  const stageInt = impInt + L.mixing + L.diffuser;
  const parasitic = L.disk_friction + L.recirculation;
  op.work_actual = op.euler_work + parasitic;
  op.eta_impeller = clamp((op.euler_work - impInt) / Math.max(op.work_actual, 1e-9), 0.02, 0.99);
  const useful = Math.max(op.euler_work - stageInt, 1e-6);
  op.eta_tt = clamp(useful / Math.max(op.work_actual, 1e-9), 0.02, 0.98);
  op.power_W = mdot * op.work_actual;

  if (fl.compressible) {
    op.T02 = d.T01 + op.work_actual / cp;
    op.pressure_ratio = Math.pow(1 + op.eta_tt * op.work_actual / (cp * d.T01), g / (g - 1));
    op.dp_Pa = d.p01 * (op.pressure_ratio - 1);
    op.head_m = null; op.npsh_required = null;
  } else {
    const rho = fl.density(d.p01, d.T01);
    op.head_m = useful / G;
    op.dp_Pa = rho * G * op.head_m;
    op.pressure_ratio = null;
    op.T02 = d.T01 + op.work_actual * (1 - op.eta_tt) / fl.cp(d.T01);
    op.npsh_required = (1.1 * op.c_m1 * op.c_m1 + 0.25 * op.w1s * op.w1s) / (2 * G); // Gulich
    op.npsh_available = (d.p01 - fl.vapourPressure(d.T01)) / (rho * G);
    op.cavitating = op.npsh_available < 1.1 * op.npsh_required;
    if (op.cavitating) op.messages.push(
      `Cavitation risk: NPSH available ${op.npsh_available.toFixed(1)} m is below 1.1\u00d7 required ${op.npsh_required.toFixed(1)} m.`);
  }

  const vol = mdot / Math.max(rhoIn, 1e-9);
  op.flow_coeff = vol / Math.max(op.U2 * r2 * r2, 1e-9);
  op.work_coeff = op.euler_work / Math.max(op.U2 * op.U2, 1e-9);
  const headNs = op.head_m != null ? op.head_m * G : op.euler_work;
  op.specific_speed = omega * Math.sqrt(Math.max(vol, 1e-12)) / Math.pow(Math.max(headNs, 1e-9), 0.75);
  op.diffusion_ratio = op.w1s / Math.max(op.w2, 1e-9);
  op.surge_risk = op.diffusion_ratio > 1.8;                   // de Haller-type limit
  if (op.M1_rel != null && op.M1_rel > 1)
    op.messages.push(`Inducer tip relative Mach ${op.M1_rel.toFixed(2)} — supersonic.`);
  return op;
}

function chokeMassFlow(d, fl, rpmIn) {
  if (!fl.compressible) return null;
  const rpm = rpmIn ?? d.rpm, omega = rpm * TAU / 60;
  const r1s = d.r1_shroud, r1h = d.r1_hub;
  const rRms = Math.sqrt(0.5 * (r1s * r1s + r1h * r1h));
  const pitch = TAU * rRms / Math.max(d.n_main, 1);
  const throat = Math.max(pitch * Math.cos(rad(d.beta1_shroud_deg)) - d.t_le, 1e-6);
  const Ath = throat * (r1s - r1h) * Math.max(d.n_main, 1);
  const A1 = PI * (r1s * r1s - r1h * r1h);
  const g = fl.gamma(d.T01), R = fl.gasConstant(), cp = fl.cp(d.T01);
  const U = omega * rRms;
  const K = Math.sqrt(g / R) * Math.pow(2 / (g + 1), (g + 1) / (2 * (g - 1)));
  let mdot = d.mdot;
  for (let i = 0; i < 25; i++) {
    const inl = inletCompressible(fl, d.p01, d.T01, mdot, A1);
    if (!inl) { mdot *= 0.8; continue; }
    const p1 = inl.rho * R * inl.T1;
    // With zero inlet swirl T0rel = T01 + U^2/(2cp). Treating it as T01 made
    // choke independent of shaft speed and drew a vertical choke line.
    const T0rel = inl.T1 + (inl.cm * inl.cm + U * U) / (2 * cp);
    const p0rel = p1 * Math.pow(T0rel / inl.T1, g / (g - 1));
    const next = Ath * p0rel / Math.sqrt(T0rel) * K;
    if (Math.abs(next - mdot) < 1e-9) return next;
    mdot = 0.5 * mdot + 0.5 * next;
  }
  return mdot;
}

function optimalBeta1(d, fl) {
  const omega = d.rpm * TAU / 60;
  const A1 = PI * (d.r1_shroud ** 2 - d.r1_hub ** 2);
  let cm;
  if (fl.compressible) {
    const inl = inletCompressible(fl, d.p01, d.T01, d.mdot, A1);
    if (!inl) return [null, null]; cm = inl.cm;
  } else cm = d.mdot / Math.max(fl.density(d.p01, d.T01) * A1, 1e-9);
  return [deg(Math.atan2(omega * d.r1_hub, cm)), deg(Math.atan2(omega * d.r1_shroud, cm))];
}

/* ------------------------------------------------------- performance map */
const T_REF = 288.15, P_REF = 101325;
const corrFlow = (m, T, p) => m * Math.sqrt(T / T_REF) / (p / P_REF);

function generateMap(d, fl, fracs = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1], nPts = 22) {
  const lines = [], surge = [], choke = [];
  for (const sf of fracs) {
    const rpm = d.rpm * sf;
    const mc = fl.compressible ? chokeMassFlow(d, fl, rpm) : null;
    const hi = mc ? Math.min(1.45 * d.mdot, 0.98 * mc) : 1.45 * d.mdot;
    const lo = 0.35 * d.mdot;
    if (hi <= lo) continue;
    const pts = [];
    for (let i = 0; i < nPts; i++) {
      const m = lo + (hi - lo) * i / (nPts - 1);
      const op = evaluate(d, fl, m, rpm);
      if (!op.ok) continue;
      const y = fl.compressible ? op.pressure_ratio : op.head_m;
      if (y == null || !isFinite(y) || y <= 0) continue;
      pts.push({ mdot: m, x: corrFlow(m, d.T01, d.p01), y, eta: op.eta_tt,
                 surge: op.surge_risk, dr: op.diffusion_ratio });
    }
    if (pts.length < 3) continue;
    const okPts = pts.filter(p => !p.surge);
    if (okPts.length) { const s = okPts.reduce((a, b) => a.mdot < b.mdot ? a : b); surge.push([s.x, s.y]); }
    const c = pts.reduce((a, b) => a.mdot > b.mdot ? a : b); choke.push([c.x, c.y]);
    lines.push({ sf, rpm, pts });
  }
  const op0 = evaluate(d, fl);
  return { lines, surge, choke,
    design: { x: corrFlow(d.mdot, d.T01, d.p01),
              y: fl.compressible ? op0.pressure_ratio : op0.head_m },
    yLabel: fl.compressible ? "Total pressure ratio" : "Head (m)",
    compressible: fl.compressible };
}

function mapToCsv(m) {
  const rows = ["speed_frac,rpm,mdot_kg_s,corrected_flow_kg_s,y_value,efficiency,diffusion_ratio,surge_flag"];
  for (const ln of m.lines) for (const p of ln.pts)
    rows.push([ln.sf.toFixed(3), ln.rpm.toFixed(1), p.mdot.toFixed(6), p.x.toFixed(6),
               p.y.toFixed(6), p.eta.toFixed(6), p.dr.toFixed(4), p.surge ? 1 : 0].join(","));
  return rows.join("\n");
}

/* ---------------------------------------------------------- validation */
function validate(d) {
  const out = [];
  const warn = (f, m) => out.push({ level: "warn", field: f, message: m });
  const err = (f, m) => out.push({ level: "error", field: f, message: m });

  if (d.r1_shroud <= d.r1_hub)
    err("r1_shroud", "Inlet shroud radius must exceed the hub radius — the annulus has no height.");
  else {
    const htr = d.r1_hub / d.r1_shroud;
    if (htr < 0.15 || htr > 0.75)
      warn("r1_hub", `Hub-tip ratio ${htr.toFixed(2)} sits outside the usual 0.25–0.65 band.`);
  }
  if (d.r2 <= d.r1_shroud) err("r2", "Exit radius must exceed the inlet shroud radius.");
  if (d.b2 <= 0) err("b2", "Exit blade height must be positive.");
  else if (d.b2 / Math.max(d.r2, 1e-9) > 0.35) warn("b2", "Exit height over radius above 0.35 is unusually wide.");
  if (d.axial_length <= 0) err("axial_length", "Axial length must be positive.");

  // Blade blockage / self-intersection at the inducer.
  if (d.n_main > 0 && d.r1_hub > 0) {
    const pitch = TAU * d.r1_hub / Math.max(d.n_main, 1);
    // The root fillet adds 2*R of lateral width at the hub, so it consumes
    // pitch exactly like thickness and belongs in this check.
    const tTan = (d.t_le + 2 * d.hub_fillet)
      / Math.max(Math.cos(rad(Math.max(d.beta1_hub_deg, 0))), 0.15);
    const block = tTan / Math.max(pitch, 1e-9);
    if (block >= 1) err("n_main",
      `Blades self-intersect at the hub leading edge — tangential thickness plus root fillet is ${block.toFixed(2)}\u00d7 the pitch. Reduce blade count, LE thickness, fillet radius, or \u03b2\u2081.`);
    else if (block > 0.45) warn("n_main",
      `Inducer blockage is ${(block * 100).toFixed(0)}% of pitch — valid but heavily blocked.`);
  }
  if (d.n_splitter && d.n_main && d.n_splitter % d.n_main)
    warn("n_splitter", "Splitter count is not a multiple of the main blade count — spacing will be uneven.");
  if (d.t_max < Math.max(d.t_le, d.t_te))
    warn("t_max", "Max thickness is below the LE/TE thickness — the distribution will be non-physical.");
  if (Math.abs(d.beta2_hub_deg) > 65)
    warn("beta2_hub_deg", "Backsweep beyond about 60\u00b0 is outside normal design practice.");
  if (d.hub_fillet > 0.5 * d.b2)
    warn("hub_fillet", "Fillet radius exceeds half the exit blade height — the fillet will fail at export.");
  // The mass-flux function is flat near M=1, so a transonic inducer has very
  // little flow left before choking. Real for a fast wheel, but never silent.
  const flv = makeFluid(d);
  if (flv.compressible) {
    try {
      const mc = chokeMassFlow(d, flv);
      if (mc) {
        const margin = mc / Math.max(d.mdot, 1e-9);
        if (margin <= 1)
          err("mdot", `Design flow is past the estimated choke limit (${mc.toPrecision(4)} kg/s) — the wheel cannot pass it.`);
        else if (margin < 1.06)
          warn("mdot", `Only ${((margin - 1) * 100).toFixed(0)}% choke margin (choke at ${mc.toPrecision(4)} kg/s). Normal for a transonic inducer, but there is no room to increase flow.`);
      }
    } catch (e) { /* fluid cannot be evaluated here; other checks still apply */ }
  }

  if (d.fluid_kind === "water" && d.target_pressure_ratio > 1.0001)
    warn("target_pressure_ratio", "A liquid is selected — set a target head instead of a pressure ratio.");
  return out;
}

/* ------------------------------------------------------------ self test */
function selfTest() {
  const bad = [];
  let worst = 0;
  // allclose-style: |a-b| <= atol + rtol*|b|. A pure relative test made a
  // 5e-7 J/kg loss term look like a 540x error against a near-zero reference.
  const cmp = (name, got, want, rtol = 1e-9, atol = 1e-12) => {
    if (want == null || got == null) { if (want !== got) bad.push(`${name} (null mismatch)`); return; }
    const d = Math.abs(got - want);
    const e = d / Math.max(Math.abs(want), 1e-30);
    if (Math.abs(want) > 1e-6 && e > worst) worst = e;
    if (d > atol + rtol * Math.abs(want))
      bad.push(`${name} (JS ${got.toPrecision(8)} vs Py ${want.toPrecision(8)})`);
  };
  for (const key of Object.keys(REF)) {
    const R0 = REF[key], d = R0.params, fl = makeFluid(d);
    const st = streamline(d, 0.5, 9);
    for (let i = 0; i < 9; i++) {
      cmp(`${key}.z[${i}]`, st.z[i], R0.mid_z[i], 1e-9, 1e-12);
      cmp(`${key}.r[${i}]`, st.r[i], R0.mid_r[i], 1e-9, 1e-12);
    }
    cmp(`${key}.M`, st.M, R0.M_mid, 1e-9, 1e-12);
    const ch = solveCamber(streamline(d, 0, 160), d.beta1_hub_deg, d.beta2_hub_deg, "derived", 1);
    const cs = solveCamber(streamline(d, 1, 160), d.beta1_shroud_deg, d.beta2_shroud_deg, "derived", 1);
    cmp(`${key}.wrapHub`, ch.wrapDeg, R0.wrap_hub, 1e-9, 1e-9);
    cmp(`${key}.wrapShroud`, cs.wrapDeg, R0.wrap_shroud, 1e-9, 1e-9);
    const tg = solveCamber(streamline(d, 0, 160), d.beta1_hub_deg, d.beta2_hub_deg,
                           "target", 1, R0.wrap_hub * 0.75);
    cmp(`${key}.targetWrap`, tg.wrapDeg, R0.target_wrap, 1e-7, 1e-7);
    cmp(`${key}.targetExp`, tg.exponent, R0.target_exp, 1e-6, 1e-8);
    const op = evaluate(d, fl);
    cmp(`${key}.U2`, op.U2, R0.U2); cmp(`${key}.slip`, op.slip, R0.slip);
    cmp(`${key}.cm1`, op.c_m1, R0.cm1); cmp(`${key}.cm2`, op.c_m2, R0.cm2);
    cmp(`${key}.cth2`, op.c_th2, R0.cth2); cmp(`${key}.euler`, op.euler_work, R0.euler);
    cmp(`${key}.eta`, op.eta_tt, R0.eta); cmp(`${key}.etaImp`, op.eta_impeller, R0.eta_imp);
    cmp(`${key}.power`, op.power_W, R0.power);
    cmp(`${key}.PR`, op.pressure_ratio, R0.PR); cmp(`${key}.head`, op.head_m, R0.head);
    cmp(`${key}.M1`, op.M1_rel, R0.M1); cmp(`${key}.npshr`, op.npsh_required, R0.npshr);
    cmp(`${key}.phi`, op.flow_coeff, R0.phi); cmp(`${key}.psi`, op.work_coeff, R0.psi);
    cmp(`${key}.ns`, op.specific_speed, R0.ns);
    for (const k of Object.keys(R0.losses)) cmp(`${key}.loss.${k}`, op.losses[k], R0.losses[k], 1e-9, 1e-6);
    const mc = chokeMassFlow(d, fl);
    cmp(`${key}.choke`, mc, R0.choke, 1e-7, 1e-12);
    // fillet profile and the section widths it produces
    const Rf = d.hub_fillet;
    [0, .25, .5, 1, 1.5].forEach((h, i) =>
      cmp(`${key}.filletW[${h}]`, filletWidth(h * Rf, Rf), R0.fil[i], 1e-9, 1e-15));
    const [Lb, dh] = passageGeometry(d, d.n_main + d.n_splitter * (1 - d.splitter_start_frac),
                                     d.beta2_hub_deg);
    cmp(`${key}.L_b`, Lb, R0.Lb, 1e-9, 1e-12);
    cmp(`${key}.d_hyd`, dh, R0.dhyd, 1e-9, 1e-12);
    const sp = spanPositions(9, 0);
    R0.spans.forEach((v, i) => cmp(`${key}.span[${i}]`, sp[i], v, 1e-9, 1e-12));
    const bl = buildBlade(d, 9, 30, 0, 0);
    [0, 1, 4, 8].forEach((si, i) => {
      const P = bl.P[si][15], S2 = bl.S[si][15];
      const w = hypot(P[0] - S2[0], P[1] - S2[1], P[2] - S2[2]);
      cmp(`${key}.width[${si}]`, w, R0.widths[i], 1e-9, 1e-12);
    });
  }
  return { pass: bad.length === 0, worst, failures: bad.slice(0, 6), total: bad.length };
}
