// 3D Drosophila on a dish (three.js), built from primitives: no model files to download.
// setState() takes the display state from state.js; render() animates toward it. What the
// fly does comes from the brain (see fly_motion.js); this file only draws it.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { CONFIG } from "./config.js";
import { POSES, blendPose, pumpHz, groomWeight, nextFullness, approach, qualityForRenderer } from "./fly_motion.js";

const BODY_Y = 0.78;          // thorax height above the dish when standing
const DROP_X = 1.45;          // food drop, under the extended proboscis
const COLORS = {
  cuticle: 0xa8743d,
  thoraxTop: 0x6e4a24,
  head: 0xc28a4c,
  eye: 0xb0141b,
  leg: 0x3a2814,
  dish: 0x1a2536,
  rim: 0x9fb8d8,
};

// ------------------------------------------------------------------ textures
function canvasTexture(w, h, draw, srgb = true) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

/** Compound eye: a hexagonal grid of ommatidia. */
function eyeTextures() {
  const draw = (bump) => (g, w, h) => {
    g.fillStyle = bump ? "#000" : "#7d0c12";
    g.fillRect(0, 0, w, h);
    const r = 3.2;
    const dx = r * 2;
    const dy = r * Math.sqrt(3);
    for (let row = 0, y = 0; y < h + r; row++, y += dy) {
      for (let x = row % 2 ? r : 0; x < w + r; x += dx) {
        const grad = g.createRadialGradient(x - 0.8, y - 0.8, 0.2, x, y, r);
        if (bump) {
          grad.addColorStop(0, "#fff");
          grad.addColorStop(1, "#000");
        } else {
          grad.addColorStop(0, "#ff5a4a");
          grad.addColorStop(0.6, "#c0161e");
          grad.addColorStop(1, "#5e080c");
        }
        g.fillStyle = grad;
        g.beginPath();
        g.arc(x, y, r * 0.92, 0, Math.PI * 2);
        g.fill();
      }
    }
  };
  return { map: canvasTexture(256, 256, draw(false)), bump: canvasTexture(256, 256, draw(true), false) };
}

/** Abdomen: tan with dark bands on the back of each segment, fading toward the belly. */
function abdomenTexture() {
  return canvasTexture(256, 256, (g, w, h) => {
    g.fillStyle = "#b8843f";
    g.fillRect(0, 0, w, h);
    // Lathe u = around the body; the back (world up) is at u = 0.25.
    const bands = [0.34, 0.46, 0.58, 0.7, 0.82];
    for (let x = 0; x < w; x++) {
      const u = x / w;
      const dorsal = Math.max(0, Math.cos(2 * Math.PI * (u - 0.25)));
      for (const v of bands) {
        const y = (1 - v) * h;
        g.fillStyle = `rgba(52, 30, 12, ${0.9 * Math.pow(dorsal, 0.6)})`;
        g.fillRect(x, y - 9, 1, 13 + 6 * dorsal);
      }
    }
    // Darker tip.
    g.fillStyle = "rgba(52, 30, 12, 0.85)";
    g.fillRect(0, 0, w, 0.06 * h);
  });
}

/** Thorax: darker on top with fine speckles (bristle sockets). */
function thoraxTexture() {
  return canvasTexture(256, 128, (g, w, h) => {
    const grad = g.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "#5e3d1c");
    grad.addColorStop(0.45, "#96652f");
    grad.addColorStop(1, "#b98449");
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
    g.fillStyle = "rgba(30, 18, 8, 0.5)";
    for (let i = 0; i < 700; i++) g.fillRect(Math.random() * w, Math.random() * h * 0.6, 1.2, 1.2);
  });
}

function dishTexture() {
  return canvasTexture(512, 512, (g, w, h) => {
    const grad = g.createRadialGradient(w / 2, h / 2, 10, w / 2, h / 2, w / 2);
    grad.addColorStop(0, "#26354d");
    grad.addColorStop(0.75, "#1a2536");
    grad.addColorStop(1, "#121a27");
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
    g.strokeStyle = "rgba(159, 184, 216, 0.07)";
    g.lineWidth = 1;
    for (let r = 40; r < w / 2; r += 40) {
      g.beginPath();
      g.arc(w / 2, h / 2, r, 0, Math.PI * 2);
      g.stroke();
    }
  });
}

function spriteTexture(draw) {
  return canvasTexture(128, 128, (g, w, h) => draw(g, w, h));
}

