"""
NOXAR ARCANA — Keys Route
Sistema de easter egg: chaves do A.R. + registros anônimos + recompensas
"""

import os
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from routes.auth import require_auth
from supabase import create_client

logger = logging.getLogger(__name__)

keys_bp = Blueprint("keys", __name__)


def get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


# ─── STATUS ──────────────────────────────────────────────────────
@keys_bp.route("/status", methods=["GET"])
@require_auth
def status():
    """Retorna status completo das chaves e recompensas."""
    try:
        supabase = get_supabase()
        response = supabase.table("easter_keys")\
            .select("*").eq("user_id", g.user_id).single().execute()

        if not response.data:
            supabase.table("easter_keys").insert({"user_id": g.user_id}).execute()
            return jsonify({
                "success": True,
                "chaves": {"chave1": False, "chave2": False, "chave3": False, "chave4": False},
                "total_encontradas": 0,
                "todas_encontradas": False,
                "tema_dourado": False,
                "chave4_disponivel": False,
            }), 200

        d = response.data
        chaves = {k: d.get(k, False) for k in ["chave1","chave2","chave3","chave4"]}
        total  = sum(1 for v in chaves.values() if v)
        tres   = chaves["chave1"] and chaves["chave2"] and chaves["chave3"]

        return jsonify({
            "success":           True,
            "chaves":            chaves,
            "total_encontradas": total,
            "todas_encontradas": total >= 3,
            "tema_dourado":      d.get("tema_dourado", False),
            "chave4_disponivel": tres and not chaves["chave4"],
            "timestamps": {k: d.get(f"{k}_at") for k in ["chave1","chave2","chave3","chave4"]},
        }), 200

    except Exception as e:
        logger.error(f"Erro status chaves: {e}")
        return jsonify({"error": "erro ao buscar status"}), 500


# ─── ENCONTRAR CHAVE ─────────────────────────────────────────────
@keys_bp.route("/encontrar", methods=["POST"])
@require_auth
def encontrar():
    """
    Valida e registra chave encontrada.

    Body: { "chave": "chave1-4", "prova": "string" }

    Provas:
    - chave1: "40.7128"
    - chave2: "AR-2847-FINAL"
    - chave3: "ainda respira"
    - chave4: "2847"  (só após as 3 principais)
    """
    data  = request.get_json() or {}
    chave = str(data.get("chave", "")).strip().lower()
    prova = str(data.get("prova", "")).strip().lower()

    if chave not in {"chave1","chave2","chave3","chave4"}:
        return jsonify({"error": "chave inválida"}), 400

    provas = {
        "chave1": ["40.7128", "40.7128°n", "40.7128n"],
        "chave2": ["ar-2847-final", "ar2847final"],
        "chave3": ["ainda respira", "aindarespira"],
        "chave4": ["2847", "..-----..----...--..."],
    }

    prova_norm = prova.replace(" ", "").lower()
    if not any(prova == p or prova_norm == p.replace(" ","").lower() for p in provas[chave]):
        logger.warning(f"Prova inválida {g.user_id[:8]} {chave}")
        return jsonify({"error": "prova incorreta"}), 400

    try:
        supabase = get_supabase()
        d        = (supabase.table("easter_keys").select("*")
                    .eq("user_id", g.user_id).single().execute()).data or {}

        if chave == "chave4" and not (d.get("chave1") and d.get("chave2") and d.get("chave3")):
            return jsonify({"error": "encontre as 3 chaves principais primeiro"}), 403

        if d.get(chave):
            return jsonify({"success": True, "nova": False, "mensagem": f"{chave.upper()} já catalogada."}), 200

        now    = datetime.now(timezone.utc).isoformat()
        update = {chave: True, f"{chave}_at": now, "updated_at": now}

        # Verifica se ativa tema dourado (3 chaves principais)
        atuais = {k: d.get(k, False) for k in ["chave1","chave2","chave3"]}
        atuais[chave] = True
        tema_dourado_ativado = False

        if all(atuais.values()) and not d.get("tema_dourado"):
            update["tema_dourado"]    = True
            update["tema_dourado_at"] = now
            tema_dourado_ativado      = True
            logger.info(f"🌕 Tema dourado ativado {g.user_id[:8]}")

        supabase.table("easter_keys").update(update).eq("user_id", g.user_id).execute()

        todas = {**d, **update}
        total = sum(1 for k in ["chave1","chave2","chave3","chave4"] if todas.get(k))

        msgs = {
            "chave1": "As coordenadas foram catalogadas. O arquivo se aproxima.",
            "chave2": "Código verificado. Um fragmento do arquivo foi liberado.",
            "chave3": "A frase foi reconhecida. A.R. estava esperando por isso.",
            "chave4": "Você ouviu o que não deveria. O arquivo completo é seu.",
        }

        logger.info(f"Chave encontrada {g.user_id[:8]} {chave} ({total}/4)")

        return jsonify({
            "success":              True,
            "nova":                 True,
            "chave":                chave,
            "total_encontradas":    total,
            "todas_encontradas":    total >= 3,
            "tema_dourado_ativado": tema_dourado_ativado,
            "arquivo_liberado":     chave == "chave4",
            "mensagem":             msgs[chave],
        }), 200

    except Exception as e:
        logger.error(f"Erro registrar chave: {e}")
        return jsonify({"error": "erro ao registrar chave"}), 500


