"""
NOXAR ARCANA — Script Route
Endpoint de geração de roteiro via Groq
"""

import os
import logging
from flask import Blueprint, request, jsonify, g
from routes.auth import require_auth
from services.groq_service import pipeline_roteiro, gerar_hooks

logger = logging.getLogger(__name__)

script_bp = Blueprint("script", __name__)


# ─── GERAR ROTEIRO ───────────────────────────────────────────────
@script_bp.route("/gerar", methods=["POST"])
@require_auth
def gerar():
    """
    Gera roteiro completo com storyboard e SEO.

    Body JSON:
    {
        "tema":       "string",
        "nicho":      "true_crime|terror|misterio|dark_history",
        "plataforma": "tiktok|youtube|kwai|reels",
        "duracao":    60,
        "persona":    "investigador|contador|informante",
        "template":   "sangue_frio|nevoa|abismo"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "body JSON inválido"}), 400

    # Valida campos obrigatórios
    campos = ["tema", "nicho", "plataforma", "duracao", "persona", "template"]
    for campo in campos:
        if campo not in data:
            return jsonify({"error": f"campo obrigatório: {campo}"}), 400

    tema      = str(data["tema"]).strip()
    nicho     = str(data["nicho"]).strip()
    plataforma = str(data["plataforma"]).strip()
    duracao   = int(data["duracao"])
    persona   = str(data["persona"]).strip()
    template  = str(data["template"]).strip()

    if not tema:
        return jsonify({"error": "tema não pode estar vazio"}), 400

    if duracao < 15 or duracao > 600:
        return jsonify({"error": "duração deve estar entre 15 e 600 segundos"}), 400

    # Valida enums
    nichos_validos     = {"true_crime", "terror", "misterio", "dark_history"}
    plataformas_validas = {"tiktok", "youtube", "kwai", "reels"}
    personas_validas   = {"investigador", "contador", "informante"}
    templates_validos  = {"sangue_frio", "nevoa", "abismo"}

    if nicho not in nichos_validos:
        return jsonify({"error": f"nicho inválido. Use: {nichos_validos}"}), 400
    if plataforma not in plataformas_validas:
        return jsonify({"error": f"plataforma inválida. Use: {plataformas_validas}"}), 400
    if persona not in personas_validas:
        return jsonify({"error": f"persona inválida. Use: {personas_validas}"}), 400
    if template not in templates_validos:
        return jsonify({"error": f"template inválido. Use: {templates_validos}"}), 400

    logger.info(f"Gerando roteiro — user={g.user_id[:8]} tema='{tema[:40]}'")

    # Executa pipeline
    resultado = pipeline_roteiro(
        tema=tema,
        nicho=nicho,
        plataforma=plataforma,
        duracao=duracao,
        persona=persona,
        template=template,
    )

    if not resultado:
        return jsonify({"error": "falha ao gerar roteiro — tente novamente"}), 500

    return jsonify({
        "success":  True,
        "roteiro":  resultado["roteiro"],
        "storyboard": resultado["storyboard"],
        "seo":      resultado["seo"],
    }), 200


# ─── GERAR HOOKS ─────────────────────────────────────────────────
@script_bp.route("/hooks", methods=["POST"])
@require_auth
def hooks():
    """
    Gera variações de gancho para um tema.

    Body JSON:
    {
        "tema":    "string",
        "nicho":   "string",
        "persona": "string"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "body JSON inválido"}), 400

    tema    = str(data.get("tema", "")).strip()
    nicho   = str(data.get("nicho", "misterio")).strip()
    persona = str(data.get("persona", "contador")).strip()

    if not tema:
        return jsonify({"error": "tema obrigatório"}), 400

    resultado = gerar_hooks(tema, nicho, persona)
    if not resultado:
        return jsonify({"error": "falha ao gerar hooks"}), 500

    return jsonify({"success": True, "hooks": resultado.get("ganchos", [])}), 200

