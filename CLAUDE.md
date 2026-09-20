# CLAUDE.md — BikeGuard (Hackathon de Visão Computacional)

> MVP de hackathon. **Prioridade absoluta: funcionar na demo.** Código simples, poucos arquivos,
> nada de abstração prematura. Se uma decisão não estiver aqui, escolha a opção mais simples
> e registre em "Decisões tomadas" no fim deste arquivo.

## 1. O que o sistema faz

Câmera USB aponta para o bicicletário da universidade. As vagas já têm bounding boxes conhecidas.

1. Detecta/segmenta **bicicletas** e **pessoas** em cada frame.
2. Quando uma vaga passa de **VAZIA → OCUPADA** (confirmado por debounce), pega o melhor rosto
   da pessoa que estava sobrepondo a vaga/bike nos últimos segundos e gera um **embedding** → abre uma "sessão".
3. Quando a vaga passa de **OCUPADA → VAZIA**, pega o rosto de quem retirou e compara com o embedding do depósito.
4. Similaridade baixa (ou nenhum rosto) → **alerta para a portaria** no dashboard, com as duas fotos lado a lado.

É **verificação 1:1** (quem depositou vs. quem retirou), não identificação. Não precisa de banco vetorial.

## 2. Arquitetura

A ideia central: **só a inferência muda de lugar**. A captura e a máquina de estados das vagas
rodam sempre no dispositivo (Pi/Jetson). O mesmo servidor de inferência (mesmo código, mesmo
contrato HTTP) roda em três lugares, e o agente escolhe a URL conforme o modo configurado no site.

```
                    ┌──────────────────────── Dispositivo (RPi 5 / Jetson) ─────────────────────┐
 Webcam USB ──────► │ agent (Python)                                                           │
                    │  captura → POST /infer ──┬──► inference @ localhost:8001   (modo EDGE)   │
                    │                          │                                                │
                    │  occupancy + debounce    ├──► inference @ PC da univ:8001 (modo FOG)     │
                    │  ring buffer de rostos   │                                                │
                    │  → eventos               └──► inference @ nuvem (HTTPS)   (modo CLOUD)   │
                    └───────────────┬───────────────────────────────────────────────────────────┘
                                    │ POST /api/events, /api/metrics, /api/cameras/:id/frame
                                    │ GET  /api/config  (polling a cada 5 s)
                                    ▼
                    ┌─────────────────────────────┐        ┌──────────────────────────┐
                    │ api (TypeScript, Fastify)   │ ◄────► │ web (React + Vite + TS)  │
                    │ SQLite + imagens em disco   │  REST  │ dashboard / portaria /   │
                    │ comparação de embeddings    │        │ eventos / config / métricas
                    └─────────────────────────────┘        └──────────────────────────┘
```

- **Fallback**: se o modo for fog/cloud e a chamada falhar ou passar de 2 s, o agente usa edge
  naquele frame e marca `fallback=true` na métrica. (Ótimo ponto de apresentação: resiliência.)
- A **api + web** rodam num lugar fixo (laptop da equipe ou PC fog na demo). O "modo de processamento"
  se refere apenas à inferência.

## 3. Estrutura do repositório

```
/
├── CLAUDE.md
├── vision/                    # Python 3.11+
│   ├── requirements.txt
│   ├── models/                # pesos (gitignored); script de download em scripts/
│   ├── common/
│   │   ├── schemas.py         # dataclasses/pydantic do contrato /infer
│   │   └── geometry.py        # IoU, cobertura de vaga, conversão bbox normalizada
│   ├── inference/
│   │   ├── server.py          # FastAPI: POST /infer, GET /health
│   │   ├── detector.py        # YOLO26n-seg (ultralytics), classes person=0, bicycle=1
│   │   └── faces.py           # crop da pessoa → upscale → SCRFD + MobileFaceNet (insightface buffalo_s)
│   ├── agent/
│   │   ├── main.py            # loop: captura → infer → occupancy → state machine → eventos
│   │   ├── occupancy.py       # bike mask/bbox ∩ vaga → ocupada?
│   │   ├── slots_state.py     # máquina de estados com debounce por vaga
│   │   ├── face_buffer.py     # ring buffer de rostos recentes por vaga
│   │   ├── api_client.py      # config, eventos, métricas, frame anotado
│   │   └── draw.py            # overlay das vagas/detecções no frame
│   ├── config/slots.json      # polígonos das vagas + interaction_zone, normalizados [0..1]
│   ├── samples/               # fotos/vídeos reais do bicicletário (teste e calibração)
│   ├── scripts/               # export_ncnn.sh, download_models.sh, calibrate.py, annotate_slots.py
│   └── Dockerfile.inference   # imagem usada no modo CLOUD (e opcional no FOG)
├── api/                       # Node 20+, TypeScript
│   ├── src/
│   │   ├── index.ts           # Fastify + rotas
│   │   ├── db.ts              # better-sqlite3, schema criado no boot
│   │   ├── routes/            # events.ts, sessions.ts, alerts.ts, config.ts, metrics.ts, cameras.ts
│   │   └── similarity.ts      # cosine similarity
│   └── data/                  # bikeguard.db + faces/*.jpg (gitignored)
└── web/                       # Vite + React + TypeScript (+ Tailwind)
    └── src/pages/             # Dashboard, Portaria, Eventos, Configuracoes, Metricas
```

