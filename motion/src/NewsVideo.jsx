import { useEffect, useState } from "react";
import {
  AbsoluteFill, Audio, Img, Sequence, continueRender, delayRender, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig,
} from "remotion";
import { useAudioData, visualizeAudio } from "@remotion/media-utils";
import { Mascot } from "./Mascot";

const Y = "#ffd400", INK = "#0b1220", WHITE = "#ffffff", CYAN = "#4de1ff";
const FONT = "Anton, Impact, sans-serif";

const useFont = () => {
  const [handle] = useState(() => delayRender("font"));
  useEffect(() => {
    const f = new FontFace("Anton", `url(${staticFile("Anton-Regular.ttf")})`);
    f.load().then(ff => { document.fonts.add(ff); continueRender(handle); }).catch(() => continueRender(handle));
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

const Scene = ({ src, dur, index, L }) => {
  const frame = useCurrentFrame();
  const fade = 12;
  const opacity = interpolate(frame, [0, fade, dur, dur + fade], [0, 1, 1, 0], { extrapolateRight: "clamp" });
  const zoomIn = index % 2 === 0;
  const scale = interpolate(frame, [0, dur + fade], zoomIn ? [1.04, 1.18] : [1.18, 1.04]);
  const drift = interpolate(frame, [0, dur + fade], [index % 3 === 0 ? -20 : 20, 0]);
  return (
    <AbsoluteFill style={{ opacity }}>
      {!L && (  // blurred fill behind a "contain" photo; drawn at 1/4 size then scaled up = far cheaper blur
        <Img src={staticFile(src)} style={{ position: "absolute", left: 0, top: 0, width: "25%", height: "25%",
          objectFit: "cover", filter: "blur(7px) brightness(0.55)", transform: "scale(4.4)", transformOrigin: "top left" }} />
      )}
      <Img src={staticFile(src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
        objectFit: L ? "cover" : "contain", transform: `scale(${scale}) translateX(${drift}px)` }} />
    </AbsoluteFill>
  );
};

const FallbackBg = () => {
  const frame = useCurrentFrame();
  const a = frame / 3;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(${a}deg, #0b1220, #14264a 45%, #0b1220)` }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(77,225,255,.08) 2px, transparent 2px), linear-gradient(90deg, rgba(77,225,255,.08) 2px, transparent 2px)",
        backgroundSize: "80px 80px", backgroundPosition: `0 ${frame}px` }} />
    </AbsoluteFill>
  );
};

const Header = ({ channel, L }) => {
  const frame = useCurrentFrame();
  const dot = 0.4 + 0.6 * Math.abs(Math.sin(frame / 10));
  const s = L ? 1 : 1.25;
  return (
    <div style={{ position: "absolute", top: L ? 36 : 120, left: L ? 44 : 50, display: "flex", gap: 14 * s, alignItems: "center" }}>
      <div style={{ background: Y, color: INK, fontFamily: FONT, fontSize: 34 * s, padding: `${4 * s}px ${16 * s}px`,
        borderRadius: 8, letterSpacing: 2 }}>{channel}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, background: "rgba(11,18,32,.75)", color: WHITE,
        fontFamily: FONT, fontSize: 26 * s, padding: `${6 * s}px ${14 * s}px`, borderRadius: 8, letterSpacing: 1.5 }}>
        <span style={{ width: 14 * s, height: 14 * s, borderRadius: 99, background: "#ff3b5c", opacity: dot }} />TECH NEWS
      </div>
    </div>
  );
};

const SectionCard = ({ text, L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 15 } });
  const out = interpolate(frame, [fps * 3.6, fps * 4.1], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const x = (1 - inn) * -900 + out * -900;
  return (
    <div style={{ position: "absolute", top: L ? 120 : 260, left: 0, transform: `translateX(${x}px)`, display: "flex" }}>
      <div style={{ width: 18, background: CYAN }} />
      <div style={{ background: Y, color: INK, fontFamily: FONT, fontSize: L ? 64 : 76, padding: "10px 34px 10px 26px",
        textTransform: "uppercase", maxWidth: L ? 1100 : 900, lineHeight: 1.05 }}>{text}</div>
    </div>
  );
};

