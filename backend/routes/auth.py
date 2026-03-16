"""
NOXAR ARCANA — Autenticação
Valida JWT do Supabase em toda requisição protegida
"""

import os
import logging
from functools import wraps
from flask import Blueprint, request, jsonify, g
from supabase import create_client, Client

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# ─── CLIENTE SUPABASE ────────────────────────────────────────────
def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY não configurados")
    return create_client(url, key)


# ─── DECORATOR DE PROTEÇÃO ───────────────────────────────────────
def require_auth(f):
    """
    Decorator que valida o JWT do Supabase.
    Uso: @require_auth na rota protegida.
    Injeta g.user_id e g.user_email no contexto da requisição.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "token não fornecido"}), 401

        token = auth_header.split(" ")[1]

        try:
            supabase = get_supabase()
            # Valida o token com o Supabase
            response = supabase.auth.get_user(token)

            if not response or not response.user:
                return jsonify({"error": "token inválido"}), 401

            # Injeta dados do usuário no contexto
            g.user_id    = response.user.id
            g.user_email = response.user.email
            g.token      = token

        except Exception as e:
            logger.warning(f"Falha na autenticação: {e}")
            return jsonify({"error": "token expirado ou inválido"}), 401

        return f(*args, **kwargs)
    return decorated


# ─── ROTAS ───────────────────────────────────────────────────────

@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    """Retorna dados do usuário autenticado."""
    try:
        supabase = get_supabase()
        profile  = supabase.table("profiles")\
            .select("*")\
            .eq("id", g.user_id)\
            .single()\
            .execute()

        return jsonify({
            "user_id":      g.user_id,
            "email":        g.user_email,
            "display_name": profile.data.get("display_name"),
            "videos_count": profile.data.get("videos_count", 0),
            "plan":         profile.data.get("plan", "free"),
        }), 200

    except Exception as e:
        logger.error(f"Erro ao buscar perfil: {e}")
        return jsonify({"error": "erro ao buscar perfil"}), 500


@auth_bp.route("/verify", methods=["POST"])
def verify():
    """
    Verifica se um token é válido.
    Usado pelo frontend para checar sessão ao abrir o app.
    """
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"valid": False}), 200

    token = auth_header.split(" ")[1]

    try:
        supabase = get_supabase()
        response = supabase.auth.get_user(token)

        if response and response.user:
            return jsonify({
                "valid":    True,
                "user_id":  response.user.id,
                "email":    response.user.email,
            }), 200

        return jsonify({"valid": False}), 200

    except Exception:
        return jsonify({"valid": False}), 200