## 4. Modelos e parâmetros

| Tarefa | Modelo | Por quê |
|---|---|---|
| Pessoas + bikes | **YOLO26n-seg** (Ultralytics, COCO: `person`=0, `bicycle`=1) | Nano roda no Pi 5 na CPU; máscara separa bikes encostadas melhor que bbox |
| Detecção de rosto | **SCRFD-10G** (pacote InsightFace `buffalo_l`) | padrão; com `buffalo_s` (SCRFD-500M, 2.5 MB) a margem cai pela metade |
| Embedding facial | **ResNet50 ArcFace** (`w600k_r50.onnx`, 512-d, mesmo pacote) | margem +0.288 contra +0.117 do MobileFaceNet nos vídeos reais |

Uso: `pip install insightface onnxruntime` e `FaceAnalysis(name='buffalo_l', allowed_modules=['detection','recognition'])`,
ou `INSIGHTFACE_PACK=buffalo_s` onde não houver GPU (aí o limiar desce de 0.38 para 0.31).
Pesos: os `.zip` de `https://github.com/deepinsight/insightface/releases` (apagar os .onnx de
landmark 3D / genderage, não são usados). Licença dos pesos é não comercial — ok para hackathon.
Fallback se o insightface não instalar no Pi: YuNet + SFace do OpenCV Zoo (mesmo pipeline, limiar diferente).

- Rodar sem fine-tuning. COCO já cobre as duas classes.
- **`detector.py` deve ser plugável** (`DETECTOR=yolo26|rfdetr` na config), porque o modelo muda por modo:

| Medido em 32 fotos reais (thr 0.4, frame inteiro) | YOLO26n-seg | RF-DETR-Seg Nano |
|---|---|---|
| Fotos com **zero** bikes detectadas | **14 / 32** | **0 / 32** |
| Média de bikes por foto (havia ~2) | 0.69 | 1.97 |
| Confiança média nas bikes | 0.58 | 0.78 |
| Confiança média nas pessoas | ~0.80 | ~0.89 |
| Latência (CPU do Colab, 640 px) | **232 ms** | **1152 ms** |
| Licença | AGPL-3.0 | **Apache 2.0** |
| mAP máscara COCO | ~30 (classe nano) | 40.3 |

**Decisão: RF-DETR-Seg Nano é o modelo padrão no fog e no cloud; YOLO26n-seg é o padrão no edge**, onde o
RF-DETR (5× mais lento, ~2–3 s/frame estimados no Pi 5) não fecha a conta. No Jetson com TensorRT, RF-DETR em todos os modos.

**Atenção — o edge é o modo frágil.** O YOLO26n perdeu as bicicletas em 14 das 32 fotos. Isso quebraria a
máquina de estados das vagas. Antes de fechar o modo edge, refazer o teste do notebook com as três mudanças
abaixo e só então ajustar os parâmetros:
1. `conf=0.25` para bicicleta (o teste usou 0.4);
2. rodar sobre o **recorte da ROI**, não o frame inteiro — as bikes ficam bem maiores em pixels;
3. se ainda falhar, `imgsz=960` ou `yolo26s-seg`, aceitando ~1 FPS no Pi.

E, independentemente disso, a ocupação precisa de **histerese** no modo edge (ver §6): com falhas frequentes de
detecção, um simples "tem bike neste frame" gera oscilação.

