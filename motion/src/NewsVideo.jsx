import { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill, Audio, Easing, Img, Sequence, continueRender, delayRender, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig,
} from "remotion";
import { useAudioData, visualizeAudio } from "@remotion/media-utils";
import { Presenter } from "./Presenter";

// Brand colors from the TechPulse logo: neon cyan -> blue -> purple on deep navy.
const Y = "#2be4ff", INK = "#070d1a", WHITE = "#ffffff", CYAN = "#2be4ff", BLUE = "#3b82f6", PURPLE = "#a855f7";
const NEON = `linear-gradient(90deg, ${CYAN}, ${BLUE} 55%, ${PURPLE})`;
const FONT = "Anton, Mukta, Impact, sans-serif";  // Mukta draws Devanagari (Hindi)
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" };

const useFont = () => {
  const [handle] = useState(() => delayRender("font"));
  useEffect(() => {
    const faces = [new FontFace("Anton", `url(${staticFile("Anton-Regular.ttf")})`),
      new FontFace("Mukta", `url(${staticFile("Mukta-ExtraBold.ttf")})`)];
    Promise.all(faces.map(f => f.load().then(ff => document.fonts.add(ff)).catch(() => null)))
      .then(() => continueRender(handle));
  }, [handle]);
};

const useTalk = (src) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const data = useAudioData(src);
  if (!data) return 0;
  const bins = visualizeAudio({ fps, frame, audioData: data, numberOfSamples: 32 }).slice(0, 12);
  const level = bins.reduce((a, b) => a + b, 0) / bins.length;
  return Math.min(1, Math.max(0, (level - 0.004) * 9));
};

// ---------- backgrounds: 4 camera styles + 3 transitions, so photos feel like footage ----------
const Scene = ({ src, dur, index, L }) => {
  const frame = useCurrentFrame();
  const T = 12;
  const style = index % 4, trans = index % 3;
  const p = interpolate(frame, [0, dur + T], [0, 1], clamp);
  const enter = interpolate(frame, [0, T], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const exit = interpolate(frame, [dur, dur + T], [1, 0], clamp);
  let tx = 0, sc = 1, flash = 0;
  if (index > 0) {
    if (trans === 0) tx = (1 - enter) * 100;          // whip slide
    if (trans === 1) { sc = 1 + (1 - enter) * 0.25; flash = (1 - enter) * 0.7; } // punch-in flash
  }
  const opacity = (index === 0 || trans === 2 ? enter : 1) * exit;
  const img = (extra) => <Img src={staticFile(src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", ...extra }} />;
  const blurBg = (
    <Img src={staticFile(src)} style={{ position: "absolute", left: 0, top: 0, width: "25%", height: "25%", objectFit: "cover",
      filter: "blur(7px) brightness(0.5) saturate(1.3)", transform: "scale(4.4)", transformOrigin: "top left" }} />
  );
  let content;
  if (style === 0) {
    content = img({ objectFit: L ? "cover" : "contain", transform: `scale(${1.04 + p * 0.16})` });
  } else if (style === 1) {
    content = img({ objectFit: L ? "cover" : "contain", transform: `scale(1.18) translateX(${(p - 0.5) * (L ? -90 : -60)}px)` });
  } else if (style === 2) {
    const ry = interpolate(p, [0, 1], [14, -6]);
    content = (
      <AbsoluteFill style={{ perspective: 1600, justifyContent: "center", alignItems: L ? "flex-start" : "center",
        paddingLeft: L ? 120 : 0 }}>
        <div style={{ width: L ? "62%" : "88%", height: L ? "68%" : "46%", borderRadius: 28, overflow: "hidden",
          transform: `rotateY(${ry}deg) scale(${0.96 + p * 0.06})`, boxShadow: "0 40px 90px rgba(0,0,0,.6)",
          border: `6px solid rgba(255,255,255,.9)`, position: "relative" }}>
          {img({ objectFit: "cover" })}
          <div style={{ position: "absolute", inset: 0, background: `linear-gradient(105deg, transparent ${p * 140 - 40}%, rgba(255,255,255,.35) ${p * 140 - 25}%, transparent ${p * 140 - 10}%)` }} />
        </div>
      </AbsoluteFill>
    );
  } else {
    content = (
      <AbsoluteFill>
        <Img src={staticFile(src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover",
          transform: `scale(${1.25 - p * 0.1}) translateX(${(0.5 - p) * 70}px)`, filter: "blur(2px) brightness(.75)" }} />
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
          <div style={{ width: L ? "70%" : "92%", height: L ? "74%" : "50%", overflow: "hidden", borderRadius: 24,
            transform: `scale(${1 + p * 0.08}) translateX(${(p - 0.5) * 40}px)`, boxShadow: "0 30px 80px rgba(0,0,0,.55)" }}>
            {img({ objectFit: "cover" })}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ opacity, transform: `translateX(${tx}%) scale(${sc})` }}>
      <AbsoluteFill style={{ background: INK }}>{blurBg}</AbsoluteFill>
      {content}
      {flash > 0 && <AbsoluteFill style={{ background: WHITE, opacity: flash }} />}
    </AbsoluteFill>
  );
};

const Particles = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {Array.from({ length: 18 }, (_, i) => {
        const sp = 0.3 + (i % 5) * 0.12;
        const x = ((i * 397) % width + Math.sin((frame + i * 40) / 60) * 30);
        const y = (height - ((frame * sp * 3 + i * 211) % (height + 100)));
        return <div key={i} style={{ position: "absolute", left: x, top: y, width: 4 + (i % 3) * 3, height: 4 + (i % 3) * 3,
          borderRadius: 99, background: i % 3 ? CYAN : PURPLE, opacity: 0.25 }} />;
      })}
    </AbsoluteFill>
  );
};

