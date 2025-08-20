import os, re, io
from typing import List, Tuple
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field, conint
from deepgram import DeepgramClient
from deepgram.speak import SpeakOptions
from pydub import AudioSegment
from imageio_ffmpeg import get_ffmpeg_exe
from pydub import AudioSegment

DEEPGRAM_API_KEY = "7685102e54552e3305a689630ef8b311720507e4"
if not DEEPGRAM_API_KEY:
    raise RuntimeError("Set DEEPGRAM_API_KEY")

MODEL = "aura-2-thalia-en"
ENCODING = "linear16"
CONTAINER = "wav"
NO_PAUSE_PAIRS: List[Tuple[str, str]] = [
    ("Welcome to InnovatioCuris Daily News", "Here are today's headlines"),
    ("Thank you for listening", "Subscribe to InnovatioCuris Daily News"),
]

app = FastAPI(title="TTS API", version="1.1.0")

class SynthesisRequest(BaseModel):
    text: str = Field(..., description="Text to convert to speech")
    pause_ms: conint(ge=0, le=10000) = Field(1000, description="Silence between sentences (ms)")

def split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p and p.strip()]

def skip_pause(a: str, b: str) -> bool:
    a, b = a.lower().strip(), b.lower().strip()
    for x, y in NO_PAUSE_PAIRS:
        if a == x.lower() and b == y.lower():
            return True
    return False

@app.post("/synthesize")
def synthesize(req: SynthesisRequest = Body(...)):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")

    try:
        deepgram = DeepgramClient(api_key=DEEPGRAM_API_KEY)
        speak_opts = SpeakOptions(model=MODEL, encoding=ENCODING, container=CONTAINER)
        sentences = split_sentences(text)
        if not sentences:
            raise HTTPException(status_code=400, detail="no sentences found")
              

        segments: List[AudioSegment] = []
        for i, s in enumerate(sentences):
            # Prefer bytes() if your deepgram-sdk supports it
            try:
                audio_bytes = deepgram.speak.rest.v("1").bytes({"text": s}, speak_opts)
            except AttributeError:
                # Fallback to temp file -> bytes -> delete
                import tempfile
                from pathlib import Path
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    deepgram.speak.rest.v("1").save(str(tmp_path), {"text": s}, speak_opts)
                    audio_bytes = tmp_path.read_bytes()
                finally:
                    try: tmp_path.unlink(missing_ok=True)
                    except Exception: pass

            segments.append(AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav"))

            if i < len(sentences) - 1 and not skip_pause(s, sentences[i + 1]) and req.pause_ms > 0:
                segments.append(AudioSegment.silent(duration=req.pause_ms))

        final = segments[0]
        for seg in segments[1:]:
            final += seg

        buf = io.BytesIO()
        final.export(buf, format="wav")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="audio/wav",
            headers={"Content-Disposition": 'attachment; filename="output.wav"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e!s}")  # helpful error

@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})