Pesos RF-DETR: `RFDETRSegNano()` do pacote `rfdetr` (baixa de `storage.googleapis.com`).
- **Raspberry Pi 5**: exportar para NCNN (`yolo export model=yolo26n-seg.pt format=ncnn imgsz=480`).
  Usar `imgsz` 320–480; alvo de 2–4 FPS é suficiente (bike não se move rápido).
  Se seg ficar lento demais, trocar para `yolo26n.pt` (detecção) e usar bbox na ocupação — o resto não muda.
- **Jetson**: exportar para TensorRT (`format=engine half=True`).
- **Fog/Cloud**: mesmo `.pt` ou ONNX, pode usar `yolo26s-seg` se houver GPU/CPU sobrando.
- **Nunca rodar o detector de rosto no frame inteiro.** O SCRFD redimensiona a entrada para 640, e os rostos
  nessa cena têm só 20–45 px no frame original. Pipeline obrigatório: bbox da pessoa (YOLO) → recortar os 45%
  superiores da bbox **do frame em resolução original** → ampliar o recorte até 640 no maior lado (INTER_CUBIC)
  → SCRFD + embedding. No teste isso subiu a similaridade mínima entre fotos da mesma pessoa de 0.05 para 0.21.
- Rosto só vale se: score SCRFD ≥ 0.5 e lado do rosto ≥ 20 px **no frame original**. (Os scores nas fotos reais
  ficaram entre 0.5 e 0.85; um corte em 0.8 descartaria quase tudo.)
- **Limiar**: cosine ≥ **0.38** = mesma pessoa, com `buffalo_l` + template (0.31 com `buffalo_s`).
  Calibrado nos vídeos de `samples/`, mas com só 2 atores — recalibrar com mais gente (§10, passo 2b).
  Configurável no site.

## 4.1 Cena e câmera (validado com 18 fotos reais do local)

Teste feito com YOLOX-s (substituto do YOLO26 no teste) + SCRFD/MobileFaceNet nas fotos da equipe:

| Ângulo | Pessoa | Bike | Rosto (px, frame 1600 px) | Similaridade mesma pessoa |
|---|---|---|---|---|
| **Frontal ao rack, pessoa atrás empurrando a bike** | 0.89–0.91 | 0.55–0.74 | **40–45** | mín 0.43, média 0.63 |
| Oblíquo / lateral, pessoa na calçada | 0.83–0.87 | 0.51–0.85 | 20–25, perfil | mín 0.21 |

**Ângulo escolhido: frontal.** Quem coloca ou tira a bike fica atrás do rack, empurrando a bike em direção à câmera,
então olha para a câmera nos dois eventos. A câmera fica no gramado, de frente para o rack.

Consequências para o código:
- **Vagas viram colunas.** No ângulo frontal cada vaga é uma faixa vertical entre duas barras do rack.
  `slots.json` guarda um polígono por vaga cobrindo a altura das rodas (base do rack até o topo do rack).
  Uma bike ocupa a vaga se a parte inferior da bbox/máscara dela cai dentro do polígono.
- **ROI (região de interesse).** Nas fotos, ~20% de cima é céu/copa e ~40% de baixo é grama. O agente recorta a
  faixa `roi` (normalizada, configurável) **antes** de redimensionar para a inferência. Mais pixels em rostos e bikes
  sem custo extra.
- **Filtrar transeuntes.** Tem uma calçada logo atrás do rack. Só contam pessoas cuja base da bbox (pés) está
  entre a linha do rack e a borda da calçada (`interaction_zone`, polígono em `slots.json`) **e** cuja faixa horizontal
  sobrepõe a coluna da vaga.
- **Cabeça baixa.** Ao encaixar a bike a pessoa olha para baixo (rosto piora). O melhor rosto costuma aparecer na
  **chegada**, antes do encaixe — por isso o buffer de rostos precisa de janela generosa (15 s) e começa antes da transição.
- **Bikes fora das vagas** (rack vizinho, borda do quadro) aparecem com confiança baixa: sempre descartar
  detecções cujo polígono não cai dentro de nenhuma vaga.
- **Pessoas ao fundo**: o RF-DETR detectou gente na calçada em 10 das 32 fotos (conf 0.4–0.55). É detecção
  correta, não erro — quem filtra é a `interaction_zone`.

Montagem: câmera a 1.2–1.6 m de altura, 3–4 m do rack, levemente inclinada para baixo, enquadrando só a seção de
vagas monitorada (6–8 vagas). Evitar o sol de frente. Gravar o vídeo de teste **com a webcam que vai ser usada**,
não com celular: a webcam terá menos nitidez e os números acima vão piorar.

