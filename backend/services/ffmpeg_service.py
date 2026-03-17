"""
NOXAR ARCANA — FFmpeg Service
Montagem profissional de vídeo:
- Ken Burns (zoom + pan) nas imagens
- Color grading por emoção
- Efeitos cinematográficos (flash, shake, vinheta, grain)
- Legenda karaoke word-by-word sincronizada
- Fade in/out entre cenas
- Intro e outro profissionais
"""

import os
import json
import math
import logging
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ─── CONFIGURAÇÕES ───────────────────────────────────────────────
VIDEO_WIDTH   = 1080
VIDEO_HEIGHT  = 1920
VIDEO_FPS     = 30
VIDEO_CODEC   = "libx264"
AUDIO_CODEC   = "aac"
VIDEO_BITRATE = "4M"
AUDIO_BITRATE = "128k"
CRF           = "18"       # Qualidade (menor = melhor, maior arquivo)
PRESET        = "medium"   # Velocidade de encoding


# ─── COLOR GRADING POR EMOÇÃO ────────────────────────────────────
COLOR_GRADES = {
    "misterio": {
        "curves":     "0/0 0.3/0.25 0.7/0.6 1/0.9",  # Sombras profundas
        "hue":        "H=0:S=0.7:V=0.85",             # Dessaturado frio
        "colorbalance": "rs=-0.1:gs=0:bs=0.15",       # Toque azul frio
        "vignette":   0.5,
        "grain":      0.03,
    },
    "tensao": {
        "curves":     "0/0 0.25/0.2 0.75/0.7 1/1",
        "hue":        "H=0:S=1.1:V=0.9",
        "colorbalance": "rs=0.15:gs=-0.05:bs=-0.1",  # Toque vermelho
        "vignette":   0.7,
        "grain":      0.04,
    },
    "choque": {
        "curves":     "0/0 0.1/0.05 0.9/0.95 1/1",
        "hue":        "H=0:S=0.5:V=1.0",              # Alto contraste
        "colorbalance": "rs=0.2:gs=-0.1:bs=-0.1",
        "vignette":   0.8,
        "grain":      0.05,
    },
    "revelacao": {
        "curves":     "0/0 0.3/0.28 0.7/0.65 1/0.95",
        "hue":        "H=180:S=0.8:V=0.85",           # Teal
        "colorbalance": "rs=-0.1:gs=0.05:bs=0.2",
        "vignette":   0.4,
        "grain":      0.025,
    },
    "calma": {
        "curves":     "0/0.05 0.5/0.5 1/0.95",
        "hue":        "H=0:S=0.6:V=0.9",
        "colorbalance": "rs=0:gs=0:bs=0",
        "vignette":   0.3,
        "grain":      0.02,
    },
}

# ─── PARÂMETROS KEN BURNS POR TEMPLATE ───────────────────────────
KEN_BURNS = {
    "sangue_frio": {"zoom_start": 1.0,  "zoom_end": 1.12, "speed": "fast"},
    "nevoa":       {"zoom_start": 1.05, "zoom_end": 1.18, "speed": "slow"},
    "abismo":      {"zoom_start": 1.0,  "zoom_end": 1.08, "speed": "medium"},
}

# ─── CONFIGURAÇÕES DE LEGENDA ────────────────────────────────────
SUBTITLE_FONT        = "Arial-Bold"
SUBTITLE_SIZE        = 72        # px
SUBTITLE_COLOR       = "white"
SUBTITLE_GLOW_COLOR  = "0x7B2FBE"
SUBTITLE_OUTLINE     = 4
SUBTITLE_Y_POSITION  = "(h*0.75)"  # 75% da altura


@dataclass
class Segmento:
    """Representa um segmento visual com imagem + timing."""
    imagem_path: str
    duracao: float
    emocao: str
    transicao: str
    timestamp_inicio: float
    timestamp_fim: float
    prompt_imagem: str = ""
    indice: int = 0


@dataclass
class PalavraTimestamp:
    """Palavra com timestamps para legenda karaoke."""
    palavra: str
    inicio: float
    fim: float