const FallbackBg = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: `linear-gradient(${frame / 3}deg, #0b1220, #14264a 45%, #0b1220)` }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(77,225,255,.08) 2px, transparent 2px), linear-gradient(90deg, rgba(77,225,255,.08) 2px, transparent 2px)",
        backgroundSize: "80px 80px", backgroundPosition: `0 ${frame}px` }} />
    </AbsoluteFill>
  );
};

// ---------- overlays ----------
const Header = ({ channel, L, ui }) => {
  const frame = useCurrentFrame();
  const dot = 0.4 + 0.6 * Math.abs(Math.sin(frame / 10));
  const s = L ? 1 : 1.25;
  return (
    <div style={{ position: "absolute", top: L ? 36 : 110, left: L ? 44 : 50, display: "flex", gap: 14 * s, alignItems: "center" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 * s, background: "rgba(7,13,26,.85)", borderRadius: 12,
        padding: `${4 * s}px ${14 * s}px ${4 * s}px ${4 * s}px`, border: `2px solid ${CYAN}`, boxShadow: `0 0 18px ${CYAN}66` }}>
        <Img src={staticFile("logo.jpg")} style={{ width: 46 * s, height: 46 * s, borderRadius: 10 }} />
        <span style={{ fontFamily: FONT, fontSize: 34 * s, letterSpacing: 2, color: WHITE }}>
          {channel.slice(0, 4)}<span style={{ color: CYAN }}>{channel.slice(4)}</span></span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, background: "rgba(11,18,32,.75)", color: WHITE,
        fontFamily: FONT, fontSize: 26 * s, padding: `${6 * s}px ${14 * s}px`, borderRadius: 8, letterSpacing: 1.5 }}>
        <span style={{ width: 14 * s, height: 14 * s, borderRadius: 99, background: "#ff3b5c", opacity: dot }} />{ui.news}
      </div>
    </div>
  );
};