## 5. Contrato do servidor de inferência (idêntico nos 3 modos)

`POST /infer` — multipart, campo `image` (JPEG). Query opcional: `faces=true|false` (default true).

```json
{
  "model": "yolo26n-seg",
  "device": "rpi5-cpu",
  "inference_ms": 142.3,
  "width": 640, "height": 480,
  "bikes":   [{ "bbox": [x1,y1,x2,y2], "conf": 0.81, "polygon": [[x,y], ...] }],
  "persons": [{ "bbox": [x1,y1,x2,y2], "conf": 0.90,
                "face": { "bbox": [x,y,w,h], "score": 0.93,
                          "embedding": [128 floats], "crop_jpg_b64": "..." } | null }]
}
```

- O agente envia o **recorte da ROI em resolução nativa** (não reduzido). O servidor reduz para o YOLO internamente
  e recorta os rostos da imagem original. Isso custa ~100–200 KB por frame; a 3 FPS dá ~0.5 MB/s, aceitável no wifi
  e um bom número para a comparação edge/fog/cloud.
- Coordenadas em **pixels do frame enviado**. `polygon` pode ser omitido se usar só detecção.
- Servidor é **stateless** (sem tracking). Todo estado fica no agente.
- `GET /health` → `{ "ok": true, "model": "...", "device": "..." }`.

## 6. Lógica do agente

**Ocupação da vaga** (`occupancy.py`): para cada vaga, calcular a fração da área da vaga coberta
pela união das máscaras de bike (rasterizar em grade reduzida, ex. 160×120, com `cv2.fillPoly`).
Ocupada se cobertura ≥ `OCCUPANCY_THRESHOLD` (default 0.25). Sem máscara → usar interseção de bbox.

**Debounce com histerese** (`slots_state.py`): o estado bruto por frame entra numa janela deslizante dos
últimos `debounce_seconds` (default 3 s) de frames. A vaga só passa para `OCCUPIED` se **≥70%** dos frames da
janela viram bike, e só volta para `EMPTY` se **≤20%** viram. Entre os dois limites o estado é mantido.
Isso absorve as falhas de detecção do YOLO no edge, que são frequentes (ver §4).

**Ring buffer de rostos** (`face_buffer.py`): a cada frame, para cada pessoa com rosto válido **dentro da
`interaction_zone`**, para cada vaga cuja coluna sobrepõe horizontalmente a bbox da pessoa → guardar
`(ts, slot_id, embedding, crop, quality)` onde `quality = score * min(lado_rosto, 112)`.
Manter janela de `face_window_seconds` (default 15 s). Ao confirmar transição, pegar os **`top_k` (default 5) de
maior `quality`** para aquela vaga, contando a janela desde **antes** do início da transição bruta.

**Eventos** enviados para a api:
- `deposit`: `{ camera_id, slot_id, ts, embeddings: number[][] (até top_k), face_jpg_b64 | null (melhor rosto), frame_jpg_b64 }`
- `withdrawal`: mesmo formato.

**Comparação** (na api): cada lado vira um **template** — a média dos até `top_k` embeddings
normalizados, renormalizada — e a similaridade é um único cosseno entre os dois templates.
Assim um frame ruim (cabeça baixa, borrado) é diluído na média em vez de decidir sozinho.
Era o **máximo** entre todos os pares; medido nos vídeos reais, o máximo separava mal, porque
pescava o melhor de até 25 comparações ruidosas e isso levantava o impostor junto com o genuíno.

**Outros envios**: 1 frame anotado por segundo em `POST /api/cameras/:id/frame` (JPEG) e
métricas a cada frame em lote a cada 5 s (`mode, inference_ms, rtt_ms, payload_bytes, fallback`).

**Fonte de vídeo**: `--source 0` (webcam) ou `--source demo.mp4` (loop). O modo vídeo é o
plano B da demo e o ambiente padrão de desenvolvimento.

## 7. API (TypeScript)

Stack: **Fastify + better-sqlite3 + tsx** (dev). Sem ORM. Schema criado no boot com `CREATE TABLE IF NOT EXISTS`.
Imagens salvas em `api/data/faces/<uuid>.jpg`, servidas estaticamente em `/files/`.