// ------------------------------------------------------------------ quality
/** "high" on a real GPU, "low" on a software renderer (see qualityForRenderer). */
export function detectQuality() {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    if (!gl) return "low";
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const name = gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return qualityForRenderer(name);
  } catch {
    return "low";
  }
}

// ------------------------------------------------------------------ helpers
const UP = new THREE.Vector3(0, 1, 0);
const tmpV = new THREE.Vector3();

/** A unit cylinder along +y from 0 to 1, stretched between two points each frame. */
function segmentMesh(radius, material) {
  const geo = new THREE.CylinderGeometry(radius * 0.8, radius, 1, 8, 1);
  geo.translate(0, 0.5, 0);
  const m = new THREE.Mesh(geo, material);
  m.castShadow = true;
  return m;
}

function placeSegment(mesh, a, b) {
  tmpV.subVectors(b, a);
  const len = tmpV.length();
  mesh.position.copy(a);
  mesh.quaternion.setFromUnitVectors(UP, tmpV.normalize());
  mesh.scale.set(1, len, 1);
}

function wingShape() {
  const s = new THREE.Shape();
  s.moveTo(0, 0.03);
  s.bezierCurveTo(0.4, 0.16, 1.1, 0.26, 1.5, 0.18);
  s.quadraticCurveTo(1.7, 0.04, 1.5, -0.12);
  s.bezierCurveTo(1.1, -0.3, 0.45, -0.28, 0.12, -0.1);
  s.lineTo(0, -0.03);
  s.closePath();
  return s;
}

/** Wing veins (Drosophila L1-L5 and two crossveins) in wing-shape coordinates. */
function wingVeins() {
  const pts = [];
  const curve = (a, c, b) => {
    const q = new THREE.QuadraticBezierCurve(new THREE.Vector2(...a), new THREE.Vector2(...c), new THREE.Vector2(...b));
    const p = q.getPoints(12);
    for (let i = 0; i < p.length - 1; i++) pts.push(p[i].x, p[i].y, 0, p[i + 1].x, p[i + 1].y, 0);
  };
  curve([0.02, 0.03], [0.7, 0.2], [1.5, 0.18]);    // costa / L1
  curve([0.05, 0.02], [0.8, 0.14], [1.47, 0.16]);  // L2
  curve([0.06, 0.0], [0.9, 0.04], [1.66, 0.02]);   // L3
  curve([0.08, -0.03], [0.9, -0.1], [1.5, -0.13]); // L4
  curve([0.1, -0.06], [0.7, -0.2], [1.12, -0.28]); // L5
  pts.push(0.72, 0.035, 0, 0.72, -0.085, 0);        // anterior crossvein
  pts.push(1.02, 0.03, 0, 1.0, -0.19, 0);           // posterior crossvein
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return geo;
}

// ------------------------------------------------------------------ the fly
export class Fly3D {
  /**
   * @param {HTMLElement} el container (gets data-state for the validation script)
   * @param {"auto"|"high"|"low"} quality "high": antialiasing, shadows, reflections;
   *   "low": none of those, lower resolution (for software renderers). "auto" picks by GPU.
   */
  constructor(el, config = CONFIG, quality = "auto") {
    this.el = el;
    this.cfg = config.fly3d;
    this.quality = quality === "high" || quality === "low" ? quality : detectQuality();
    this.hi = this.quality === "high";
    el.dataset.quality = this.quality;
    this.frameMs = [];
    this.colors = config.colors;
    this.state = "idle";
    this.food = { sugar: false, bitter: false };
    this.mn9Hz = 0;
    this.pose = { ...POSES.idle };
    this.t = 0;
    this.lastMs = performance.now();
    this.pumpPhase = 0;
    this.fullness = 0;
    this.dropScale = { sugar: 0, bitter: 0 };
    this.nextParticleAt = 0;
    this.flickAt = 3;

    const dpr = this.hi ? Math.min(window.devicePixelRatio || 1, this.cfg.maxPixelRatio) : this.cfg.lowPixelRatio;
    this.renderer = new THREE.WebGLRenderer({ antialias: this.hi, alpha: true, preserveDrawingBuffer: false });
    this.renderer.setPixelRatio(dpr);
    this.renderer.shadowMap.enabled = this.hi;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.95;
    el.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    if (this.hi) {
      const pmrem = new THREE.PMREMGenerator(this.renderer);
      this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      this.scene.environmentIntensity = 0.45;
    }

    this.camera = new THREE.PerspectiveCamera(this.cfg.fov, 1, 0.1, 60);
    this.camera.position.set(4.6, 2.9, 6.6);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0.15, 0.5, 0);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.minDistance = 4;
    this.controls.maxDistance = 12;
    this.controls.maxPolarAngle = Math.PI * 0.47;
    this.controls.update();

