// Synthetic sensor data shared by the unit tests and the end-to-end mock-event script.

/** DeviceMotion samples of a sinusoid on the x axis (m/s^2), at `hz` samples per second. */
export function motionSamples({ amp, freq, ms, hz = 60, t0 = 0, withGravity = false, gravityOnly = false }) {
  const out = [];
  for (let i = 0; i * (1000 / hz) <= ms; i++) {
    const t = t0 + i * (1000 / hz);
    const x = amp * Math.sin((2 * Math.PI * freq * (t - t0)) / 1000);
    const acc = { x, y: 0.3, z: -0.2 };
    const accG = { x, y: 0.3, z: -0.2 + (withGravity || gravityOnly ? 9.81 : 0) };
    out.push({ acc: gravityOnly ? { x: null, y: null, z: null } : acc, accG, t });
  }
  return out;
}

/** A vigorous hand shake: 25 m/s^2 at 5 Hz for 700 ms. */
export const shake = (t0 = 0, opts = {}) => motionSamples({ amp: 25, freq: 5, ms: 700, t0, ...opts });
/** Walking with the phone in hand: 4 m/s^2 at 2 Hz for 3 s. */
export const walking = (t0 = 0, opts = {}) => motionSamples({ amp: 4, freq: 2, ms: 3000, t0, ...opts });

/** A w x h RGBA frame filled with one color. */
export function frame(r, g = r, b = r, w = 32, h = 24) {
  const px = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < px.length; i += 4) { px[i] = r; px[i + 1] = g; px[i + 2] = b; px[i + 3] = 255; }
  return px;
}

/** A camera covered by a hand: nearly black with a little sensor noise. */
export function coveredFrame(w = 32, h = 24, seed = 1) {
  const px = new Uint8ClampedArray(w * h * 4);
  let s = seed;
  for (let i = 0; i < px.length; i += 4) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const v = s % 9; // 0..8 of 255
    px[i] = v; px[i + 1] = v; px[i + 2] = v; px[i + 3] = 255;
  }
  return px;
}