```sql
sessions(id TEXT PK, camera_id, slot_id, deposit_ts, deposit_embeddings TEXT /*JSON number[][]*/, deposit_face,
         deposit_frame, withdrawal_ts, withdrawal_face, withdrawal_frame, similarity REAL,
         status TEXT /* parked | ok | alert */)
alerts(id TEXT PK, session_id, ts, reason /* low_similarity | no_face_deposit | no_face_withdrawal */,
       similarity REAL, acknowledged INTEGER DEFAULT 0)
events(id INTEGER PK, ts, camera_id, slot_id, type, payload TEXT)
metrics(id INTEGER PK, ts, camera_id, mode, inference_ms, rtt_ms, payload_bytes, fallback INTEGER)
config(id INTEGER PK CHECK(id=1), json TEXT)
```

Regras:
- `deposit` → cria sessão `parked` para a vaga (se já houver uma aberta, fecha a antiga como órfã).
- `withdrawal` → busca sessão `parked` da vaga, calcula o cosine entre os templates (`setSimilarity`); `similarity < threshold` ou rosto ausente → `alert`, senão `ok`.
  **Depois de comparar, apagar os embeddings** (`deposit_embeddings = NULL`) — LGPD.
- Retenção: fotos de sessões `ok` apagadas após `RETENTION_HOURS` (default 24). Implementar como limpeza no boot + setInterval.

Rotas:
```
GET  /api/config                 PUT /api/config
POST /api/events                 GET /api/events?limit=
GET  /api/sessions?status=       GET /api/slots          (estado atual por vaga, derivado das sessões)
GET  /api/alerts?open=1          POST /api/alerts/:id/ack
POST /api/metrics                GET /api/metrics?since=
POST /api/cameras/:id/frame      GET /api/cameras/:id/frame.jpg
```

Config default:
```json
{
  "mode": "edge",
  "inference_urls": { "edge": "http://localhost:8001", "fog": "http://192.168.0.10:8001", "cloud": "https://<app>.run.app" },
  "target_fps": 3, "jpeg_quality": 75, "infer_width": 640,
  "roi": [0.0, 0.15, 1.0, 0.80],
  "occupancy_threshold": 0.25, "debounce_seconds": 3, "face_window_seconds": 15,
  "bike_min_conf": { "yolo26": 0.25, "rfdetr": 0.5 },
  "occupied_ratio": 0.7, "empty_ratio": 0.2, "face_min_score": 0.5, "face_min_px": 20, "top_k": 5,
  "similarity_threshold": 0.38, "retention_hours": 24, "timeout_ms": 2000
}
```

## 8. Web (TypeScript)

Vite + React + TS + Tailwind. React Router com 5 páginas. **Polling** com `fetch` a cada 1–2 s (sem WebSocket).

1. **Dashboard** — frame ao vivo (`<img>` recarregando `/api/cameras/cam1/frame.jpg?t=`), grade de vagas
   (verde vazia / azul ocupada / vermelho alerta), modo atual e FPS.
2. **Portaria** — alertas abertos em cards: foto de quem deixou vs. quem retirou, similaridade, vaga, horário, botão "Verificado".
3. **Eventos (backlog)** — tabela de sessões/eventos com filtro por status.
4. **Configurações** — seletor Edge/Fog/Cloud (grande e visível, é o momento "uau" da demo), URLs, limiares, FPS.
5. **Métricas** — gráfico (recharts) de latência total e de inferência por modo ao longo do tempo + tabela de médias
   (latência, FPS, bytes enviados, % fallback).

## 9. Comandos

```bash
# visão
cd vision && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # ultralytics, insightface, onnxruntime, opencv-python, fastapi, uvicorn, python-multipart, requests, numpy
bash scripts/download_models.sh            # yolo26n-seg.pt + buffalo_s.zip (só det_500m.onnx e w600k_mbf.onnx)
uvicorn inference.server:app --host 0.0.0.0 --port 8001
python -m agent.main --source demo.mp4 --api http://localhost:3000 --camera cam1

# api
cd api && npm i && npm run dev             # porta 3000

# web
cd web && npm i && npm run dev             # porta 5173, proxy /api e /files → 3000

# cloud (qualquer provedor que aceite container: Cloud Run, Azure Container Apps, AWS App Runner)
docker build -f vision/Dockerfile.inference -t bikeguard-inference vision/
```

## 10. Plano de implementação (ordem de prioridade)

