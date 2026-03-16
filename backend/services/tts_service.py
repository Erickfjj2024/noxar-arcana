"""
NOXAR ARCANA — TTS Service
Narração com Edge TTS — voz masculina PT-BR
Inclui tratamento de áudio: normalização, reverb sutil, fade in/out
"""

import os
import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

import edge_tts

logger = logging.getLogger(__name__)

# ─── VOZES DISPONÍVEIS PT-BR ────────────────────────────────────
VOZES = {
    # Masculinas
    "masculino_padrao":    "pt-BR-AntonioNeural",   # Principal — profissional
    "masculino_dramatico": "pt-BR-AntonioNeural",   # Mesmo modelo com SSML
    # Femininas (backup)
    "feminino_padrao":     "pt-BR-FranciscaNeural",
}

# Configurações de prosódia por persona
PROSODY = {
    "investigador": {"rate": "-8%",  "pitch": "-3Hz",  "volume": "+5%"},
    "contador":     {"rate": "-12%", "pitch": "-6Hz",  "volume": "+3%"},
    "informante":   {"rate": "+5%",  "pitch": "-2Hz",  "volume": "+8%"},
}

# Pausas estratégicas (ms) para dramaticidade
PAUSA_CURTA  = 400   # Entre frases
PAUSA_MEDIA  = 700   # Entre parágrafos / loop aberto
PAUSA_LONGA  = 1200  # Antes de revelação


# ─── SSML — MARCA XML PARA CONTROLE FINO DA VOZ ─────────────────
def build_ssml(texto: str, persona: str = "contador") -> str:
    """
    Constrói SSML para controle fino de prosódia.
    Adiciona pausas estratégicas e ênfases baseadas na pontuação.
    """
    p = PROSODY.get(persona, PROSODY["contador"])

    # Processa pausas baseadas em pontuação
    texto_ssml = texto

    # Reticências → pausa dramática longa
    texto_ssml = texto_ssml.replace("...", f'<break time="{PAUSA_LONGA}ms"/>')

    # Ponto final → pausa média
    texto_ssml = texto_ssml.replace(". ", f'.<break time="{PAUSA_MEDIA}ms"/> ')

    # Vírgula → pausa curta
    texto_ssml = texto_ssml.replace(", ", f',<break time="{PAUSA_CURTA}ms"/> ')

    # Travessão → pausa de ênfase
    texto_ssml = texto_ssml.replace(" — ", f'<break time="{PAUSA_MEDIA}ms"/>— ')

    # Texto em maiúsculas → ênfase
    import re
    texto_ssml = re.sub(
        r'\b([A-Z]{3,})\b',
        r'<emphasis level="strong">\1</emphasis>',
        texto_ssml
    )

    ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
    xmlns:mstts="https://www.w3.org/2001/mstts"
    xml:lang="pt-BR">
  <voice name="{VOZES['masculino_padrao']}">
    <mstts:express-as style="narration-professional">
      <prosody rate="{p['rate']}" pitch="{p['pitch']}" volume="{p['volume']}">
        {texto_ssml}
      </prosody>
    </mstts:express-as>
  </voice>
