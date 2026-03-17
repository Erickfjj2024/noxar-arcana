"""
NOXAR ARCANA — TTS Service
Narração com ElevenLabs — 3 vozes masculinas PT-BR por persona
Fallback para gTTS se ElevenLabs falhar
"""

import os
import logging
import subprocess
import shutil
import requests
from gtts import gTTS

logger = logging.getLogger(__name__)

# ─── VOZES ELEVENLABS ────────────────────────────────────
# IDs de vozes masculinas disponíveis no plano gratuito
VOZES = {
    # Profissional, seco, jornalístico
    "investigador": {
        "voice_id": "onwK4e9ZLuTAKqWW03F9",  # Daniel
        "stability":        0.75,
        "similarity_boost": 0.75,
        "style":            0.2,
        "speaking_rate":    0.9,
    },
    # Caloroso, narrativo, próximo
    "contador": {
        "voice_id": "N2lVS1w4EtoT3dr4eOWO",  # Callum
        "stability":        0.65,
        "similarity_boost": 0.80,
        "style":            0.35,
        "speaking_rate":    0.85,
    },
    # Tenso, urgente, conspiratório
    "informante": {
        "voice_id": "CwhRBWXzGAHq8TQ4Fs17",  # Roger
        "stability":        0.55,
        "similarity_boost": 0.85,
        "style":            0.45,
        "speaking_rate":    1.0,
    },
}

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
MODEL_ID       = "eleven_multilingual_v2"


# ─── UTILIDADES FFMPEG ───────────────────────────────────
def run_ffmpeg(cmd: list, desc: str = "") -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"FFmpeg {desc}: {result.stderr[-200:]}")
            return False
        return True
    except Exception as e:
        logger.error(f"FFmpeg exceção {desc}: {e}")
        return False


def get_duracao(path: str) -> float | None:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


# ─── ELEVENLABS ──────────────────────────────────────────
def gerar_elevenlabs(texto: str, output_path: str, persona: str = "contador") -> bool:
    """
    Gera narração via ElevenLabs API.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        logger.warning("ELEVENLABS_API_KEY não configurada")
        return False

    cfg = VOZES.get(persona, VOZES["contador"])

    url = ELEVENLABS_URL.format(voice_id=cfg["voice_id"])

    headers = {
        "xi-api-key":   api_key,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }

    payload = {
        "text":     texto,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability":         cfg["stability"],
            "similarity_boost":  cfg["similarity_boost"],
            "style":             cfg["style"],
            "use_speaker_boost": True,
        },
    }

    try:
        logger.info(f"ElevenLabs — persona={persona} voice_id={cfg['voice_id']}")
        response = requests.post(url, json=payload, headers=headers, timeout=60)

        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            ok = os.path.exists(output_path) and os.path.getsize(output_path) > 0
            if ok:
                logger.info(f"ElevenLabs OK: {output_path}")
            return ok

        elif response.status_code == 401:
            logger.error("ElevenLabs: API key inválida")
        elif response.status_code == 422:
            logger.error(f"ElevenLabs: texto inválido — {response.text[:200]}")
        elif response.status_code == 429:
            logger.warning("ElevenLabs: rate limit ou cota esgotada")
        else:
            logger.error(f"ElevenLabs status {response.status_code}: {response.text[:200]}")

        return False

    except Exception as e:
        logger.error(f"ElevenLabs exceção: {e}")
        return False


# ─── FALLBACK: gTTS ──────────────────────────────────────
def gerar_gtts(texto: str, output_path: str) -> bool:
    """Fallback com gTTS se ElevenLabs falhar."""
    try:
        logger.info("Fallback: gerando com gTTS...")
        tts = gTTS(text=texto, lang="pt", tld="com.br", slow=False)
        tts.save(output_path)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logger.error(f"gTTS fallback falhou: {e}")
        return False


# ─── TRATAMENTO DE ÁUDIO ────────────────────────────────
def tratar_audio(input_path: str, output_path: str) -> bool:
    """
    Tratamento profissional:
    - Normalização EBU R128
    - EQ boost de graves 120hz
    - Fade in 0.1s / fade out 0.4s
    """
    try:
        duracao = get_duracao(input_path)
        if not duracao:
            shutil.copy(input_path, output_path)
            return True

        fade_out_start = max(0, duracao - 0.5)

        filtro = (
            "equalizer=f=120:width_type=o:width=2:g=2,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d=0.1,"
            f"afade=t=out:st={fade_out_start:.3f}:d=0.4"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", filtro,
            "-ar", "44100",
            "-ac", "1",
            "-b:a", "128k",
            output_path
        ]

        if not run_ffmpeg(cmd, "tratar_audio"):
            shutil.copy(input_path, output_path)

        return os.path.exists(output_path)

    except Exception as e:
        logger.error(f"Erro tratar_audio: {e}")
        shutil.copy(input_path, output_path)
        return True


# ─── PIPELINE COMPLETO ───────────────────────────────────
def pipeline_tts(
    narracao_completa: str,
    output_dir: str,
    persona: str = "contador",
) -> dict | None:
    """
    Pipeline completo:
    1. Tenta ElevenLabs (voz realista por persona)
    2. Fallback para gTTS se ElevenLabs falhar
    3. Tratamento profissional com FFmpeg

    Returns:
        dict com raw, final, duracao — ou None se tudo falhar
    """
    os.makedirs(output_dir, exist_ok=True)

    raw_path   = os.path.join(output_dir, "narracao_raw.mp3")
    final_path = os.path.join(output_dir, "narracao_final.mp3")

    # 1. Tenta ElevenLabs
    ok = gerar_elevenlabs(narracao_completa, raw_path, persona)

    # 2. Fallback gTTS
    if not ok:
        logger.warning("ElevenLabs falhou — usando gTTS como fallback")
        ok = gerar_gtts(narracao_completa, raw_path)

    if not ok:
        logger.error("Falha em todos os TTS")
        return None

    # 3. Tratamento
    logger.info("Aplicando tratamento de áudio...")
    tratar_audio(raw_path, final_path)

    duracao = get_duracao(final_path)
    logger.info(f"TTS pipeline concluído — {duracao:.1f}s" if duracao else "TTS concluído")

    return {
        "raw":     raw_path,
        "final":   final_path,
        "duracao": duracao,
    }