1. `inference/server.py` com YOLO + rostos, testado com uma imagem via curl.
2. `agent` com fonte de vídeo, ROI, ocupação, debounce, buffer de rostos, eventos (pode logar no console antes da api existir).
   2a. `scripts/annotate_slots.py`: abre um frame da câmera fixa, clica nos polígonos das vagas e da zona de interação, salva `slots.json`.
   2b. `scripts/calibrate.py`: grava 3–4 pessoas da equipe depositando/retirando; calcula cosseno de pares da mesma pessoa
       (genuínos) e de pessoas diferentes (impostores); plota os dois histogramas e sugere o limiar. **O gráfico vai para a apresentação.**
3. `api` com events/sessions/alerts + comparação.
4. `web`: Dashboard + Portaria.
5. Config + troca de modo + fallback.
6. Métricas + página de métricas.
7. Deploy cloud do container de inferência.
8. Polimento: Eventos, retenção LGPD, export NCNN/TensorRT.

Cada passo deve resultar em algo rodável. Não começar o passo N+1 sem o N funcionando ponta a ponta.

## 11. Roteiro da demo

1. Mostrar o dashboard com as vagas.
2. Pessoa A deixa a bike → vaga fica azul, sessão aparece em Eventos.
3. Pessoa A retira → sessão `ok`, sem alerta.
4. Pessoa A deixa, **pessoa B** retira → alerta na Portaria com as duas fotos.
5. Trocar Edge → Fog → Cloud ao vivo e mostrar o gráfico de latência mudando; derrubar o fog e mostrar o fallback.
6. Fechar com LGPD e trade-offs de cada modo.

Gravar um `demo.mp4` do cenário antes do evento como plano B (wifi de evento costuma falhar).

## 12. Privacidade (LGPD) — mencionar na apresentação

Biometria é dado pessoal sensível (LGPD art. 5º II / art. 11). Medidas do MVP: embeddings existem só
enquanto a bike está estacionada; fotos de sessões normais são apagadas após a retenção; o alerta é
**pedido de verificação**, não acusação (humano no loop); no modo edge nenhuma imagem de rosto sai do
dispositivo exceto em eventos. Em produção: sinalização no local, base legal e política de retenção da universidade.

## 13. Convenções

- Python: funções simples, type hints, sem classes desnecessárias. Logs com `print`/`logging` são ok.
- TypeScript: `strict: true`, sem camadas de service/repository — rota acessa o db direto.
- Coordenadas das vagas em `slots.json` são **normalizadas [0..1]**; converter para pixels no agente.
- Tudo configurável vem do `GET /api/config`; o agente cai para defaults se a api estiver fora.
- Não adicionar autenticação, filas, Docker Compose ou testes automatizados salvo pedido explícito.

## 14. Riscos conhecidos

- **Rostos pequenos** (20–45 px): mitigado com ROI + crop/upscale + top-K. Se a webcam for fraca, aproximar a câmera
  ou reduzir o número de vagas enquadradas.
- **Limiar sem calibração**: o teste só tinha uma pessoa (sem impostores). Até rodar o `calibrate.py`, o limiar 0.30 é provisório.
- **Cabeça baixa ao encaixar a bike**: mitigado pelo buffer de 15 s começando antes da transição.
- Oclusão entre bikes vizinhas → por isso segmentação + limiar de cobertura.
- Mais de uma pessoa perto da vaga → escolhe maior `quality`; se ambíguo, alerta com reason específico (futuro).
- Iluminação noturna → fora do escopo do MVP.

## Decisões tomadas

<!-- Claude Code: registre aqui decisões que não estavam especificadas acima. -->

- **2026-09-20 — Implementação inicial (vision + api + web, passos 1–6 do §10).**
  Pesos COCO pré-treinados, sem fine-tuning. Quando os pesos com fine-tuning chegarem,
  basta apontar `YOLO_WEIGHTS` (ou `model_path`) para o novo `.pt`: o resto do pipeline não muda.
- **Ambos os detectores implementados e validados.** `DETECTOR=yolo26|rfdetr` no servidor de
  inferência, e a config tem um detector por modo (`detector.edge=yolo26`, `fog`/`cloud`=`rfdetr`).
  O `class_id` do `rfdetr` 1.10.1 é **1-indexado** em relação a `model.class_names` (person=1, bicycle=2);
  o pacote não tem mais `rfdetr.util.coco_classes`.
- **Rostos: insightface 2.0 (`buffalo_s`) instalou sem problema no Python 3.12** — não foi preciso o
  fallback. Ele continua em `faces.py` como `FACE_BACKEND=opencv` (YuNet + SFace), com embedding de 128-d
  em vez de 512-d, então o limiar precisa ser recalibrado se alguém trocar.
