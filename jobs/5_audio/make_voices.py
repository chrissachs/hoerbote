"""Reference clips for qwen3-tts's voices: every text below read by every
Gemini voice (only those not rendered yet), then voices/voices.toml with the
text picked by --use."""

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from gemini_tts import DEFAULT_STYLE, MODEL_ID, GeminiEngine
from qwen3_tts import VOICES_DIR, VOICES_FILE
from speech_engine import Request, configure_logging

load_dotenv(Path(__file__).parent / ".env")

log = logging.getLogger(__name__)

CANDIDATES_DIR = VOICES_DIR / "candidates"
# Our own texts: takes from an issue read newspaper content, which stays
# out of the repo. No names or numbers, where the model stumbles.
TEXTS = {
    "a": "Der Gemeinderat hat am Dienstagabend über den neuen Haushalt beraten. Nach einer langen und teils "
    "hitzigen Debatte einigte man sich schließlich auf einen Kompromiss, der vor allem Schulen und "
    "Kindergärten zugutekommt.",
    "b": "Guten Morgen und willkommen zur heutigen Ausgabe. Wir blättern gemeinsam durch die Zeitung: von der "
    "großen Politik über das Geschehen in der Region bis zu den kleinen Geschichten, die man beim schnellen "
    "Lesen leicht übersieht.",
    "c": "Am Ufer des Flusses stehen ein paar alte Bäume, deren Blätter im Herbstwind leise rascheln. Ein "
    "Spaziergänger bleibt kurz stehen, schaut den Enten zu und zieht dann weiter, Richtung Brücke und "
    "Marktplatz.",
}
# Pool order: the engine alternates through them by segment, F, M.
VOICES = {"female": "de-de-storyteller-1", "male": "de-de-storyteller-8"}


def candidate(voice: str, text: str) -> Path:
    return CANDIDATES_DIR / f"{voice}-{text}.ogg"


def render_missing() -> None:
    missing = {
        f"{voice}-{text}": Request([TEXTS[text]], gemini_voice)
        for voice, gemini_voice in VOICES.items()
        for text in TEXTS
        if not candidate(voice, text).is_file()
    }
    if not missing:
        return
    log.info("Rendering %d candidates", len(missing))
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    for key, result in GeminiEngine(CANDIDATES_DIR, DEFAULT_STYLE).render(missing):
        if isinstance(result, Exception):
            failed.append(f"{key}: {result!r}")
        else:
            (CANDIDATES_DIR / f"{key}.ogg").write_bytes(result)
    if failed:
        raise SystemExit("failed:\n" + "\n".join(failed))


def write_voices_file(text: str) -> None:
    entries = [
        "# The Qwen3-TTS engine's voices (qwen3_tts.py), in pool order. Written by\n"
        "# make_voices.py; the clips are its candidates/.\n"
    ]
    for voice, gemini_voice in VOICES.items():
        entries.append(
            f"\n[[voice]]\n"
            f'name = "{voice}"\n'
            f'clip = "{candidate(voice, text).relative_to(VOICES_DIR)}"\n'
            f'transcript = "{TEXTS[text]}"\n'
            f'source = "{MODEL_ID}, {gemini_voice}, style: {DEFAULT_STYLE}"\n'
        )
    VOICES_FILE.write_text("".join(entries), encoding="utf-8")
    log.info("%s: text %r for %s", VOICES_FILE, text, ", ".join(VOICES))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Reference clips for the qwen3-tts voices.")
    parser.add_argument("--use", choices=sorted(TEXTS), default="a", help="which text the voices use")
    args = parser.parse_args()
    render_missing()
    write_voices_file(args.use)


if __name__ == "__main__":
    main()
