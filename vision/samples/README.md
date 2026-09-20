# samples/

Material real do bicicletário — esta é a única pasta de imagens versionada
(o `.gitignore` da raiz abre exceção para `vision/samples/**`).

O que colocar aqui:

- `frame.jpg` — um frame da câmera fixa, já na posição final. É a entrada de
  `scripts/annotate_slots.py --source samples/frame.jpg`, que gera `config/slots.json`.
- `demo.mp4` — gravação do cenário da demo (plano B se a webcam falhar no evento).
  Grave **com a webcam que vai ser usada**, não com celular.
- `pessoas/<nome>/*.jpg` — 3–4 fotos por pessoa da equipe, chegando e saindo do rack.
  É a entrada de `scripts/calibrate.py --dir samples/pessoas`, que mede genuínos ×
  impostores e sugere o `similarity_threshold`.