- **PYTHONPATH do ROS.** Se o shell tiver `/opt/ros/.../site-packages` no `PYTHONPATH`, ele entra **antes**
  da venv e sombreia numpy/opencv. Use `vision/run_inference.sh` (que faz `env -u PYTHONPATH`) ou rode
  `env -u PYTHONPATH .venv/bin/python -m agent.main ...`.
- **Status `orphan`.** Além de `parked|ok|alert`, uma sessão vira `orphan` quando chega um novo depósito
  numa vaga que já tinha sessão aberta (a retirada nunca foi vista). Sem isso a sessão antiga ficaria
  `parked` para sempre e travaria a vaga.
- **`slot_ids` na config** só alimenta a grade do Dashboard. A verdade sobre as vagas continua em
  `vision/config/slots.json` (hoje um exemplo de 6 colunas — refazer com `scripts/annotate_slots.py`
  quando as fotos reais estiverem anotadas).
- **Métrica no fallback**: o campo `mode` guarda onde a inferência **realmente** rodou (`edge`), e
  `fallback=1` marca que o modo escolhido falhou. A página de Métricas mostra a % de fallback.
- **Pesos fora do repositório**: `yolo26n-seg.pt` em `vision/models/`, RF-DETR em `~/.roboflow/models/`,
  buffalo_s em `~/.insightface/models/`. `vision/samples/` é a única pasta de imagens versionada.

- **2026-09-20 — Primeiro teste com os vídeos reais (`samples/Insercao_P1`, `Remocao_P1`, `Remocao_P2`).**
  Três tomadas de 14 s a 1024×576, ~30 fps. A `Remoção_P2` foi filmada com a bike numa vaga
  diferente das outras duas, então os pares *mesma vaga* possíveis são Inserção_P1 + Remoção_P1.
  - **`config/slots.json` agora é a geometria real** do rack: 6 vãos entre os 7 montantes
    (x = 133, 283, 432, 577, 723, 866, 1008 px; y = 330 a 545). Inserção/Remoção_P1 caem na **S3**,
    Remoção_P2 na **S2**. Cobertura medida com a bike estacionada: 0.30–0.41 na vaga certa, 0.00
    nas outras — o limiar de 0.25 tem folga, mas não muita.
  - **A ROI default cortava a cena.** Neste enquadramento a cabeça de quem empurra a bike encosta
    no topo do frame e as rodas vão até ~95% da altura: `roi` virou `[0,0,1,1]`. Se a câmera final
    ficar mais longe, dá para voltar a cortar.
  - **YOLO26n-seg com pesos COCO não serve para o edge nesta cena.** Vê a bike em 55% dos frames
    (rfdetr: 96%), a vaga nunca chega aos 70% da janela e **nenhum evento é emitido**. Com
    `imgsz=960` + `bike_conf=0.15` sobe para 75% e os eventos saem, mas nos instantes errados
    (o depósito foi reconhecido ~12 s atrasado, segundos antes da retirada real). `detector.edge`
    passou a `rfdetr` até os pesos com fine-tuning chegarem — é exatamente esse o problema que o
    fine-tuning precisa resolver.
  - **Limiar facial recalibrado.** `scripts/calibrate.py` nos três vídeos: 97 pares genuínos
    (média 0.252) × 56 impostores (média 0.076, **máx 0.251**), sugestão par a par **0.18**.
    A decisão real usa o máximo dos pares, que mediu **0.32–0.34** (mesma pessoa) contra **0.15**
    (pessoas diferentes). `similarity_threshold` foi de 0.30 para **0.23**. A margem é estreita e
    há só 2 pessoas na amostra — recalibrar com mais gente. Histograma em `samples/calibracao.png`.
    *(Superado na entrada seguinte: o máximo dos pares foi trocado pelo template e o limiar por 0.38.)*
  - **Rostos**: 73 rostos válidos nos 129 frames amostrados, score médio 0.65, lado médio **42 px**
    (mín 22, máx 55) — coerente com o previsto no §4.1 para o ângulo frontal.
  - **Agente em arquivo de vídeo rodava em câmera lenta.** Consumia um frame por iteração, então um
    clipe de 14 s levava 2m21s a 3 FPS e o debounce (que conta segundos de relógio) não correspondia
    ao que foi gravado. Agora descarta `src_fps/target_fps - 1` frames por iteração. Novo
    `--no-loop` para parar no fim do arquivo, e o loop **não** reinicia mais a máquina de estados
    (o rack reaparece vazio e a retirada sai sozinha, fechando a sessão a cada ciclo).
  - **`GET /api/cameras/:id/frame.jpg` só lia da memória**, apesar do comentário dizendo que o disco
    existia para sobreviver a um restart. Depois de reiniciar a api o Dashboard ficava com a imagem
    quebrada. Agora cai para `data/frames/<id>.jpg`.
  - **A coluna FPS da página de Métricas mostrava `1000/rtt`** (19.7) — o teto que a inferência
    permitiria, não o ritmo real de captura. Passou a ser `frames / (último_ts − primeiro_ts)`,
    com `first_ts`/`last_ts` novos no resumo de `/api/metrics`.
  - **As cinco páginas foram verificadas no navegador** (headless Chrome), não só pelo build.

