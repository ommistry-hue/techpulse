import { interpolate } from "remotion";

// Two recurring hosts: Max (male voice) and Nova (female voice). Flat vector news-anchor style, waist up.
const LOOKS = {
  max: { skin: "#d9a066", skinDark: "#b98350", hair: "#22160f", blazer: "#1e3a6b", lapel: "#152b50", shirt: "#ffffff",
    accent: "#e63950", iris: "#3b2a20", lips: "#a8584a" },
  nova: { skin: "#f0c4a0", skinDark: "#d39f7c", hair: "#4a2a1a", blazer: "#7b2d5b", lapel: "#5c1f43", shirt: "#fff3e6",
    accent: "#2be4ff", iris: "#2d5f8a", lips: "#c4505f" },
};

// Arm poses: [upper arm, forearm] rotation in degrees for (viewer's) left and right arm. 0 = hanging straight down.
export const POSES = {
  idle: { l: [10, -58], r: [-10, 58] },
  explain: { l: [10, -58], r: [-28, -138] },
  explain2: { l: [32, 132], r: [-10, 58] },
  point: { l: [122, 14], r: [-10, 58] },   // up-left, toward the fact/section cards
  wave: { l: [10, -58], r: [-162, -8] },
};

const lerp = (a, b, t) => a + (b - a) * t;

// Rhubarb mouth shapes: A=M/B/P closed, B=K/S/T teeth, C=EH open, D=AA wide, E=AO round, F=OO pucker, G=F/V, H=L, X=rest.
const Mouth = ({ shape, c }) => {
  const open = (w, h, teeth, tongue) => (
    <g>
      <ellipse cx="200" cy="274" rx={w} ry={h} fill="#3a1218" />
      {teeth && <rect x={200 - w * 0.75} y={274 - h} width={w * 1.5} height={Math.min(7, h * 0.7)} rx="3" fill="#fff" />}
      {tongue && <ellipse cx="200" cy={274 + h * 0.45} rx={w * 0.55} ry={h * 0.4} fill="#e06a7a" />}
      <ellipse cx="200" cy="274" rx={w} ry={h} fill="none" stroke={c.lips} strokeWidth="4" />
    </g>
  );
  switch (shape) {
    case "A": return <path d="M182 274 Q200 279 218 274" stroke={c.lips} strokeWidth="5" fill="none" strokeLinecap="round" />;
    case "B": return open(17, 6, true, false);
    case "C": return open(18, 11, true, true);
    case "D": return open(21, 17, true, true);
    case "E": return open(13, 13, false, true);
    case "F": return open(8, 8, false, false);
    case "G": return <g>{open(16, 7, false, false)}<rect x="188" y="266" width="24" height="7" rx="3" fill="#fff" /></g>;
    case "H": return <g>{open(17, 12, true, false)}<ellipse cx="200" cy="270" rx="9" ry="5" fill="#e06a7a" /></g>;
    default: return <path d="M184 273 Q200 281 216 273" stroke={c.lips} strokeWidth="5" fill="none" strokeLinecap="round" />;
  }
};

const Arm = ({ x, y, upper, fore, c, side }) => (
  <g transform={`translate(${x} ${y}) rotate(${upper})`}>
    <rect x="-22" y="-10" width="44" height="118" rx="22" fill={c.blazer} />
    <g transform={`translate(0 104) rotate(${fore})`}>
      <rect x="-19" y="-12" width="38" height="104" rx="19" fill={c.blazer} />
      <rect x="-19" y="80" width="38" height="14" rx="5" fill={c.shirt} />
      <g transform="translate(0 112)">
        <ellipse cx="0" cy="0" rx="21" ry="24" fill={c.skin} />
        <ellipse cx={side === "l" ? 15 : -15} cy="-6" rx="8" ry="13" fill={c.skin} transform={`rotate(${side === "l" ? -25 : 25})`} />
        <path d="M-10 -14 L-10 -26 M0 -16 L0 -30 M10 -14 L10 -26" stroke={c.skinDark} strokeWidth="3" strokeLinecap="round" />
      </g>
    </g>
  </g>
);