const SectionCard = ({ text, L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 15 } });
  const out = interpolate(frame, [fps * 3.6, fps * 4.1], [0, 1], clamp);
  return (
    <div style={{ position: "absolute", top: L ? 120 : 250, left: 0, transform: `translateX(${(1 - inn) * -900 + out * -900}px)`, display: "flex" }}>
      <div style={{ width: 18, background: CYAN }} />
      <div style={{ background: NEON, color: WHITE, fontFamily: FONT, fontSize: L ? 64 : 76, padding: "10px 34px 10px 26px",
        textShadow: "0 3px 0 rgba(0,0,0,.35)",
        textTransform: "uppercase", maxWidth: L ? 1100 : 900, lineHeight: 1.05 }}>{text}</div>
    </div>
  );
};

const FactCard = ({ text, L, ui }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 13 } });
  const out = interpolate(frame, [fps * 4.2, fps * 4.7], [1, 0], clamp);
  const pulse = 1 + Math.sin(frame / 4) * 0.05;
  return (
    <div style={{ position: "absolute", left: L ? 60 : 50, right: L ? "auto" : 50, top: L ? 250 : 420,
      transform: `translateY(${(1 - inn) * 60}px) scale(${0.85 + inn * 0.15})`, opacity: inn * out,
      display: "flex", alignItems: "stretch", maxWidth: L ? 1050 : "none", boxShadow: "0 20px 50px rgba(0,0,0,.5)" }}>
      <div style={{ background: CYAN, color: INK, fontFamily: FONT, fontSize: L ? 40 : 50, padding: "14px 22px",
        display: "flex", alignItems: "center", borderRadius: "16px 0 0 16px", transform: `scale(${pulse})` }}>{ui.fact}</div>
      <div style={{ background: "rgba(11,18,32,.92)", color: WHITE, fontFamily: FONT, fontSize: L ? 54 : 66, lineHeight: 1.1,
        padding: "14px 28px", borderRadius: "0 16px 16px 0", textTransform: "uppercase", borderTop: `4px solid ${CYAN}` }}>{text}</div>
    </div>
  );
};

const HookTitle = ({ title, L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 11 } });
  const out = interpolate(frame, [fps * 3.2, fps * 3.8], [1, 0], clamp);
  const shake = frame < 10 ? Math.sin(frame * 2.5) * (10 - frame) : 0;
  return (
    <AbsoluteFill style={{ justifyContent: L ? "center" : "flex-start", alignItems: "center", opacity: out,
      paddingTop: L ? 0 : 300, paddingRight: L ? 420 : 0 }}>
      <div style={{ transform: `scale(${0.5 + inn * 0.5}) rotate(${-2 + shake * 0.2}deg)`, background: "rgba(7,13,26,.92)",
        borderRadius: 18, border: `5px solid ${CYAN}`, padding: L ? "22px 44px" : "26px 36px", maxWidth: L ? 1250 : 960,
        boxShadow: `0 0 50px ${CYAN}88, 0 25px 70px rgba(0,0,0,.6)` }}>
        <div style={{ fontFamily: FONT, color: WHITE, fontSize: L ? 92 : 104, lineHeight: 1.02, textAlign: "center",
          textTransform: "uppercase" }}>{title}</div>
      </div>
    </AbsoluteFill>
  );
};

