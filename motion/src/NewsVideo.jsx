import { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill, Audio, Easing, Img, OffthreadVideo, Sequence, continueRender, delayRender, interpolate, spring, staticFile,
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
const Scene = ({ src, dur, index, L, video = false }) => {
  const frame = useCurrentFrame();
  const T = 12;
  // real clips: full-frame zoom/pan only; Shorts: mostly full-frame, floating cards ~1 in 4 scenes
  const style = video ? index % 2 : L ? index % 4 : [0, 1, 0, 1, 2, 0, 1, 3][index % 8], trans = index % 3;
  const p = interpolate(frame, [0, dur + T], [0, 1], clamp);
  const enter = interpolate(frame, [0, T], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const exit = interpolate(frame, [dur, dur + T], [1, 0], clamp);
  let tx = 0, sc = 1, flash = 0;
  if (index > 0) {
    if (trans === 0) tx = (1 - enter) * 100;          // whip slide
    if (trans === 1) { sc = 1 + (1 - enter) * 0.25; flash = (1 - enter) * 0.7; } // punch-in flash
  }
  const opacity = (index > 0 && trans === 2 ? enter : 1) * exit;
  const img = (extra) => video
    ? <OffthreadVideo src={staticFile(src)} muted style={{ position: "absolute", inset: 0, width: "100%", height: "100%", ...extra, objectFit: "cover" }} />
    : <Img src={staticFile(src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", ...extra }} />;
  const blurBg = video ? null : (
    <Img src={staticFile(src)} style={{ position: "absolute", left: 0, top: 0, width: "25%", height: "25%", objectFit: "cover",
      filter: "blur(7px) brightness(0.5) saturate(1.3)", transform: "scale(4.4)", transformOrigin: "top left" }} />
  );
  let content;
  if (style === 0) {
    content = img({ objectFit: "cover", transform: `scale(${1.04 + p * 0.16})` });
  } else if (style === 1) {
    content = img({ objectFit: "cover", transform: `scale(1.18) translateX(${(p - 0.5) * (L ? -90 : -60)}px)` });
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

const HookTitle = ({ title, L, duo }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 11 } });
  const out = interpolate(frame, [fps * 3.2, fps * 3.8], [1, 0], clamp);
  const shake = frame < 10 ? Math.sin(frame * 2.5) * (10 - frame) : 0;
  return (
    <AbsoluteFill style={{ justifyContent: L ? "center" : "flex-start", alignItems: "center", opacity: out,
      paddingTop: L ? 0 : 300, paddingRight: L && !duo ? 420 : 0 }}>
      <div style={{ transform: `scale(${L ? 0.5 + inn * 0.5 : 0.92 + inn * 0.08}) rotate(${-2 + shake * 0.2}deg)`, background: "rgba(7,13,26,.92)",
        borderRadius: 18, border: `5px solid ${CYAN}`, padding: L ? "22px 44px" : "26px 36px", maxWidth: L ? 1250 : 960,
        boxShadow: `0 0 50px ${CYAN}88, 0 25px 70px rgba(0,0,0,.6)` }}>
        <div style={{ fontFamily: FONT, color: WHITE, fontSize: L ? 92 : 104, lineHeight: 1.02, textAlign: "center",
          textTransform: "uppercase" }}>{title}</div>
      </div>
    </AbsoluteFill>
  );
};

// Names and numbers carry a news story: brand words from the title and any number/price/percent are drawn in gold.
const GOLD = "#ffd23f";
const isKey = (w, hl) => /[0-9$₹€£%]/.test(w) || hl.has(w.toLowerCase().replace(/[^\p{L}\p{N}+]/gu, ""));

const Captions = ({ words, L, duo, lift = false, highlights = [] }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const hl = new Set(highlights);
  const n = L ? 6 : 3;
  let spoken = 0;
  for (let i = 0; i < words.length && words[i][0] <= t; i++) spoken = i;
  const gi = Math.floor(spoken / n);
  const group = words.slice(gi * n, gi * n + n);
  if (!group.length || t < group[0][0] - 0.05) return null;
  return (
    <AbsoluteFill style={{ justifyContent: L ? "flex-end" : "center", alignItems: "center",
      paddingBottom: L ? 70 : 0, paddingTop: L ? 0 : lift ? 880 : 560, paddingLeft: L ? (duo ? 430 : 0) : 40, paddingRight: L ? (duo ? 430 : 560) : 40 }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: L ? "0 26px" : "0 40px",
        background: L ? "rgba(11,18,32,.72)" : "transparent", borderRadius: 18, padding: L ? "10px 30px" : 0, maxWidth: L ? 1200 : 1000 }}>
        {group.map(([t0, , w], i) => {
          const active = t >= t0;
          const isCurrent = active && (i === group.length - 1 || t < group[i + 1][0]);
          const pop = isCurrent ? spring({ frame: frame - Math.round(t0 * fps), fps, config: { damping: 9, stiffness: 220 } }) : 1;
          return (
            <span key={i} style={{ fontFamily: FONT, fontSize: L ? 76 : 124, lineHeight: 1.15, textTransform: "uppercase",
              color: isKey(w, hl) ? GOLD : isCurrent ? Y : WHITE, opacity: active ? 1 : 0.55,
              transform: `scale(${isCurrent ? 0.9 + pop * 0.18 : 1})`, display: "inline-block",
              WebkitTextStroke: L ? "0" : "10px #000", paintOrder: "stroke fill", textShadow: "0 6px 0 rgba(0,0,0,.55)" }}>{w}</span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const ICONS = {
  like: "M2 21h4V9H2v12zm20-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L13.17 1 7.59 6.59C7.22 6.95 7 7.45 7 8v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1z",
  comment: "M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z",
  share: "M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92z",
  bell: "M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z",
};
export const CTA_STEP = 0.45;  // seconds between buttons popping in

// End sequence: Like -> Comment -> Share -> Subscribe pop in one by one; each gets "tapped" (fills with colour).
const EndCTA = ({ L, ui }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const items = [
    { key: "like", label: ui.like, on: BLUE },
    { key: "comment", label: ui.comment, on: CYAN },
    { key: "share", label: ui.share, on: PURPLE },
    { key: "bell", label: ui.subscribe, on: "#ff0033", big: true },
  ];
  return (
    <div style={{ position: "absolute", left: L ? 70 : 60, right: L ? "auto" : 60, top: L ? 200 : 300,
      display: "flex", flexDirection: L ? "row" : "column", flexWrap: "wrap", gap: L ? 18 : 22, alignItems: L ? "center" : "stretch",
      maxWidth: L ? 1150 : "none" }}>
      {items.map((it, i) => {
        const at = Math.round(i * CTA_STEP * fps);
        const inn = spring({ frame: frame - at, fps, config: { damping: 11, stiffness: 160 } });
        const tap = interpolate(frame - at, [fps * 0.55, fps * 0.68, fps * 0.85], [1, 0.9, 1], clamp);
        const filled = frame - at > fps * 0.62;
        const ring = it.key === "bell" ? Math.sin(frame / 4) * 14 : 0;
        const bg = filled || it.big ? it.on : "rgba(7,13,26,.88)";
        return (
          <div key={it.key} style={{ display: "flex", alignItems: "center", gap: 16, background: bg, color: WHITE,
            border: `3px solid ${it.on}`, borderRadius: 18, fontFamily: FONT, letterSpacing: 2,
            fontSize: it.big ? (L ? 56 : 74) : (L ? 44 : 60), padding: it.big ? (L ? "14px 32px" : "18px 36px") : (L ? "10px 24px" : "14px 30px"),
            transform: `scale(${Math.max(0, inn) * tap})`, opacity: Math.min(1, Math.max(0, inn) * 1.5),
            boxShadow: filled || it.big ? `0 0 34px ${it.on}88, 0 14px 40px rgba(0,0,0,.45)` : "0 14px 40px rgba(0,0,0,.45)" }}>
            <svg width={it.big ? (L ? 50 : 66) : (L ? 40 : 54)} height={it.big ? (L ? 50 : 66) : (L ? 40 : 54)} viewBox="0 0 24 24"
              style={{ transform: `rotate(${ring}deg)` }}><path fill="#fff" d={ICONS[it.key]} /></svg>
            {it.label}
          </div>
        );
      })}
    </div>
  );
};

// Long videos: a small reminder at ~40%, when viewers who will subscribe have usually decided they like the video.
const SubscribePill = ({ ui }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 13 } });
  const out = interpolate(frame, [fps * 3.2, fps * 3.7], [1, 0], clamp);
  return (
    <div style={{ position: "absolute", right: 60, top: 40, transform: `translateX(${(1 - inn) * 500}px)`, opacity: out,
      display: "flex", alignItems: "center", gap: 12, background: "#ff0033", color: WHITE, fontFamily: FONT, fontSize: 40,
      padding: "10px 24px", borderRadius: 14, letterSpacing: 2, boxShadow: "0 10px 30px rgba(255,0,51,.45)" }}>
      <svg width="38" height="38" viewBox="0 0 24 24" style={{ transform: `rotate(${Math.sin(frame / 4) * 14}deg)` }}>
        <path fill="#fff" d={ICONS.bell} /></svg>
      {ui.subscribe}
    </div>
  );
};

// Music ducking: quiet under the voice, fuller in pauses, swells under the end sequence.
const speechSpans = (words, gap = 0.45) => {
  const spans = [];
  for (const [a, b] of words) {
    const last = spans[spans.length - 1];
    if (last && a - last[1] <= gap) last[1] = Math.max(last[1], b); else spans.push([a, b]);
  }
  return spans;
};
const speakingAmount = (spans, t, ramp = 0.25) => {  // 0 = silence, 1 = talking (smooth edges)
  let best = 0;
  for (const [a, b] of spans) {
    if (t < a - ramp) break;
    if (t <= b + ramp) best = Math.max(best, Math.min(1, (t - (a - ramp)) / ramp, ((b + ramp) - t) / ramp));
  }
  return Math.max(0, Math.min(1, best));
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

// Big centre card for one sourced number, quote or comparison (breaks up the photo run, explains at a glance).
const DataCard = ({ card, L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 12 } });
  const out = interpolate(frame, [fps * 3.4, fps * 3.9], [1, 0], clamp);
  const box = { background: "rgba(7,13,26,.94)", border: `4px solid ${CYAN}`, borderRadius: 26, color: WHITE, fontFamily: FONT,
    boxShadow: `0 0 60px ${CYAN}55, 0 30px 80px rgba(0,0,0,.6)`, textAlign: "center" };
  let body;
  if (card.type === "stat") {
    body = <div style={{ ...box, padding: L ? "30px 70px" : "36px 50px" }}>
      <div style={{ fontSize: L ? 150 : 170, lineHeight: 1, color: CYAN }}>{card.value}</div>
      <div style={{ fontSize: L ? 54 : 62, marginTop: 14, textTransform: "uppercase" }}>{card.label}</div></div>;
  } else if (card.type === "quote") {
    body = <div style={{ ...box, padding: L ? "34px 60px" : "40px 46px", maxWidth: L ? 1300 : 960 }}>
      <div style={{ fontSize: L ? 140 : 160, lineHeight: 0.6, color: CYAN }}>&ldquo;</div>
      <div style={{ fontSize: L ? 62 : 70, lineHeight: 1.15 }}>{card.text}</div>
      <div style={{ fontSize: L ? 40 : 46, marginTop: 18, color: CYAN }}>&mdash; {card.source}</div></div>;
  } else {
    const side = (txt, color) => <div style={{ ...box, borderColor: color, padding: L ? "28px 44px" : "30px 36px",
      fontSize: L ? 66 : 70, flex: 1 }}>{txt}</div>;
    body = <div style={{ display: "flex", flexDirection: L ? "row" : "column", alignItems: "center", gap: 24, width: L ? 1300 : 900 }}>
      {side(card.left, BLUE)}
      <div style={{ fontFamily: FONT, fontSize: L ? 80 : 90, color: CYAN }}>VS</div>
      {side(card.right, PURPLE)}</div>;
  }
  return (
    <AbsoluteFill style={{ background: `rgba(7,13,26,${0.55 * inn * out})`, justifyContent: "center", alignItems: "center",
      paddingBottom: L ? 120 : 300 }}>
      <div style={{ transform: `scale(${0.6 + inn * 0.4})`, opacity: out }}>
        {card.type === "versus" && card.label && <div style={{ fontFamily: FONT, color: WHITE, fontSize: L ? 52 : 60,
          textAlign: "center", marginBottom: 18, textTransform: "uppercase" }}>{card.label}</div>}
        {body}
      </div>
    </AbsoluteFill>
  );
};

// versus_test Shorts: split screen for the whole video, side A on top, side B below, VS badge on the seam.
// The panel whose name is being spoken flashes; near the end the winner lights up and the loser dims.
const TROPHY = "M19 4h-2V3H7v1H5c-1.1 0-2 .9-2 2v1c0 2.55 1.92 4.63 4.39 4.94A5.01 5.01 0 0 0 11 15.9V19H7v2h10v-2h-4v-3.1a5.01 5.01 0 0 0 3.61-2.96C19.08 12.63 21 10.55 21 8V6c0-1.1-.9-2-2-2zM5 8V6h2v3.82C5.84 9.4 5 8.3 5 8zm14 0c0 .3-.84 1.4-2 1.82V6h2v2z";
const VersusPanel = ({ data, side, versus, L }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = frame / fps;
  const top = side === "left";
  const color = top ? BLUE : PURPLE;
  const p = frame / durationInFrames;
  const hit = Math.max(0, ...(data.hits || []).map(h => (t >= h && t < h + 0.6 ? 1 - (t - h) / 0.6 : 0)));
  const decided = versus.winner && versus.winAt != null && t >= versus.winAt;
  const won = decided && versus.winner === side, lost = decided && versus.winner !== side;
  const winIn = decided ? spring({ frame: frame - Math.round(versus.winAt * fps), fps, config: { damping: 10 } }) : 0;
  const [head, ...rest] = String(data.name).split(":");
  const sub = rest.join(":").trim();
  const media = (extra) => data.video
    ? <OffthreadVideo src={staticFile(data.src)} muted style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", ...extra }} />
    : <Img src={staticFile(data.src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", ...extra }} />;
  const box = L ? { left: top ? 0 : "50%", top: 0, width: "50%", height: "100%" }
    : { left: 0, top: top ? 0 : "50%", width: "100%", height: "50%" };
  return (
    <div style={{ position: "absolute", ...box, overflow: "hidden", background: INK }}>
      <div style={{ position: "absolute", inset: 0, filter: lost ? `grayscale(${0.9 * winIn}) brightness(${1 - 0.55 * winIn})` : `brightness(${1 + hit * 0.25})` }}>
        {!data.video && media({ objectFit: "cover", filter: "blur(18px) brightness(.45) saturate(1.4)", transform: "scale(1.2)" })}
        {media({ objectFit: data.video ? "cover" : "contain",
          transform: `scale(${1.02 + p * 0.12 + hit * 0.05 + (won ? winIn * 0.06 : 0)}) translateX(${(top ? 1 : -1) * (p - 0.5) * 30}px)` })}
        <div style={{ position: "absolute", inset: 0, background: `linear-gradient(${top ? 180 : 0}deg, ${color}55 0%, transparent 30%, transparent 70%, rgba(7,13,26,.7) 100%)` }} />
      </div>
      <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 0 ${won ? 14 : 6 + hit * 8}px ${won ? CYAN : color}${won ? "" : "cc"}` }} />
      {/* name label: top panel near the seam (bottom), bottom panel near the seam (top); clear of the right-side buttons */}
      <div style={{ position: "absolute", left: 40, right: L ? 40 : 170, ...(top || L ? { bottom: L ? 60 : 150 } : { top: 150 }),
        display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8, transform: `scale(${1 + hit * 0.06})`, transformOrigin: "left center" }}>
        <div style={{ background: color, color: WHITE, fontFamily: FONT, fontSize: L ? 64 : 84, lineHeight: 1.05, padding: "6px 24px",
          borderRadius: 14, textTransform: "uppercase", boxShadow: "0 12px 30px rgba(0,0,0,.5)", textShadow: "0 3px 0 rgba(0,0,0,.35)" }}>{head}</div>
        {(sub || won) && <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {sub && <div style={{ background: "rgba(7,13,26,.88)", color: CYAN, fontFamily: FONT, fontSize: L ? 46 : 58, padding: "4px 20px",
            borderRadius: 12, textTransform: "uppercase", border: `3px solid ${color}` }}>{sub}</div>}
          {won && <div style={{ transform: `scale(${winIn}) rotate(-4deg)`, display: "flex", alignItems: "center", gap: 10, background: NEON,
            color: WHITE, fontFamily: FONT, fontSize: L ? 48 : 60, padding: "4px 22px", borderRadius: 12, letterSpacing: 3,
            boxShadow: `0 0 40px ${CYAN}, 0 12px 30px rgba(0,0,0,.5)`, border: `4px solid ${WHITE}`, textShadow: "0 3px 0 rgba(0,0,0,.35)" }}>
            <svg width={L ? 46 : 58} height={L ? 46 : 58} viewBox="0 0 24 24"><path fill="#fff" d={TROPHY} /></svg>WINNER</div>}
        </div>}
      </div>
    </div>
  );
};

const VersusSplit = ({ versus, L }) => {
  const frame = useCurrentFrame();
  const pulse = 1 + Math.sin(frame / 5) * 0.05;
  const seam = L ? { left: "50%", top: 0, bottom: 0, width: 12, marginLeft: -6 } : { top: "50%", left: 0, right: 0, height: 12, marginTop: -6 };
  return (
    <AbsoluteFill>
      <VersusPanel data={versus.left} side="left" versus={versus} L={L} />
      <VersusPanel data={versus.right} side="right" versus={versus} L={L} />
      <div style={{ position: "absolute", ...seam, background: NEON, boxShadow: `0 0 30px ${CYAN}` }} />
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <div style={{ width: L ? 200 : 230, height: L ? 200 : 230, borderRadius: 999, background: NEON, border: `8px solid ${WHITE}`,
          display: "flex", justifyContent: "center", alignItems: "center", transform: `scale(${pulse}) rotate(-8deg)`,
          boxShadow: `0 0 60px ${CYAN}, 0 20px 50px rgba(0,0,0,.6)`, fontFamily: FONT, fontSize: L ? 100 : 118, color: WHITE,
          textShadow: "0 5px 0 rgba(0,0,0,.4)" }}>VS</div>
      </AbsoluteFill>
      {versus.label && <div style={{ position: "absolute", ...(L ? { left: "50%", top: 40, transform: "translateX(-50%)" } : { left: 40, top: 960 - 34 }),
        background: "rgba(7,13,26,.92)", color: CYAN, border: `3px solid ${CYAN}`, borderRadius: 12, fontFamily: FONT,
        fontSize: L ? 44 : 50, padding: "2px 18px", textTransform: "uppercase", letterSpacing: 2, maxWidth: L ? 600 : 290,
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{versus.label}</div>}
    </AbsoluteFill>
  );
};

// top3_unique Shorts: "#3", "#2", "#1" slam into the centre, then settle as a badge in the top-left corner.
const CountBadge = ({ n, L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 9, stiffness: 180 } });
  const move = interpolate(frame, [fps * 0.75, fps * 1.15], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const flash = interpolate(frame, [0, 6], [0.55, 0], clamp);
  const shake = frame < 12 ? Math.sin(frame * 2.2) * (12 - frame) * 1.5 : 0;
  // centre (big) -> corner (small)
  const cx = L ? 960 : 540, cy = L ? 480 : 760, ex = L ? 150 : 150, ey = L ? 210 : 330;
  const x = cx + (ex - cx) * move + shake, y = cy + (ey - cy) * move;
  const scale = (L ? 1.6 : 2.1) * (1 - move) + move;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {flash > 0 && <AbsoluteFill style={{ background: WHITE, opacity: flash }} />}
      <AbsoluteFill style={{ background: `rgba(7,13,26,${0.45 * (1 - move)})` }} />
      <div style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) scale(${Math.max(0, inn) * scale}) rotate(-6deg)`,
        background: NEON, borderRadius: 26, border: `6px solid ${WHITE}`, padding: "0 30px", display: "flex", alignItems: "baseline",
        boxShadow: `0 0 50px ${CYAN}aa, 0 20px 50px rgba(0,0,0,.6)`, fontFamily: FONT, color: WHITE, textShadow: "0 6px 0 rgba(0,0,0,.4)" }}>
        <span style={{ fontSize: 90, opacity: 0.85 }}>#</span><span style={{ fontSize: 170, lineHeight: 1.1 }}>{n}</span>
      </div>
    </AbsoluteFill>
  );
};

// "Wait for it" Shorts: a pulsing pill under the header once the hook title has gone (curiosity -> watch to the end)
const WaitBadge = ({ text }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 12 } });
  const out = interpolate(frame, [fps * 4.4, fps * 5], [1, 0], clamp);
  const pulse = 1 + Math.sin(frame / 5) * 0.04;
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 300, opacity: out }}>
      <div style={{ transform: `scale(${(0.6 + inn * 0.4) * pulse})`, background: "#ff3b5c", color: WHITE, fontFamily: FONT,
        fontSize: 78, padding: "14px 40px", borderRadius: 999, letterSpacing: 2, boxShadow: "0 0 40px rgba(255,59,92,.6), 0 18px 50px rgba(0,0,0,.5)",
        border: "5px solid #fff" }}>{text}</div>
    </AbsoluteFill>
  );
};

