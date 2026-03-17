"""
NOXAR ARCANA — Script Route
Endpoint de geração de roteiro via Groq
"""

import logging
from flask import Blueprint, request, jsonify, g
from routes.auth import require_auth
from services.groq_service import pipeline_roteiro, gerar_hooks

logger = logging.getLogger(__name__)

script_bp = Blueprint("script", __name__)

NICHOS_VALIDOS = {"true_crime", "terror", "misterio", "dark_history"}
PLATAFORMAS_VALIDAS = {"tiktok", "youtube", "kwai", "reels"}
PERSONAS_VALIDAS = {"investigador", "contador", "informante"}
TEMPLATES_VALIDOS = {"sangue_frio", "nevoa", "abismo"}


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
    try:
        duracao = int(data["duracao"])
    except (TypeError, ValueError):
        return jsonify({"error": "duração deve ser numérica"}), 400

    persona   = str(data["persona"]).strip()
    template  = str(data["template"]).strip()

    if not tema:
        return jsonify({"error": "tema não pode estar vazio"}), 400

    if duracao < 15 or duracao > 600:
        return jsonify({"error": "duração deve estar entre 15 e 600 segundos"}), 400

    # Valida enums
    if nicho not in NICHOS_VALIDOS:
        return jsonify({"error": f"nicho inválido. Use: {sorted(NICHOS_VALIDOS)}"}), 400
    if plataforma not in PLATAFORMAS_VALIDAS:
        return jsonify({"error": f"plataforma inválida. Use: {sorted(PLATAFORMAS_VALIDAS)}"}), 400
    if persona not in PERSONAS_VALIDAS:
        return jsonify({"error": f"persona inválida. Use: {sorted(PERSONAS_VALIDAS)}"}), 400
    if template not in TEMPLATES_VALIDOS:
        return jsonify({"error": f"template inválido. Use: {sorted(TEMPLATES_VALIDOS)}"}), 400

    logger.info(f"Gerando roteiro — user={g.user_id[:8]} tema='{tema[:40]}'")

    # Executa pipeline
    try:
        resultado = pipeline_roteiro(
            tema=tema,
            nicho=nicho,
            plataforma=plataforma,
            duracao=duracao,
            persona=persona,
            template=template,
        )
    except Exception as e:
        logger.error(f"Falha no pipeline de roteiro: {e}", exc_info=True)
        return jsonify({"error": "falha no provedor de IA"}), 502

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

    if nicho not in NICHOS_VALIDOS:
        return jsonify({"error": f"nicho inválido. Use: {sorted(NICHOS_VALIDOS)}"}), 400
    if persona not in PERSONAS_VALIDAS:
        return jsonify({"error": f"persona inválida. Use: {sorted(PERSONAS_VALIDAS)}"}), 400

    resultado = gerar_hooks(tema, nicho, persona)
    if not resultado:
        return jsonify({"error": "falha ao gerar hooks"}), 500

    return jsonify({"success": True, "hooks": resultado.get("ganchos", [])}), 200

