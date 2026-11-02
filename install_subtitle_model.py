"""Prepare one fixed open-source model; separate from offline inference."""
import os
from pathlib import Path

MODEL = "Systran/faster-whisper-small"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"


def main():
    from huggingface_hub import snapshot_download
    destination = Path(os.environ["SUBTITLE_MODEL_DIR"]).resolve()
    snapshot_download(repo_id=MODEL, revision=REVISION, local_dir=destination,
                      allow_patterns=["config.json", "model.bin", "tokenizer.json",
                                      "vocabulary.*", "preprocessor_config.json"])
    if not all((destination / f).is_file() for f in ("config.json", "model.bin", "tokenizer.json")):
        raise RuntimeError("speech_model_incomplete")
    print("Pinned local multilingual speech model ready; no media uploaded.")


if __name__ == "__main__":
    main()