# ─── MENSAGEM PERSONALIZADA DO A.R. ─────────────────────────────
@keys_bp.route("/mensagem-ar", methods=["GET"])
@require_auth
def mensagem_ar():
    """
    Gera mensagem única do A.R. endereçada ao usuário pelo nome.
    Requer chave 4. Gerada uma vez e salva para sempre.
    """
    try:
        supabase = get_supabase()
        d = (supabase.table("easter_keys").select("*")
             .eq("user_id", g.user_id).single().execute()).data or {}

        if not d.get("chave4"):
            return jsonify({"error": "chave 4 necessária"}), 403

        # Retorna cached se já gerada
        if d.get("mensagem_ar"):
            return jsonify({"success": True, "mensagem": d["mensagem_ar"], "cached": True}), 200

        # Busca nome do perfil
        profile = (supabase.table("profiles").select("display_name")
                   .eq("id", g.user_id).single().execute()).data or {}
        nome = profile.get("display_name", "Você")

        # Formata datas
        def fmt(iso):
            try:
                return datetime.fromisoformat(iso.replace("Z","+00:00")).strftime("%d/%m/%Y")
            except Exception:
                return "data desconhecida"

        datas = [d.get(f"chave{i}_at") for i in range(1,5)]
        datas = [fmt(x) for x in datas if x]

        data_primeira = datas[0]  if datas     else "?"
        data_ultima   = datas[-1] if len(datas) > 1 else data_primeira

        # Gera via Groq
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        prompt = f"""
Você é A.R., pesquisador que desapareceu em 2021 após documentar 2.847 casos removidos da internet.
Escreva uma mensagem curta, pessoal e perturbadora endereçada a {nome}.

Contexto:
- {nome} encontrou a primeira pista em {data_primeira}
- A última pista foi encontrada em {data_ultima}
- Foram necessárias 4 etapas para chegar aqui
- {nome} ouviu o morse no áudio — algo que exige atenção e dedicação

Regras:
- Máximo 8 linhas
- Soe como alguém que estava esperando especificamente por essa pessoa
- Mencione as datas de forma perturbadora
- Termine com "— A.R."
- Português do Brasil, íntimo, quase sussurrado
- SEM aspas, markdown ou formatação especial

Escreva apenas a mensagem.
"""

        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=300,
        )
        mensagem = resp.choices[0].message.content.strip()

        # Salva para não regenerar
        supabase.table("easter_keys").update({"mensagem_ar": mensagem})\
            .eq("user_id", g.user_id).execute()

        logger.info(f"Mensagem A.R. gerada {g.user_id[:8]}")
        return jsonify({"success": True, "mensagem": mensagem, "cached": False}), 200

    except Exception as e:
        logger.error(f"Erro mensagem A.R.: {e}")
        return jsonify({"error": "erro ao gerar mensagem"}), 500


# ─── REGISTROS ANÔNIMOS ──────────────────────────────────────────
@keys_bp.route("/registros", methods=["GET"])
def listar_registros():
    """Registros anônimos do terminal. Público."""
    try:
        supabase = get_supabase()
        registros = (supabase.table("anonymous_records")
                     .select("id,content,city,created_at")
                     .order("created_at", desc=True)
                     .limit(50).execute()).data or []

        import random
        random.shuffle(registros)
        return jsonify({"success": True, "registros": registros[:10]}), 200

    except Exception as e:
        logger.error(f"Erro listar registros: {e}")
        return jsonify({"error": "erro ao buscar registros"}), 500


@keys_bp.route("/registros", methods=["POST"])
@require_auth
def criar_registro():
    """Salva registro anônimo. Requer 3 chaves."""
    data    = request.get_json() or {}
    content = str(data.get("content", "")).strip()
    city    = str(data.get("city",    "")).strip()[:50]

    if not content or len(content) > 280:
        return jsonify({"error": "conteúdo inválido (máx 280 chars)"}), 400

    try:
        supabase = get_supabase()
        d = (supabase.table("easter_keys").select("chave1,chave2,chave3")
             .eq("user_id", g.user_id).single().execute()).data or {}

        if not (d.get("chave1") and d.get("chave2") and d.get("chave3")):
            return jsonify({"error": "encontre as 3 chaves para deixar um registro"}), 403

        supabase.table("anonymous_records").insert({
            "content": content, "city": city or None
        }).execute()

        return jsonify({"success": True, "mensagem": "Seu registro foi adicionado ao arquivo."}), 201

    except Exception as e:
        logger.error(f"Erro criar registro: {e}")
        return jsonify({"error": "erro ao salvar registro"}), 500

