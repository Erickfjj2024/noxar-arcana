"""
NOXAR ARCANA — Image Service
Geração de imagens via Pollinations.ai (modelo Flux)
Seeds consistentes por cena, download paralelo, retry automático
"""

import os
import time
import logging
import hashlib
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ─── CONFIGURAÇÕES ───────────────────────────────────────────────
POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
IMAGE_WIDTH       = 1080
IMAGE_HEIGHT      = 1920   # 9:16 vertical
IMAGE_MODEL       = "flux"
MAX_RETRIES       = 2
TIMEOUT_SEGUNDOS  = 60
DELAY_ENTRE_IMGS  = 3.0    # Delay maior para evitar 429


# ─── UTILITÁRIOS ─────────────────────────────────────────────────
def build_url(
    prompt: str,
    seed: int,
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT,
    negative_prompt: str = "",
) -> str:
    """Constrói URL da API do Pollinations com parâmetros."""
    prompt_encoded = quote(prompt)

    url = (
        f"{POLLINATIONS_BASE}/{prompt_encoded}"
        f"?width={width}"
        f"&height={height}"
        f"&model={IMAGE_MODEL}"
        f"&seed={seed}"
        f"&nologo=true"
        f"&enhance=true"
    )

    if negative_prompt:
        url += f"&negative={quote(negative_prompt)}"

    return url


def prompt_para_seed(prompt: str, base_seed: int = 0) -> int:
    """
    Gera seed determinístico baseado no prompt + seed base.
    Garante que o mesmo prompt sempre gere a mesma imagem.
    """
    hash_val = int(hashlib.md5(f"{base_seed}_{prompt}".encode()).hexdigest(), 16)
    return (hash_val % 2_000_000) + 1


# ─── DOWNLOAD INDIVIDUAL ─────────────────────────────────────────
async def _baixar_imagem_async(
    session: aiohttp.ClientSession,
    url: str,
    output_path: str,
    retries: int = MAX_RETRIES,
) -> bool:
    """Baixa uma imagem de forma assíncrona com retry."""
    for attempt in range(retries):
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_SEGUNDOS)
            ) as response:
                if response.status == 200:
                    content = await response.read()
                    if len(content) > 1000:  # Verifica se é uma imagem válida
                        async with aiofiles.open(output_path, "wb") as f:
                            await f.write(content)
                        return True
                    else:
                        logger.warning(f"Imagem muito pequena na tentativa {attempt + 1}")
                else:
                    logger.warning(f"Status {response.status} na tentativa {attempt + 1}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout na tentativa {attempt + 1}: {url[:80]}")
        except Exception as e:
            logger.warning(f"Erro tentativa {attempt + 1}: {e}")

        if attempt < retries - 1:
            await asyncio.sleep(5 * (attempt + 1))  # backoff maior

    return False


# ─── DOWNLOAD EM LOTE ────────────────────────────────────────────
async def _baixar_lote_async(
    segmentos: list[dict],
    output_dir: str,
) -> list[dict]:
    """
    Baixa todas as imagens de um lote de forma assíncrona.
    Limita concorrência para respeitar rate limit do Pollinations.
    """
    os.makedirs(output_dir, exist_ok=True)
    resultados = []

    # Semáforo para limitar concorrência (máx 3 simultâneas)
    semaforo = asyncio.Semaphore(1)  # Sequencial — evita 429

    async def baixar_com_semaforo(seg: dict, idx: int) -> dict:
        async with semaforo:
            output_path = os.path.join(output_dir, f"img_{idx:03d}.jpg")

            url = build_url(
                prompt=seg.get("prompt_imagem", ""),
                seed=seg.get("seed", idx * 100),
                negative_prompt=seg.get("prompt_negativo", ""),
            )

            logger.info(f"Baixando imagem {idx + 1}/{len(segmentos)}")
            sucesso = await _baixar_imagem_async(
                session, url, output_path
            )

            resultado = {
                **seg,
                "imagem_path": output_path if sucesso else None,
                "imagem_url":  url,
                "sucesso":     sucesso,
                "indice":      idx,
            }

            # Delay entre downloads
            await asyncio.sleep(DELAY_ENTRE_IMGS)
            return resultado

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            baixar_com_semaforo(seg, idx)
            for idx, seg in enumerate(segmentos)
        ]
        resultados = await asyncio.gather(*tasks, return_exceptions=True)

    # Filtra erros
    resultados_validos = []
    for r in resultados:
        if isinstance(r, Exception):
            logger.error(f"Erro no download: {r}")
            resultados_validos.append({"sucesso": False, "imagem_path": None})
        else:
            resultados_validos.append(r)

    return resultados_validos


