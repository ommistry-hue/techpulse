import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

const C = { shell: "#1b2640", rim: "#ffd400", screen: "#07101f", glow: "#4de1ff", dark: "#0b1220" };

// "Pulse" - the TechPulse robot anchor. `talk` is 0..1 voice loudness for this frame.
export const Mascot = ({ size = 360, talk = 0, wave = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const bob = Math.sin(frame / 14) * 6 + talk * 4;
  const tilt = Math.sin(frame / 37) * 2.5 + talk * 2;
  const blinkPhase = frame % 105;                       // blink about every 3.5 s
  const eye = blinkPhase < 5 ? interpolate(blinkPhase, [0, 2, 5], [1, 0.08, 1]) : 1;
  const mouthH = 8 + talk * 48;
  const mouthW = 74 - talk * 14;
  const antenna = 0.45 + 0.55 * Math.abs(Math.sin(frame / 9));
  const enter = spring({ frame, fps, config: { damping: 14 } });
  const armAngle = wave ? -35 + Math.sin(frame / 3) * 22 : 18;

  return (
    <svg width={size} height={size} viewBox="0 0 400 400"
      style={{ transform: `translateY(${(1 - enter) * 220 + bob}px) rotate(${tilt}deg)`, overflow: "visible" }}>
      <defs>
        <radialGradient id="glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={C.glow} stopOpacity={0.35 + talk * 0.4} />
          <stop offset="100%" stopColor={C.glow} stopOpacity="0" />
        </radialGradient>
        <linearGradient id="shell" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#26355a" />
          <stop offset="100%" stopColor={C.shell} />
        </linearGradient>
      </defs>
      <circle cx="200" cy="170" r={150 + talk * 18} fill="url(#glow)" />

      {/* body + waving arm */}
      <g transform={`rotate(${armAngle} 300 300)`}>
        <rect x="292" y="250" width="28" height="92" rx="14" fill="url(#shell)" stroke={C.rim} strokeWidth="5" />
        <circle cx="306" cy="248" r="20" fill={C.rim} />
      </g>
      <path d="M95 400 Q100 290 200 285 Q300 290 305 400 Z" fill="url(#shell)" stroke={C.rim} strokeWidth="6" />
      <circle cx="200" cy="345" r="26" fill={C.dark} stroke={C.rim} strokeWidth="4" />
      <text x="200" y="354" textAnchor="middle" fontFamily="Anton" fontSize="26" fill={C.rim}>TP</text>

      {/* neck + antenna */}
      <rect x="182" y="245" width="36" height="34" rx="8" fill="#2b3a5e" />
      <line x1="200" y1="70" x2="200" y2="30" stroke={C.rim} strokeWidth="6" strokeLinecap="round" />
      <circle cx="200" cy="24" r="13" fill={C.rim} opacity={antenna} />
      <circle cx="200" cy="24" r={20 + antenna * 8} fill={C.rim} opacity={antenna * 0.25} />

      {/* ears */}
      <rect x="56" y="130" width="30" height="74" rx="12" fill={C.rim} />
      <rect x="314" y="130" width="30" height="74" rx="12" fill={C.rim} />

      {/* head + face screen */}
      <rect x="78" y="68" width="244" height="190" rx="54" fill="url(#shell)" stroke={C.rim} strokeWidth="7" />
      <rect x="104" y="92" width="192" height="142" rx="38" fill={C.screen} />
      <rect x="148" y={140 - 26 * eye} width="34" height={52 * eye} rx="14" fill={C.glow} />
      <rect x="218" y={140 - 26 * eye} width="34" height={52 * eye} rx="14" fill={C.glow} />
      <circle cx="160" cy={130} r="6" fill="#fff" opacity={eye > 0.5 ? 0.9 : 0} />
      <circle cx="230" cy={130} r="6" fill="#fff" opacity={eye > 0.5 ? 0.9 : 0} />
      <rect x={200 - mouthW / 2} y={198 - mouthH / 2} width={mouthW} height={mouthH} rx={Math.min(mouthH, mouthW) / 2}
        fill={C.glow} />
      <circle cx="128" cy="192" r="10" fill="#ff6b8a" opacity="0.35" />
      <circle cx="272" cy="192" r="10" fill="#ff6b8a" opacity="0.35" />
    </svg>
  );
};
