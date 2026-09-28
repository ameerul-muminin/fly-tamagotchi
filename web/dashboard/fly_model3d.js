// The flybody fruit fly (Vaxenburg et al. 2025, TuragaLab/flybody, Apache-2.0), built into
// one GLB by server/fly_model.py and posed through its MuJoCo joints. setState() takes the
// display state from state.js; render() animates toward it. What the fly does comes from
// the brain (eating = MN9 spikes, disgust = bitter-neuron spikes; see fly_motion.js). This
// file only draws it. Units: 1 scene unit = 1 mm.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { CONFIG } from "./config.js";
import { POSES, blendPose, pumpHz, groomWeight, nextFullness, approach } from "./fly_motion.js";
import { detectQuality } from "./fly3d.js";
import { cubicBezier } from "./ease.js";

/**
 * Load the model for a render quality ("high" | "low"); rejects when it isn't built (the
 * caller falls back to the simple fly).
 */
export function loadFlyModel(quality = "high", urls = CONFIG.flyModelUrl) {
  return new GLTFLoader().loadAsync(urls[quality] ?? urls.high);
}

// Colors picked for three.js lighting (sRGB), by the model's MJCF material names.
const MATERIALS = {
  body: { color: "#cfa576", roughness: 0.55 },
  abdomen: { color: "#ad7b48", roughness: 0.5 },
  lower: { color: "#e6cfa2", roughness: 0.6 },
  red: { color: "#a3121a", roughness: 0.3 },
  ocelli: { color: "#3a1a0c", roughness: 0.3 },
  black: { color: "#24170c", roughness: 0.6 },
  "bristle-brown": { color: "#24170c", roughness: 0.6 },
  brown: { color: "#6b4526", roughness: 0.5 },
  membrane: { color: "#e4ebf2", roughness: 0.2, opacity: 0.3 },
};

// Joint angles (rad) found by posing the model: the proboscis tucked vs fully out, and
// front legs raised to the head for grooming.
const PROBOSCIS = { rostrum: [0.8, -0.8], haustellum: [0.8, -1.2] };
const GROOM_T1 = { coxa: 1.4, femur: 1.6, tibia: -1.0 };
const SIDES = ["left", "right"];
const ease = cubicBezier(0.77, 0, 0.175, 1);   // on-screen movement (emil-design-eng)

export class FlyModel3D {
  /**
   * @param {HTMLElement} el container (gets data-state and data-quality)
   * @param {object} gltf result of loadFlyModel()
   * @param {"auto"|"high"|"low"} quality "low" (software renderers): no shadows or
   *   reflections, lower resolution, capped frame rate
   */
  constructor(el, gltf, config = CONFIG, quality = "auto") {
    this.el = el;
    this.config = config;
    this.cfg = config.fly3d;
    this.quality = quality === "high" || quality === "low" ? quality : detectQuality();
    this.hi = this.quality === "high";
    el.dataset.quality = this.quality;
    this.state = "idle";
    this.food = { sugar: false, bitter: false };
    this.mn9Hz = 0;
    this.pose = { ...POSES.idle };
    this.t = 0;
    this.lastMs = performance.now();
    this.pumpPhase = 0;
    this.fullness = 0;
    this.groom = 0;
    this.drop = { sugar: 0, bitter: 0 };

    const dpr = this.hi ? Math.min(window.devicePixelRatio || 1, this.cfg.maxPixelRatio) : this.cfg.lowPixelRatio;
    this.renderer = new THREE.WebGLRenderer({ antialias: this.hi, alpha: true, preserveDrawingBuffer: false });
    this.renderer.setPixelRatio(dpr);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = this.hi;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    el.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    if (this.hi) {
      const pmrem = new THREE.PMREMGenerator(this.renderer);
      this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    }
    this.buildLights();
    this.buildGround();
    this.buildFly(gltf);
    this.buildDrops();

    this.camera = new THREE.PerspectiveCamera(this.cfg.fov, 1, 0.05, 200);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.minDistance = 2.2;
    this.controls.maxDistance = 14;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.addEventListener("start", () => {
      this.tween = null;      // the user took over the camera
      this.drifting = false;
    });
    this.view = "side";
    this.setView("side", true);
    this.setState("idle");
  }