def baixar_imagens_lote(
    segmentos: list[dict],
    output_dir: str,
) -> list[dict]:
    """
    Interface síncrona para download em lote.

    Args:
        segmentos:  lista de dicts com prompt_imagem, seed, prompt_negativo
        output_dir: pasta onde salvar as imagens

    Returns:
        lista de dicts com campo imagem_path adicionado
    """
    try:
        return asyncio.run(_baixar_lote_async(segmentos, output_dir))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                _baixar_lote_async(segmentos, output_dir)
            )
        finally:
            loop.close()


# ─── IMAGEM DE FALLBACK ───────────────────────────────────────────
def criar_imagem_fallback(
    output_path: str,
    cor_fundo: tuple = (10, 10, 20),
    texto: str = "",
) -> bool:
    """
    Cria imagem preta sólida como fallback quando Pollinations falha.
    Usa FFmpeg para não precisar do Pillow.
    """
    import subprocess
    try:
        r, g, b = cor_fundo
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={r:02x}{g:02x}{b:02x}:size={IMAGE_WIDTH}x{IMAGE_HEIGHT}:rate=1",
            "-frames:v", "1",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Erro ao criar fallback: {e}")
        return False


# ─── PROCESSAMENTO PÓS-DOWNLOAD ──────────────────────────────────
def garantir_dimensoes(
    imagem_path: str,
    output_path: str,
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT,
) -> bool:
    """
    Garante que a imagem tem exatamente as dimensões 9:16.
    Faz crop centralizado se necessário.
    """
    import subprocess
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", imagem_path,
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            ),
            "-frames:v", "1",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Erro ao redimensionar: {e}")
        return False


# ─── PIPELINE PRINCIPAL ───────────────────────────────────────────
def pipeline_imagens(
    storyboard: list[dict],
    output_dir: str,
    nicho: str = "misterio",
) -> list[dict] | None:
    """
    Pipeline completo de geração de imagens:
    1. Extrai todos os segmentos do storyboard
    2. Atribui seeds determinísticos
    3. Baixa todas as imagens em paralelo
    4. Garante dimensões corretas
    5. Cria fallbacks para falhas

    Args:
        storyboard: lista de cenas com segmentos visuais
        output_dir: pasta onde salvar as imagens
        nicho:      para prefixo nos logs

    Returns:
        lista de segmentos com imagem_path preenchido
    """
    logger.info(f"Iniciando pipeline de imagens — nicho: {nicho}")
    os.makedirs(output_dir, exist_ok=True)

    # 1. Extrai todos os segmentos em uma lista plana
    todos_segmentos = []
    for cena in storyboard:
        for seg in cena.get("segmentos", []):
            todos_segmentos.append(seg)

    if not todos_segmentos:
        logger.error("Nenhum segmento encontrado no storyboard")
        return None

    logger.info(f"Total de imagens a gerar: {len(todos_segmentos)}")

    # 2. Atribui seeds determinísticos se não tiverem
    for i, seg in enumerate(todos_segmentos):
        if not seg.get("seed"):
            seg["seed"] = prompt_para_seed(
                seg.get("prompt_imagem", ""), base_seed=i
            )

    # 3. Download em lote
    resultados = baixar_imagens_lote(todos_segmentos, output_dir)

    # 4. Pós-processamento — garante dimensões e cria fallbacks
    segmentos_finais = []
    sucessos = 0
    falhas   = 0

    for i, resultado in enumerate(resultados):
        img_path = resultado.get("imagem_path")

        if img_path and os.path.exists(img_path):
            # Garante dimensões corretas
            resized_path = img_path.replace(".jpg", "_resized.jpg")
            if garantir_dimensoes(img_path, resized_path):
                resultado["imagem_path"] = resized_path
                sucessos += 1
            else:
                resultado["imagem_path"] = img_path  # Usa original se resize falhar
                sucessos += 1
        else:
            # Cria fallback preto
            fallback_path = os.path.join(output_dir, f"fallback_{i:03d}.jpg")
            criar_imagem_fallback(fallback_path)
            resultado["imagem_path"] = fallback_path
            falhas += 1
            logger.warning(f"Fallback criado para segmento {i}")

        segmentos_finais.append(resultado)

    logger.info(
        f"Pipeline imagens concluído: {sucessos} sucesso, {falhas} fallback"
    )

    return segmentos_finais