export const Presenter = ({ character = "max", frame, mouth = "X", pose, prevPose, blend, talk = 0, brow = 0,
  look = 0, size = 600 }) => {
  const c = LOOKS[character] || LOOKS.max;
  const female = character === "nova";
  const P = POSES[pose] || POSES.idle, Q = POSES[prevPose] || POSES.idle;
  const swing = Math.sin(frame / 5) * (pose === "wave" ? 18 : pose.startsWith("explain") ? 9 * (0.4 + talk) : 0);
  const lU = lerp(Q.l[0], P.l[0], blend), lF = lerp(Q.l[1], P.l[1], blend) + (pose === "explain2" ? swing : 0);
  const rU = lerp(Q.r[0], P.r[0], blend), rF = lerp(Q.r[1], P.r[1], blend) + (pose === "explain" || pose === "wave" ? swing : 0);

  const blinkCycle = (frame + (female ? 40 : 0)) % 113;
  const eye = blinkCycle < 6 ? interpolate(blinkCycle, [0, 3, 6], [1, 0.08, 1]) : 1;
  const saccade = Math.round(Math.sin(frame / 47) * 2) + look * 5;
  const tilt = Math.sin(frame / 41) * 2.5 + (pose === "point" ? -4 : 0);
  const nod = talk * 3;
  const breathe = 1 + Math.sin(frame / 22) * 0.006;
  const browY = -brow * 9;

  return (
    <svg width={size} height={size * 1.3} viewBox="0 0 400 520" style={{ overflow: "visible" }}>
      <defs>
        <radialGradient id={`shadow-${character}`} cx="50%" cy="100%" r="60%">
          <stop offset="0%" stopColor="#000" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#000" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="200" cy="520" rx="210" ry="60" fill={`url(#shadow-${character})`} />

      <g transform={`translate(200 520) scale(1 ${breathe}) translate(-200 -520)`}>
        {female && <path d="M118 230 Q100 330 128 372 L272 372 Q300 330 282 230 Q270 150 200 140 Q130 150 118 230 Z" fill={c.hair} />}

        {/* torso */}
        <path d="M58 520 Q60 402 110 374 Q150 352 175 348 L225 348 Q250 352 290 374 Q340 402 342 520 Z" fill={c.blazer} />
        <path d="M175 348 L200 438 L225 348 Z" fill={c.shirt} />
        {female
          ? <g><path d="M178 360 Q200 400 222 360" stroke={c.accent} strokeWidth="3" fill="none" /><circle cx="200" cy="401" r="7" fill={c.accent} /></g>
          : <g><path d="M191 360 L209 360 L215 442 L200 462 L185 442 Z" fill={c.accent} /><rect x="189" y="352" width="22" height="14" rx="4" fill={c.accent} /></g>}
        <path d="M175 348 L200 438 L156 396 L168 352 Z" fill={c.lapel} />
        <path d="M225 348 L200 438 L244 396 L232 352 Z" fill={c.lapel} />
        <circle cx="262" cy="430" r="6" fill="#c9d4ea" opacity="0.8" />

        {/* neck */}
        <rect x="178" y="296" width="44" height="62" rx="16" fill={c.skin} />
        <path d="M178 330 Q200 344 222 330" stroke={c.skinDark} strokeWidth="5" fill="none" opacity="0.6" />

        {/* head */}
        <g transform={`translate(0 ${nod}) rotate(${tilt} 200 330)`}>
          <ellipse cx="118" cy="232" rx="13" ry="22" fill={c.skin} />
          <ellipse cx="282" cy="232" rx="13" ry="22" fill={c.skin} />
          {female && <><circle cx="116" cy="254" r="5" fill={c.accent} /><circle cx="284" cy="254" r="5" fill={c.accent} /></>}
          <path d="M120 215 Q120 128 200 124 Q280 128 280 215 Q280 290 230 316 Q200 330 170 316 Q120 290 120 215 Z" fill={c.skin} />
          {female
            ? <path d="M114 248 Q104 122 204 112 Q300 116 290 250 Q282 178 240 160 Q206 196 150 170 Q124 188 114 248 Z" fill={c.hair} />
            : <path d="M116 218 Q110 120 200 112 Q292 116 284 218 Q278 166 238 156 Q204 174 160 158 Q126 166 116 218 Z" fill={c.hair} />}

          <g transform={`translate(0 ${browY})`}>
            <path d="M150 190 Q168 178 188 188" stroke={c.hair} strokeWidth={female ? 5 : 8} fill="none" strokeLinecap="round" />
            <path d="M212 188 Q232 178 250 190" stroke={c.hair} strokeWidth={female ? 5 : 8} fill="none" strokeLinecap="round" />
          </g>
          {[168, 232].map((ex, i) => (
            <g key={i} transform={`translate(${ex} 216) scale(1 ${eye})`}>
              <ellipse cx="0" cy="0" rx="16" ry="12" fill="#fff" />
              <circle cx={saccade} cy="1" r="8" fill={c.iris} />
              <circle cx={saccade} cy="1" r="3.5" fill="#111" />
              <circle cx={saccade + 3} cy="-3" r="2.5" fill="#fff" />
              {female && <path d={i === 0 ? "M-16 -4 L-23 -12 M-11 -9 L-15 -17" : "M16 -4 L23 -12 M11 -9 L15 -17"}
                stroke="#222" strokeWidth="2.5" strokeLinecap="round" />}
            </g>
          ))}
          <path d="M200 224 Q192 248 199 254 Q206 255 209 250" stroke={c.skinDark} strokeWidth="4" fill="none" strokeLinecap="round" />
          <ellipse cx="150" cy="258" rx="14" ry="8" fill="#ff7a8a" opacity={female ? 0.3 : 0.14} />
          <ellipse cx="250" cy="258" rx="14" ry="8" fill="#ff7a8a" opacity={female ? 0.3 : 0.14} />
          <Mouth shape={mouth} c={c} />
        </g>

        <Arm x={112} y={392} upper={lU} fore={lF} c={c} side="l" />
        <Arm x={288} y={392} upper={rU} fore={rF} c={c} side="r" />
      </g>
    </svg>
  );
};