const speakerAt = (turns, t) => {
  let s = turns.length ? turns[0][2] : null;
  for (const [a, , who] of turns) { if (a <= t) s = who; else break; }
  return s;
};

export const NewsVideo = ({ kind, audio, words, scenes, sections, facts = [], mouth = [], title, channel, music = null,
  turns = [], cards = [], versus = null, countdown = [], wait = null, emotions = [], highlights = [], character = "max", ui = { news: "TECH NEWS", fact: "FACT", subscribe: "SUBSCRIBE", like: "LIKE", comment: "COMMENT", share: "SHARE" }, durationInFrames }) => {
  useFont();
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const L = kind === "long";
  const t = frame / fps;
  const talk = useTalk(audio ? staticFile(audio) : null);
  const ctaStart = L ? Math.max(0, durationInFrames - fps * 8) : durationInFrames;  // Shorts loop: no end sequence
  const spans = useMemo(() => speechSpans(words), [words]);
  const events = useMemo(() => [...sections.map(s => s.start), ...facts.map(f => f.t), ...countdown.map(c => c.t)], [sections, facts, countdown]);
  const gestures = useMemo(() => buildGestures(fps, durationInFrames, events, ctaStart), [fps, durationInFrames, events, ctaStart]);
  const gi = Math.max(0, gestures.findIndex(g => frame >= g.start && frame < g.end));
  const g = gestures[gi], prev = gestures[gi - 1] || g;
  const blend = interpolate(frame - g.start, [0, 9], [0, 1], { ...clamp, easing: Easing.inOut(Easing.quad) });
  const emo = (emotions.find(([a, b]) => t >= a && t < b) || [0, 0, "neutral"]);
  const lively = (emo[2] === "excited" || emo[2] === "surprised") && t < emo[0] + 1.4;  // react at the start of the line
  const brow = events.some(e => t >= e && t < e + 1.1) || frame < fps * 1.2 || lively ? 1 : 0;
  const duo = turns.length > 0;
  const speaker = duo ? speakerAt(turns, t) : character;
  // In a conversation the current speaker acts (mouth, gestures); the other listens and looks at them.
  const host = (who) => {
    const active = !duo || who === speaker;
    return <Presenter character={who} frame={frame} mouth={active ? mouthAt(mouth, t, talk) : "X"}
      pose={active ? g.type : "idle"} prevPose={active ? prev.type : "idle"} blend={active ? blend : 1}
      talk={active ? talk : 0} brow={active ? brow : 0}
      look={active && g.type !== "point" ? 0 : -1} size={L ? (duo ? 480 : 560) : versus ? 380 : 520} />;  // -1 = toward the other host / the cards
  };

  return (
    <AbsoluteFill style={{ background: INK }}>
      {versus ? <VersusSplit versus={versus} L={L} /> : scenes.length ? scenes.map((s, i) => {
        const from = Math.round(s.start * fps), dur = Math.max(1, Math.round((s.end - s.start) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={dur + 12} layout="none">
            <Scene src={s.src} dur={dur} index={i} L={L} video={!!s.video} />
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

      {cards.filter(c => !(versus && c.type === "versus")).map((c, i) => (
        <Sequence key={`k${i}`} from={Math.round(c.t * fps)} durationInFrames={Math.round(fps * 4)} layout="none">
          <DataCard card={c} L={L} />
          <Audio src={staticFile("pop.wav")} volume={0.35} />
        </Sequence>
      ))}

      {duo ? <>
        {/* Nova on the left, mirrored so she faces Max and points toward the middle */}
        <div style={{ position: "absolute", left: 30, bottom: -50, transform: "scaleX(-1)" }}>{host("nova")}</div>
        <div style={{ position: "absolute", right: 30, bottom: -50 }}>{host("max")}</div>
      </> : (
        // Shorts: bottom-left, clear of YouTube's like/comment buttons on the right
        <div style={{ position: "absolute", ...(L ? { right: 40, bottom: -70 } : { left: 10, bottom: -40 }) }}>{host(character)}</div>
      )}

      <Sequence durationInFrames={fps * 4} layout="none"><HookTitle title={title} L={L} duo={duo} /></Sequence>
      {wait && !L && (
        <Sequence from={Math.round(fps * 3.6)} durationInFrames={Math.round(fps * 5)} layout="none">
          <WaitBadge text={wait} />
          <Audio src={staticFile("whoosh.wav")} volume={0.3} />
        </Sequence>
      )}
      {countdown.map((c, i) => (
        <Sequence key={`n${i}`} from={Math.round(c.t * fps)} durationInFrames={i + 1 < countdown.length
          ? Math.max(1, Math.round(countdown[i + 1].t * fps) - Math.round(c.t * fps)) : undefined} layout="none">
          <CountBadge n={c.n} L={L} />
          <Audio src={staticFile(i === countdown.length - 1 ? "ding.wav" : "hit.wav")} volume={0.45} />
        </Sequence>
      ))}
      {(!L || frame >= fps * 3.4) && <Captions words={words} L={L} duo={duo} lift={!!versus} highlights={highlights} />}
      {versus && versus.winner && versus.winAt != null && (
        <Sequence from={Math.round(versus.winAt * fps)} durationInFrames={Math.round(fps * 1.2)} layout="none">
          <Audio src={staticFile("ding.wav")} volume={0.45} />
        </Sequence>
      )}
      {L && <Sequence from={ctaStart} layout="none"><EndCTA L={L} ui={ui} /></Sequence>}
      {L && durationInFrames > fps * 60 && (
        <Sequence from={Math.round(durationInFrames * 0.4)} durationInFrames={Math.round(fps * 3.8)} layout="none">
          <SubscribePill ui={ui} />
          <Audio src={staticFile("pop.wav")} volume={0.35} />
        </Sequence>
      )}

      {L && <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 10, background: "rgba(255,255,255,.15)" }}>
        <div style={{ width: `${(frame / durationInFrames) * 100}%`, height: "100%", background: NEON }} />
      </div>}
      {audio && <Audio src={staticFile(audio)} />}
      {music && <Audio src={staticFile(music)} loop volume={(f) => {
        const t = f / fps, under = L ? 0.055 : 0.075, open = L ? 0.16 : 0.2;
        let v = under + (open - under) * (1 - speakingAmount(spans, t));
        if (f >= ctaStart) v = interpolate(f, [ctaStart, ctaStart + fps], [v, open * 1.15], clamp);  // swell under the end sequence
        const fadeIn = interpolate(f, [0, fps * 0.4], [0.4, 1], clamp);
        const fadeOut = L ? interpolate(f, [durationInFrames - fps * 1.5, durationInFrames], [1, 0], clamp) : 1;
        return v * fadeIn * fadeOut;
      }} />}
      <Audio src={staticFile("hit.wav")} volume={0.45} />
      {L && ["pop.wav", "pop.wav", "pop.wav", "ding.wav"].map((s, i) => (
        <Sequence key={`c${i}`} from={ctaStart + Math.round(i * CTA_STEP * fps)} durationInFrames={Math.round(fps * 1.2)} layout="none">
          <Audio src={staticFile(s)} volume={s === "ding.wav" ? 0.4 : 0.32} />
        </Sequence>
      ))}
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