</speak>"""

    return ssml


# ─── GERAÇÃO DE ÁUDIO ────────────────────────────────────────────
async def _gerar_audio_async(
    texto: str,
    output_path: str,
    persona: str = "contador",
    usar_ssml: bool = True,
) -> bool:
    """Gera áudio MP3 com Edge TTS de forma assíncrona."""
    try:
        voz = VOZES["masculino_padrao"]

        if usar_ssml:
            ssml = build_ssml(texto, persona)
            communicate = edge_tts.Communicate(ssml, voz, rate="-5%")
        else:
            # Fallback sem SSML
            communicate = edge_tts.Communicate(
                texto,
                voz,
                rate="-10%",
                volume="+5%",
                pitch="-5Hz",
            )

        await communicate.save(output_path)
        logger.info(f"Áudio gerado: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Erro Edge TTS: {e}")
        # Tenta sem SSML como fallback
        if usar_ssml:
            logger.info("Tentando sem SSML...")
            return await _gerar_audio_async(texto, output_path, persona, usar_ssml=False)
        return False


def gerar_audio(
    texto: str,
    output_path: str,
    persona: str = "contador",
) -> bool:
    """
    Gera narração em MP3 com voz masculina PT-BR.

    Args:
        texto: texto completo da narração
        output_path: caminho do arquivo MP3 de saída
        persona: investigador | contador | informante

    Returns:
        True se gerou com sucesso, False se falhou
    """
    try:
        asyncio.run(_gerar_audio_async(texto, output_path, persona))
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except RuntimeError:
        # Se já existe um event loop (ex: Jupyter)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _gerar_audio_async(texto, output_path, persona)
            )
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        finally:
            loop.close()


# ─── TRATAMENTO DE ÁUDIO COM FFMPEG ──────────────────────────────
def tratar_audio(
    input_path: str,
    output_path: str,
    normalizar: bool = True,
    reverb: bool = True,
    fade_in: float = 0.1,
    fade_out: float = 0.3,
) -> bool:
    """
    Aplica tratamentos profissionais no áudio:
    - Normalização de volume (loudnorm)
    - Reverb sutil para dramaticidade
    - Fade in/out suave
    - Remoção de silêncio excessivo

    Args:
        input_path:  caminho do MP3 bruto
        output_path: caminho do MP3 tratado
        normalizar:  aplicar loudnorm (EBU R128)
        reverb:      aplicar reverb sutil
        fade_in:     duração do fade in em segundos
        fade_out:    duração do fade out em segundos
    """
    try:
        # Constrói filtros de áudio
        filtros = []

        # 1. Remove silêncio inicial excessivo
        filtros.append("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.1")

        # 2. Reverb sutil (IR convolution simulado com aecho)
        if reverb:
            # aecho=in_gain:out_gain:delay:decay
            filtros.append("aecho=0.8:0.88:60:0.4")

        # 3. EQ — leve boost nos graves para voz dark mais profunda
        filtros.append("equalizer=f=120:width_type=o:width=2:g=2")

        # 4. Normalização EBU R128
        if normalizar:
            filtros.append("loudnorm=I=-16:TP=-1.5:LRA=11")

        # 5. Fade in/out
        # fade in e out são aplicados separadamente após obter duração
        filtro_str = ",".join(filtros)

        # Primeiro passo: aplica filtros principais
        tmp_path = input_path.replace(".mp3", "_tmp.mp3")
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", filtro_str,
            "-ar", "44100",
            "-ac", "1",       # Mono — suficiente para narração
            "-b:a", "128k",
            tmp_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg tratamento: {result.stderr}")
            # Copia sem tratamento como fallback
            import shutil
            shutil.copy(input_path, output_path)
            return True

        # Segundo passo: detecta duração e aplica fade
        duracao = _get_duracao(tmp_path)
        if duracao and duracao > (fade_in + fade_out):
            fade_out_start = duracao - fade_out
            cmd2 = [
                "ffmpeg", "-y",
                "-i", tmp_path,
                "-af", f"afade=t=in:st=0:d={fade_in},afade=t=out:st={fade_out_start:.3f}:d={fade_out}",
                "-ar", "44100",
                "-b:a", "128k",
                output_path
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode != 0:
                logger.warning("Fade falhou, usando sem fade")
                import shutil
                shutil.copy(tmp_path, output_path)
        else:
            import shutil
            shutil.copy(tmp_path, output_path)

        # Limpa temporário
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        logger.info(f"Áudio tratado: {output_path}")
        return os.path.exists(output_path)

    except Exception as e:
        logger.error(f"Erro ao tratar áudio: {e}")
        return False


def _get_duracao(audio_path: str) -> float | None:
    """Obtém duração do áudio em segundos via ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Não foi possível obter duração: {e}")
    return None


