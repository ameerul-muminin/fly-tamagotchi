// 3D brain, front view. Two point clouds:
//  - the backdrop: every annotated FlyWire neuron (/api/atlas), so the whole brain's shape
//    shows, drawn dim; these neurons are not simulated and never light up;
//  - the simulated neurons (/api/positions order = the first n_sim atlas entries), which
//    show resting, stimulated (the phone input drives their group) or firing (a spike in a
//    recent tick, from tick.spiking_ids).

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CONFIG } from "./config.js";
import { pickNearest } from "./brain_logic.js";

const SIM_VERT = `
attribute float aFlash;
attribute float aStim;
attribute float aSel;
uniform float uPx, uFirePx, uDpr, uRestAlpha, uDim, uSelActive;
uniform vec3 uRest, uStim, uFire;
varying vec3 vColor;
varying float vAlpha;
varying float vGlow;
void main() {
  float f = clamp(aFlash, 0.0, 1.0);
  float s = clamp(aStim, 0.0, 1.0);
  float sel = uSelActive > 0.5 ? aSel : 1.0;
  vec3 c = mix(mix(uRest, uStim, s), uFire, f);
  float a = mix(uRestAlpha, 1.0, max(f, 0.9 * s));
  if (uSelActive > 0.5 && aSel > 0.5) {
    a = 1.0;
    c = mix(c, vec3(1.0), 0.3 * (1.0 - f));
  }
  vColor = c;
  vAlpha = a * mix(uDim, 1.0, sel);
  vGlow = f;
  float size = uPx + f * uFirePx + s * 3.0 + uSelActive * aSel * 5.0;
  gl_PointSize = size * uDpr;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const SIM_FRAG = `
