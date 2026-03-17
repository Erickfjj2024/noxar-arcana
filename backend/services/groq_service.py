"""
NOXAR ARCANA — Groq Service
Geração de roteiro + transcrição Whisper com timestamps por palavra
Modelo: llama-3.3-70b-versatile
"""

import os
import json
import time
import logging
import re
from groq import Groq

logger = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"


# ─── CLIENTE ────────────────────────────────────────────────────
def get_client() -> Groq:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY não configurada")
    return Groq(api_key=key)


# ─── UTILITÁRIOS ────────────────────────────────────────────────
def extract_json(text: str) -> dict | None:
    """Extrai JSON de resposta que pode ter texto ao redor."""
    text = text.strip()
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                return None
    return None


def fix_json(raw: str) -> dict | None:
    """Usa o modelo para corrigir JSON malformado."""
    client = get_client()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um validador de JSON. Receba o texto abaixo e retorne "
                        "APENAS o JSON corrigido e válido. Sem markdown, sem explicações, "
                        "sem texto fora do JSON. Se um campo obrigatório estiver faltando, "
                        "insira com valor padrão razoável."
                    )
                },
                {"role": "user", "content": raw},
            ],
            temperature=0.1,
            max_tokens=4000,
        )
        return extract_json(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Erro ao corrigir JSON: {e}")
        return None


def call_groq(
    system: str,
    user: str,
    temperature: float = 0.85,
    max_tokens: int = 4000,
    top_p: float = 0.95,
    max_retries: int = 2,
) -> dict | None:
    """
    Chama Groq com retry automático e validação de JSON.
    Reduz temperatura a cada tentativa para aumentar consistência.
    """
    client  = get_client()
    temps   = [temperature, 0.2]

    for attempt, temp in enumerate(temps[:max_retries]):
        try:
            logger.info(f"Groq call — tentativa {attempt + 1}, temp={temp:.2f}")
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                temperature=temp,
                max_tokens=max_tokens,
                top_p=top_p,
                timeout=90,
            )

            raw  = response.choices[0].message.content
            data = extract_json(raw)

            if data:
                return data

            logger.warning(f"JSON inválido na tentativa {attempt + 1}")

            if attempt == max_retries - 2:
                corrected = fix_json(raw)
                if corrected:
                    return corrected

        except Exception as e:
            logger.error(f"Erro Groq tentativa {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    return None


# ════════════════════════════════════════════════════════════════
# PROMPT 1 — ROTEIRO COMPLETO
# ════════════════════════════════════════════════════════════════
SYSTEM_ROTEIRO = """
Você é o melhor roteirista de conteúdo dark do Brasil, com mais de 10 anos criando vídeos virais para TikTok, Kwai, YouTube Shorts e Reels. Taxa de retenção acima de 75%.

PSICOLOGIA DO ESPECTADOR BRASILEIRO:
- Para de rolar o feed quando sente que vai descobrir um segredo proibido
- Referências a casos reais brasileiros geram 3x mais retenção
- A voz narrativa deve soar como um amigo contando algo proibido
- Frases curtas prendem mais que períodos longos
- Silêncio narrativo (reticências, pausas implícitas) cria tensão

FRAMEWORK DE RETENÇÃO "GANCHO BRASILEIRO":
1. ANZOL (0-3s): Frase que faz o dedo parar. Sem rodeios.
2. PROMESSA: Justifica assistir até o final
3. ESCALADA: Cada cena revela uma camada
4. VIRADA: Fato que muda tudo (~70% do vídeo)
5. IMPACTO FINAL: Última frase causa arrepio ou inquietação

REGRAS PT-BR:
✓ Use "você" (nunca "tu")
✓ Contrações: "tá", "tô", "pro", "pra", "num", "numa"
✓ Proximidade: "olha", "escuta", "presta atenção"
✓ Urgência: "mas espera", "só que", "e aí"
✓ Segredo: "o que poucos sabem", "isso nunca foi divulgado"
✗ NUNCA: "surpreendente", "incrível", "chocante", "prepare-se"
✗ NUNCA voz passiva excessiva
✗ NUNCA inicie cena com "Então", "Depois", "Em seguida"

PERSONAS:
- investigador: jornalístico, seco — "Os documentos mostram"
- contador: íntimo, dramático — "Deixa eu te contar"
- informante: urgente, conspiratório — "Isso não deveria existir"

EMOÇÕES (use exatamente): misterio | tensao | choque | revelacao | calma

ESTRUTURA:
- Cenas: 4-8 total
- Palavras por cena: 40-80
- Cena do meio: maior virada emocional
- Última cena: impacto + pergunta sem resposta (loop eterno)

GANCHO RUIM: "Você não vai acreditar no que aconteceu nessa cidade!"
GANCHO BOM: "Essa cidade existe no mapa, mas ninguém que entrou voltou pra contar."

RETORNE APENAS JSON VÁLIDO:
{
  "titulo": "string (máx 60 chars)",
  "gancho": "string (máx 15 palavras, sem clichê)",
  "promessa": "string (justifica assistir até o fim)",
  "persona": "investigador|contador|informante",
  "plataforma_alvo": "string",
  "duracao_estimada_segundos": number,
  "cenas": [
    {
      "numero": number,
      "emocao": "misterio|tensao|choque|revelacao|calma",
      "narracao": "string (40-80 palavras PT-BR coloquial culto)",
      "loop_aberto": "string (pergunta implantada, máx 10 palavras)",
      "micro_cliffhanger": "string (tensão final, máx 10 palavras)",
      "prompt_imagem": "string (inglês, dark cinematográfico, sem rostos, termina com: cinematic 8k sharp focus professional lighting photorealistic)",
      "prompt_negativo": "string",
      "preset_edicao": "sangue_frio|nevoa|abismo",
      "efeitos_sonoros": ["sons para a cena"],
      "palavras_impacto": ["2-3 palavras para legenda maior"],
      "duracao_segundos": number
    }
  ],
  "encerramento": "string (frase final, máx 20 palavras)",
  "loop_eterno": "string (pergunta sem resposta)",
  "tags_seo": {
    "tiktok": ["5 hashtags"],
    "youtube": ["8 tags"],
    "kwai": ["5 hashtags"],
    "reels": ["7 hashtags"]
  }
}
"""


def gerar_roteiro(
    tema: str,
    nicho: str,
    plataforma: str,
    duracao: int,
    persona: str,
    template: str,
) -> dict | None:
    user = f"""
Raciocine antes de gerar:
1. Qual o ângulo mais perturbador desse tema?
2. Que pergunta vai ficar na cabeça do espectador?
3. Como dividir a revelação para cada cena parecer incompleta?
4. Que fato vai fazer o brasileiro parar tudo e assistir?

Dados:
- Nicho: {nicho}
- Tema: {tema}
- Plataforma: {plataforma}
- Duração alvo: {duracao} segundos
- Persona: {persona}
- Template: {template}

Gere apenas o JSON.
"""
    return call_groq(
        system=SYSTEM_ROTEIRO,
        user=user,
        temperature=0.85,
        max_tokens=4000,
        top_p=0.95,
    )


# ════════════════════════════════════════════════════════════════
# PROMPT 2 — STORYBOARD (SEGMENTOS VISUAIS)
# ════════════════════════════════════════════════════════════════
SYSTEM_STORYBOARD = """
Você é um storyboard artist especializado em conteúdo dark cinematográfico.

SEGMENTAÇÃO: 1 imagem a cada 3-4 segundos de narração.

PROGRESSÃO POR EMOÇÃO:
- misterio: plano aberto → médio → detalhe
- tensao: médio → sobre o ombro → close-up extremo
- choque: close-up extremo → revelação ampla
- revelacao: ângulo baixo → médio revelação → detalhe
- calma: amplo atmosférico → médio → respiração

PALETA POR EMOÇÃO:
- misterio: "desaturated teal and deep navy, low saturation, fog diffusion"
- tensao: "high contrast black and crimson, harsh shadows, heavy vignette"
- choque: "stark monochrome with single blood red accent, blown highlights"
- revelacao: "cold steel blue, dim practical lighting, cinematic teal grade"
- calma: "muted grey-green, soft gradients, minimal contrast"

ILUMINAÇÃO (escolha uma por segmento):
- "single candle illumination casting long shadows"
- "flickering fluorescent light, cold and clinical"
- "moonlight through broken window, dust particles visible"
- "distant streetlight, heavy rain, reflective wet surfaces"
- "emergency red lighting, alarm glow"
- "phone screen glow in complete darkness"
- "deep shadow with single shaft of light from above"

SUJEITOS: APENAS silhuetas humanas, nunca rostos claros.

TERMINE SEMPRE COM:
"cinematic photography, Kodak film grain, shallow depth of field, anamorphic lens, 8k resolution, no text, no watermark"

PROMPT NEGATIVO:
"cartoon, anime, illustration, bright colors, happy, sunlight, faces clearly visible, text overlay, watermark, low quality, blurry"

RETORNE APENAS JSON VÁLIDO:
{
  "cena_numero": number,
  "total_segmentos": number,
  "segmentos": [
    {
      "segmento_id": "string (ex: cena_1_seg_1)",
      "timestamp_inicio": number,
      "timestamp_fim": number,
      "trecho_narracao": "string",
      "tipo_plano": "establishing|medium|close-up|extreme_close-up|dutch-angle",
      "emocao": "misterio|tensao|choque|revelacao|calma",
      "intensidade": number,
      "prompt_imagem": "string (completo em inglês)",
      "prompt_negativo": "string",
      "seed": number,
      "duracao_exibicao_segundos": number,
      "transicao_saida": "fade|cut|flash_branco|flash_vermelho|dissolve"
    }
  ]
}
"""


def gerar_storyboard(
    cena_numero: int,
    narracao: str,
    emocao: str,
    nicho: str,
    template: str,
    duracao_segundos: float,
    timestamp_inicio: float,
    seed_base: int = 1000,
) -> dict | None:
    user = f"""
Raciocine antes:
1. Quantos momentos visuais distintos há nesta narração?
2. Como a composição deve evoluir para amplificar a tensão?
3. Quais elementos ancoram continuidade entre segmentos?

Dados:
- Número da cena: {cena_numero}
- Narração: "{narracao}"
- Emoção: {emocao}
- Nicho: {nicho}
- Template: {template}
- Duração: {duracao_segundos}s
- Timestamp início: {timestamp_inicio}s
- Seed base: {seed_base} (use seed_base + índice_segmento)

Gere apenas o JSON.
"""
    return call_groq(
        system=SYSTEM_STORYBOARD,
        user=user,
        temperature=0.75,
        max_tokens=2000,
        top_p=0.90,
    )


# ════════════════════════════════════════════════════════════════
# PROMPT 3 — HOOKS
# ════════════════════════════════════════════════════════════════
SYSTEM_HOOKS = """
Você é especialista em ganchos para conteúdo dark brasileiro.

FÓRMULAS:
1. SEGREDO: "Isso foi removido da internet três vezes."
2. AMEAÇA: "Se você mora perto de [X], precisa saber disso."
3. ENCOBRIMENTO: "O governo tentou apagar isso."
4. ANOMALIA: "Esse lugar existe, mas não deveria."
5. CONSEQUÊNCIA: "Quem descobriu isso pagou caro."
6. PROXIMIDADE: "Isso aconteceu a 200km daqui."
7. INVERSÃO: "A vítima não era quem você pensa."
8. TEMPO: "Faz 30 anos e ninguém sabe a verdade."

REGRAS:
✗ Nunca ponto de exclamação
✗ Nunca "incrível", "surpreendente", "chocante"
✗ Nunca comece com "Você sabia"
✓ Máximo 15 palavras
✓ Especificidade cria credibilidade

RETORNE APENAS JSON VÁLIDO:
{
  "ganchos": [
    {
      "formula": "string",
      "texto": "string",
      "score_curiosidade": number,
      "por_que_funciona": "string",
      "recomendado": boolean
    }
  ]
}
"""


def gerar_hooks(tema: str, nicho: str, persona: str) -> dict | None:
    user = f"Tema: {tema}\nNicho: {nicho}\nPersona: {persona}\nGere 5 ganchos. Marque o melhor com recomendado: true."
    return call_groq(
        system=SYSTEM_HOOKS,
        user=user,
        temperature=0.90,
        max_tokens=600,
        top_p=0.95,
    )


# ════════════════════════════════════════════════════════════════
# PROMPT 4 — SEO
# ════════════════════════════════════════════════════════════════
SYSTEM_SEO = """
Você é especialista em SEO para conteúdo dark PT-BR.

FÓRMULAS DE TÍTULO:
1. "O [caso] que [autoridade] tentou apagar para sempre"
2. "Por que ninguém fala sobre [tema] no Brasil?"
3. "[N] fatos sobre [tema] que vão te fazer dormir com a luz acesa"
4. "A verdade por trás de [tema] é pior do que você imagina"
5. "Isso aconteceu no Brasil e foi completamente silenciado"

REGRAS:
✓ PT-BR coloquial culto
✓ Máximo 60 caracteres
✓ Hashtags em PT-BR
✗ Nunca ALL CAPS

RETORNE APENAS JSON VÁLIDO:
{
  "titulos": [
    {
      "plataforma": "string",
      "titulo": "string",
      "formula_usada": "string",
      "score_ctr": number
    }
  ],
  "hashtags": {
    "tiktok": ["5 hashtags"],
    "youtube": ["8 tags"],
    "kwai": ["5 hashtags"],
    "reels": ["7 hashtags"]
  },
  "descricao": "string (2-3 frases SEO)"
}
"""


def gerar_seo(tema: str, nicho: str, titulo_roteiro: str) -> dict | None:
    user = f"Tema: {tema}\nNicho: {nicho}\nTítulo: {titulo_roteiro}"
    return call_groq(
        system=SYSTEM_SEO,
        user=user,
        temperature=0.60,
        max_tokens=800,
        top_p=0.90,
    )


# ════════════════════════════════════════════════════════════════
# WHISPER — TRANSCRIÇÃO COM TIMESTAMPS POR PALAVRA
# ════════════════════════════════════════════════════════════════
def transcrever_audio(audio_path: str) -> dict | None:
    """
    Transcreve áudio com timestamps por palavra via Groq Whisper.
    Usado para sincronização da legenda karaoke.
    """
    client = get_client()
    try:
        logger.info(f"Transcrevendo: {audio_path}")
        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                language="pt",
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )

        words = []
        if hasattr(response, "words") and response.words:
            for w in response.words:
                words.append({
                    "word":  w.word.strip(),
                    "start": round(w.start, 3),
                    "end":   round(w.end,   3),
                })

        logger.info(f"Transcrição: {len(words)} palavras")
        return {"text": response.text, "words": words}

    except Exception as e:
        logger.error(f"Erro Whisper: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ════════════════════════════════════════════════════════════════
def pipeline_roteiro(
    tema: str,
    nicho: str,
    plataforma: str,
    duracao: int,
    persona: str,
    template: str,
) -> dict | None:
    """
    Pipeline completo:
    1. Roteiro com estrutura de retenção
    2. Storyboard (segmentos visuais por cena)
    3. SEO (títulos e hashtags)
    """
    logger.info(f"Pipeline roteiro: {tema[:50]}")

    # 1. Roteiro
    roteiro = gerar_roteiro(tema, nicho, plataforma, duracao, persona, template)
    if not roteiro:
        logger.error("Falha ao gerar roteiro")
        return None

    logger.info(f"Roteiro: {len(roteiro.get('cenas', []))} cenas")

    # 2. Storyboard — gerado diretamente do roteiro sem chamadas extras ao Groq
    storyboard_completo = []
    timestamp_atual = 0.0
    NEGATIVE = "cartoon, anime, illustration, bright colors, happy, sunlight, faces clearly visible, text overlay, watermark, low quality, blurry"
    transicao_map = {"sangue_frio": "cut", "nevoa": "fade", "abismo": "dissolve"}

    for i, cena in enumerate(roteiro.get("cenas", [])):
        duracao_cena = float(cena.get("duracao_segundos", 10))
        n_segs = max(1, int(duracao_cena / 4))
        segmentos = []
        for s in range(n_segs):
            t_inicio = timestamp_atual + s * (duracao_cena / n_segs)
            t_fim    = timestamp_atual + (s + 1) * (duracao_cena / n_segs)
            segmentos.append({
                "segmento_id":              f"cena_{i+1}_seg_{s+1}",
                "timestamp_inicio":         round(t_inicio, 2),
                "timestamp_fim":            round(t_fim, 2),
                "trecho_narracao":          cena.get("narracao", "")[:80],
                "tipo_plano":               ["establishing","medium","close-up","dutch-angle"][s % 4],
                "emocao":                   cena.get("emocao", "misterio"),
                "intensidade":              min(10, 4 + i),
                "prompt_imagem":            cena.get("prompt_imagem", "dark cinematic scene, mysterious atmosphere, no faces, cinematic 8k"),
                "prompt_negativo":          cena.get("prompt_negativo", NEGATIVE),
                "seed":                     (i + 1) * 1000 + s,
                "duracao_exibicao_segundos": round(duracao_cena / n_segs, 2),
                "transicao_saida":          transicao_map.get(template, "fade"),
            })
        storyboard_completo.append({
            "cena_numero":     cena.get("numero", i + 1),
            "total_segmentos": n_segs,
            "segmentos":       segmentos,
        })
        timestamp_atual += duracao_cena

    logger.info(f"Storyboard: {len(storyboard_completo)} cenas (direto do roteiro)")

    # 3. SEO
    seo = gerar_seo(tema, nicho, roteiro.get("titulo", tema))
    logger.info("SEO gerado")

    return {
        "roteiro":    roteiro,
        "storyboard": storyboard_completo,
        "seo":        seo,
    }