    this.buildLights();
    this.buildDish();
    this.buildFly();
    this.buildDrops();
    this.buildParticles();
    this.setState("idle", this.food, {});
  }

  // ---------------------------------------------------------------- scene parts
  buildLights() {
    this.hemi = new THREE.HemisphereLight(0xcfe3ff, 0x2a1d10, 0.7);
    this.key = new THREE.DirectionalLight(0xfff1dc, 2.4);
    this.key.position.set(3, 6, 2.5);
    this.key.castShadow = this.hi;
    this.key.shadow.mapSize.set(this.cfg.shadowMapSize, this.cfg.shadowMapSize);
    Object.assign(this.key.shadow.camera, { left: -2.6, right: 2.6, top: 2.6, bottom: -2.6, near: 1, far: 14 });
    this.key.shadow.radius = 4;
    this.key.shadow.bias = -0.0005;
    this.rim = new THREE.DirectionalLight(0x7fb6ff, 1.4);
    this.rim.position.set(-4, 2.5, -3);
    this.moon = new THREE.DirectionalLight(0x4a6fb5, 0);
    this.moon.position.set(-1, 4, 3);
    this.scene.add(this.hemi, this.key, this.rim, this.moon);
    // Without reflections (low quality) the hemisphere light makes up the missing fill.
    this.baseIntensity = { hemi: this.hi ? 0.7 : 1.5, key: 2.4, rim: 1.4, env: 0.45 };
  }

  buildDish() {
    // The dish covers most of the view, so in low quality it is unlit (cheapest to draw).
    this.dishMat = this.hi
      ? new THREE.MeshStandardMaterial({ map: dishTexture(), roughness: 0.85, metalness: 0 })
      : new THREE.MeshBasicMaterial({ map: dishTexture() });
    const dish = new THREE.Mesh(new THREE.CylinderGeometry(3.3, 3.3, 0.06, 96), this.dishMat);
    dish.position.y = -0.03;
    dish.receiveShadow = true;
    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(3.3, 0.05, 12, 128),
      this.hi
        ? new THREE.MeshPhysicalMaterial({ color: COLORS.rim, roughness: 0.1, transparent: true, opacity: 0.35, clearcoat: 1 })
        : new THREE.MeshBasicMaterial({ color: COLORS.rim, transparent: true, opacity: 0.25 }),
    );
    rim.rotation.x = Math.PI / 2;
    rim.position.y = 0.02;
    this.scene.add(dish, rim);

    // A true 1 mm scale bar on the dish.
    const mm = this.cfg.unitsPerMm;
    const bar = new THREE.Mesh(
      new THREE.BoxGeometry(mm, 0.012, 0.035),
      new THREE.MeshBasicMaterial({ color: 0xe6ebf3, toneMapped: false }),
    );
    bar.position.set(1.5, 0.006, 1.5);
    const label = new THREE.Sprite(new THREE.SpriteMaterial({
      map: spriteTexture((g, w, h) => {
        g.fillStyle = "#e6ebf3";
        g.font = "600 44px 'Atkinson Hyperlegible', system-ui, sans-serif";
        g.textAlign = "center";
        g.textBaseline = "middle";
        g.fillText("1 mm", w / 2, h / 2);
      }),
      transparent: true,
      depthWrite: false,
    }));
    label.scale.set(0.34, 0.34, 1);
    label.position.set(1.5, 0.12, 1.5);
    this.scene.add(bar, label);
  }

  buildFly() {
    const cuticle = new THREE.MeshStandardMaterial({ color: COLORS.cuticle, roughness: 0.55 });
    const legMat = new THREE.MeshStandardMaterial({ color: COLORS.leg, roughness: 0.6 });
    this.legMat = legMat;

    this.body = new THREE.Group();
    this.scene.add(this.body);

    // Thorax
    const thorax = new THREE.Mesh(
      new THREE.SphereGeometry(1, 40, 28),
      new THREE.MeshStandardMaterial({ map: thoraxTexture(), roughness: 0.5 }),
    );
    thorax.scale.set(0.5, 0.42, 0.42);
    thorax.position.set(0.35, 0.06, 0);
    thorax.castShadow = true;
    this.body.add(thorax);

    // Bristles (macrochaetae) on the back of the thorax, pointing backward.
    const bristleGeo = new THREE.ConeGeometry(0.007, 0.17, 4);
    bristleGeo.translate(0, 0.085, 0);
    const bristles = new THREE.InstancedMesh(bristleGeo, new THREE.MeshStandardMaterial({ color: 0x1a0f06 }), 14);
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const dir = new THREE.Vector3();
    for (let i = 0; i < 14; i++) {
      const row = i % 7;
      const side = i < 7 ? 1 : -1;
      const ax = 0.62 - row * 0.1;                      // along the body
      const az = side * (0.07 + 0.09 * Math.abs(Math.sin(row * 1.3)));
      const nx = (ax - 0.35) / 0.5;
      const nz = az / 0.42;
      const ny = Math.sqrt(Math.max(0.05, 1 - nx * nx - nz * nz));
      dir.set(-0.85, 0.5, side * 0.15).normalize();
      q.setFromUnitVectors(UP, dir);
      m.compose(new THREE.Vector3(ax, 0.06 + ny * 0.42, az), q, new THREE.Vector3(1, 1, 1));
      bristles.setMatrixAt(i, m);
    }
    this.body.add(bristles);

    // Abdomen: a lathe profile, tip at the back.
    const prof = [
      [0, -0.45], [0.26, -0.42], [0.37, -0.28], [0.4, -0.05], [0.37, 0.25],
      [0.29, 0.52], [0.17, 0.76], [0.06, 0.9], [0, 0.93],
    ].map(([r, y]) => new THREE.Vector2(r, y));
    const abdGeo = new THREE.LatheGeometry(prof, 40);
    this.abdomen = new THREE.Mesh(abdGeo, new THREE.MeshStandardMaterial({ map: abdomenTexture(), roughness: 0.45 }));
    this.abdomen.rotation.z = Math.PI / 2;           // lathe +y -> world -x
    this.abdomenPivot = new THREE.Group();
    this.abdomenPivot.position.set(-0.28, -0.02, 0);
    this.abdomenPivot.add(this.abdomen);
    this.abdomen.position.set(-0.32, 0, 0);
    this.abdomen.scale.set(0.95, 1, 0.92);
    this.abdomen.castShadow = true;
    this.body.add(this.abdomenPivot);

    // Halteres (balance organs)
    for (const side of [1, -1]) {
      const h = new THREE.Mesh(new THREE.SphereGeometry(0.04, 12, 8), cuticle);
      h.position.set(0.02, 0.2, side * 0.26);
      this.body.add(h);
    }

    // Head on a neck pivot
    this.head = new THREE.Group();
    this.head.position.set(0.8, 0.12, 0);
    this.body.add(this.head);
    const headBall = new THREE.Mesh(
      new THREE.SphereGeometry(1, 36, 24),
      new THREE.MeshStandardMaterial({ color: COLORS.head, roughness: 0.5 }),
    );
    headBall.scale.set(0.2, 0.3, 0.34);
    headBall.position.set(0.12, 0, 0);
    headBall.castShadow = true;
    this.head.add(headBall);

    const eye = eyeTextures();
    this.eyeMat = new THREE.MeshPhysicalMaterial({
      map: eye.map, bumpMap: eye.bump, bumpScale: 1.2, roughness: 0.35, clearcoat: 1,
      clearcoatRoughness: 0.15, emissive: 0x5a0000, emissiveIntensity: 0,
    });
    for (const side of [1, -1]) {
      const e = new THREE.Mesh(new THREE.SphereGeometry(1, 40, 30), this.eyeMat);
      e.scale.set(0.22, 0.28, 0.15);
      e.position.set(0.2, 0.03, side * 0.26);
      e.rotation.y = side * 0.35;
      e.castShadow = true;
      this.head.add(e);
    }
    // Ocelli: three small eyes on top of the head
    const ocMat = new THREE.MeshStandardMaterial({ color: 0x3a0a08, roughness: 0.2 });
    for (const [x, z] of [[0.12, 0], [0.06, 0.05], [0.06, -0.05]]) {
      const o = new THREE.Mesh(new THREE.SphereGeometry(0.025, 10, 8), ocMat);
      o.position.set(x, 0.3, z);
      this.head.add(o);
    }

    // Antennae with feathery aristae
    this.antennae = [];
    const antMat = new THREE.MeshStandardMaterial({ color: 0xd49a55, roughness: 0.5 });
    const aristaMat = new THREE.LineBasicMaterial({ color: 0x2a1a0a });
    for (const side of [1, -1]) {
      const a = new THREE.Group();
      a.position.set(0.4, 0.1, side * 0.07);
      const seg = new THREE.Mesh(new THREE.SphereGeometry(1, 14, 10), antMat);
      seg.scale.set(0.05, 0.08, 0.05);
      seg.position.set(0.02, -0.05, 0);
      a.add(seg);
      const pts = [0, -0.02, 0, 0.1, 0.22, side * 0.08];
      for (let k = 1; k <= 5; k++) {
        const f = k / 6;
        const x = 0.1 * f;
        const y = -0.02 + 0.24 * f;
        const z = side * 0.08 * f;
        pts.push(x, y, z, x + 0.035, y + 0.02, z + side * 0.01, x, y, z, x - 0.03, y + 0.02, z - side * 0.01);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      a.add(new THREE.LineSegments(g, aristaMat));
      this.head.add(a);
      this.antennae.push({ group: a, side });
    }

    // Proboscis: rostrum + labellum, extends downward from under the head.
    this.proboscis = new THREE.Group();
    this.proboscis.position.set(0.3, -0.2, 0);
    this.proboscis.rotation.z = 0.35;                // tip points forward
    const rostGeo = new THREE.CylinderGeometry(0.045, 0.06, 1, 12);
    rostGeo.translate(0, -0.5, 0);
    const rostrum = new THREE.Mesh(rostGeo, new THREE.MeshStandardMaterial({ color: 0x9c6a38, roughness: 0.5 }));
    this.rostrum = rostrum;
    this.labellum = new THREE.Mesh(
      new THREE.SphereGeometry(1, 20, 14),
      new THREE.MeshStandardMaterial({ color: 0x7a4f26, roughness: 0.45 }),
    );
    this.labellum.scale.set(0.09, 0.05, 0.12);
    this.proboscis.add(rostrum, this.labellum);
    this.head.add(this.proboscis);

    // Wings: membrane + veins, on pivots at the wing base.
    const membrane = new THREE.ShapeGeometry(wingShape(), 24);
    const wingMat = new THREE.MeshPhysicalMaterial({
      color: 0xf2f7ff, roughness: 0.25, transparent: true, opacity: 0.2, emissive: 0x6f8fb8, emissiveIntensity: 0.15, side: THREE.DoubleSide,
      depthWrite: false, iridescence: 1, iridescenceIOR: 1.3, iridescenceThicknessRange: [200, 600],
    });
    this.wingMat = wingMat;
    const veinMat = new THREE.LineBasicMaterial({ color: 0x5a4a38, transparent: true, opacity: 0.45 });
    const veins = wingVeins();
    this.wings = [];
    for (const side of [1, -1]) {
      const pivot = new THREE.Group();
      pivot.rotation.order = "YXZ";
      pivot.position.set(0.42, 0.38, side * 0.1);
      const w = new THREE.Group();
      w.rotation.x = -Math.PI / 2;
      w.scale.set(1, side, 1);                        // mirror the left wing
      const mem = new THREE.Mesh(membrane, wingMat);
      mem.castShadow = true;
      w.add(mem, new THREE.LineSegments(veins, veinMat));
      pivot.add(w);
      this.body.add(pivot);
      this.wings.push({ pivot, side });
    }

    // Legs live in world space so the feet stay planted when the body moves.
    const feet = [
      [1.02, 0.46], [0.36, 0.64], [-0.34, 0.56],      // [x, |z|] front, middle, hind
    ];
    const hips = [[0.58, -0.28, 0.1], [0.4, -0.3, 0.13], [0.22, -0.28, 0.12]];
    this.legs = [];
    for (let i = 0; i < 3; i++) {
      for (const side of [1, -1]) {
        const leg = {
          i,
          side,
          hip: new THREE.Vector3(hips[i][0], hips[i][1], side * hips[i][2]),
          foot: new THREE.Vector3(feet[i][0], 0.01, side * feet[i][1]),
          segs: [segmentMesh(0.034, legMat), segmentMesh(0.027, legMat), segmentMesh(0.02, legMat)],
        };
        leg.segs.forEach((s) => this.scene.add(s));
        this.legs.push(leg);
      }
    }
  }

  buildDrops() {
    const dropGeo = new THREE.SphereGeometry(0.2, 32, 20);
    const make = (color) => {
      const mesh = new THREE.Mesh(dropGeo, new THREE.MeshPhysicalMaterial({
        color, roughness: 0.04, transparent: true, opacity: 0.82, clearcoat: 1, clearcoatRoughness: 0.03,
        emissive: color, emissiveIntensity: 0.25, envMapIntensity: 1.6,
      }));
      mesh.scale.setScalar(0.0001);
      mesh.position.set(DROP_X, 0.06, 0);
      mesh.castShadow = true;
      this.scene.add(mesh);
      return mesh;
    };
    this.drops = { sugar: make(new THREE.Color(this.colors.sugar_grn)), bitter: make(new THREE.Color(this.colors.bitter_grn)) };
  }

  buildParticles() {
    const tex = {
      z: spriteTexture((g, w, h) => {
        g.fillStyle = "#cfe0ff";
        g.font = "700 96px 'Bricolage Grotesque', system-ui, sans-serif";
        g.textAlign = "center";
        g.textBaseline = "middle";
        g.fillText("z", w / 2, h / 2);
      }),
      puff: spriteTexture((g, w, h) => {
        const grad = g.createRadialGradient(w / 2, h / 2, 4, w / 2, h / 2, w / 2);
        grad.addColorStop(0, "rgba(179, 90, 224, 0.9)");
        grad.addColorStop(1, "rgba(179, 90, 224, 0)");
        g.fillStyle = grad;
        g.fillRect(0, 0, w, h);
      }),
      spark: spriteTexture((g, w, h) => {
        g.translate(w / 2, h / 2);
        g.fillStyle = "#b9f5d4";
        g.beginPath();
        for (let k = 0; k < 8; k++) {
          const r = k % 2 ? 12 : 56;
          const a = (k * Math.PI) / 4;
          g.lineTo(Math.cos(a) * r, Math.sin(a) * r);
        }
        g.closePath();
        g.fill();
      }),
    };
    this.particleTex = tex;
    this.particles = [];
    for (let i = 0; i < 28; i++) {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex.z, transparent: true, depthWrite: false }));
      s.visible = false;
      this.scene.add(s);
      this.particles.push({ s, life: 0, age: 0, v: new THREE.Vector3(), size: 0.2 });
    }
  }

  spawn(kind, pos, vel, size, life) {
    const p = this.particles.find((q) => q.life <= 0);
    if (!p) return;
    p.s.material.map = this.particleTex[kind];
    p.s.material.needsUpdate = true;
    p.s.position.copy(pos);
    p.v.copy(vel);
    p.size = size;
    p.life = life;
    p.age = 0;
    p.s.visible = true;
  }

  // ---------------------------------------------------------------- state
  /**
   * @param {string} state idle | eating | disgusted | resting (from state.js)
   * @param {{sugar: boolean, bitter: boolean}} food which inputs are driven now
   * @param {{mn9Hz?: number}} drive brain readouts that shape the animation
   */
  setState(state, food = {}, drive = {}) {
    if (state !== this.state && state === "eating") this.burst = true;
    this.state = POSES[state] ? state : "idle";
    this.food = { sugar: !!food.sugar, bitter: !!food.bitter };
    this.mn9Hz = drive.mn9Hz ?? 0;
    this.el.dataset.state = this.state;
  }

  // ---------------------------------------------------------------- frame
  render(now = performance.now()) {
    // Low quality: draw at most lowMaxFps times a second (software rendering is slow).
    if (!this.hi && now - this.lastMs < 1000 / this.cfg.lowMaxFps - 1) return;
    this.watchFrameRate(now - this.lastMs);
    const dt = Math.min(0.05, Math.max(0, (now - this.lastMs) / 1000));
    this.lastMs = now;
    this.t += dt;
    const t = this.t;
    const c = this.cfg;
    this.pose = blendPose(this.pose, POSES[this.state], dt, c.poseTauSec);
    const p = this.pose;

    // Body: breathing, belly fullness, position.
    this.fullness = nextFullness(this.fullness, this.state === "eating", dt, c);
    const breath = Math.sin(t * Math.PI * 2 * (this.state === "resting" ? 0.25 : 0.55));
    this.body.position.set(p.bodyX, BODY_Y + p.bodyY + 0.006 * breath, 0);
    this.body.rotation.z = 0.04 * p.headPitch;
    const belly = 1 + 0.12 * this.fullness;
    this.abdomen.scale.set(0.95 * (1 + 0.02 * breath), belly * (1 + 0.015 * breath), 0.92 * belly);
    this.abdomenPivot.rotation.z = -0.05 - 0.04 * p.antennaDroop;

    // Head: pitch by state, small glances when idle, recoil shudder when disgusted.
    const glance = this.state === "idle" ? 0.18 * Math.sin(t * 0.7) * Math.sin(t * 0.23) : 0;
    const shudder = p.buzz * 0.05 * Math.sin(t * 47);
    this.head.rotation.set(shudder, glance, -p.headPitch);

    // Proboscis: extends while eating; pumps at a rate set by MN9 firing.
    this.pumpPhase += dt * Math.PI * 2 * pumpHz(this.mn9Hz, c);
    const pump = this.state === "eating" ? 0.5 * (1 + Math.sin(this.pumpPhase)) : 0;
    const ext = 0.14 + 0.5 * p.proboscis;
    this.rostrum.scale.set(1, ext * (1 - 0.1 * pump), 1);
    this.labellum.position.y = -ext * (1 - 0.1 * pump);
    const lab = 1 + 0.35 * pump * p.proboscis;
    this.labellum.scale.set(0.09 * lab, 0.05, 0.12 * lab);
    // Swing forward as it extends, so the tip reaches the drop despite the head tilt.
    this.proboscis.rotation.z = 0.35 + 0.5 * p.proboscis;

    // Antennae: twitch when idle, droop when resting.
    for (const a of this.antennae) {
      const twitch = this.state === "idle" ? 0.12 * Math.max(0, Math.sin(t * 3.1 + a.side)) ** 8 : 0;
      a.group.rotation.set(0, 0, -0.5 * p.antennaDroop + twitch);
    }

    // Wings: folded over the abdomen; buzz when disgusted; an occasional flick when idle.
    if (this.state === "idle" && t > this.flickAt) {
      this.flickStart = t;
      this.flickAt = t + 4 + Math.random() * 5;
    }
    // A 0.25 s up-and-down triangle after each flick start.
    const since = t - (this.flickStart ?? -10);
    const flick = this.state === "idle" ? 0.35 * Math.max(0, 1 - Math.abs(since - 0.125) / 0.125) : 0;
    for (const w of this.wings) {
      const jitter = p.buzz * (0.25 + 0.5 * Math.random());
      w.pivot.rotation.set(-w.side * (0.08 + jitter + flick), Math.PI + w.side * p.wingSpread, 0.12);
    }
    this.wingMat.opacity = 0.2 + 0.12 * p.buzz;

    // Legs
    const groomTarget = groomWeight(this.state, t, c);
    this.groom = approach(this.groom ?? 0, groomTarget, dt, 0.25);
    this.body.updateMatrixWorld(true);
    const headWorld = this.head.getWorldPosition(new THREE.Vector3());
    const rubHz = this.state === "disgusted" ? 5 : 2.2;
    for (const leg of this.legs) this.poseLeg(leg, headWorld, t, rubHz);

    // Food drops: grow in when the input is on, shrink when it stops.
    const both = this.food.sugar && this.food.bitter;
    for (const k of ["sugar", "bitter"]) {
      const on = this.food[k];
      const target = on ? (k === "sugar" && this.state === "eating" ? 1 - 0.3 * this.fullness : 1) : 0;
      this.dropScale[k] = approach(this.dropScale[k], target, dt, on ? 0.12 : 0.25);
      const d = this.drops[k];
      const s = Math.max(0.0001, this.dropScale[k]);
      const wob = 1 + 0.04 * Math.sin(t * 9 + (k === "sugar" ? 0 : 2)) * s;
      d.scale.set(s * wob, s * 0.55 / wob, s * wob);
      d.position.z = approach(d.position.z, both ? (k === "sugar" ? 0.2 : -0.2) : 0, dt, 0.2);
      d.position.y = 0.06 * s;
    }

    // Light: dim for resting; the eyes keep a faint glow.
    const L = p.light;
    this.hemi.intensity = this.baseIntensity.hemi * L;
    this.key.intensity = this.baseIntensity.key * L;
    this.rim.intensity = this.baseIntensity.rim * (0.4 + 0.6 * L);
    this.moon.intensity = 1.2 * (1 - L);
    this.scene.environmentIntensity = this.baseIntensity.env * (0.25 + 0.75 * L);
    if (!this.hi) this.dishMat.color.setScalar(0.25 + 0.75 * L);
    this.eyeMat.emissiveIntensity = 0.6 * p.eyeGlow;

    this.updateParticles(dt, headWorld);

    // Size and draw
    const { clientWidth: w, clientHeight: h } = this.el;
    const size = this.renderer.getSize(new THREE.Vector2());
    if (w && h && (size.x !== w || size.y !== h)) {
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      // Narrow (portrait) views: widen the lens so the whole fly stays in frame.
      const narrow = this.cfg.wideAspect / this.camera.aspect;
      this.camera.fov = narrow > 1 ? Math.min(this.cfg.maxFov, this.cfg.fov * narrow) : this.cfg.fov;
      this.camera.updateProjectionMatrix();
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  /** High quality on a GPU that can't keep up: drop shadows and reflections, once. */
  watchFrameRate(ms) {
    if (!this.hi || this.reduced) return;
    this.frameMs.push(ms);
    if (this.frameMs.length < this.cfg.slowCheckFrames) return;
    const sorted = [...this.frameMs].sort((a, b) => a - b);
    this.frameMs = [];
    if (sorted[sorted.length >> 1] > this.cfg.slowFrameMs) {
      this.reduced = true;
      this.renderer.shadowMap.enabled = false;
      this.key.castShadow = false;
      this.scene.environment = null;
      this.baseIntensity.hemi = 1.5;
      this.renderer.setPixelRatio(1);
      this.el.dataset.quality = "high, reduced";
    }
  }

  poseLeg(leg, headWorld, t, rubHz) {
    const hip = this.body.localToWorld(leg.hip.clone());
    let foot = leg.foot.clone();
    if (leg.i === 0 && this.groom > 0.001) {
      // Front legs come up in front of the head and rub together.
      const rub = Math.sin(t * Math.PI * 2 * rubHz);
      const g = new THREE.Vector3(
        headWorld.x + 0.34 + 0.05 * rub * leg.side,
        headWorld.y - 0.22 + 0.06 * Math.sin(t * Math.PI * 2 * rubHz * 0.5),
        leg.side * (0.07 + 0.035 * rub),
      );
      foot.lerp(g, this.groom);
    } else if (leg.i === 0 && this.state === "eating") {
      foot.x += 0.12;                                   // step up to the food
    }
    // Knee: up and out from the hip-foot midpoint (a simple two-bone look, no IK solve).
    const mid = hip.clone().lerp(foot, 0.45);
    const out = new THREE.Vector3(0, 0, leg.side);
    const knee = mid.add(new THREE.Vector3(0, 0.3 - 0.12 * this.groom * (leg.i === 0), 0)).addScaledVector(out, 0.18);
    const ankle = knee.clone().lerp(foot, 0.72);
    ankle.y += 0.05;
    placeSegment(leg.segs[0], hip, knee);
    placeSegment(leg.segs[1], knee, ankle);
    placeSegment(leg.segs[2], ankle, foot);
  }

  updateParticles(dt, headWorld) {
    const t = this.t;
    if (this.burst) {
      this.burst = false;
      for (let k = 0; k < 7; k++) {
        const a = (k / 7) * Math.PI * 2;
        this.spawn("spark", new THREE.Vector3(DROP_X, 0.2, 0),
          new THREE.Vector3(Math.cos(a) * 0.6, 0.9 + 0.3 * Math.random(), Math.sin(a) * 0.6), 0.16, 0.8);
      }
    }
    if (t >= this.nextParticleAt) {
      if (this.state === "resting") {
        this.spawn("z", headWorld.clone().add(new THREE.Vector3(0.1, 0.35, 0.1)),
          new THREE.Vector3(0.12, 0.35, 0.05), 0.22, 2.4);
        this.nextParticleAt = t + 0.9;
      } else if (this.state === "disgusted") {
        this.spawn("puff", headWorld.clone().add(new THREE.Vector3(0.45, -0.25, (Math.random() - 0.5) * 0.4)),
          new THREE.Vector3(0.35, 0.35 + 0.3 * Math.random(), (Math.random() - 0.5) * 0.4), 0.3, 1.1);
        this.nextParticleAt = t + 0.14;
      } else if (this.state === "eating" && Math.random() < 0.5) {
        this.spawn("spark", new THREE.Vector3(DROP_X, 0.15, (Math.random() - 0.5) * 0.2),
          new THREE.Vector3((Math.random() - 0.5) * 0.3, 0.6, (Math.random() - 0.5) * 0.3), 0.09, 0.7);
        this.nextParticleAt = t + 0.25;
      } else {
        this.nextParticleAt = t + 0.25;
      }
    }
    for (const q of this.particles) {
      if (q.life <= 0) continue;
      q.age += dt;
      if (q.age >= q.life) {
        q.life = 0;
        q.s.visible = false;
        continue;
      }
      const f = q.age / q.life;
      q.s.position.addScaledVector(q.v, dt);
      q.s.material.opacity = f < 0.2 ? f / 0.2 : 1 - (f - 0.2) / 0.8;
      q.s.scale.setScalar(q.size * (0.6 + 0.8 * f));
    }
  }
}
