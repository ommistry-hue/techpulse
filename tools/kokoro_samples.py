"""Make Kokoro voice samples (English + Hindi, male + female) to compare with Edge voices."""
from pathlib import Path

import soundfile as sf
from kokoro import KPipeline

EN = ("A massive Google Cloud outage just knocked major UK banks offline. Millions of people could not open their "
      "banking apps. So what actually happened, and could it happen to your money too? Let's break it down.")
HI = ("Google Cloud में एक बड़ा outage हुआ, और UK के बड़े banks के apps घंटों तक बंद रहे। लाखों लोग अपना bank account "
      "नहीं खोल पाए। तो आखिर हुआ क्या, और क्या ये आपके पैसों के साथ भी हो सकता है? चलिए समझते हैं।")
out = Path("voice_samples")
out.mkdir(exist_ok=True)
for lang, code, text, voices in (("EN", "a", EN, ["af_heart", "af_bella", "am_michael", "am_fenrir"]),
                                 ("HI", "h", HI, ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"])):
    pipe = KPipeline(lang_code=code)
    for v in voices:
        audio = [a for _, _, a in pipe(text, voice=v)]
        import numpy as np
        sf.write(out / f"{lang}_kokoro_{v}.wav", np.concatenate(audio), 24000)
        print("ok", lang, v)
