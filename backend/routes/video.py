"""
NOXAR ARCANA — Video Route
Endpoint principal: orquestra todo o pipeline e entrega vídeo para download
"""

import os
import uuid
import shutil
import logging
from flask import Blueprint, request, jsonify, g, send_file, after_this_request
from routes.auth import require_auth
from services.groq_service import pipeline_roteiro, transcrever_audio
from services.tts_service import pipeline_tts
from services.image_service import pipeline_imagens
from services.ffmpeg_service import pipeline_video
from supabase import create_client

logger = logging.getLogger(__name__)

video_bp = Blueprint("video", __name__)

TEMP_DIR = os.getenv("TEMP_VIDEO_DIR", "/tmp/noxar_videos")


# ─── SUPABASE CLIENT ─────────────────────────────────────────────
def get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


# ─── HELPERS ─────────────────────────────────────────────────────
def update_video_status(video_id: str, status: str, error: str = None, video_url: str = None):
    """Atualiza status do vídeo no Supabase."""
    try:
        supabase = get_supabase()
        data = {"status": status}
        if error:
            data["error_msg"] = error
        if video_url:
            data["video_url"] = video_url
        if status == "done":
            from datetime import datetime, timezone
            data["completed_at"] = datetime.now(timezone.utc).isoformat()

        supabase.table("videos").update(data).eq("id", video_id).execute()
    except Exception as e:
        logger.warning(f"Falha ao atualizar status: {e}")


def extrair_narracao_completa(roteiro: dict) -> str:
    """Concatena narração de todas as cenas em texto único."""
    cenas = roteiro.get("cenas", [])
    partes = []

    gancho = roteiro.get("gancho", "")
    if gancho:
        partes.append(gancho)

    for cena in cenas:
        narracao = cena.get("narracao", "").strip()
        if narracao:
            partes.append(narracao)

    encerramento = roteiro.get("encerramento", "")
    if encerramento:
        partes.append(encerramento)

    return " ".join(partes)


def extrair_segmentos_planos(storyboard: list) -> list:
    """Extrai lista plana de segmentos do storyboard aninhado."""
    segmentos = []
    for cena in storyboard:
        for seg in cena.get("segmentos", []):
            segmentos.append(seg)
    return segmentos


