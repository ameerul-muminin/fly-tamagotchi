// CSS-style cubic-bezier easing for JS animations (camera moves), so JS and CSS motion
// share the same curves.

/** Returns f(t) for t in [0, 1], matching CSS cubic-bezier(x1, y1, x2, y2). */
export function cubicBezier(x1, y1, x2, y2) {
  const bez = (a, b, t) => 3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t * t + t ** 3;
  const dBez = (a, b, t) => 3 * a * (1 - t) ** 2 + 6 * (b - a) * (1 - t) * t + 3 * (1 - b) * t * t;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    // Newton steps on x(t) = x, then bisection if the slope is too flat.
    let t = x;
    for (let i = 0; i < 6; i++) {
      const d = dBez(x1, x2, t);
      if (Math.abs(d) < 1e-6) break;
      t -= (bez(x1, x2, t) - x) / d;
    }
    if (!(t >= 0 && t <= 1) || Math.abs(bez(x1, x2, t) - x) > 1e-4) {
      let lo = 0;
      let hi = 1;
      t = x;
      for (let i = 0; i < 30; i++) {
        if (bez(x1, x2, t) < x) lo = t;
        else hi = t;
        t = (lo + hi) / 2;
      }
    }
    return bez(y1, y2, t);
  };
}