const HookTitle = ({ title, L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 12 } });
  const out = interpolate(frame, [fps * 3.2, fps * 3.8], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: L ? "center" : "flex-start", alignItems: "center", opacity: out,
      paddingTop: L ? 0 : 330 }}>
      <div style={{ transform: `scale(${0.6 + inn * 0.4})`, background: "rgba(11,18,32,.82)", borderRadius: 24,
        padding: L ? "28px 48px" : "30px 40px", maxWidth: L ? 1400 : 960, border: `6px solid ${Y}` }}>
        <div style={{ fontFamily: FONT, color: WHITE, fontSize: L ? 86 : 92, lineHeight: 1.05, textAlign: "center",
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
  let spoken = 0;  // index of the last word that has started
  for (let i = 0; i < words.length && words[i][0] <= t; i++) spoken = i;
  const gi = Math.floor(spoken / n);
  const group = words.slice(gi * n, gi * n + n);
  if (!group.length || t < group[0][0] - 0.05) return null;
  return (
    <AbsoluteFill style={{ justifyContent: L ? "flex-end" : "center", alignItems: "center",
      paddingBottom: L ? 70 : 0, paddingTop: L ? 0 : 520, paddingLeft: L ? 0 : 40, paddingRight: L ? 420 : 40 }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: L ? "0 26px" : "0 40px",
        background: L ? "rgba(11,18,32,.72)" : "transparent", borderRadius: 18, padding: L ? "10px 30px" : 0, maxWidth: L ? 1300 : 1000 }}>
        {group.map(([t0, , w], i) => {
          const active = t >= t0;
          const isCurrent = active && (i === group.length - 1 || t < group[i + 1][0]);
          const pop = isCurrent ? spring({ frame: frame - Math.round(t0 * fps), fps, config: { damping: 9, stiffness: 220 } }) : 1;
          return (
            <span key={i} style={{ fontFamily: FONT, fontSize: L ? 76 : 128, lineHeight: 1.15, textTransform: "uppercase",
              color: isCurrent ? Y : WHITE, opacity: active ? 1 : 0.55,
              transform: `scale(${isCurrent ? 0.9 + pop * 0.18 : 1})`, display: "inline-block",
              WebkitTextStroke: L ? "0" : "10px #000", paintOrder: "stroke fill",
              textShadow: "0 6px 0 rgba(0,0,0,.55)" }}>{w}</span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Subscribe = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 10 } });
  const ring = Math.sin(frame / 4) * 12;
  return (
    <div style={{ position: "absolute", left: L ? 80 : 0, right: L ? "auto" : 0, bottom: L ? 220 : 520,
      display: "flex", justifyContent: "center", transform: `scale(${inn})` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18, background: "#ff0033", color: WHITE, fontFamily: FONT,
        fontSize: L ? 58 : 76, padding: L ? "14px 34px" : "18px 44px", borderRadius: 16, letterSpacing: 2,
        boxShadow: "0 12px 40px rgba(255,0,51,.45)" }}>
        SUBSCRIBE
        <svg width={L ? 52 : 68} height={L ? 52 : 68} viewBox="0 0 24 24" style={{ transform: `rotate(${ring}deg)` }}>
          <path fill="#fff" d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z" />
        </svg>
      </div>
    </div>
  );
};

export const NewsVideo = ({ kind, audio, words, scenes, sections, title, channel, durationInFrames }) => {
  useFont();
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const L = kind === "long";
  const talk = useTalk(audio ? staticFile(audio) : null);
  const progress = frame / durationInFrames;
  const ctaStart = Math.max(0, durationInFrames - fps * (L ? 8 : 5));

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

      <AbsoluteFill style={{ background: L
        ? "linear-gradient(0deg, rgba(11,18,32,.85) 0%, rgba(11,18,32,0) 45%), linear-gradient(180deg, rgba(11,18,32,.6) 0%, rgba(11,18,32,0) 25%)"
        : "linear-gradient(0deg, rgba(11,18,32,.75) 0%, rgba(11,18,32,0) 35%), linear-gradient(180deg, rgba(11,18,32,.75) 0%, rgba(11,18,32,0) 25%)" }} />

      <Header channel={channel} L={L} />
      {L && sections.map((s, i) => (
        <Sequence key={i} from={Math.round(s.start * fps) + (i === 0 ? fps * 4 : 0)} durationInFrames={fps * 4.2} layout="none">
          <SectionCard text={s.heading} L={L} />
        </Sequence>
      ))}
      <Sequence durationInFrames={fps * 4} layout="none"><HookTitle title={title} L={L} /></Sequence>
      {frame >= fps * 3.4 && <Captions words={words} L={L} />}
      <Sequence from={ctaStart} layout="none"><Subscribe L={L} /></Sequence>

      <div style={{ position: "absolute", right: L ? 30 : "auto", left: L ? "auto" : 30, bottom: L ? -30 : 150 }}>
        <Mascot size={L ? 400 : 330} talk={talk} wave={frame < fps * 2.5 || frame >= ctaStart} />
      </div>

      <div style={{ position: "absolute", left: 0, right: 0, [L ? "bottom" : "top"]: 0, height: L ? 10 : 14,
        background: "rgba(255,255,255,.15)" }}>
        <div style={{ width: `${progress * 100}%`, height: "100%", background: Y }} />
      </div>
      {audio && <Audio src={staticFile(audio)} />}
    </AbsoluteFill>
  );
};