# ─── ENDPOINT PRINCIPAL ───────────────────────────────────────────
@video_bp.route("/gerar", methods=["POST"])
@require_auth
def gerar_video():
    """
    Pipeline completo de geração de vídeo.

    Body JSON:
    {
        "tema":       "string",
        "nicho":      "true_crime|terror|misterio|dark_history",
        "plataforma": "tiktok|youtube|kwai|reels",
        "duracao":    60,
        "persona":    "investigador|contador|informante",
        "template":   "sangue_frio|nevoa|abismo"
    }

    Retorna o arquivo MP4 diretamente para download.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "body JSON inválido"}), 400

    # Valida campos
    campos = ["tema", "nicho", "plataforma", "duracao", "persona", "template"]
    for campo in campos:
        if campo not in data:
            return jsonify({"error": f"campo obrigatório: {campo}"}), 400

    tema       = str(data["tema"]).strip()
    nicho      = str(data["nicho"]).strip()
    plataforma = str(data["plataforma"]).strip()
    duracao    = int(data["duracao"])
    persona    = str(data["persona"]).strip()
    template   = str(data["template"]).strip()

    if not tema or duracao < 15 or duracao > 600:
        return jsonify({"error": "parâmetros inválidos"}), 400

    # Cria registro no Supabase
    video_id  = str(uuid.uuid4())
    work_dir  = os.path.join(TEMP_DIR, video_id)
    os.makedirs(work_dir, exist_ok=True)

    try:
        supabase = get_supabase()
        supabase.table("videos").insert({
            "id":              video_id,
            "user_id":         g.user_id,
            "title":           tema[:100],
            "niche":           nicho,
            "platform":        plataforma,
            "persona":         persona,
            "template":        template,
            "duration_target": duracao,
            "status":          "processing",
        }).execute()
    except Exception as e:
        logger.warning(f"Falha ao criar registro: {e}")

    logger.info(f"[{video_id[:8]}] Iniciando pipeline — '{tema[:40]}'")

    try:
        # ── ETAPA 1: ROTEIRO ─────────────────────────────────────
        logger.info(f"[{video_id[:8]}] Etapa 1/5: Roteiro")
        update_video_status(video_id, "processing")

        resultado_roteiro = pipeline_roteiro(
            tema=tema,
            nicho=nicho,
            plataforma=plataforma,
            duracao=duracao,
            persona=persona,
            template=template,
        )

        if not resultado_roteiro:
            update_video_status(video_id, "error", "falha na geração do roteiro")
            return jsonify({"error": "falha ao gerar roteiro"}), 500

        roteiro    = resultado_roteiro["roteiro"]
        storyboard = resultado_roteiro["storyboard"]

        # Salva roteiro no Supabase
        try:
            supabase.table("videos").update({
                "script": resultado_roteiro,
                "title":  roteiro.get("titulo", tema)[:100],
            }).eq("id", video_id).execute()
        except Exception:
            pass

        # ── ETAPA 2: IMAGENS ─────────────────────────────────────
        logger.info(f"[{video_id[:8]}] Etapa 2/5: Imagens")
        images_dir = os.path.join(work_dir, "images")

        segmentos_com_imagens = pipeline_imagens(
            storyboard=storyboard,
            output_dir=images_dir,
            nicho=nicho,
        )

        if not segmentos_com_imagens:
            update_video_status(video_id, "error", "falha na geração de imagens")
            return jsonify({"error": "falha ao gerar imagens"}), 500

        # ── ETAPA 3: NARRAÇÃO ────────────────────────────────────
        logger.info(f"[{video_id[:8]}] Etapa 3/5: Narração")
        audio_dir     = os.path.join(work_dir, "audio")
        narracao_text = extrair_narracao_completa(roteiro)

        resultado_tts = pipeline_tts(
            narracao_completa=narracao_text,
            output_dir=audio_dir,
            persona=persona,
        )

        if not resultado_tts:
            update_video_status(video_id, "error", "falha na geração de narração")
            return jsonify({"error": "falha ao gerar narração"}), 500

        audio_final = resultado_tts["final"]

        # ── ETAPA 4: TRANSCRIÇÃO (WHISPER) ───────────────────────
        logger.info(f"[{video_id[:8]}] Etapa 4/5: Whisper")
        transcricao = transcrever_audio(audio_final)
        palavras_whisper = transcricao.get("words", []) if transcricao else []

        if not palavras_whisper:
            logger.warning(f"[{video_id[:8]}] Whisper sem palavras — legendas desativadas")

        # ── ETAPA 5: MONTAGEM ────────────────────────────────────
        logger.info(f"[{video_id[:8]}] Etapa 5/5: Montagem")
        video_dir = os.path.join(work_dir, "video")

        video_final = pipeline_video(
            segmentos=segmentos_com_imagens,
            audio_path=audio_final,
            palavras_whisper=palavras_whisper,
            output_dir=video_dir,
            titulo=roteiro.get("titulo", tema),
            template=template,
            nicho=nicho,
        )

        if not video_final or not os.path.exists(video_final):
            update_video_status(video_id, "error", "falha na montagem do vídeo")
            return jsonify({"error": "falha ao montar vídeo"}), 500

        # ── ENTREGA ──────────────────────────────────────────────
        update_video_status(video_id, "done")

        # Incrementa contador de vídeos do usuário
        try:
            supabase.rpc("increment_video_count", {"user_uuid": g.user_id}).execute()
        except Exception:
            pass

        tamanho = os.path.getsize(video_final)
        logger.info(
            f"[{video_id[:8]}] ✅ Concluído — "
            f"{tamanho / (1024*1024):.1f}MB"
        )

        # Nome do arquivo para download
        titulo_slug = roteiro.get("titulo", "noxar_video")\
            .lower()\
            .replace(" ", "_")\
            .replace("/", "_")[:40]
        filename = f"{titulo_slug}_{video_id[:8]}.mp4"

        # Deleta pasta de trabalho após enviar o arquivo
        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
                logger.info(f"[{video_id[:8]}] Temp limpo")
            except Exception:
                pass
            return response

        return send_file(
            video_final,
            mimetype="video/mp4",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        logger.error(f"[{video_id[:8]}] Erro inesperado: {e}", exc_info=True)
        update_video_status(video_id, "error", str(e)[:200])
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
        return jsonify({"error": "erro interno — tente novamente"}), 500


# ─── HISTÓRICO ───────────────────────────────────────────────────
@video_bp.route("/historico", methods=["GET"])
@require_auth
def historico():
    """
    Retorna histórico de vídeos do usuário.
    Query params: limit (default 20), offset (default 0)
    """
    limit  = min(int(request.args.get("limit",  20)), 50)
    offset = int(request.args.get("offset", 0))

    try:
        supabase = get_supabase()
        response = supabase.table("videos")\
            .select("id,title,niche,platform,persona,template,status,created_at,completed_at,duration_target")\
            .eq("user_id", g.user_id)\
            .order("created_at", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()

        return jsonify({
            "success": True,
            "videos":  response.data,
            "total":   len(response.data),
        }), 200

    except Exception as e:
        logger.error(f"Erro ao buscar histórico: {e}")
        return jsonify({"error": "erro ao buscar histórico"}), 500


# ─── STATUS ──────────────────────────────────────────────────────
@video_bp.route("/status/<video_id>", methods=["GET"])
@require_auth
def status(video_id: str):
    """Retorna status atual de um vídeo específico."""
    try:
        supabase = get_supabase()
        response = supabase.table("videos")\
            .select("id,title,status,error_msg,created_at,completed_at")\
            .eq("id", video_id)\
            .eq("user_id", g.user_id)\
            .single()\
            .execute()

        if not response.data:
            return jsonify({"error": "vídeo não encontrado"}), 404

        return jsonify({"success": True, "video": response.data}), 200

    except Exception as e:
        logger.error(f"Erro ao buscar status: {e}")
        return jsonify({"error": "erro ao buscar status"}), 500


# ─── DELETAR ─────────────────────────────────────────────────────
@video_bp.route("/<video_id>", methods=["DELETE"])
@require_auth
def deletar(video_id: str):
    """Remove um vídeo do histórico do usuário."""
    try:
        supabase = get_supabase()
        supabase.table("videos")\
            .delete()\
            .eq("id", video_id)\
            .eq("user_id", g.user_id)\
            .execute()

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Erro ao deletar vídeo: {e}")
        return jsonify({"error": "erro ao deletar vídeo"}), 500

