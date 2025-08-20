import os, re, io
from typing import List, Tuple

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field, conint

import httpx
from pydub import AudioSegment
from imageio_ffmpeg import get_ffmpeg_exe

# Point pydub to a bundled ffmpeg binary (works on Render)
AudioSegment.converter = get_ffmpeg_exe()

# --- Config ---
DEEPGRAM_API_KEY = '7685102e54552e3305a689630ef8b311720507e4'
if not DEEPGRAM_API_KEY:
    raise RuntimeError("Set DEEPGRAM_API_KEY environment variable")

MODEL = "aura-2-thalia-en"
ENCODING = "linear16"
CONTAINER = "wav"

NO_PAUSE_PAIRS: List[Tuple[str, str]] = [
    ("Welcome to InnovatioCuris Daily News", "Here are today's headlines"),
    ("Thank you for listening", "Subscribe to InnovatioCuris Daily News"),
]

DG_SPEAK_URL = (
    f"https://api.deepgram.com/v1/speak"
    f"?model={MODEL}&encoding={ENCODING}&container={CONTAINER}"
)

app = FastAPI(title="TTS API", version="1.2.0")

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

async def tts_sentence(sentence: str) -> bytes:
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Accept": "audio/wav",
        "Content-Type": "application/json",
    }
    payload = {"text": sentence}
    # Using a single POST per sentence; you can batch/parallelize later if needed.
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(DG_SPEAK_URL, headers=headers, json=payload)
        if r.status_code != 200:
            # Bubble up Deepgram error text to help debugging
            raise HTTPException(status_code=502, detail=f"Deepgram error {r.status_code}: {r.text}")
        return r.content

@app.post("/synthesize")
async def synthesize(req: SynthesisRequest = Body(...)):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")

    sentences = split_sentences(text)
    if not sentences:
        raise HTTPException(status_code=400, detail="no sentences found")

    try:
        segments: List[AudioSegment] = []

        # Generate audio per sentence
        for i, s in enumerate(sentences):
            audio_bytes = await tts_sentence(s)
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
            segments.append(seg)
            if i < len(sentences) - 1 and not skip_pause(s, sentences[i + 1]) and req.pause_ms > 0:
                segments.append(AudioSegment.silent(duration=req.pause_ms))

        # Concatenate
        final = segments[0]
        for seg in segments[1:]:
            final += seg

        # Export to memory
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
        raise HTTPException(status_code=500, detail=f"TTS failed: {e!s}")

@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})