  // ------------------------------------------------------------------ scene parts
  buildLights() {
    this.key = new THREE.DirectionalLight(0xffffff, 2.4);
    this.key.position.set(-3, 7, -4);
    this.key.castShadow = this.hi;
    this.key.shadow.mapSize.set(this.cfg.shadowMapSize, this.cfg.shadowMapSize);
    Object.assign(this.key.shadow.camera, { left: -3.5, right: 3.5, top: 3.5, bottom: -3.5, near: 1, far: 20 });
    this.key.shadow.radius = 5;
    this.key.shadow.bias = -0.0005;
    this.fill = new THREE.DirectionalLight(0xdbe6ff, 0.8);
    this.fill.position.set(4, 3, 5);
    this.hemi = new THREE.HemisphereLight(0xe8edf5, 0x2b2e34, this.hi ? 0.7 : 1.4);
    this.moon = new THREE.DirectionalLight(0x6f8cff, 0);
    this.moon.position.set(2, 5, -2);
    this.scene.add(this.key, this.fill, this.hemi, this.moon);
    this.base = { key: this.key.intensity, fill: this.fill.intensity, hemi: this.hemi.intensity, env: 0.55 };
  }

  buildGround() {
    // Real shadow on a GPU; a soft blob under the fly everywhere (grounds it in low quality).
    const g = new THREE.PlaneGeometry(40, 40);
    this.ground = new THREE.Mesh(g, new THREE.ShadowMaterial({ opacity: 0.32 }));
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.receiveShadow = true;
    this.ground.visible = this.hi;
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const ctx = c.getContext("2d");
    const grad = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
    grad.addColorStop(0, "rgba(0,0,0,0.5)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 128, 128);
    this.blob = new THREE.Mesh(new THREE.PlaneGeometry(3.4, 1.9),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
    this.blob.rotation.x = -Math.PI / 2;
    this.blob.position.set(-0.1, 0.002, 0);
    this.scene.add(this.ground, this.blob);
  }

  buildFly(gltf) {
    // MuJoCo: z up, head along +x, centimetres. Here: y up, millimetres.
    this.fly = new THREE.Group();
    const model = new THREE.Group();
    model.rotation.x = -Math.PI / 2;
    model.scale.setScalar(10);
    model.add(gltf.scene);
    this.fly.add(model);
    this.scene.add(this.fly);

    const mats = {};
    const mat = (name) => {
      if (!mats[name]) {
        const m = MATERIALS[name] ?? MATERIALS.body;
        // Low quality: Lambert shading, far cheaper per pixel on a software renderer.
        const Mat = this.hi ? THREE.MeshStandardMaterial : THREE.MeshLambertMaterial;
        mats[name] = new Mat({
          color: m.color, ...(this.hi ? { roughness: m.roughness, metalness: 0 } : {}),
          transparent: m.opacity != null, opacity: m.opacity ?? 1,
          side: m.opacity != null ? THREE.DoubleSide : THREE.FrontSide,
          depthWrite: m.opacity == null,
        });
      }
      return mats[name];
    };
    this.materials = mats;
    this.nodes = new Map();
    gltf.scene.traverse((o) => {
      this.nodes.set(o.name, o);
      o.userData.base = o.quaternion.clone();
      if (o.isMesh) {
        o.geometry.computeVertexNormals();
        let name = o.material?.name || "body";
        // Darker dorsal abdomen plates, as on a real fly.
        if (name === "body" && /^abdomen/.test(o.name) && !/lower/.test(o.name)) name = "abdomen";
        o.material = mat(name);
        o.castShadow = name !== "membrane";
        if (name === "membrane") o.renderOrder = 2;
      }
    });
    const extras = gltf.parser.json.scenes?.[0]?.extras ?? {};
    this.joints = new Map();
    for (const j of extras.joints ?? []) {
      this.joints.set(j.name, { ...j, axis: new THREE.Vector3(...j.axis).normalize(), angle: 0 });
    }
    this.jointsByBody = new Map();
    for (const j of this.joints.values()) {
      if (!this.jointsByBody.has(j.body)) this.jointsByBody.set(j.body, []);
      this.jointsByBody.get(j.body).push(j);
    }
    this.abdomenNode = this.nodes.get("abdomen");

    // Where the labellum touches down with the proboscis out: the food drop goes there.
    this.poseJoints({ ...POSES.eating }, 0, 0);
    this.scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(model);
    this.standY = -box.min.y;
    this.fly.position.y = this.standY;
    this.scene.updateMatrixWorld(true);
    const tip = new THREE.Vector3();
    const labra = ["labrum_left", "labrum_right"].map((n) => this.nodes.get(n)).filter(Boolean);
    for (const n of labra) tip.add(n.getWorldPosition(new THREE.Vector3()).multiplyScalar(1 / labra.length));
    this.dropAt = tip;
    this.poseJoints({ ...POSES.idle }, 0, 0);
  }

  buildDrops() {
    // A dome of liquid on the floor, tall enough that the extended labellum dips into it.
    const geo = new THREE.SphereGeometry(1, 40, 14, 0, Math.PI * 2, 0, Math.PI / 2);
    this.dropSize = { r: 0.36, h: Math.max(0.15, this.dropAt.y - 0.06) };
    const make = (color) => {
      const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
        color, roughness: 0.05, metalness: 0, transparent: true, opacity: 0.72,
      }));
      m.scale.setScalar(0.0001);
      m.position.set(this.dropAt.x + 0.04, 0.001, 0);
      this.scene.add(m);
      return m;
    };
    this.drops = { sugar: make("#f3dca0"), bitter: make("#b69cf0") };
  }

  // ------------------------------------------------------------------ joints
  setJoint(name, angle) {
    const j = this.joints.get(name);
    if (j) j.angle = angle;
  }

  /** Apply every joint angle to its body node (MJCF: body frame, then joints in order). */
  applyJoints() {
    const q = new THREE.Quaternion();
    for (const [body, js] of this.jointsByBody) {
      const node = this.nodes.get(body);
      if (!node) continue;
      node.quaternion.copy(node.userData.base);
      for (const j of js) if (j.angle) node.quaternion.multiply(q.setFromAxisAngle(j.axis, j.angle));
    }
  }

  /** Set joint angles for a pose (see fly_motion.POSES) at time t. */
  poseJoints(p, t, pump) {
    for (const j of this.joints.values()) j.angle = j.name.startsWith("wing") ? j.rest : 0;

    // Proboscis: tucked -> out with p.proboscis; the pump rocks the tip and opens the
    // labellum at the MN9-driven rate.
    const ext = p.proboscis;
    const lerp = (a, b, k) => a + (b - a) * k;
    this.setJoint("rostrum", lerp(...PROBOSCIS.rostrum, ext));
    this.setJoint("haustellum", lerp(...PROBOSCIS.haustellum, ext) + 0.22 * pump * ext);
    for (const s of SIDES) this.setJoint(`labrum_${s}`, 0.55 * pump * ext);

    // Head: pitch by state (+ = face down), idle glances, a shudder when disgusted.
    const glance = this.state === "idle" ? 0.14 * Math.sin(t * 0.7) * Math.sin(t * 0.23) : 0;
    this.setJoint("head", p.headPitch * 0.9);
    this.setJoint("head_abduct", glance);
    this.setJoint("head_twist", p.buzz * 0.06 * Math.sin(t * 43));

    // Antennae: small twitches when awake, still when resting.
    for (const [k, s] of SIDES.entries()) {
      const twitch = this.state === "resting" ? 0 : 0.18 * Math.max(0, Math.sin(t * 2.3 + 1.7 * k)) ** 10;
      this.setJoint(`antenna_${s}`, twitch - 0.12 * p.antennaDroop);
    }

    // Wings: folded; spread a little and buzz when disgusted, one quick flick when idle.
    const flick = this.flick ?? 0;
    for (const [k, s] of SIDES.entries()) {
      const buzz = p.buzz * Math.sin(t * 157 + k * 0.6);
      const yaw = this.joints.get(`wing_yaw_${s}`);
      const roll = this.joints.get(`wing_roll_${s}`);
      if (yaw) yaw.angle = yaw.rest - 0.9 * p.wingSpread - 0.25 * flick;
      if (roll) roll.angle = roll.rest + 0.35 * buzz + 0.3 * flick;
    }

    // Front legs groom (rub together in front of the head) when idle now and then, and
    // constantly when disgusted (see fly_motion.groomWeight).
    const g = this.groom;
    if (g > 0.001) {
      const rubHz = this.state === "disgusted" ? 5 : 2.2;
      for (const [k, s] of SIDES.entries()) {
        const rub = Math.sin(t * Math.PI * 2 * rubHz + k * Math.PI);
        this.setJoint(`coxa_T1_${s}`, g * GROOM_T1.coxa);
        this.setJoint(`femur_T1_${s}`, g * (GROOM_T1.femur + 0.15 * rub));
        this.setJoint(`tibia_T1_${s}`, g * (GROOM_T1.tibia + 0.2 * rub));
        this.setJoint(`coxa_abduct_T1_${s}`, g * 0.12 * rub);
      }
    }

    // Abdomen: breathing, and a slight sag while resting.
    const breath = Math.sin(t * Math.PI * 2 * (this.state === "resting" ? 0.25 : 0.55));
    for (let n = 1; n <= 7; n++) {
      this.setJoint(n === 1 ? "abdomen" : `abdomen_${n}`, 0.012 * breath + 0.015 * p.antennaDroop);
    }
    this.applyJoints();
  }

  // ------------------------------------------------------------------ camera
  /** Switch to a named view ("side", "top", "follow"); animated unless `instant`. */
  setView(name, instant = false) {
    const v = this.config.flyViews[name];
    if (!v) return;
    this.view = name;
    this.drifting = name === "follow";
    this.driftT0 = this.t;
    const to = { radius: v.radius, polar: v.polar, azimuth: v.azimuth, target: new THREE.Vector3(...v.target) };
    if (instant) {
      this.placeCamera(to);
      this.tween = null;
      return;
    }
    const from = this.currentSpherical();
    // Shortest way round.
    let dAz = to.azimuth - from.azimuth;
    dAz = Math.atan2(Math.sin(dAz), Math.cos(dAz));
    this.tween = { from, to: { ...to, azimuth: from.azimuth + dAz }, t0: performance.now() };
  }

  currentSpherical() {
    const off = this.camera.position.clone().sub(this.controls.target);
    const s = new THREE.Spherical().setFromVector3(off);
    return { radius: s.radius, polar: s.phi, azimuth: s.theta, target: this.controls.target.clone() };
  }

  placeCamera(s) {
    this.controls.target.copy(s.target);
    const off = new THREE.Vector3().setFromSpherical(new THREE.Spherical(s.radius, s.polar, s.azimuth));
    this.camera.position.copy(s.target).add(off);
    this.camera.lookAt(s.target);
  }

  /** Pixels per millimetre at the camera target (for the scale bar). */
  pxPerMm() {
    const h = this.el.clientHeight || 1;
    const d = this.camera.position.distanceTo(this.controls.target);
    return h / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * d);
  }

  // ------------------------------------------------------------------ frame
  setState(state, food = {}, drive = {}) {
    this.state = POSES[state] ? state : "idle";
    this.food = { sugar: !!food.sugar, bitter: !!food.bitter };
    this.mn9Hz = drive.mn9Hz ?? 0;
    this.el.dataset.state = this.state;
  }

  render(now = performance.now()) {
    if (!this.hi && now - this.lastMs < 1000 / this.cfg.lowMaxFps - 1) return;
    const dt = Math.min(0.05, Math.max(0, (now - this.lastMs) / 1000));
    this.lastMs = now;
    this.t += dt;
    const t = this.t;
    const c = this.cfg;
    this.pose = blendPose(this.pose, POSES[this.state], dt, c.poseTauSec);
    const p = this.pose;

    this.pumpPhase += dt * Math.PI * 2 * pumpHz(this.mn9Hz, c);
    const pump = this.state === "eating" ? 0.5 * (1 + Math.sin(this.pumpPhase)) : 0;
    this.groom = approach(this.groom, groomWeight(this.state, t, c), dt, 0.25);
    if (this.state === "idle" && t > (this.nextFlick ?? 4)) {
      this.flickStart = t;
      this.nextFlick = t + 5 + 4 * Math.random();
    }
    const since = t - (this.flickStart ?? -10);
    this.flick = this.state === "idle" ? Math.max(0, 1 - Math.abs(since - 0.15) / 0.15) : 0;
    this.poseJoints(p, t, pump);

    // Body: lean toward the food while eating, rear back when disgusted, sink a touch
    // when resting. Belly swells with eating time (a drawing of MN9-driven eating).
    this.fly.position.set(0.25 * p.bodyX, this.standY + 0.25 * p.bodyY, 0);
    this.fullness = nextFullness(this.fullness, this.state === "eating", dt, c);
    if (this.abdomenNode) this.abdomenNode.scale.setScalar(1 + 0.07 * this.fullness);

    // Food drops: the phone input that is on, under the proboscis tip.
    const both = this.food.sugar && this.food.bitter;
    for (const k of ["sugar", "bitter"]) {
      const on = this.food[k];
      this.drop[k] = approach(this.drop[k], on ? 1 : 0, dt, on ? 0.12 : 0.2);
      const d = this.drops[k];
      const s = Math.max(0.0001, this.drop[k]);
      const wob = 1 + 0.04 * Math.sin(t * 8 + (k === "sugar" ? 0 : 2)) * s;
      const { r, h } = this.dropSize;
      d.scale.set(r * s * wob, h * s / wob, r * s * wob);
      d.position.z = approach(d.position.z, both ? (k === "sugar" ? 0.3 : -0.3) : 0, dt, 0.2);
    }

    // Light: dims for resting (game-only light level).
    const L = p.light;
    this.key.intensity = this.base.key * L;
    this.fill.intensity = this.base.fill * L;
    this.hemi.intensity = this.base.hemi * (0.1 + 0.9 * L);
    this.moon.intensity = 0.9 * (1 - L);
    this.scene.environmentIntensity = this.base.env * (0.12 + 0.88 * L);

    // Camera: view tween, then the slow drift of the follow view.
    if (this.tween) {
      const k = Math.min(1, (performance.now() - this.tween.t0) / this.config.flyViewMs);
      const e = ease(k);
      const { from, to } = this.tween;
      this.placeCamera({
        radius: from.radius + (to.radius - from.radius) * e,
        polar: from.polar + (to.polar - from.polar) * e,
        azimuth: from.azimuth + (to.azimuth - from.azimuth) * e,
        target: from.target.clone().lerp(to.target, e),
      });
      if (k >= 1) {
        this.tween = null;
        this.driftT0 = t;
      }
    } else if (this.drifting) {
      const v = this.config.flyViews.follow;
      const s = this.currentSpherical();
      s.azimuth = v.azimuth + v.drift * Math.sin((t - this.driftT0) * 0.22);
      this.placeCamera(s);
    }

    const { clientWidth: w, clientHeight: h } = this.el;
    const size = this.renderer.getSize(new THREE.Vector2());
    if (w && h && (size.x !== w || size.y !== h)) {
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      const narrow = this.cfg.wideAspect / this.camera.aspect;
      this.camera.fov = narrow > 1 ? Math.min(this.cfg.maxFov, this.cfg.fov * narrow) : this.cfg.fov;
      this.camera.updateProjectionMatrix();
    }
    if (!this.tween) this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
