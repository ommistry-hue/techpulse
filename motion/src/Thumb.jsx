import { useEffect, useState } from "react";
import { AbsoluteFill, Img, continueRender, delayRender, staticFile } from "remotion";
import { Presenter } from "./Presenter";

const CYAN = "#2be4ff", INK = "#070d1a";
const FONT = "Anton, Mukta, Impact, sans-serif";

// 1280x720 thumbnail: story photo, huge headline (last word in brand cyan), a host reacting and pointing at it.
export const Thumb = ({ image, text = "TECH NEWS", character = "max", channel = "TECHPULSE" }) => {
  const [handle] = useState(() => delayRender("thumb fonts"));
  useEffect(() => {
    const faces = [new FontFace("Anton", `url(${staticFile("Anton-Regular.ttf")})`),
      new FontFace("Mukta", `url(${staticFile("Mukta-ExtraBold.ttf")})`)];
    Promise.all(faces.map(f => f.load().then(ff => document.fonts.add(ff)).catch(() => null))).then(() => continueRender(handle));
  }, [handle]);
  const words = String(text).toUpperCase().split(/\s+/).filter(Boolean);
  const last = words.pop() || "";
  return (
    <AbsoluteFill style={{ background: INK, overflow: "hidden" }}>
      {image && <Img src={staticFile(image)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
        objectFit: "cover", filter: "saturate(1.3) brightness(.8)" }} />}
      <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(7,13,26,.92) 0%, rgba(7,13,26,.6) 50%, rgba(7,13,26,.1) 80%)" }} />
      <div style={{ position: "absolute", top: 36, left: 44, display: "flex", alignItems: "center", gap: 12,
        background: "rgba(7,13,26,.85)", border: `2px solid ${CYAN}`, borderRadius: 12, padding: "6px 16px 6px 6px" }}>
        <Img src={staticFile("logo.jpg")} style={{ width: 52, height: 52, borderRadius: 10 }} />
        <span style={{ fontFamily: FONT, fontSize: 36, letterSpacing: 2, color: "#fff" }}>
          {channel.slice(0, 4)}<span style={{ color: CYAN }}>{channel.slice(4)}</span></span>
      </div>
      <div style={{ position: "absolute", left: 50, top: 150, width: 760, fontFamily: FONT, fontSize: words.length > 2 ? 118 : 140,
        lineHeight: 1.0, color: "#fff", textShadow: "0 6px 0 rgba(0,0,0,.6), 0 0 30px rgba(0,0,0,.5)" }}>
        {words.join(" ")} <span style={{ color: CYAN }}>{last}</span>
      </div>
      <div style={{ position: "absolute", right: -40, bottom: -150 }}>
        <Presenter character={character} frame={0} mouth="E" pose="point" prevPose="point" blend={1} talk={0.6}
          brow={1} look={-1} size={520} />
      </div>
    </AbsoluteFill>
  );
};