# ─── UTILITÁRIOS FFMPEG ──────────────────────────────────────────
def run_ffmpeg(cmd: list[str], desc: str = "") -> bool:
    """
    Executa FFmpeg com limites de recursos para Render free tier:
    - nice 19: prioridade mínima de CPU
    - RAM limitada a 400MB via resource.RLIMIT_AS
    """
    import resource

    def set_limits():
        # Limita memória virtual a 400MB
        # (deixa ~112MB livre para gunicorn + Flask)
        mem = 400 * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except Exception:
            pass
        # Prioridade mínima de CPU
        try:
            os.nice(19)
        except Exception:
            pass

    logger.info(f"FFmpeg: {desc or ' '.join(cmd[:4])}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            preexec_fn=set_limits,
        )
        if result.returncode != 0:
            logger.error(f"FFmpeg erro: {result.stderr[-300:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg timeout: {desc}")
        return False
    except Exception as e:
        logger.error(f"FFmpeg exceção: {e}")
        return False


def get_duracao(path: str) -> float:
    """Obtém duração de arquivo de mídia em segundos."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


# ─── KEN BURNS EFFECT ────────────────────────────────────────────
def build_kenburns_filter(
    duracao: float,
    template: str = "nevoa",
    emocao: str = "misterio",
    indice: int = 0,
) -> str:
    """
    Constrói filtro FFmpeg para efeito Ken Burns.
    Alterna entre zoom in, zoom out e pan baseado no índice.
    """
    kb     = KEN_BURNS.get(template, KEN_BURNS["nevoa"])
    fps    = 24  # 24fps — menos frames, menos memória RAM
    frames = int(duracao * fps)

    z_start = kb["zoom_start"]
    z_end   = kb["zoom_end"]

    # Alterna direção baseado no índice para variedade
    movimentos = [
        # (zoom, x_expr, y_expr)
        (f"zoom+{(z_end-z_start)/frames:.6f}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),   # Centro
        (f"zoom+{(z_end-z_start)/frames:.6f}", "0", "0"),                                   # Canto sup-esq
        (f"zoom+{(z_end-z_start)/frames:.6f}", "iw-(iw/zoom)", "ih-(ih/zoom)"),             # Canto inf-dir
        (f"if(lte(zoom,{z_start}),{z_end},{z_start})",
         "iw/2-(iw/zoom/2)+{pan}".format(pan=int(VIDEO_WIDTH * 0.02)),
         "ih/2-(ih/zoom/2)"),                                                                 # Pan lateral
    ]

    mov = movimentos[indice % len(movimentos)]
    zoom_expr, x_expr, y_expr = mov

    return (
        f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
        f"zoompan="
        f"z='{zoom_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d={frames}:"
        f"s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
        f"fps={fps}"
    )


# ─── COLOR GRADING ───────────────────────────────────────────────
def build_colorgrade_filter(emocao: str) -> str:
    """Constrói filtro de color grading para uma emoção."""
    grade = COLOR_GRADES.get(emocao, COLOR_GRADES["misterio"])

    filtros = []

    # Curves — contraste e sombras
    filtros.append(f"curves=all='{grade['curves']}'")

    # Vinheta
    v = grade["vignette"]
    if v > 0:
        filtros.append(
            f"vignette=PI/4*{v}:mode=backward"
        )

    # Grain de filme
    g = grade["grain"]
    if g > 0:
        filtros.append(
            f"noise=alls={int(g*100)}:allf=t+u"
        )

    return ",".join(filtros)


# ─── TRANSIÇÕES ──────────────────────────────────────────────────
def build_xfade_filter(
    transicao: str,
    duracao_transicao: float = 0.4,
) -> str:
    """Mapeia tipo de transição para filtro xfade do FFmpeg."""
    mapa = {
        "fade":          "fade",
        "dissolve":      "dissolve",
        "cut":           "fade",       # Corte seco = fade curtíssimo
        "flash_branco":  "fadewhite",
        "flash_vermelho":"fade",        # Vermelho simulado via colorbalance
    }
    return mapa.get(transicao, "fade")


# ─── LEGENDA KARAOKE ─────────────────────────────────────────────
def build_subtitle_filter(
    palavras: list[PalavraTimestamp],
    offset: float = 0.0,
) -> str:
    """
    Constrói filtro drawtext para legenda karaoke word-by-word.
    Cada palavra acende em roxo vibrante quando é falada.

    Args:
        palavras: lista de palavras com timestamps
        offset:   offset de tempo em segundos (para vídeos concatenados)
    """
    if not palavras:
        return ""

    filtros = []

    # Agrupa palavras em blocos de 3-4 para exibição
    PALAVRAS_POR_BLOCO = 3
    blocos = []

    for i in range(0, len(palavras), PALAVRAS_POR_BLOCO):
        bloco = palavras[i:i + PALAVRAS_POR_BLOCO]
        blocos.append(bloco)

    for bloco_idx, bloco in enumerate(blocos):
        if not bloco:
            continue

        bloco_inicio = bloco[0].inicio + offset
        bloco_fim    = bloco[-1].fim + offset
        texto_bloco  = " ".join(p.palavra for p in bloco)

        # Texto base do bloco (branco)
        filtros.append(
            f"drawtext="
            f"text='{_escape_text(texto_bloco)}':"
            f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"fontsize={SUBTITLE_SIZE}:"
            f"fontcolor=white:"
            f"borderw={SUBTITLE_OUTLINE}:"
            f"bordercolor=black:"
            f"x=(w-text_w)/2:"
            f"y={SUBTITLE_Y_POSITION}:"
            f"enable='between(t,{bloco_inicio:.3f},{bloco_fim:.3f})'"
        )

        # Highlight roxo em cada palavra individual
        x_acumulado = 0
        for palavra_idx, palavra in enumerate(bloco):
            p_inicio = palavra.inicio + offset
            p_fim    = palavra.fim + offset

            # Calcula posição X aproximada da palavra no bloco
            palavras_antes = " ".join(p.palavra for p in bloco[:palavra_idx])
            x_offset = f"(w-text_w)/2+{len(palavras_antes) * SUBTITLE_SIZE * 0.5:.0f}"

            filtros.append(
                f"drawtext="
                f"text='{_escape_text(palavra.palavra)}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize={int(SUBTITLE_SIZE * 1.08)}:"
                f"fontcolor=0xC77DFF:"
                f"borderw={SUBTITLE_OUTLINE + 1}:"
                f"bordercolor=0x4A0E8F:"
                f"x={x_offset}:"
                f"y={SUBTITLE_Y_POSITION}:"
                f"enable='between(t,{p_inicio:.3f},{p_fim:.3f})'"
            )

    return ",".join(filtros) if filtros else ""


def _escape_text(texto: str) -> str:
    """Escapa caracteres especiais para drawtext do FFmpeg."""
    return (
        texto
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


# ─── PROCESSAMENTO DE SEGMENTO INDIVIDUAL ───────────────────────
def processar_segmento(
    segmento: Segmento,
    output_path: str,
    template: str = "nevoa",
    palavras: list[PalavraTimestamp] | None = None,
) -> bool:
    """
    Processa segmento com qualidade completa mas uso controlado de CPU.
    Ken Burns + color grade + legendas — limitado a 1 thread de CPU.
    """
    kb_filter    = build_kenburns_filter(
        segmento.duracao, template, segmento.emocao, segmento.indice
    )
    grade_filter = build_colorgrade_filter(segmento.emocao)

    vf_parts = [kb_filter, grade_filter]

    if palavras:
        subtitle_filter = build_subtitle_filter(
            palavras, offset=-segmento.timestamp_inicio
        )
        if subtitle_filter:
            vf_parts.append(subtitle_filter)

    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-threads", "1",     # Limita a 1 thread de CPU — não mata o servidor
        "-loop", "1",
        "-i", segmento.imagem_path,
        "-vf", vf,
        "-t", str(segmento.duracao),
        "-r", str(VIDEO_FPS),
        "-pix_fmt", "yuv420p",
        "-preset", "faster",  # Bom equilíbrio qualidade/CPU
        "-crf", CRF,
        "-an",
        output_path
    ]

    return run_ffmpeg(cmd, f"Segmento {segmento.indice}")


# ─── CONCATENAÇÃO COM TRANSIÇÕES ────────────────────────────────
def concatenar_segmentos(
    segmentos_paths: list[str],
    transicoes: list[str],
    output_path: str,
    duracao_transicao: float = 0.4,
) -> bool:
    """
    Concatena todos os segmentos com transições xfade entre eles.
    """
    if len(segmentos_paths) == 1:
        import shutil
        shutil.copy(segmentos_paths[0], output_path)
        return True

    if len(segmentos_paths) == 0:
        return False

    # Cria arquivo de lista para concat simples (sem transições)
    # Para projetos futuros: implementar xfade encadeado
    lista_path = output_path.replace(".mp4", "_list.txt")
    with open(lista_path, "w") as f:
        for path in segmentos_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-threads", "1",
        "-f", "concat",
        "-safe", "0",
        "-i", lista_path,
        "-c", "copy",
        output_path
    ]

    sucesso = run_ffmpeg(cmd, "Concatenação")

    if os.path.exists(lista_path):
        os.remove(lista_path)

    return sucesso


# ─── ADICIONA ÁUDIO AO VÍDEO ────────────────────────────────────
def adicionar_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> bool:
    """Combina vídeo sem áudio com narração final."""
    duracao_video = get_duracao(video_path)
    duracao_audio = get_duracao(audio_path)

    # Usa a menor duração para não ter vídeo sem áudio ou vice-versa
    duracao_final = min(duracao_video, duracao_audio) if duracao_audio > 0 else duracao_video

    cmd = [
        "ffmpeg", "-y",
        "-threads", "1",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", AUDIO_CODEC,
        "-b:a", AUDIO_BITRATE,
        "-t", str(duracao_final),
        "-shortest",
        output_path
    ]

    return run_ffmpeg(cmd, "Adicionar áudio")


# ─── INTRO ───────────────────────────────────────────────────────
def criar_intro(
    titulo: str,
    output_path: str,
    duracao: float = 2.5,
) -> bool:
    """
    Cria intro com título em texto sobre fundo preto.
    Título aparece com fade in + glitch sutil.
    """
    titulo_escaped = _escape_text(titulo[:50])  # Limita tamanho

    # Fundo preto + texto centralizado com fade in
    vf = (
        f"color=black:size={VIDEO_WIDTH}x{VIDEO_HEIGHT}:rate={VIDEO_FPS},"
        f"drawtext="
        f"text='{titulo_escaped}':"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"fontsize=60:"
        f"fontcolor=white:"
        f"alpha='if(lt(t,0.5),t/0.5,1)':"
        f"x=(w-text_w)/2:"
        f"y=(h-text_h)/2:"
        f"borderw=3:"
        f"bordercolor=0x7B2FBE"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", vf,
        "-t", str(duracao),
        "-r", str(VIDEO_FPS),
        "-pix_fmt", "yuv420p",
        "-an",
        output_path
    ]

    return run_ffmpeg(cmd, "Criar intro")


# ─── OUTRO ───────────────────────────────────────────────────────
def criar_outro(output_path: str, duracao: float = 1.5) -> bool:
    """Cria fade to black final."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=black:size={VIDEO_WIDTH}x{VIDEO_HEIGHT}:rate={VIDEO_FPS}",
        "-t", str(duracao),
        "-r", str(VIDEO_FPS),
        "-pix_fmt", "yuv420p",
        "-an",
        output_path
    ]
    return run_ffmpeg(cmd, "Criar outro")


