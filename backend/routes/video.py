"""
NOXAR ARCANA — Video Route
Sistema de polling: backend gera em background, frontend busca quando pronto.
"""

import os
import uuid
import shutil
import logging
import threading
import requests
from flask import Blueprint, request, jsonify, g, send_file
from routes.auth import require_auth
from services.groq_service import pipeline_roteiro, transcrever_audio
from services.tts_service import pipeline_tts
from services.image_service import pipeline_imagens
from services.ffmpeg_service import pipeline_video
from supabase import create_client

logger = logging.getLogger(__name__)

video_bp   = Blueprint("video", __name__)
TEMP_DIR   = os.getenv("TEMP_VIDEO_DIR", "/tmp/noxar_videos")
VIDEOS_DIR = os.path.join(TEMP_DIR, "ready")

NICHOS_VALIDOS = {"true_crime", "terror", "misterio", "dark_history"}
PLATAFORMAS_VALIDAS = {"tiktok", "youtube", "kwai", "reels"}
PERSONAS_VALIDAS = {"investigador", "contador", "informante"}
TEMPLATES_VALIDOS = {"sangue_frio", "nevoa", "abismo"}

PIPELINE_RUNNER = os.getenv("PIPELINE_RUNNER", "github").lower()
GITHUB_API = "https://api.github.com"


os.makedirs(TEMP_DIR,   exist_ok=True)
os.makedirs(VIDEOS_DIR, exist_ok=True)


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configurados")
    return create_client(url, key)


def update_status(video_id, status, error=None):
    try:
        data = {"status": status}
        if error:
            data["error_msg"] = error[:200]
        if status == "done":
            from datetime import datetime, timezone
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
        get_supabase().table("videos").update(data).eq("id", video_id).execute()
    except Exception as e:
        logger.warning(f"update_status: {e}")


def extrair_narracao(roteiro):
    partes = []
    if roteiro.get("gancho"):     partes.append(roteiro["gancho"])
    for c in roteiro.get("cenas", []):
        if c.get("narracao"):     partes.append(c["narracao"].strip())
    if roteiro.get("encerramento"): partes.append(roteiro["encerramento"])
    return " ".join(partes)


