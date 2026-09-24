// 2D cartoon fly (side view). The state only changes CSS classes; styles live in style.css.

const SVG = `
<svg class="fly" viewBox="0 0 320 230" role="img" aria-label="cartoon fly">
  <g class="ground"><line x1="10" y1="196" x2="310" y2="196"/></g>
  <g class="food">
    <path class="drop sugar-drop" d="M262 196 q-18 0 -18 -9 q0 -8 18 -8 q18 0 18 8 q0 9 -18 9z"/>
    <path class="drop bitter-drop" d="M262 196 q-18 0 -18 -9 q0 -8 18 -8 q18 0 18 8 q0 9 -18 9z"/>
  </g>
  <g class="body-wrap">
    <g class="wing wing-back"><ellipse cx="118" cy="86" rx="66" ry="20" transform="rotate(-14 118 86)"/></g>
    <g class="legs">
      <path d="M160 140 q-12 22 -30 56"/><path d="M176 142 q2 26 -4 54"/><path d="M190 138 q14 24 22 58"/>
    </g>
    <ellipse class="abdomen" cx="108" cy="128" rx="58" ry="36"/>
    <path class="stripe" d="M84 96 q-8 32 0 64"/><path class="stripe" d="M108 92 q-8 36 0 72"/>
    <path class="stripe" d="M132 96 q-8 32 0 64"/>
    <ellipse class="thorax" cx="176" cy="118" rx="34" ry="30"/>
    <g class="wing wing-front"><ellipse cx="128" cy="80" rx="70" ry="22" transform="rotate(-18 128 80)"/></g>
    <g class="head">
      <g class="proboscis"><path d="M232 136 L240 160"/><ellipse cx="241" cy="163" rx="6" ry="4"/></g>
      <circle class="head-ball" cx="224" cy="116" r="26"/>
      <ellipse class="eye" cx="231" cy="108" rx="16" ry="19"/>
      <circle class="eye-shine" cx="236" cy="100" r="4"/>
      <path class="lid" d="M215 108 a16 19 0 0 1 32 0 z"/>
      <g class="lid-closed"><ellipse cx="231" cy="108" rx="17" ry="20"/><path d="M217 110 q14 10 28 0"/></g>
      <path class="brow" d="M214 86 L244 94"/>
      <path class="antenna" d="M214 92 q-6 -18 -18 -22"/>
    </g>
  </g>
  <g class="fx fx-eating"><text x="270" y="150">slurp</text></g>
  <g class="fx fx-disgusted">
    <path d="M262 70 q6 -8 0 -16 q-6 -8 0 -16"/><path d="M278 76 q6 -8 0 -16 q-6 -8 0 -16"/>
    <text x="250" y="30">blech!</text>
  </g>
  <g class="fx fx-resting"><text class="z1" x="250" y="80">z</text><text class="z2" x="264" y="62">z</text>
    <text class="z3" x="280" y="42">Z</text></g>
</svg>`;

export const FLY_STATES = ["idle", "eating", "disgusted", "resting"];

/** Put a fly in `container`; returns {setState(state, {sugar, bitter})}. */
export function createFly(container) {
  container.innerHTML = SVG;
  const svg = container.querySelector("svg");
  return {
    setState(state, food = {}) {
      for (const s of FLY_STATES) svg.classList.toggle(`is-${s}`, s === state);
      svg.classList.toggle("has-sugar", !!food.sugar);
      svg.classList.toggle("has-bitter", !!food.bitter);
      svg.dataset.state = state;
    },
  };
}