# ─── ENCODING FINAL ──────────────────────────────────────────────
def encoding_final(
    video_path: str,
    output_path: str,
) -> bool:
    """
    Encoding final otimizado para mobile:
    - H.264 compatível com todos os players
    - Fast start para streaming
    - Resolução 1080x1920 confirmada
    """
    cmd = [
        "ffmpeg", "-y",
        "-threads", "1",
        "-i", video_path,
        "-c:v", VIDEO_CODEC,
        "-crf", CRF,
        "-preset", "faster",
        "-c:a", AUDIO_CODEC,
        "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2",
        "-pix_fmt", "yuv420p",
        output_path
    ]

    return run_ffmpeg(cmd, "Encoding final")


# ─── PIPELINE PRINCIPAL ──────────────────────────────────────────
def pipeline_video(
    segmentos: list[dict],
    audio_path: str,
    palavras_whisper: list[dict],
    output_dir: str,
    titulo: str = "",
    template: str = "nevoa",
    nicho: str = "misterio",
) -> str | None:
    """
    Pipeline completo de montagem:
    1. Processa cada segmento (Ken Burns + color grade + legenda)
    2. Concatena todos os segmentos
    3. Adiciona áudio
    4. Encoding final otimizado

    Args:
        segmentos:        lista de segmentos com imagem_path e metadados
        audio_path:       caminho do áudio final (narração + música)
        palavras_whisper: timestamps por palavra do Whisper
        output_dir:       pasta de trabalho
        titulo:           título para intro
        template:         sangue_frio | nevoa | abismo
        nicho:            para logs

    Returns:
        caminho do vídeo final ou None se falhar
    """
    logger.info(f"Pipeline vídeo: {len(segmentos)} segmentos, template={template}")
    os.makedirs(output_dir, exist_ok=True)

    # Converte palavras do Whisper para dataclass
    palavras = [
        PalavraTimestamp(
            palavra=w.get("word", ""),
            inicio=w.get("start", 0),
            fim=w.get("end", 0),
        )
        for w in palavras_whisper
    ]

    # 1. Processa segmentos individuais
    segmentos_processados = []

    for i, seg_dict in enumerate(segmentos):
        img_path = seg_dict.get("imagem_path")
        if not img_path or not os.path.exists(img_path):
            logger.warning(f"Segmento {i} sem imagem, pulando")
            continue

        seg = Segmento(
            imagem_path=img_path,
            duracao=seg_dict.get("duracao_exibicao_segundos", 4.0),
            emocao=seg_dict.get("emocao", "misterio"),
            transicao=seg_dict.get("transicao_saida", "fade"),
            timestamp_inicio=seg_dict.get("timestamp_inicio", 0),
            timestamp_fim=seg_dict.get("timestamp_fim", 4),
            indice=i,
        )

        seg_output = os.path.join(output_dir, f"seg_{i:03d}.mp4")

        # Filtra palavras para este segmento
        palavras_seg = [
            p for p in palavras
            if p.inicio >= seg.timestamp_inicio and p.fim <= seg.timestamp_fim + 0.5
        ]

        if processar_segmento(seg, seg_output, template, palavras_seg):
            segmentos_processados.append({
                "path":     seg_output,
                "transicao": seg.transicao,
            })
        else:
            logger.warning(f"Falha no segmento {i}")

    if not segmentos_processados:
        logger.error("Nenhum segmento processado com sucesso")
        return None

    logger.info(f"Segmentos processados: {len(segmentos_processados)}")

    # 2. Intro
    intro_path = os.path.join(output_dir, "intro.mp4")
    tem_intro  = titulo and criar_intro(titulo, intro_path)

    # 3. Outro
    outro_path = os.path.join(output_dir, "outro.mp4")
    criar_outro(outro_path)

    # 4. Monta lista de concatenação
    todos_paths = []
    if tem_intro:
        todos_paths.append(intro_path)
    todos_paths.extend([s["path"] for s in segmentos_processados])
    todos_paths.append(outro_path)

    transicoes = ["fade"] + [s["transicao"] for s in segmentos_processados] + ["fade"]

    # 5. Concatena
    concat_path = os.path.join(output_dir, "concat.mp4")
    if not concatenar_segmentos(todos_paths, transicoes, concat_path):
        logger.error("Falha na concatenação")
        return None

    # 6. Adiciona áudio
    com_audio_path = os.path.join(output_dir, "com_audio.mp4")
    if not adicionar_audio(concat_path, audio_path, com_audio_path):
        logger.error("Falha ao adicionar áudio")
        return None

    # 7. Encoding final
    final_path = os.path.join(output_dir, "noxar_video_final.mp4")
    if not encoding_final(com_audio_path, final_path):
        logger.error("Falha no encoding final")
        return None

    tamanho_mb = os.path.getsize(final_path) / (1024 * 1024)
    duracao    = get_duracao(final_path)
    logger.info(
        f"✅ Vídeo final: {final_path} "
        f"({tamanho_mb:.1f}MB, {duracao:.1f}s)"
    )

    return final_path
