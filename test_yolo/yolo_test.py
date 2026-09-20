import shutil
from pathlib import Path

from ultralytics import YOLO

model = YOLO("yolo26n-seg.pt")

image_dir = Path(__file__).parent / "imagens"
output_dir = Path(__file__).parent / "resultados"
output_dir.mkdir(exist_ok=True)

for child in output_dir.iterdir():
    if child.is_dir():
        shutil.rmtree(child)
    else:
        child.unlink()

for image_path in sorted(image_dir.glob("*")):
    if not image_path.is_file():
        continue

    if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        continue

    results = model.predict(
        source=str(image_path),
        classes=[0, 1],
        save=False,
        device="cpu",
    )

    if results and len(results) > 0:
        output_file = output_dir / f"{image_path.stem}_detected.jpg"
        results[0].save(filename=str(output_file))

    print(f"Imagem processada: {image_path.name}")