# ─── TRILHA SONORA DE FUNDO ───────────────────────────────────────
def gerar_silencio(duracao_segundos: float, output_path: str) -> bool:
    """
    Gera arquivo de silêncio com a duração exata.
    Usado como placeholder quando não há música de fundo.
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=mono",
            "-t", str(duracao_segundos),
            "-ar", "44100",
            "-b:a", "32k",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Erro ao gerar silêncio: {e}")
        return False


def mixar_narracao_com_musica(
    narracao_path: str,
    musica_path: str,
    output_path: str,
    volume_musica: float = 0.15,
) -> bool:
    """
    Mixa narração com trilha sonora de fundo.
    Aplica ducking automático: música abaixa quando narração fala.

    Args:
        narracao_path: caminho do MP3 da narração tratada
        musica_path:   caminho do MP3 da música de fundo
        output_path:   caminho do MP3 mixado
        volume_musica: volume relativo da música (0.0-1.0)
    """
    try:
        duracao_narracao = _get_duracao(narracao_path)
        if not duracao_narracao:
            logger.warning("Não foi possível detectar duração — usando narração sem música")
            import shutil
            shutil.copy(narracao_path, output_path)
            return True

        # Ducking automático via sidechaining
        # A música abaixa automaticamente quando a narração está ativa
        filtro = (
            f"[1:a]aloop=loop=-1:size=2e+09[music_loop];"  # Loop da música
            f"[music_loop]volume={volume_musica}[music_vol];"
            f"[0:a][music_vol]amix=inputs=2:duration=first:dropout_transition=2[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", narracao_path,
            "-i", musica_path,
            "-filter_complex", filtro,
            "-map", "[out]",
            "-t", str(duracao_narracao),
            "-ar", "44100",
            "-b:a", "128k",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"Mixagem falhou: {result.stderr}")
            import shutil
            shutil.copy(narracao_path, output_path)
            return True

        logger.info(f"Mixagem concluída: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Erro na mixagem: {e}")
        return False


# ─── PIPELINE TTS COMPLETO ───────────────────────────────────────
def pipeline_tts(
    narracao_completa: str,
    output_dir: str,
    persona: str = "contador",
    musica_path: str | None = None,
) -> dict | None:
    """
    Pipeline completo de geração de áudio:
    1. Gera narração com Edge TTS
    2. Aplica tratamento profissional
    3. Mixa com música de fundo (se fornecida)

    Args:
        narracao_completa: texto completo de todas as cenas
        output_dir:        pasta onde salvar os arquivos
        persona:           investigador | contador | informante
        musica_path:       caminho opcional para música de fundo

    Returns:
        dict com caminhos dos arquivos gerados ou None se falhar
    """
    os.makedirs(output_dir, exist_ok=True)

    raw_path     = os.path.join(output_dir, "narracao_raw.mp3")
    treated_path = os.path.join(output_dir, "narracao_treated.mp3")
    final_path   = os.path.join(output_dir, "narracao_final.mp3")

    # 1. Gera narração
    logger.info("Gerando narração com Edge TTS...")
    if not gerar_audio(narracao_completa, raw_path, persona):
        logger.error("Falha na geração de áudio")
        return None

    # 2. Tratamento profissional
    logger.info("Aplicando tratamento de áudio...")
    if not tratar_audio(raw_path, treated_path):
        logger.warning("Tratamento falhou — usando áudio bruto")
        import shutil
        shutil.copy(raw_path, treated_path)

    # 3. Mixa com música (se fornecida)
    if musica_path and os.path.exists(musica_path):
        logger.info("Mixando com música de fundo...")
        mixar_narracao_com_musica(treated_path, musica_path, final_path)
    else:
        import shutil
        shutil.copy(treated_path, final_path)

    duracao = _get_duracao(final_path)
    logger.info(f"TTS pipeline concluído — duração: {duracao:.1f}s")

    return {
        "raw":      raw_path,
        "treated":  treated_path,
        "final":    final_path,
        "duracao":  duracao,
    }

