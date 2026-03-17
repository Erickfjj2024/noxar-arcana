"""Runner de geração de vídeo para execução on-demand no GitHub Actions."""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routes.video import run_pipeline  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def parse_args():
    parser = argparse.ArgumentParser(description="Executa pipeline completo de vídeo")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--tema", required=True)
    parser.add_argument("--nicho", required=True)
    parser.add_argument("--plataforma", required=True)
    parser.add_argument("--duracao", required=True, type=int)
    parser.add_argument("--persona", required=True)
    parser.add_argument("--template", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    run_pipeline(
        video_id=args.video_id,
        user_id=args.user_id,
        tema=args.tema,
        nicho=args.nicho,
        plataforma=args.plataforma,
        duracao=args.duracao,
        persona=args.persona,
        template=args.template,
    )


if __name__ == "__main__":
    main()
