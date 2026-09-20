const fs = require("fs");
const { JSDOM } = require("jsdom");

// Minimal THREE stub: the UI's geometry maths is what we want to exercise,
// not WebGL. Anything the UI calls must exist, or the test is meaningless.
const V3 = class { constructor(x=0,y=0,z=0){this.x=x;this.y=y;this.z=z;}
  set(x,y,z){this.x=x;this.y=y;this.z=z;return this;} copy(v){return this.set(v.x,v.y,v.z);}
  addScaledVector(){return this;} setFromMatrixColumn(){return this;} };
const Obj = class { constructor(){this.children=[];} add(...o){this.children.push(...o);}
  get position(){ return this._p||(this._p=new V3()); }
  get rotation(){ return this._r||(this._r=new V3()); } };
let triTotal = 0;
const THREE = {
  WebGLRenderer: class { constructor(){ this.domElement = { style:{}, addEventListener(){}, setPointerCapture(){}, releasePointerCapture(){} }; }
    setPixelRatio(){} setSize(){} render(){} },
  Scene: Obj, Group: Obj, Mesh: class extends Obj { constructor(g,m){super(); this.geometry=g; this.material=m;} },
  PerspectiveCamera: class extends Obj { constructor(){super(); this.matrix={}; } updateProjectionMatrix(){} lookAt(){} },
  Vector3: V3,
  Color: class { constructor(c){this.c=c;} offsetHSL(){return this;} },
  HemisphereLight: Obj, DirectionalLight: Obj,
  MeshStandardMaterial: class { constructor(o){Object.assign(this,o);} dispose(){} },
  BufferGeometry: class { constructor(){this.attributes={};} 
    setAttribute(n,a){this.attributes[n]=a;} setIndex(i){this.index={array:i,count:i.length};
      triTotal += i.length/3;} computeVertexNormals(){} dispose(){} },
  BufferAttribute: class { constructor(a,i){this.array=a;this.itemSize=i;} },
  RingGeometry: class { constructor(){ this.index={array:[],count:0}; } dispose(){} },
  BoxGeometry: class { constructor(){ this.index={array:[],count:0}; } dispose(){} },
  TubeGeometry: class { constructor(){ this.index={array:[],count:0}; } dispose(){} },
  CatmullRomCurve3: class {},
  Box3: class { setFromObject(){ this.isEmpty=()=>false; return this; }
    getCenter(v){return v;} getSize(v){return v.set(0.1,0.1,0.1);} },
  DoubleSide: 2,
};

const errors = [];
const dom = new JSDOM(fs.readFileSync("/tmp/build.html","utf8"), {
  runScripts: "dangerously", pretendToBeVisual: true,
  beforeParse(w){
    w.THREE = THREE;
    w.ResizeObserver = class { observe(){} disconnect(){} };
    w.URL.createObjectURL = () => "blob:x"; w.URL.revokeObjectURL = () => {};
    w.HTMLCanvasElement.prototype.getContext = () => null;
    w.onerror = (m)=>errors.push("window.onerror: "+m);
  },
});
const w = dom.window, d = w.document;
const step = (name, fn) => { try { fn(); } catch(e) { errors.push(`${name}: ${e.message}`); } };

setTimeout(() => {
  const badge = d.querySelector("#selftest");
  console.log("engine badge:", badge.textContent, "| class:", badge.className);

  step("preset switch", () => {
    for (const k of ["baseline_compressor","pump","mixed_flow_fan","turbocharger"]) {
      const s = d.querySelector("#preset"); s.value = k;
      s.dispatchEvent(new w.Event("change"));
    }
  });
  step("units toggle", () => {
    const [si, imp] = [...d.querySelectorAll("#units button")];
    imp.click();
    const v = d.querySelector("#f_r2").value;
    si.click();
    const v2 = d.querySelector("#f_r2").value;
    if (v === v2) errors.push("units toggle did not change the displayed r2 value");
    else console.log("units: r2 imperial", v, "-> SI", v2);
  });
  step("fluid switch", () => {
    const f = d.querySelector("#fluid");
    for (const v of ["water","custom","air"]) { f.value = v; f.dispatchEvent(new w.Event("change")); }
  });
  step("shading modes", () => [...d.querySelectorAll("#shade button")].forEach(b=>b.click()));
  step("downstream toggles", () => { d.querySelector("#tglDiff").click(); d.querySelector("#tglVol").click(); });
  step("tabs", () => [...d.querySelectorAll("#tabs button")].forEach(b=>{
    b.click();
    if (!d.querySelector("#plot svg")) errors.push("tab "+b.dataset.t+" rendered no svg");
  }));
  step("snapshots + compare", () => {
    d.querySelector("#snap").click();
    const r2 = d.querySelector("#f_r2"); r2.value = String(parseFloat(r2.value)*1.2);
    r2.dispatchEvent(new w.Event("change"));
    d.querySelector("#snap").click();
    const boxes = [...d.querySelectorAll("#snaps input[type=checkbox]")];
    if (boxes.length !== 2) errors.push("expected 2 snapshot chips, got "+boxes.length);
    boxes.forEach(b=>{ b.checked = true; b.dispatchEvent(new w.Event("change")); });
    [...d.querySelectorAll("#tabs button")].find(b=>b.dataset.t==="compare").click();
    const rows = d.querySelectorAll(".difftab tr").length;
    console.log("compare diff rows:", rows);
    if (rows < 2) errors.push("compare produced no diff rows after changing r2");
  });
  step("undo/redo", () => {
    const u = d.querySelector("#undo");
    for (let i=0;i<5;i++) if (!u.disabled) u.click();
    const r = d.querySelector("#redo");
    for (let i=0;i<3;i++) if (!r.disabled) r.click();
  });
  step("extreme sweep", () => {
    const set = (id, v) => { const e=d.querySelector(id); if(!e) throw new Error("missing "+id);
      e.value=String(v); e.dispatchEvent(new w.Event("change")); };
    set("#f_n_main", 40); set("#f_n_splitter", 40); set("#f_t_max", 20);
    set("#f_beta2_hub_deg", 70); set("#f_b2", 0.2); set("#f_exit_pitch_deg", 70);
    const iss = d.querySelectorAll("#issues .issue").length;
    console.log("extremes -> issues flagged:", iss);
    if (!iss) errors.push("extreme values produced no warnings");
  });
  step("export paths", () => {
    d.querySelector("#exportBtn").click();
    [...d.querySelectorAll("#exportDlg [data-x]")].forEach(b=>b.click());
  });

  console.log("triangles built across all rebuilds:", triTotal.toLocaleString());
  console.log(errors.length ? "\nERRORS:" : "\nNo runtime errors.");
  errors.forEach(e=>console.log("  -", e));
  process.exit(errors.length ? 1 : 0);
}, 700);
