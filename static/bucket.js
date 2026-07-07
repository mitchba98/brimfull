// Animated bucket SVG — extracted from static-site/index.html

let _bkN = 0;

function wavePath(amp) {
  let d = 'M -42 240 L -42 0';
  for (let x = -42; x <= 142; x += 4) {
    d += ` L ${x} ${(-amp * Math.sin(x / 40 * Math.PI * 2)).toFixed(2)}`;
  }
  return d + ' L 142 240 Z';
}

function faceSVG(kind, dark) {
  if (kind === 'none') return '';
  const cy = 13;
  let eyes, mouth, extra = '';
  if (kind === 'calm') {
    eyes  = `<ellipse cx="${50-6}" cy="${cy-2}" rx="1.7" ry="2" fill="${dark}"/><ellipse cx="${50+6}" cy="${cy-2}" rx="1.7" ry="2" fill="${dark}"/>`;
    mouth = `<path d="M46 ${cy+4} Q50 ${cy+5.6} 54 ${cy+4}" stroke="${dark}" stroke-width="1.4" fill="none" stroke-linecap="round"/>`;
  } else if (kind === 'concern') {
    eyes  = `<ellipse cx="${50-6}" cy="${cy-2}" rx="1.8" ry="2.2" fill="${dark}"/><ellipse cx="${50+6}" cy="${cy-2}" rx="1.8" ry="2.2" fill="${dark}"/>`;
    mouth = `<path d="M46.5 ${cy+5} L53.5 ${cy+5}" stroke="${dark}" stroke-width="1.5" fill="none" stroke-linecap="round"/>`;
    extra = `<path d="M43.5 ${cy-5.6} L48 ${cy-4.6}" stroke="${dark}" stroke-width="1.1" stroke-linecap="round"/>
             <path d="M56.5 ${cy-5.6} L52 ${cy-4.6}" stroke="${dark}" stroke-width="1.1" stroke-linecap="round"/>`;
  } else {
    eyes  = `<ellipse cx="${50-6.2}" cy="${cy-2}" rx="2.4" ry="2.8" fill="${dark}"/><ellipse cx="${50+6.2}" cy="${cy-2}" rx="2.4" ry="2.8" fill="${dark}"/>`;
    mouth = `<ellipse cx="50" cy="${cy+5.5}" rx="2.5" ry="3.1" fill="${dark}"/>`;
    extra = `<path d="M43 ${cy-6.5} L48 ${cy-8}" stroke="${dark}" stroke-width="1.2" stroke-linecap="round"/>
             <path d="M57 ${cy-6.5} L52 ${cy-8}" stroke="${dark}" stroke-width="1.2" stroke-linecap="round"/>`;
  }
  return `<g class="bf-bob"><g class="bf-blink">${eyes}</g>${mouth}${extra}</g>`;
}

function dropsSVG(color, dur) {
  return [[44,15,0],[52,13,0.35],[59,16,0.7]].map(([cx,cy,delay]) =>
    `<circle cx="${cx}" cy="${cy}" r="1.6" fill="${color}" style="transform-box:fill-box;transform-origin:center;animation:bf-drop ${dur}s ease-in infinite;animation-delay:${delay}s"/>`
  ).join('');
}

function bucketSVG(st, px, opts) {
  opts = opts || {};
  const stroke     = opts.stroke     || '#2A2620';
  const glass      = opts.glass      || 'rgba(28,24,21,0.03)';
  const innerShade = opts.innerShade || 'rgba(28,24,21,0.07)';
  const faceDark   = opts.faceDark   || '#241F1A';
  const id         = 'bk' + (++_bkN);
  const surfaceY   = (108 - st.level * 90).toFixed(1);
  const h          = Math.round(px * 1.24);
  return `<svg viewBox="0 0 100 124" width="${px}" height="${h}" style="overflow:visible;display:block;">
    <defs><clipPath id="${id}"><path d="M16.5 20 A33.5 7.5 0 0 0 83.5 20 L73 108 A23 7 0 0 1 27 108 Z"/></clipPath></defs>
    <ellipse cx="58" cy="117" rx="16" ry="3.2" fill="#9A9080" opacity="${(st.puddle * 0.6).toFixed(2)}" style="transition:opacity .7s ease"/>
    <g style="transform:rotate(${st.tip}deg);transform-box:view-box;transform-origin:50px 108px;transition:transform .9s cubic-bezier(.4,0,.2,1)">
      <ellipse cx="50" cy="20" rx="33" ry="7.5" fill="${innerShade}"/>
      <g clip-path="url(#${id})">
        <g style="transform:translateY(${surfaceY}px);transition:transform .9s cubic-bezier(.4,0,.2,1)">
          <g style="animation:bf-slosh ${st.dur}s linear infinite">
            <path d="${wavePath(st.amp)}" fill="${st.color}" style="transition:fill .9s ease"/>
          </g>
          <rect x="23" y="3" width="8" height="70" rx="4" fill="#fff" opacity="0.16"/>
          <ellipse cx="50" cy="0" rx="29" ry="3" fill="#fff" opacity="0.28"/>
          <g style="opacity:${st.faceOpacity};transition:opacity .5s ease">${faceSVG(st.face, faceDark)}</g>
        </g>
      </g>
      <path d="M16 20 L27 108 A23 7 0 0 0 73 108 L84 20" fill="${glass}" stroke="${stroke}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="50" cy="20" rx="34" ry="8" fill="none" stroke="${stroke}" stroke-width="2"/>
      <path d="M18 19 Q50 -12 82 19" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round"/>
      ${st.drops ? dropsSVG(st.color, st.dur) : ''}
    </g>
  </svg>`;
}

const LOGO_STATE = { level:0.42, color:'#2840C8', amp:1.2, dur:4.5, face:'calm', tip:0, puddle:0, faceOpacity:1, drops:0 };

const STATUS_STATES = {
  ok:       { level:0.21, color:'#128A5E', amp:1,   dur:5,   face:'calm',    tip:0,   puddle:0, faceOpacity:1, drops:0 },
  warning:  { level:0.70, color:'#C9820B', amp:2.6, dur:2.4, face:'concern', tip:0,   puddle:0, faceOpacity:1, drops:0 },
  critical: { level:0.93, color:'#CF4034', amp:5,   dur:1,   face:'panic',   tip:0,   puddle:0, faceOpacity:1, drops:1 },
  offline:  { level:0.05, color:'#9A9080', amp:0.4, dur:6,   face:'none',    tip:-18, puddle:1, faceOpacity:0, drops:0 },
};

document.addEventListener('DOMContentLoaded', function () {
  const el = document.getElementById('nav-logo');
  if (el) el.innerHTML = bucketSVG(LOGO_STATE, 28);
});
