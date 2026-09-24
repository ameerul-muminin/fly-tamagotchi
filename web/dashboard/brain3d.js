// 3D brain: one dot per placed neuron (positions from /api/positions). Neurons listed in a
// tick's `spiking_ids` flash and fade, colored by group.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CONFIG } from "./config.js";

const VERT = `
attribute vec3 aColor;
attribute float aFlash;
attribute float aGroup;
uniform float uBase, uFlash, uBonus, uDpr, uRestAlpha;
uniform vec3 uRest;
varying vec3 vColor;
varying float vAlpha;
void main() {
  float f = clamp(aFlash, 0.0, 1.0);
  vec3 rest = mix(uRest, aColor * 0.8, aGroup);
  vColor = mix(rest, aColor, f);
  vAlpha = max(uRestAlpha + f * (1.0 - uRestAlpha), 0.55 * aGroup);
  gl_PointSize = (uBase + f * uFlash + aGroup * uBonus) * uDpr;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const FRAG = `
varying vec3 vColor;
varying float vAlpha;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float r = length(d);
  if (r > 0.5) discard;
  gl_FragColor = vec4(vColor, vAlpha * smoothstep(0.5, 0.3, r));
}`;

export class BrainView {
  /**
   * @param {HTMLElement} el container
   * @param {{ids: string[], xyz: number[]}} positions body of /api/positions
   * @param {(id: string) => string} colorGroup neuron ID -> color group name
   */
  constructor(el, positions, colorGroup, config = CONFIG) {
    this.config = config;
    this.el = el;
    this.index = new Map(positions.ids.map((id, i) => [id, i]));
    const n = positions.ids.length;
    this.n = n;

    const pos = new Float32Array(positions.xyz);
    // Center, and flip y so dorsal is up (EM image y grows downward).
    const c = [0, 1, 2].map((k) => {
      let s = 0;
      for (let i = k; i < pos.length; i += 3) s += pos[i];
      return s / n;
    });
    let radius = 0;
    for (let i = 0; i < pos.length; i += 3) {
      pos[i] -= c[0];
      pos[i + 1] = -(pos[i + 1] - c[1]);
      pos[i + 2] -= c[2];
      radius = Math.max(radius, Math.hypot(pos[i], pos[i + 1], pos[i + 2]));
    }

    const color = new Float32Array(3 * n);
    const group = new Float32Array(n);
    const tmp = new THREE.Color();
    positions.ids.forEach((id, i) => {
      const g = colorGroup(id);
      tmp.set(config.colors[g] ?? config.colors.other);
      color.set([tmp.r, tmp.g, tmp.b], 3 * i);
      group[i] = g === "other" ? 0 : 1;
    });
    this.flash = new Float32Array(n);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("aColor", new THREE.BufferAttribute(color, 3));
    geo.setAttribute("aGroup", new THREE.BufferAttribute(group, 1));
    this.flashAttr = new THREE.BufferAttribute(this.flash, 1).setUsage(THREE.DynamicDrawUsage);
    geo.setAttribute("aFlash", this.flashAttr);

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const mat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      uniforms: {
        uBase: { value: config.pointSizeBase },
        uFlash: { value: config.pointSizeFlash },
        uBonus: { value: config.pointSizeGroupBonus },
        uDpr: { value: dpr },
        uRestAlpha: { value: config.restAlpha },
        uRest: { value: new THREE.Color(config.colors.rest) },
      },
    });
    this.points = new THREE.Points(geo, mat);

    this.scene = new THREE.Scene();
    this.scene.add(this.points);
    this.camera = new THREE.PerspectiveCamera(35, 1, radius * 0.05, radius * 10);
    this.camera.position.set(0, 0, radius * config.cameraDistance); // front view, along the section axis
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(dpr);
    el.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.autoRotate = config.autoRotateDegPerSec > 0;
    // OrbitControls: autoRotateSpeed 1 = one turn per 60 s = 6 deg/s.
    this.controls.autoRotateSpeed = config.autoRotateDegPerSec / 6;
    this.lastMs = performance.now();
    this.litCount = 0;
    this.flashedTotal = 0;
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

  /** Decay flashes (unless `frozen`) and draw one frame. Returns how many neurons are lit. */
  render(frozen = false) {
    const now = performance.now();
    const k = frozen ? 1 : Math.exp(-(now - this.lastMs) / this.config.flashDecayMs);
    this.lastMs = now;
    let lit = 0;
    for (let i = 0; i < this.n; i++) {
      const f = this.flash[i] * k;
      this.flash[i] = f < 0.01 ? 0 : f;
      if (f > 0.1) lit += 1;
    }
    this.flashAttr.needsUpdate = true;
    this.litCount = lit;

    const { clientWidth: w, clientHeight: h } = this.el;
    const size = this.renderer.getSize(new THREE.Vector2());
    if (size.x !== w || size.y !== h) {
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / Math.max(1, h);
      this.camera.updateProjectionMatrix();
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    return lit;
  }
}
