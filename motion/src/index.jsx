import { Composition, registerRoot } from "remotion";
import { NewsVideo } from "./NewsVideo";

const defaults = {
  kind: "long", width: 1920, height: 1080, fps: 30, durationInFrames: 150,
  audio: null, words: [], scenes: [], sections: [], facts: [], mouth: [], title: "TechPulse", channel: "TECHPULSE",
  character: "max",
};

const meta = ({ props }) => ({
  durationInFrames: props.durationInFrames, width: props.width, height: props.height, fps: props.fps,
});

const Root = () => (
  <>
    <Composition id="Long" component={NewsVideo} defaultProps={defaults} calculateMetadata={meta}
      width={1920} height={1080} fps={30} durationInFrames={150} />
    <Composition id="Short" component={NewsVideo} defaultProps={{ ...defaults, kind: "short", width: 1080, height: 1920 }}
      calculateMetadata={meta} width={1080} height={1920} fps={30} durationInFrames={150} />
  </>
);

registerRoot(Root);