varying vec3 vColor;
varying float vAlpha;
varying float vGlow;
void main() {
  float r = length(gl_PointCoord - 0.5);
  if (r > 0.5) discard;
  // Resting points are small solid dots; firing ones get a soft halo around a hot core.
  float disk = smoothstep(0.5, 0.32, r);
  float halo = smoothstep(0.5, 0.0, r);
  float a = mix(disk, 0.35 * halo + 0.65 * smoothstep(0.22, 0.1, r), vGlow);
  vec3 c = mix(vColor, vec3(1.0, 0.96, 0.85), vGlow * smoothstep(0.18, 0.0, r) * 0.6);
  gl_FragColor = vec4(c, vAlpha * a);
}`;

const BACK_VERT = `
uniform float uPx, uDpr;
void main() {
  gl_PointSize = uPx * uDpr;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const BACK_FRAG = `
uniform vec3 uColor;
uniform float uAlpha;
void main() {
  float r = length(gl_PointCoord - 0.5);
  if (r > 0.5) discard;
  gl_FragColor = vec4(uColor, uAlpha * smoothstep(0.5, 0.3, r));
}`;

export class BrainView {
  /**
   * @param {HTMLElement} el container
   * @param {{ids: string[]}} positions body of /api/positions (simulated neurons)
   * @param {{header: object, xyz: Int16Array}} atlas /api/atlas + /api/atlas.bin
   * @param {Record<string, string[]>} groups group name -> neuron IDs (hello.brain.groups)
   * @param {"high"|"low"} quality "low" draws a subsample of the backdrop
   */
  constructor(el, positions, atlas, groups, config = CONFIG, quality = "high") {
    this.cfg = config.brain;
    this.el = el;
    const { header, xyz } = atlas;
    this.header = header;
    this.nAtlas = header.n;
    this.nSim = header.n_sim;
    this.index = new Map(positions.ids.map((id, i) => [id, i]));
    this.ids = positions.ids;
    const scale = header.scale_um;

    // Center on the whole brain's extent (0.2-99.8 percentile, so a few stray somata
    // don't shrink the view); flip y so dorsal is up (EM image y grows downward).
    const c = [0, 0, 0];
    const ext = [0, 0, 0];
    for (let k = 0; k < 3; k++) {
      const v = new Int16Array(this.nAtlas);
      for (let i = 0; i < this.nAtlas; i++) v[i] = xyz[3 * i + k];
      v.sort();
      const lo = v[Math.floor(0.002 * this.nAtlas)];
      const hi = v[Math.floor(0.998 * this.nAtlas)];
      c[k] = (lo + hi) / 2;
      ext[k] = ((hi - lo) / 2) * scale;
    }
    const world = (i, out) => {
      out[0] = (xyz[3 * i] - c[0]) * scale;
      out[1] = -(xyz[3 * i + 1] - c[1]) * scale;
      out[2] = (xyz[3 * i + 2] - c[2]) * scale;
      return out;
    };
    this.center = c.map((v) => v * scale);

    // Simulated neurons.
    const simPos = new Float32Array(3 * this.nSim);
    const tmp = [0, 0, 0];
    for (let i = 0; i < this.nSim; i++) simPos.set(world(i, tmp), 3 * i);
    // Backdrop (low quality: every n-th neuron).
    const every = quality === "low" ? this.cfg.lowBackdropEvery : 1;
    const backIdx = [];
    for (let i = this.nSim; i < this.nAtlas; i += every) backIdx.push(i);
    const backPos = new Float32Array(3 * backIdx.length);
    backIdx.forEach((ai, k) => backPos.set(world(ai, tmp), 3 * k));
    this.halfW = ext[0];
    this.halfH = ext[1];
    this.backIdx = Int32Array.from(backIdx);
    this.pickPos = [simPos, backPos];
    this.nDrawn = this.nSim + backIdx.length;

    // Hemisphere anchors for the L / R labels (mean x of each side, brain center y, z).
    this.leftAnchor = new THREE.Vector3(header.left_x_um - this.center[0], 0, 0);
    this.rightAnchor = new THREE.Vector3(header.right_x_um - this.center[0], 0, 0);

    this.flash = new Float32Array(this.nSim);
    this.stim = new Float32Array(this.nSim);
    this.stimTarget = new Float32Array(this.nSim);
    this.sel = new Float32Array(this.nSim);
    this.groupIdx = {};
    for (const [g, gids] of Object.entries(groups ?? {})) {
      this.groupIdx[g] = gids.map((id) => this.index.get(id)).filter((i) => i !== undefined);
    }
    this.stimCandidates = [...new Set(Object.values(this.groupIdx).flat())];

    const colors = this.cfg.colors;
    const dpr = Math.min(window.devicePixelRatio || 1, quality === "low" ? 1 : this.cfg.maxPixelRatio);
    const simGeo = new THREE.BufferGeometry();
    simGeo.setAttribute("position", new THREE.BufferAttribute(simPos, 3));
    this.flashAttr = new THREE.BufferAttribute(this.flash, 1).setUsage(THREE.DynamicDrawUsage);
    this.stimAttr = new THREE.BufferAttribute(this.stim, 1).setUsage(THREE.DynamicDrawUsage);
    this.selAttr = new THREE.BufferAttribute(this.sel, 1);
    simGeo.setAttribute("aFlash", this.flashAttr);
    simGeo.setAttribute("aStim", this.stimAttr);
    simGeo.setAttribute("aSel", this.selAttr);
    this.simMat = new THREE.ShaderMaterial({
      vertexShader: SIM_VERT,
      fragmentShader: SIM_FRAG,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      uniforms: {
        uPx: { value: this.cfg.pointPx },
        uFirePx: { value: this.cfg.firingPx },
        uDpr: { value: dpr },
        uRestAlpha: { value: this.cfg.restAlpha },
        uDim: { value: 1 },
        uSelActive: { value: 0 },
        uRest: { value: new THREE.Color(colors.resting) },
        uStim: { value: new THREE.Color(colors.stimulated) },
        uFire: { value: new THREE.Color(colors.firing) },
      },
    });
    const backGeo = new THREE.BufferGeometry();
    backGeo.setAttribute("position", new THREE.BufferAttribute(backPos, 3));
    this.backMat = new THREE.ShaderMaterial({
      vertexShader: BACK_VERT,
      fragmentShader: BACK_FRAG,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      uniforms: {
        uPx: { value: this.cfg.backdropPx },
        uDpr: { value: dpr },
        uColor: { value: new THREE.Color(colors.backdrop) },
        uAlpha: { value: this.cfg.backdropAlpha },
      },
    });
    const back = new THREE.Points(backGeo, this.backMat);
    const sim = new THREE.Points(simGeo, this.simMat);
    back.renderOrder = 0;
    sim.renderOrder = 1;
    back.frustumCulled = sim.frustumCulled = false;

    this.scene = new THREE.Scene();
    this.scene.add(back, sim);
    this.camera = new THREE.PerspectiveCamera(this.cfg.fov, 1, 1, 1e5);
    this.renderer = new THREE.WebGLRenderer({ antialias: quality !== "low", alpha: true, preserveDrawingBuffer: false });
    this.renderer.setPixelRatio(dpr);
    el.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.rotateSpeed = 0.6;
    this.controls.addEventListener("change", () => (this.screenDirty = true));
    this.renderer.domElement.addEventListener("dblclick", () => this.resetView());
    this.zoom = 1;
    this.fitDistance = 1;
    this.resetView();

    this.lastMs = performance.now();
    this.litCount = 0;
    this.flashedTotal = 0;
    this.selection = "all";
    this.screen = new Float32Array(2 * this.nDrawn);
    this.screenDirty = true;
  }

  /** Front view, whole brain in frame. */
  resetView() {
    this.zoom = 1;
    this.controls.target.set(0, 0, 0);
    this.camera.position.set(0, 0, this.fitDistance);
    this.camera.up.set(0, 1, 0);
    this.controls.update();
    this.screenDirty = true;
  }

  /** Distance at which the brain's width and height fit the view. */
  fit(aspect) {
    const t = Math.tan(THREE.MathUtils.degToRad(this.cfg.fov / 2));
    return this.cfg.fitMargin * Math.max(this.halfW / (t * aspect), this.halfH / t);
  }

  /** Light up the given neuron IDs (IDs without a position are skipped). */
  spike(ids) {
    for (const id of ids) {
      const i = this.index.get(id);
      if (i !== undefined) {
        this.flash[i] = 1;
        this.flashedTotal += 1;
      }
    }
  }

  /** Mark the groups the phone input drives now (see brain_logic.stimulatedGroups). */
  setStimulated(groupNames) {
    this.stimTarget.fill(0);
    for (const g of groupNames) for (const i of this.groupIdx[g] ?? []) this.stimTarget[i] = 1;
  }

  /** Highlight one group ("all" = none). Returns how many of its neurons are drawn. */
  setSelection(key) {
    this.selection = key;
    this.sel.fill(0);
    const idx = key === "all" ? [] : this.groupIdx[key] ?? [];
    for (const i of idx) this.sel[i] = 1;
    this.selAttr.needsUpdate = true;
    const active = key !== "all";
    this.simMat.uniforms.uSelActive.value = active ? 1 : 0;
    this.simMat.uniforms.uDim.value = active ? this.cfg.dimAlpha : 1;
    this.backMat.uniforms.uAlpha.value = this.cfg.backdropAlpha * (active ? this.cfg.dimAlpha * 1.6 : 1);
    return idx.length;
  }

  /** Screen position (CSS px, relative to the canvas) of a world point; null if behind. */
  toScreen(v) {
    const p = v.clone().project(this.camera);
    if (p.z > 1) return null;
    return { x: (p.x + 1) * 0.5 * this.w, y: (1 - p.y) * 0.5 * this.h };
  }

  /** Where the L and R labels go: screen x of each hemisphere's mean position. */
  sideScreenX() {
    return { left: this.toScreen(this.leftAnchor)?.x ?? 0, right: this.toScreen(this.rightAnchor)?.x ?? 0 };
  }

  /** Circle around the selected group on screen: {x, y, r} or null. */
  selectionCircle() {
    const idx = this.selection === "all" ? [] : this.groupIdx[this.selection] ?? [];
    if (!idx.length) return null;
    this.updateScreen();
    let sx = 0;
    let sy = 0;
    for (const i of idx) {
      sx += this.screen[2 * i];
      sy += this.screen[2 * i + 1];
    }
    sx /= idx.length;
    sy /= idx.length;
    let r = 0;
    for (const i of idx) r = Math.max(r, Math.hypot(this.screen[2 * i] - sx, this.screen[2 * i + 1] - sy));
    return { x: sx, y: sy, r: r + 12 };
  }

  /** Project every drawn neuron to the screen (only after the camera or size changed). */
  updateScreen() {
    if (!this.screenDirty) return;
    this.screenDirty = false;
    this.camera.updateMatrixWorld();
    const m = new THREE.Matrix4().multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse).elements;
    let k = 0;
    for (const pos of this.pickPos) {
      for (let i = 0; i < pos.length; i += 3) {
        const x = pos[i];
        const y = pos[i + 1];
        const z = pos[i + 2];
        const w = m[3] * x + m[7] * y + m[11] * z + m[15];
        if (w <= 0) {
          this.screen[k++] = NaN;
          this.screen[k++] = NaN;
          continue;
        }
        this.screen[k++] = ((m[0] * x + m[4] * y + m[8] * z + m[12]) / w + 1) * 0.5 * this.w;
        this.screen[k++] = (1 - (m[1] * x + m[5] * y + m[9] * z + m[13]) / w) * 0.5 * this.h;
      }
    }
  }

  /**
   * Neuron under the pointer: {atlasIndex, id (simulated only), x, y} or null.
   * `x`, `y` are CSS px relative to the canvas.
   */
  pick(x, y) {
    this.updateScreen();
    const i = pickNearest(this.screen, x, y, this.cfg.hoverPx, this.nSim, 3);
    if (i < 0) return null;
    const atlasIndex = i < this.nSim ? i : this.backIdx[i - this.nSim];
    return { atlasIndex, id: i < this.nSim ? this.ids[i] : null, x: this.screen[2 * i], y: this.screen[2 * i + 1] };
  }

  /** Is this simulated neuron lit or stimulated right now? */
  activity(id) {
    const i = this.index.get(id);
    if (i === undefined) return { firing: false, stimulated: false };
    return { firing: this.flash[i] > 0.1, stimulated: this.stim[i] > 0.5 };
  }

  /** Decay flashes (unless `frozen`) and draw one frame. Returns how many neurons are lit. */
  render(frozen = false) {
    const now = performance.now();
    const dtMs = now - this.lastMs;
    this.lastMs = now;
    const k = frozen ? 1 : Math.exp(-dtMs / this.cfg.flashDecayMs);
    let lit = 0;
    for (let i = 0; i < this.nSim; i++) {
      const f = this.flash[i] * k;
      this.flash[i] = f < 0.01 ? 0 : f;
      if (f > 0.1) lit += 1;
    }
    this.flashAttr.needsUpdate = true;
    const ks = 1 - Math.exp(-dtMs / this.cfg.stimTauMs);
    for (const i of this.stimCandidates) this.stim[i] += (this.stimTarget[i] - this.stim[i]) * ks;
    this.stimAttr.needsUpdate = true;
    this.litCount = lit;

    const { clientWidth: w, clientHeight: h } = this.el;
    const size = this.renderer.getSize(new THREE.Vector2());
    if (w && h && (size.x !== w || size.y !== h)) {
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      // Keep the user's zoom relative to the fitted distance.
      const dir = this.camera.position.clone().sub(this.controls.target);
      const rel = dir.length() / this.fitDistance;
      this.fitDistance = this.fit(this.camera.aspect);
      this.camera.position.copy(this.controls.target).add(dir.setLength(this.fitDistance * rel));
      this.controls.minDistance = this.fitDistance * 0.3;
      this.controls.maxDistance = this.fitDistance * 1.8;
      this.screenDirty = true;
    }
    this.w = w;
    this.h = h;
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    return lit;
  }
}
