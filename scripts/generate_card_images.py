"""Create WebP variants of tarot_images/*.jpg with the cwebp CLI."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT / "tarot_images"
SIZES = (("thumbs", 360, 68), ("medium", 700, 78))


def main():
    if not shutil.which("cwebp"):
        raise SystemExit("cwebp is required to generate card images")

    sources = sorted(
        path for path in IMAGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    )
    for folder, width, quality in SIZES:
        destination = IMAGE_DIR / folder
        destination.mkdir(exist_ok=True)
        for source in sources:
            output = destination / f"{source.stem}.webp"
            subprocess.run(
                ["cwebp", "-quiet", "-q", str(quality), "-m", "6",
                 "-resize", str(width), "0", str(source), "-o", str(output)],
                check=True,
            )
        print(f"{folder}: {len(sources)} images")


if __name__ == "__main__":
    main()
