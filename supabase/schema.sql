-- =============================================
-- NOXAR ARCANA — Supabase Schema
-- Execute este arquivo no SQL Editor do Supabase
-- =============================================

-- Habilita extensão de UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================
-- TABELA: profiles
-- Extensão do auth.users do Supabase
-- =============================================
CREATE TABLE IF NOT EXISTS public.profiles (
  id            UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  email         TEXT NOT NULL,
  display_name  TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW(),
  videos_count  INTEGER DEFAULT 0,
  plan          TEXT DEFAULT 'free' CHECK (plan IN ('free', 'pro'))
);

-- Trigger: cria profile automaticamente ao cadastrar
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email, display_name)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1))
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- =============================================
-- TABELA: videos
-- Histórico de vídeos criados por usuário
-- =============================================
CREATE TABLE IF NOT EXISTS public.videos (
  id            UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id       UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  title         TEXT NOT NULL,
  niche         TEXT NOT NULL CHECK (niche IN ('true_crime', 'terror', 'misterio', 'dark_history')),
  platform      TEXT NOT NULL CHECK (platform IN ('tiktok', 'youtube', 'kwai', 'reels')),
  persona       TEXT NOT NULL CHECK (persona IN ('investigador', 'contador', 'informante')),
  template      TEXT NOT NULL CHECK (template IN ('sangue_frio', 'nevoa', 'abismo')),
  duration_target INTEGER NOT NULL DEFAULT 60,
  script        JSONB,
  status        TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'done', 'error')),
  error_msg     TEXT,
  video_url     TEXT,
  thumbnail_url TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  completed_at  TIMESTAMPTZ
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_videos_user_id ON public.videos(user_id);
CREATE INDEX IF NOT EXISTS idx_videos_status  ON public.videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_created ON public.videos(created_at DESC);

-- =============================================
-- TABELA: easter_keys
-- Rastreia chaves do easter egg por usuário
-- =============================================
CREATE TABLE IF NOT EXISTS public.easter_keys (
  id         UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id    UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL UNIQUE,
  chave1     BOOLEAN DEFAULT FALSE,
  chave2     BOOLEAN DEFAULT FALSE,
  chave3     BOOLEAN DEFAULT FALSE,
  chave4     BOOLEAN DEFAULT FALSE,  -- A quarta chave — o mistério
  chave1_at  TIMESTAMPTZ,
  chave2_at  TIMESTAMPTZ,
  chave3_at  TIMESTAMPTZ,
  chave4_at  TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger: cria registro de easter_keys ao cadastrar
CREATE OR REPLACE FUNCTION public.handle_new_user_keys()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.easter_keys (user_id)
  VALUES (NEW.id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created_keys ON auth.users;
CREATE TRIGGER on_auth_user_created_keys
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_keys();

-- =============================================
-- TABELA: anonymous_records
-- Registros anônimos do terminal (easter egg)
-- =============================================
CREATE TABLE IF NOT EXISTS public.anonymous_records (
  id         UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  content    TEXT NOT NULL CHECK (char_length(content) <= 280),
  city       TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- ROW LEVEL SECURITY (RLS)
-- Cada usuário só acessa seus próprios dados
-- =============================================

-- profiles
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Usuário vê só seu profile"
  ON public.profiles FOR SELECT
  USING (auth.uid() = id);
CREATE POLICY "Usuário edita só seu profile"
  ON public.profiles FOR UPDATE
  USING (auth.uid() = id);

-- videos
ALTER TABLE public.videos ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Usuário vê só seus vídeos"
  ON public.videos FOR SELECT
  USING (auth.uid() = user_id);
CREATE POLICY "Usuário cria seus vídeos"
  ON public.videos FOR INSERT
  WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Usuário deleta seus vídeos"
  ON public.videos FOR DELETE
  USING (auth.uid() = user_id);
-- Backend (service_role) pode atualizar qualquer vídeo
CREATE POLICY "Service pode atualizar vídeos"
  ON public.videos FOR UPDATE
  USING (TRUE);

-- easter_keys
ALTER TABLE public.easter_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Usuário vê só suas chaves"
  ON public.easter_keys FOR SELECT
  USING (auth.uid() = user_id);
CREATE POLICY "Usuário atualiza só suas chaves"
  ON public.easter_keys FOR UPDATE
  USING (auth.uid() = user_id);

-- anonymous_records — qualquer um lê, qualquer um escreve (é anônimo)
ALTER TABLE public.anonymous_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Todos podem ler registros"
  ON public.anonymous_records FOR SELECT
  USING (TRUE);
CREATE POLICY "Todos podem criar registros"
  ON public.anonymous_records FOR INSERT
  WITH CHECK (char_length(content) <= 280);

-- =============================================
-- FUNÇÃO: incrementar contador de vídeos
-- =============================================
CREATE OR REPLACE FUNCTION public.increment_video_count(user_uuid UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE public.profiles
  SET videos_count = videos_count + 1,
      updated_at = NOW()
  WHERE id = user_uuid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