- **2026-09-20 — `a_verdade` / `a_mentira`: o limiar facial quase não separava.**
  Com o sistema antigo (buffalo_s + **máximo** dos pares) a sessão honesta deu 0.354 e a
  fraudulenta 0.301 — margem de 0.053, ou seja, nenhum limiar seguro. Diagnóstico e correção,
  medidos nos dois vídeos (3 comparações genuínas × 3 impostoras, 2 atores):

  | agregador | buffalo_s | buffalo_l |
  |---|---|---|
  | máximo dos pares (antigo) | +0.086 | +0.214 |
  | mediana dos pares | +0.159 | +0.172 |
  | **template (média dos embeddings)** | +0.117 | **+0.288** |

  (o número é a margem: menor genuíno − maior impostor.)

  - **O máximo era o pior agregador.** Ele pega o melhor de até 25 pares, então basta um par
    com sorte para o impostor subir; a média cancela o ruído de frame em vez de amplificá-lo —
    e é ela que de fato protege contra o "frame ruim" que o §6 queria evitar. `similarity.ts`
    passou a usar `setSimilarity` (cosseno entre os templates), com `maxPairwise` mantido só
    para comparação offline.
  - **O pacote de modelos pesa mais que o agregador.** `INSIGHTFACE_PACK` (novo) escolhe o
    pacote. **Decisão: `buffalo_l` (SCRFD-10G + ResNet50, 300 MB) é o default.** Custo:
    **101 ms/frame** contra 45 ms na GPU — tranquilo a 3 FPS, e a 3 FPS o orçamento é 333 ms.
    `buffalo_s` (SCRFD-500M + MobileFaceNet, 16 MB) fica como alternativa para CPU fraca; na
    CPU do Pi o buffalo_l provavelmente não fecha, então lá é `buffalo_s` **ou** a inferência
    no fog/cloud — mais um argumento para o rosto não rodar no edge.
  - `similarity_threshold` default passou para **0.38** (template + buffalo_l); com
    `buffalo_s`, baixe para **0.31**. Trocar o pacote OU o agregador muda a escala do cosseno:
    recalibrar sempre.
  - Verificado ponta a ponta: `a_verdade` → `ok`, `a_mentira` → `alert low_similarity`, nas
    duas configurações (0.405 × 0.254 com buffalo_s; 0.525 × 0.237 com buffalo_l).
  - **Sinal de roupa medido, mas a amostra é fácil demais para confiar.** Correlação de
    histograma HSV do tronco: mesma pessoa 0.77–0.95, pessoas diferentes ≈ 0.00 (margem 0.78,
    muito melhor que o rosto). Só que os dois atores vestem camiseta magenta e camiseta branca —
    qualquer histograma separa isso. Não há no conjunto nenhum caso difícil (duas pessoas de
    branco, ou a mesma pessoa tirando um casaco), então o número é otimista e **não** sustenta
    trocar rosto por roupa.
    **Decisão: roupa/corpo fica de fora por ora — o sistema é só rosto.** Reavaliar quando
    houver vídeo do caso difícil; aí o caminho é um ReID de verdade (OSNet / CLIP-ReID) como
    segundo sinal que desempata o rosto, nunca como substituto.
  - **Amostra ainda é pequena: 2 atores.** Com duas pessoas qualquer sistema parece bom. Filmar
    4–5 pessoas depositando e retirando e rodar o `calibrate.py` continua sendo o que falta
    para o limiar deixar de ser um ponto no meio de dois números.