def dispatch_github_pipeline(video_id, user_id, tema, nicho, plataforma, duracao, persona, template):
    repo = os.getenv("GITHUB_ACTIONS_REPO")
    token = os.getenv("GITHUB_ACTIONS_TOKEN")
    workflow = os.getenv("GITHUB_ACTIONS_WORKFLOW", "video-on-demand.yml")
    ref = os.getenv("GITHUB_ACTIONS_REF", "main")

    if not repo or not token:
        raise RuntimeError("GITHUB_ACTIONS_REPO e GITHUB_ACTIONS_TOKEN são obrigatórios")

    url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{workflow}/dispatches"
    payload = {
        "ref": ref,
        "inputs": {
            "video_id": video_id,
            "user_id": user_id,
            "tema": tema,
            "nicho": nicho,
            "plataforma": plataforma,
            "duracao": str(duracao),
            "persona": persona,
            "template": template,
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if resp.status_code != 204:
        raise RuntimeError(f"Falha ao disparar workflow GitHub ({resp.status_code}): {resp.text[:300]}")


def run_pipeline(video_id, user_id, tema, nicho, plataforma, duracao, persona, template):
    work_dir = os.path.join(TEMP_DIR, video_id)
    os.makedirs(work_dir, exist_ok=True)
    try:
        logger.info(f"[{video_id[:8]}] Iniciando pipeline")

        # 1. Roteiro
        resultado = pipeline_roteiro(tema, nicho, plataforma, duracao, persona, template)
        if not resultado:
            return update_status(video_id, "error", "falha no roteiro")

        roteiro    = resultado["roteiro"]
        storyboard = resultado["storyboard"]

        try:
            get_supabase().table("videos").update({
                "script": resultado,
                "title":  roteiro.get("titulo", tema)[:100],
            }).eq("id", video_id).execute()
        except Exception:
            pass

        # 2. Imagens
        segmentos = pipeline_imagens(storyboard, os.path.join(work_dir, "images"), nicho)
        if not segmentos:
            return update_status(video_id, "error", "falha nas imagens")

        # 3. Narração
        resultado_tts = pipeline_tts(extrair_narracao(roteiro), os.path.join(work_dir, "audio"), persona)
        if not resultado_tts:
            return update_status(video_id, "error", "falha na narração")

        # 4. Whisper
        transcricao  = transcrever_audio(resultado_tts["final"])
        palavras     = transcricao.get("words", []) if transcricao else []

        # 5. Montagem
        video_path = pipeline_video(
            segmentos, resultado_tts["final"], palavras,
            os.path.join(work_dir, "video"),
            roteiro.get("titulo", tema), template, nicho
        )
        if not video_path or not os.path.exists(video_path):
            return update_status(video_id, "error", "falha na montagem")

        # Salva na pasta ready
        titulo_slug = roteiro.get("titulo","noxar").lower().replace(" ","_").replace("/","_")[:40]
        filename    = f"{titulo_slug}_{video_id[:8]}.mp4"
        final_path  = os.path.join(VIDEOS_DIR, video_id + ".mp4")
        shutil.copy(video_path, final_path)

        get_supabase().table("videos").update({
            "status": "done", "video_url": filename
        }).eq("id", video_id).execute()

        try:
            get_supabase().rpc("increment_video_count", {"user_uuid": user_id}).execute()
        except Exception:
            pass

        logger.info(f"[{video_id[:8]}] ✅ Concluído — {os.path.getsize(final_path)/1024/1024:.1f}MB")

    except Exception as e:
        logger.error(f"[{video_id[:8]}] Erro: {e}", exc_info=True)
        update_status(video_id, "error", str(e)[:200])
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@video_bp.route("/gerar", methods=["POST"])
@require_auth
def gerar():
    """Inicia pipeline em background, retorna video_id imediatamente."""
    data = request.get_json() or {}
    for c in ["tema","nicho","plataforma","duracao","persona","template"]:
        if c not in data:
            return jsonify({"error": f"campo obrigatório: {c}"}), 400

    tema       = str(data["tema"]).strip()
    nicho      = str(data["nicho"]).strip()
    plataforma = str(data["plataforma"]).strip()
    try:
        duracao = int(data["duracao"])
    except (TypeError, ValueError):
        return jsonify({"error": "duração deve ser numérica"}), 400
    persona    = str(data["persona"]).strip()
    template   = str(data["template"]).strip()

    if not tema or duracao < 15 or duracao > 600:
        return jsonify({"error": "parâmetros inválidos"}), 400

    if nicho not in NICHOS_VALIDOS:
        return jsonify({"error": f"nicho inválido. Use: {sorted(NICHOS_VALIDOS)}"}), 400
    if plataforma not in PLATAFORMAS_VALIDAS:
        return jsonify({"error": f"plataforma inválida. Use: {sorted(PLATAFORMAS_VALIDAS)}"}), 400
    if persona not in PERSONAS_VALIDAS:
        return jsonify({"error": f"persona inválida. Use: {sorted(PERSONAS_VALIDAS)}"}), 400
    if template not in TEMPLATES_VALIDOS:
        return jsonify({"error": f"template inválido. Use: {sorted(TEMPLATES_VALIDOS)}"}), 400

    video_id = str(uuid.uuid4())

    try:
        get_supabase().table("videos").insert({
            "id": video_id, "user_id": g.user_id,
            "title": tema[:100], "niche": nicho,
            "platform": plataforma, "persona": persona,
            "template": template, "duration_target": duracao,
            "status": "processing",
        }).execute()
    except Exception as e:
        logger.warning(f"Insert falhou: {e}")

    if PIPELINE_RUNNER == "local":
        threading.Thread(
            target=run_pipeline,
            args=(video_id, g.user_id, tema, nicho, plataforma, duracao, persona, template),
            daemon=True
        ).start()
        logger.info(f"[{video_id[:8]}] Thread local iniciada")
        return jsonify({"success": True, "video_id": video_id, "status": "processing", "runner": "local"}), 202

    try:
        dispatch_github_pipeline(video_id, g.user_id, tema, nicho, plataforma, duracao, persona, template)
        get_supabase().table("videos").update({"status": "queued"}).eq("id", video_id).execute()
        logger.info(f"[{video_id[:8]}] Job enviado para GitHub Actions")
        return jsonify({"success": True, "video_id": video_id, "status": "queued", "runner": "github"}), 202
    except Exception as e:
        logger.error(f"[{video_id[:8]}] Falha ao despachar job GitHub: {e}")
        update_status(video_id, "error", str(e))
        return jsonify({"error": "falha ao iniciar processamento on-demand"}), 502


@video_bp.route("/status/<video_id>", methods=["GET"])
@require_auth
def status(video_id):
    """Polling — frontend chama a cada 5s."""
    try:
        res = get_supabase().table("videos")\
            .select("id,title,status,error_msg,completed_at,video_url")\
            .eq("id", video_id).eq("user_id", g.user_id)\
            .single().execute()
        if not res.data:
            return jsonify({"error": "não encontrado"}), 404
        return jsonify({"success": True, "video": res.data}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@video_bp.route("/download/<video_id>", methods=["GET"])
@require_auth
def download(video_id):
    """Serve MP4 para download após status=done."""
    try:
        res = get_supabase().table("videos")\
            .select("title,video_url,status")\
            .eq("id", video_id).eq("user_id", g.user_id)\
            .single().execute()

        if not res.data:
            return jsonify({"error": "não encontrado"}), 404
        if res.data.get("status") != "done":
            return jsonify({"error": "vídeo ainda não está pronto"}), 425

        video_path = os.path.join(VIDEOS_DIR, video_id + ".mp4")
        if not os.path.exists(video_path):
            return jsonify({"error": "arquivo não encontrado no servidor"}), 404

        return send_file(
            video_path, mimetype="video/mp4",
            as_attachment=True,
            download_name=res.data.get("video_url", "noxar_video.mp4"),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@video_bp.route("/historico", methods=["GET"])
@require_auth
def historico():
    try:
        limit = min(max(int(request.args.get("limit", 20)), 1), 50)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "parâmetros de paginação inválidos"}), 400

    try:
        res = get_supabase().table("videos")\
            .select("id,title,niche,platform,persona,template,status,created_at,completed_at,duration_target")\
            .eq("user_id", g.user_id)\
            .order("created_at", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        return jsonify({"success": True, "videos": res.data}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@video_bp.route("/<video_id>", methods=["DELETE"])
@require_auth
def deletar(video_id):
    try:
        get_supabase().table("videos")\
            .delete().eq("id", video_id).eq("user_id", g.user_id).execute()
        path = os.path.join(VIDEOS_DIR, video_id + ".mp4")
        if os.path.exists(path): os.remove(path)
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
