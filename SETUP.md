# 🌑 NOXAR ARCANA — Guia de Setup Completo

## Pré-requisitos
- Conta GitHub
- Conta Supabase (supabase.com) — gratuita
- Conta Render (render.com) — gratuita
- Conta Vercel (vercel.com) — gratuita
- Conta UptimeRobot (uptimerobot.com) — gratuita
- Chave Groq (console.groq.com) — gratuita

---

## PASSO 1 — GitHub (5 min)

```bash
# Clone ou crie o repositório
git init
git add .
git commit -m "feat: initial noxar arcana setup"
git remote add origin https://github.com/SEU_USER/noxar-arcana.git
git push -u origin main
```

---

## PASSO 2 — Supabase (10 min)

1. Acesse supabase.com → New Project
2. Nome: `noxar-arcana` | Região: South America (São Paulo)
3. Guarde a senha do banco em local seguro
4. Vá em **SQL Editor** → cole o conteúdo de `supabase/schema.sql` → Run
5. Vá em **Settings > API** e copie:
   - `Project URL` → SUPABASE_URL
   - `anon public` → SUPABASE_ANON_KEY
   - `service_role` → SUPABASE_SERVICE_KEY (⚠️ nunca exponha no frontend)
6. Vá em **Authentication > Settings**:
   - Email confirmations: **OFF** (para facilitar testes)
   - Site URL: `https://noxar-arcana.vercel.app`

---

## PASSO 3 — Render (15 min)

1. Acesse render.com → New Web Service
2. Conecte seu repositório GitHub
3. Configure:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 300`
4. Em **Environment Variables**, adicione:
   ```
   GROQ_API_KEY          = sua chave groq
   SUPABASE_URL          = url do supabase
   SUPABASE_ANON_KEY     = chave anon
   SUPABASE_SERVICE_KEY  = chave service
   FLASK_SECRET_KEY      = uma string aleatória de 32 caracteres
   FLASK_ENV             = production
   FRONTEND_URL          = https://noxar-arcana.vercel.app
   TEMP_VIDEO_DIR        = /tmp/noxar_videos
   ```
5. **Deploy** — aguarde ~3 minutos
6. Copie a URL gerada: `https://noxar-arcana-backend.onrender.com`

---

## PASSO 4 — Vercel (5 min)

1. Acesse vercel.com → New Project
2. Importe o repositório GitHub
3. Em **Environment Variables**, adicione:
   ```
   VITE_SUPABASE_URL      = url do supabase
   VITE_SUPABASE_ANON_KEY = chave anon
   VITE_BACKEND_URL       = https://noxar-arcana-backend.onrender.com
   ```
4. **Deploy** — aguarde ~1 minuto
5. Acesse a URL gerada e teste o login

---

## PASSO 5 — UptimeRobot (5 min)

1. Acesse uptimerobot.com → Add New Monitor
2. Monitor Type: **HTTP(s)**
3. URL: `https://noxar-arcana-backend.onrender.com/health`
4. Monitoring Interval: **5 minutes**
5. Save — o backend nunca mais vai dormir

---

## PASSO 6 — Groq API Key (2 min)

1. Acesse console.groq.com
2. API Keys → Create API Key
3. Copie e adicione no Render como `GROQ_API_KEY`

---

## Arquitetura de Segurança

```
Frontend (Vercel)
│   ├── Supabase JS SDK — auth direto (seguro)
│   └── JWT token em memória (nunca localStorage)
│
Backend (Render) — PRIVADO
│   ├── Valida JWT do Supabase em toda requisição
│   ├── GROQ_API_KEY em variável de ambiente
│   └── Nunca expõe chaves ao frontend
│
Supabase
│   ├── RLS ativo — cada usuário vê só seus dados
│   └── Service key só no backend
```

---

## Variáveis de Ambiente — Resumo

| Variável | Onde fica | Exposta? |
|---|---|---|
| GROQ_API_KEY | Render | ❌ Nunca |
| SUPABASE_SERVICE_KEY | Render | ❌ Nunca |
| SUPABASE_URL | Render + Vercel | ✅ Pode (é pública) |
| SUPABASE_ANON_KEY | Render + Vercel | ✅ Pode (RLS protege) |
| VITE_BACKEND_URL | Vercel | ✅ Pode |

---

## Testando Localmente

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Preencha o .env
python app.py

# Frontend
# Abra frontend/index.html no browser
# ou use Live Server no VSCode
```

---

## URLs Finais

| Serviço | URL |
|---|---|
| App | https://noxar-arcana.vercel.app |
| Backend | https://noxar-arcana-backend.onrender.com |
| Supabase | https://app.supabase.com/project/SEU_ID |
| UptimeRobot | https://uptimerobot.com/dashboard |

