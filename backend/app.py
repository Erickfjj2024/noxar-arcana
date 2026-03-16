"""
NOXAR ARCANA — Backend Principal
Flask + Supabase + Groq + FFmpeg
"""

import os
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# ─── LOGGING ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ─── APP ────────────────────────────────────────────────────────
def create_app():
    app = Flask(__name__)

    # CORS — permite requisições do frontend
    CORS(app, resources={
        r"/api/*": {
            "origins": [
                os.getenv("FRONTEND_URL", "http://localhost:3000"),
                "http://localhost:5500",
                "http://127.0.0.1:5500",
                "https://noxar-arcana.vercel.app",
            ],
            "methods": ["GET", "POST", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    })

    # ─── REGISTRA ROTAS ─────────────────────────────────────────
    from routes.auth   import auth_bp
    from routes.script import script_bp
    from routes.video  import video_bp
    from routes.keys   import keys_bp

    app.register_blueprint(auth_bp,   url_prefix="/api/auth")
    app.register_blueprint(script_bp, url_prefix="/api/script")
    app.register_blueprint(video_bp,  url_prefix="/api/video")
    app.register_blueprint(keys_bp,   url_prefix="/api/keys")

    # ─── HEALTH CHECK ───────────────────────────────────────────
    @app.route("/health")
    def health():
        return jsonify({
            "status": "alive",
            "service": "noxar-arcana-backend",
            "version": "1.0.0"
        }), 200

    # ─── ERRO GLOBAL ────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "rota não encontrada"}), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.error(f"Erro interno: {e}")
        return jsonify({"error": "erro interno do servidor"}), 500

    # ─── CRIA PASTA TEMP ────────────────────────────────────────
    temp_dir = os.getenv("TEMP_VIDEO_DIR", "/tmp/noxar_videos")
    os.makedirs(temp_dir, exist_ok=True)
    logger.info(f"Pasta de vídeos temporários: {temp_dir}")

    logger.info("🌑 Noxar Arcana backend iniciado")
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)