const Captions = ({ words, L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const n = L ? 6 : 3;
  let spoken = 0;
  for (let i = 0; i < words.length && words[i][0] <= t; i++) spoken = i;
  const gi = Math.floor(spoken / n);
  const group = words.slice(gi * n, gi * n + n);
  if (!group.length || t < group[0][0] - 0.05) return null;
  return (
    <AbsoluteFill style={{ justifyContent: L ? "flex-end" : "center", alignItems: "center",
      paddingBottom: L ? 70 : 0, paddingTop: L ? 0 : 560, paddingLeft: L ? 0 : 40, paddingRight: L ? 560 : 40 }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: L ? "0 26px" : "0 40px",
        background: L ? "rgba(11,18,32,.72)" : "transparent", borderRadius: 18, padding: L ? "10px 30px" : 0, maxWidth: L ? 1200 : 1000 }}>
        {group.map(([t0, , w], i) => {
          const active = t >= t0;
          const isCurrent = active && (i === group.length - 1 || t < group[i + 1][0]);
          const pop = isCurrent ? spring({ frame: frame - Math.round(t0 * fps), fps, config: { damping: 9, stiffness: 220 } }) : 1;
          return (
            <span key={i} style={{ fontFamily: FONT, fontSize: L ? 76 : 124, lineHeight: 1.15, textTransform: "uppercase",
              color: isCurrent ? Y : WHITE, opacity: active ? 1 : 0.55,
              transform: `scale(${isCurrent ? 0.9 + pop * 0.18 : 1})`, display: "inline-block",
              WebkitTextStroke: L ? "0" : "10px #000", paintOrder: "stroke fill", textShadow: "0 6px 0 rgba(0,0,0,.55)" }}>{w}</span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Subscribe = ({ L, ui }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 10 } });
  const ring = Math.sin(frame / 4) * 12;
  return (
    <div style={{ position: "absolute", left: L ? 80 : 0, right: L ? "auto" : 0, bottom: L ? 230 : 1180,
      display: "flex", justifyContent: "center", transform: `scale(${inn})` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18, background: "#ff0033", color: WHITE, fontFamily: FONT,
        fontSize: L ? 58 : 72, padding: L ? "14px 34px" : "16px 40px", borderRadius: 16, letterSpacing: 2,
        boxShadow: "0 12px 40px rgba(255,0,51,.45)" }}>
        {ui.subscribe}
        <svg width={L ? 52 : 64} height={L ? 52 : 64} viewBox="0 0 24 24" style={{ transform: `rotate(${ring}deg)` }}>
          <path fill="#fff" d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z" />
        </svg>
      </div>
    </div>
  );
};

// ---------- presenter acting: gestures from the edit points, mouth from Rhubarb ----------
const buildGestures = (fps, total, events, ctaStart) => {
  const segs = [{ start: 0, end: Math.round(fps * 2.2), type: "wave" }];
  const marks = events.map(t => Math.round(t * fps)).filter(f => f > segs[0].end && f < ctaStart).sort((a, b) => a - b);
  let cur = segs[0].end, alt = 0;
  const fill = (until) => {
    while (cur < until) {
      const len = Math.round(fps * (alt % 2 === 0 ? 3.6 : 2.6));
      const type = alt % 2 === 0 ? (alt % 4 === 0 ? "explain" : "explain2") : "idle";
      segs.push({ start: cur, end: Math.min(until, cur + len), type });
      cur = Math.min(until, cur + len); alt++;
    }
  };
  for (const m of marks) {
    if (m < cur) continue;
    fill(m);
    segs.push({ start: m, end: m + Math.round(fps * 2.4), type: "point" });
    cur = m + Math.round(fps * 2.4);
  }
  fill(ctaStart);
  segs.push({ start: ctaStart, end: total + 1, type: "wave" });
  return segs;
};

const mouthAt = (cues, t, talk) => {
  if (!cues.length) return talk > 0.55 ? "D" : talk > 0.3 ? "C" : talk > 0.12 ? "B" : "X";
  let lo = 0, hi = cues.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (cues[mid][1] <= t) lo = mid + 1; else if (cues[mid][0] > t) hi = mid - 1; else return cues[mid][2];
  }
  return "X";
};

export const NewsVideo = ({ kind, audio, words, scenes, sections, facts = [], mouth = [], title, channel, music = null,
  character = "max", ui = { news: "TECH NEWS", fact: "FACT", subscribe: "SUBSCRIBE" }, durationInFrames }) => {
  useFont();
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const L = kind === "long";
  const t = frame / fps;
  const talk = useTalk(audio ? staticFile(audio) : null);
  const ctaStart = Math.max(0, durationInFrames - fps * (L ? 8 : 4));
  const events = useMemo(() => [...sections.map(s => s.start), ...facts.map(f => f.t)], [sections, facts]);
  const gestures = useMemo(() => buildGestures(fps, durationInFrames, events, ctaStart), [fps, durationInFrames, events, ctaStart]);
  const gi = Math.max(0, gestures.findIndex(g => frame >= g.start && frame < g.end));
  const g = gestures[gi], prev = gestures[gi - 1] || g;
  const blend = interpolate(frame - g.start, [0, 9], [0, 1], { ...clamp, easing: Easing.inOut(Easing.quad) });
  const brow = events.some(e => t >= e && t < e + 1.1) || frame < fps * 1.2 ? 1 : 0;

  return (
    <AbsoluteFill style={{ background: INK }}>
      {scenes.length ? scenes.map((s, i) => {
        const from = Math.round(s.start * fps), dur = Math.max(1, Math.round((s.end - s.start) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={dur + 12} layout="none">
            <Scene src={s.src} dur={dur} index={i} L={L} />
          </Sequence>
        );
      }) : <FallbackBg />}
      <Particles />
      <AbsoluteFill style={{ background: L
        ? "linear-gradient(0deg, rgba(11,18,32,.85) 0%, rgba(11,18,32,0) 40%), linear-gradient(270deg, rgba(11,18,32,.6) 0%, rgba(11,18,32,0) 35%)"
        : "linear-gradient(0deg, rgba(11,18,32,.85) 0%, rgba(11,18,32,0) 38%), linear-gradient(180deg, rgba(11,18,32,.75) 0%, rgba(11,18,32,0) 22%)" }} />

      <Header channel={channel} L={L} ui={ui} />
      {L && sections.map((s, i) => (
        <Sequence key={`s${i}`} from={Math.round(s.start * fps) + (i === 0 ? fps * 4 : 0)} durationInFrames={Math.round(fps * 4.2)} layout="none">
          <SectionCard text={s.heading} L={L} />
        </Sequence>
      ))}
      {facts.map((f, i) => (
        <Sequence key={`f${i}`} from={Math.round(f.t * fps)} durationInFrames={Math.round(fps * 4.8)} layout="none">
          <FactCard text={f.text} L={L} ui={ui} />
        </Sequence>
      ))}

      <div style={{ position: "absolute", right: L ? 40 : 80, bottom: L ? -70 : -40 }}>
        <Presenter character={character} frame={frame} mouth={mouthAt(mouth, t, talk)} pose={g.type} prevPose={prev.type}
          blend={blend} talk={talk} brow={brow} look={g.type === "point" ? -1 : 0} size={L ? 560 : 640} />
      </div>

      <Sequence durationInFrames={fps * 4} layout="none"><HookTitle title={title} L={L} /></Sequence>
      {frame >= fps * 3.4 && <Captions words={words} L={L} />}
      <Sequence from={ctaStart} layout="none"><Subscribe L={L} ui={ui} /></Sequence>

      <div style={{ position: "absolute", left: 0, right: 0, [L ? "bottom" : "top"]: 0, height: L ? 10 : 14,
        background: "rgba(255,255,255,.15)" }}>
        <div style={{ width: `${(frame / durationInFrames) * 100}%`, height: "100%", background: NEON }} />
      </div>
      {audio && <Audio src={staticFile(audio)} />}
      {music && <Audio src={staticFile(music)} loop volume={(f) => interpolate(f, [0, fps, durationInFrames - fps * 2, durationInFrames],
        [0, L ? 0.07 : 0.1, L ? 0.07 : 0.1, 0], clamp)} />}
      {scenes.slice(1).map((s, i) => (
        <Sequence key={`w${i}`} from={Math.max(0, Math.round(s.start * fps) - 4)} durationInFrames={Math.round(fps * 0.5)} layout="none">
          <Audio src={staticFile("whoosh.wav")} volume={0.22} />
        </Sequence>
      ))}
      {facts.map((f, i) => (
        <Sequence key={`p${i}`} from={Math.round(f.t * fps)} durationInFrames={Math.round(fps * 0.3)} layout="none">
          <Audio src={staticFile("pop.wav")} volume={0.35} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
