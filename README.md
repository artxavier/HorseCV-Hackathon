# BikeGuard

Sistema de visão computacional que vigia um bicicletário universitário com uma câmera USB
e avisa a portaria quando **quem retira a bicicleta não é quem a deixou**.

Não é identificação facial (não há banco de rostos): é **verificação 1:1**. Quando uma vaga
passa de vazia para ocupada, o sistema guarda o embedding do rosto de quem estacionou.
Quando a vaga esvazia, compara com o rosto de quem retirou. Similaridade baixa → um **pedido
de verificação** na tela da portaria, com as duas fotos lado a lado e um humano decidindo.

MVP de hackathon: código direto, sem ORM, sem autenticação, sem filas.
As regras de projeto e os números medidos em campo estão em [`CLAUDE.md`](CLAUDE.md).

---

## Índice

- [Como funciona](#como-funciona)
- [Pipeline de comunicação](#pipeline-de-comunicação)
- [Pipeline de processamento](#pipeline-de-processamento)
- [Estrutura dos arquivos](#estrutura-dos-arquivos)
- [Como rodar](#como-rodar)
- [Flags e variáveis de ambiente](#flags-e-variáveis-de-ambiente)
- [Privacidade (LGPD)](#privacidade-lgpd)
- [Estado atual](#estado-atual)

---

## Como funciona

A câmera fica no gramado, **de frente** para o rack, a 1.2–1.6 m de altura e 3–4 m de distância.
Nesse ângulo cada vaga é uma **faixa vertical** entre duas barras do rack, e quem estaciona fica
atrás da bike empurrando-a *em direção à câmera* — ou seja, olha para a lente nos dois momentos
que importam (chegada e retirada). Os polígonos das vagas ficam em `vision/config/slots.json`,
normalizados em [0..1].

```mermaid
stateDiagram-v2
    direction LR
    [*] --> EMPTY
    EMPTY --> OCCUPIED: ≥70% → deposit
    OCCUPIED --> EMPTY: ≤20% → withdrawal
    EMPTY --> EMPTY: 20–70%: mantém
    OCCUPIED --> OCCUPIED: 20–70%: mantém
```

Os percentuais são a fração dos frames da janela de 3 s em que alguma bicicleta cobriu ≥25% da vaga.


A histerese (70% para ocupar, 20% para liberar) existe porque o detector **erra**: em 32 fotos
reais o YOLO26n-seg não viu bicicleta nenhuma em 14 delas. Um simples "tem bike neste frame"
faria a vaga piscar e geraria eventos falsos aos pares.

Três decisões que definem o resto do sistema:

1. **Só a inferência muda de lugar.** Captura, ocupação e máquina de estados rodam sempre no
   dispositivo. O mesmo servidor de inferência, com o mesmo contrato HTTP, roda em três lugares
   (edge / fog / cloud) e o agente escolhe a URL conforme o modo configurado no site.
2. **O detector de rosto nunca vê o frame inteiro.** Os rostos nessa cena têm 20–45 px. O SCRFD
   redimensiona a entrada para 640 e os apagaria. O pipeline obrigatório é recortar a pessoa
   primeiro (detalhado abaixo).
3. **A comparação usa vários rostos de cada lado.** Similaridade = **máximo** do cosseno entre
   todos os pares depósito × retirada, com até 5 rostos de cada. Um frame ruim (cabeça baixa ao
   encaixar a bike, borrado) não vira alerta falso sozinho.

---

## Pipeline de comunicação

Três processos, um contrato HTTP cada. A api e a web ficam num lugar fixo (laptop da equipe);
o "modo de processamento" se refere **apenas** à inferência.

```mermaid
flowchart LR
    subgraph DEV["Dispositivo — RPi 5 / Jetson"]
        CAM["Webcam USB"] --> AGENT["agent<br/>(Python)"]
    end

    subgraph INF["Servidor de inferência — mesmo código nos 3 lugares"]
        EDGE["EDGE<br/>localhost:8001<br/>yolo26n-seg"]
        FOG["FOG<br/>PC da univ:8001<br/>rfdetr-seg-nano"]
        CLOUD["CLOUD<br/>container HTTPS<br/>rfdetr-seg-nano"]
    end

    AGENT -->|"POST /infer<br/>multipart JPEG da ROI"| EDGE
    AGENT -->|"POST /infer"| FOG
    AGENT -->|"POST /infer"| CLOUD

    subgraph FIXO["Laptop da equipe"]
        API["api<br/>Fastify + SQLite"]
        WEB["web<br/>React + Vite"]
    end

    AGENT -->|"POST /api/events<br/>POST /api/metrics<br/>POST /api/cameras/:id/frame"| API
    API -->|"GET /api/config<br/>(polling 5 s)"| AGENT
    WEB <-->|"REST, polling 1–2 s"| API
```

### Quem fala com quem

| Chamada | De → para | Quando | Payload |
|---|---|---|---|
| `POST /infer?faces=true` | agent → inferência | todo frame (~3 FPS) | multipart, JPEG da ROI em **resolução nativa** (~120 KB) |
| `GET /health` | agent → inferência | no boot e a cada troca de modo | — |
| `GET /api/config` | agent → api | polling a cada 5 s | — |
| `POST /api/events` | agent → api | só nas transições de vaga | `deposit` / `withdrawal` com até 5 embeddings + 2 JPEGs em base64 |
| `POST /api/metrics` | agent → api | lote a cada 5 s | `mode, inference_ms, rtt_ms, payload_bytes, fallback` por frame |
| `POST /api/cameras/:id/frame` | agent → api | 1×/s | JPEG anotado (`Content-Type: image/jpeg`) |
| `GET /api/slots`, `/api/alerts?open=1`, `/api/metrics?since=` | web → api | polling 1–2 s | — |
| `PUT /api/config` | web → api | ao trocar o modo em Configurações | JSON parcial (merge) |

O agente **não recebe comandos**: ele só lê a config por polling. Trocar Edge → Fog no site
grava a config no SQLite, e no próximo poll (≤5 s) o agente passa a mandar os frames para outra
URL. É o momento "uau" da demo, e não precisou de WebSocket.

### Fallback

```mermaid
sequenceDiagram
    participant A as agent
    participant F as inferência FOG
    participant E as inferência EDGE
    participant API as api

    A->>F: POST /infer (timeout 2 s)
    F--xA: erro / timeout
    Note over A: modo ≠ edge → refaz o frame localmente
    A->>E: POST /infer
    E-->>A: detecções
    A->>API: métrica { mode: "edge", fallback: 1 }
```

O campo `mode` da métrica guarda onde a inferência **realmente** rodou; `fallback=1` marca que o
modo escolhido falhou. A página de Métricas mostra a % de fallback, então derrubar o fog ao vivo
é uma demonstração de resiliência e não um acidente.

---

## Pipeline de processamento

### Dentro do servidor de inferência (stateless — todo estado fica no agente)

```mermaid
flowchart TB
    IMG["JPEG da ROI<br/>resolução nativa"] --> DET["detector<br/>yolo26n-seg | rfdetr-seg-nano<br/>classes COCO: person, bicycle"]
    DET --> BIKES["bikes[]<br/>bbox + conf + polygon da máscara"]
    DET --> PERS["persons[]<br/>bbox + conf"]
    PERS --> CROP["recorta os 45% superiores da bbox<br/><b>do frame original</b>"]
    CROP --> UP["upscale até 640 no maior lado<br/>INTER_CUBIC"]
    UP --> SCRFD["SCRFD-500M<br/>score ≥ 0.5 e lado ≥ 20 px<br/>medidos no frame original"]
    SCRFD --> EMB["MobileFaceNet → embedding 512-d<br/>L2-normalizado + crop_jpg_b64"]
    BIKES --> RESP["resposta JSON"]
    EMB --> RESP
```

O crop + upscale não é detalhe de performance: no teste com fotos reais ele subiu a similaridade
mínima entre fotos da mesma pessoa de **0.05 para 0.21**. Rodar o SCRFD no frame inteiro
simplesmente não encontra esses rostos.

### Dentro do agente

```mermaid
flowchart TB
    CAP["captura o frame"] --> ROI["recorta a ROI<br/>(tira céu e grama)"]
    ROI --> JPG["encoda JPEG<br/>jpeg_quality"]
    JPG --> INFER["POST /infer na URL do modo"]
    INFER --> OFF["desloca as coordenadas<br/>da ROI para o frame cheio"]

    OFF --> OCC["<b>ocupação</b><br/>rasteriza as máscaras de bike<br/>numa grade 160×120 (fillPoly)<br/>cobertura da vaga ≥ 0.25?"]
    OCC --> SM["<b>máquina de estados</b><br/>janela de 3 s + histerese 70/20"]

    OFF --> LINK["<b>vincula rostos às vagas</b><br/>pés da pessoa na interaction_zone<br/>+ faixa horizontal cobre a coluna"]
    LINK --> BUF["<b>ring buffer por vaga</b><br/>janela de 15 s<br/>quality = score × min(lado, 112)"]

    SM -->|"transição confirmada"| EV["pega o top-5 por quality<br/>contando desde ANTES da transição"]
    BUF --> EV
    EV --> POST["POST /api/events"]

    OFF --> DRAW["overlay das vagas e detecções"]
    DRAW --> FRAME["POST /api/cameras/:id/frame<br/>1×/s"]
    INFER --> MET["métricas em lote, a cada 5 s"]
```

Dois filtros importantes. A **`interaction_zone`** existe porque tem uma calçada logo atrás do
rack: pessoas ao fundo são detecções *corretas*, mas não são clientes da vaga — só contam
pessoas cujos pés caem entre a linha do rack e a borda da calçada. E a **janela de 15 s começando
antes da transição** existe porque ao encaixar a bike a pessoa olha para baixo; o melhor rosto
costuma ser o da chegada.

### Dentro da api, quando chega um evento

```mermaid
flowchart TB
    EV{"type"} -->|deposit| D1["já existe sessão parked<br/>nessa vaga?"]
    D1 -->|sim| D2["a antiga vira <b>orphan</b><br/>(a retirada nunca foi vista)<br/>embeddings zerados"]
    D1 -->|não| D3
    D2 --> D3["cria sessão <b>parked</b><br/>salva embeddings + 2 fotos"]

    EV -->|withdrawal| W1["busca a sessão parked da vaga"]
    W1 --> W2["similarity = <b>máximo</b> do cosseno<br/>entre todos os pares depósito × retirada"]
    W2 --> W3{"motivo"}
    W3 -->|"rosto ausente em um dos lados"| AL["status <b>alert</b><br/>+ linha em alerts<br/>com o reason"]
    W3 -->|"similarity < threshold"| AL
    W3 -->|"similarity ≥ threshold"| OK["status <b>ok</b>"]
    AL --> LGPD["<b>deposit_embeddings = NULL</b>"]
    OK --> LGPD
    LGPD --> RET["fotos de ok/orphan apagadas<br/>após retention_hours"]
```

A precedência dos motivos é `no_face_deposit` → `no_face_withdrawal` → `low_similarity`:
"não consegui ver o rosto" é uma informação diferente de "o rosto não bate", e a portaria
precisa saber qual das duas aconteceu.

---

## Estrutura dos arquivos

```
.
├── CLAUDE.md                     # especificação, números medidos em campo, decisões tomadas
├── README.md
│
├── vision/                       # Python 3.12 (venv em vision/.venv)
│   ├── requirements.txt
│   ├── run_inference.sh          # sobe o uvicorn já sem o PYTHONPATH do ROS
│   ├── Dockerfile.inference      # imagem do modo CLOUD (pesos embutidos)
│   ├── models/                   # pesos baixados (gitignored)
│   ├── samples/                  # fotos/vídeos reais do bicicletário (VERSIONADO)
│   │
│   ├── common/
│   │   ├── schemas.py            # dataclasses do contrato /infer + Face.quality
│   │   └── geometry.py           # cobertura por fillPoly, IoU, crop_roi, denormalização
│   │
│   ├── inference/                # ── o que muda de lugar ──
│   │   ├── server.py             # FastAPI: POST /infer, GET /health. Stateless.
│   │   ├── detector.py           # YoloDetector | RFDetrDetector, build_detector() com cache
│   │   └── faces.py              # crop 45% → upscale 640 → SCRFD → MobileFaceNet
│   │
│   ├── agent/                    # ── o que roda sempre no dispositivo ──
│   │   ├── main.py               # o loop; fallback edge; CLI
│   │   ├── occupancy.py          # máscaras de bike ∩ polígono da vaga
│   │   ├── slots_state.py        # janela deslizante + histerese, emite Transition
│   │   ├── face_buffer.py        # ring buffer por vaga + link_faces_to_slots
│   │   ├── api_client.py         # config/eventos/métricas/frame + InferenceClient
│   │   └── draw.py               # overlay
│   │
│   ├── config/slots.json         # polígonos das vagas + interaction_zone, [0..1]
│   └── scripts/
│       ├── download_models.sh    # yolo26n-seg.pt + buffalo_s
│       ├── annotate_slots.py     # clica os polígonos e gera o slots.json real
│       └── calibrate.py          # genuínos × impostores, histograma + limiar sugerido
│
├── api/                          # Node + TypeScript strict, Fastify + better-sqlite3
│   ├── src/
│   │   ├── index.ts              # servidor, purga de retenção no boot e a cada hora
│   │   ├── db.ts                 # schema em CREATE TABLE IF NOT EXISTS, WAL
│   │   ├── similarity.ts         # cosine + maxPairwise
│   │   ├── config.ts             # config default + merge
│   │   ├── images.ts             # base64 → api/data/faces/<uuid>.jpg
│   │   └── routes/
│   │       ├── events.ts         # a regra de negócio: deposit / withdrawal / purga
│   │       ├── sessions.ts       # sessões + GET /api/slots (estado por vaga)
│   │       ├── alerts.ts         # abertos + /ack
│   │       ├── config.ts         # GET / PUT
│   │       ├── metrics.ts        # insert em lote + resumo por modo
│   │       └── cameras.ts        # último frame em memória + em disco
│   └── data/                     # bikeguard.db, faces/, frames/ (gitignored)
│
└── web/                          # Vite + React 19 + Tailwind 4 + recharts
    ├── vite.config.ts            # proxy /api e /files → :3000
    └── src/
        ├── api.ts                # tipos compartilhados + hook usePolling
        └── pages/
            ├── Dashboard.tsx     # frame ao vivo + grade de vagas + modo e FPS
            ├── Portaria.tsx      # alertas: as duas fotos, similaridade, "Verificado"
            ├── Eventos.tsx       # tabela de sessões, filtrável por status
            ├── Configuracoes.tsx # seletor Edge/Fog/Cloud, URLs, limiares
            └── Metricas.tsx      # latência por modo no tempo + médias e % fallback
```

Nota sobre a fronteira: **tudo em `inference/` é stateless e intercambiável de lugar; tudo em
`agent/` guarda estado e nunca sai do dispositivo.** Se um arquivo de `inference/` precisar
lembrar de algo entre frames, a arquitetura quebrou.

---

## Como rodar

### Instalação (uma vez)

```bash
# visão
cd vision
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash scripts/download_models.sh        # yolo26n-seg.pt + buffalo_s (~15 MB)

# api e web
cd ../api && npm i
cd ../web && npm i
```

> **Atenção, usuários de ROS:** se o seu shell tem `/opt/ros/.../site-packages` no `PYTHONPATH`,
> ele entra **antes** da venv e sombreia o numpy/opencv dela. Todo comando Python deste README
> usa `env -u PYTHONPATH` ou o `run_inference.sh`, que já faz isso.

### Os quatro processos

Cada um num terminal:

```bash
# 1) inferência                                                    → :8001
cd vision && ./run_inference.sh

# 2) api                                                           → :3000
cd api && npm run dev

# 3) web                                                           → :5173
cd web && npm run dev

# 4) agente (webcam)
cd vision && env -u PYTHONPATH .venv/bin/python -m agent.main --source 0 --show
```

Abra <http://localhost:5173>. Sem o agente rodando o Dashboard mostra um aviso no lugar do frame.

Plano B da demo (e ambiente padrão de desenvolvimento) é o vídeo em loop — os vídeos reais do
bicicletário estão em `vision/samples/`:

```bash
cd vision && env -u PYTHONPATH .venv/bin/python -m agent.main --source samples/Insercao_P1.mp4
```

Num arquivo o agente descarta frames para manter o tempo do vídeo colado no tempo real (um clipe
de 14 s leva 14 s), porque o debounce conta segundos de relógio. Com `--no-loop` ele para no fim.

### Se a câmera for remontada

O `slots.json` versionado é a geometria **real** do rack dos vídeos em `samples/` (6 vãos entre os
7 montantes). Mexeu na câmera, refaça:

```bash
cd vision
env -u PYTHONPATH .venv/bin/python scripts/annotate_slots.py --source 0 --out config/slots.json
```

E recalibre o limiar sempre que houver mais gente filmada (uma subpasta por pessoa):

```bash
env -u PYTHONPATH .venv/bin/python scripts/calibrate.py --dir samples/pessoas --out calibracao.png
```

O `calibrate.py` mede os cossenos de pares da mesma pessoa (genuínos) e de pessoas diferentes
(impostores), sugere o limiar que minimiza os dois erros e gera o histograma —
`samples/calibracao.png` é o resultado com as duas pessoas filmadas até agora, e vai para a
apresentação.

### Testando a inferência sozinha

```bash
curl -F image=@vision/samples/frame.jpg 'http://localhost:8001/infer?faces=true&detector=rfdetr'
curl http://localhost:8001/health
```

### Modo cloud

```bash
docker build -f vision/Dockerfile.inference -t bikeguard-inference vision/
# suba em qualquer provedor que aceite container (Cloud Run, Container Apps, App Runner)
# e cole a URL em Configurações → inference_urls.cloud
```

---

## Flags e variáveis de ambiente

### `agent.main` — o agente

| Flag | Default | O que faz |
|---|---|---|
| `--source` | `0` | Fonte de vídeo. Um número é índice de webcam (`0` = primeira); qualquer outra coisa é caminho de arquivo, e o vídeo roda **em loop** (útil para demo e desenvolvimento). |
| `--api` | `http://localhost:3000` | URL da api. Passe `--api ''` para rodar **offline**: o agente cai para os defaults da config e só loga as transições no console. Bom para testar a visão sem subir o resto. |
| `--camera` | `cam1` | Identificador desta câmera. Aparece nas rotas (`/api/cameras/cam1/frame.jpg`) e nas tabelas. Mude se houver mais de uma câmera contra a mesma api. |
| `--slots` | `vision/config/slots.json` | Arquivo de polígonos das vagas. Aponte para outro se tiver mais de um bicicletário. |
| `--edge-url` | `http://localhost:8001` | Servidor de inferência **local**. Usado no modo edge e, sempre, como destino do fallback quando fog/cloud falha — por isso vale a pena mantê-lo de pé mesmo em modo cloud. |
| `--show` | desligado | Abre uma janela OpenCV com o overlay (vagas, detecções, estado). Não use em máquina sem display / via SSH sem X. `q` fecha. |
| `--no-loop` | desligado | Só afeta arquivo de vídeo: para no fim em vez de repetir. Use para rodar um cenário uma vez e ler o resultado; sem ele o vídeo repete e cada volta gera um ciclo depósito/retirada completo. |

Tudo o mais — modo, URLs, FPS alvo, ROI, limiares, `top_k`, `timeout_ms` — vem do
`GET /api/config` e é editável na página **Configurações**, sem reiniciar o agente.

### `scripts/annotate_slots.py`

| Flag | Default | O que faz |
|---|---|---|
| `--source` | `0` | Webcam ou imagem/vídeo de onde tirar o frame de referência. |
| `--out` | `config/slots.json` | Onde salvar. **Sobrescreve** o arquivo. |
| `--camera` | `cam1` | Vai gravado no JSON. |

Teclas: clique adiciona um vértice · `n` fecha a vaga atual e começa a próxima ·
`i` marca o polígono como `interaction_zone` · `z` desfaz o último vértice ·
`r` recomeça · `s` salva · `q` sai sem salvar.

### `scripts/calibrate.py`

| Flag | Default | O que faz |
|---|---|---|
| `--dir` | **obrigatório** | Pasta com **uma subpasta por pessoa** (`pessoas/ana/*.jpg`, `pessoas/bruno/*.jpg`). Pares dentro da mesma subpasta são genuínos; entre subpastas, impostores. |
| `--out` | `calibracao.png` | PNG com os dois histogramas e o limiar sugerido. |
| `--detector` | `rfdetr` | `yolo26` ou `rfdetr`, para achar as pessoas nas fotos. |
| `--face-backend` | do ambiente | `insightface` (512-d) ou `opencv` (128-d). Trocar o backend **invalida o limiar** — os espaços de embedding são diferentes. |
| `--face-min-score` | `0.5` | Score mínimo do detector de rosto. |
| `--face-min-px` | `20` | Lado mínimo do rosto, medido no frame original. |

### Servidor de inferência — variáveis de ambiente

| Variável | Default | O que faz |
|---|---|---|
| `PORT` / `HOST` | `8001` / `0.0.0.0` | Lidas pelo `run_inference.sh`. |
| `DETECTOR` | `yolo26` | Detector padrão do processo. Use `rfdetr` no fog/cloud. A query `?detector=` sobrepõe por requisição. |
| `YOLO_WEIGHTS` | `models/yolo26n-seg.pt` | **É aqui que entram os pesos com fine-tuning.** Aponte para o novo `.pt` e nada mais no pipeline muda. |
| `MODELS_DIR` | `vision/models` | Onde procurar os pesos locais. |
| `FACE_BACKEND` | `insightface` | `opencv` cai para YuNet + SFace (128-d), que vem no próprio opencv-python. Só use se o insightface não instalar. |
| `DEVICE` | auto | `cpu`, `cuda`, `cuda:0`. |
| `DEVICE_LABEL` | auto | Texto que aparece no `/health` e nas métricas (ex. `rpi5-cpu`, `laptop-cuda`). É o que identifica o modo nos gráficos da apresentação. |

Query params do `POST /infer`: `faces` (default `true`), `detector`, `bike_conf` (`0.25`),
`person_conf` (`0.4`), `imgsz` (`640`), `face_min_score` (`0.5`), `face_min_px` (`20`).

### api e web

| Variável | Default | Onde |
|---|---|---|
| `PORT` / `HOST` | `3000` / `0.0.0.0` | api |
| `DATA_DIR` | `api/data` | api — banco e imagens |
| `VITE_API_TARGET` | `http://localhost:3000` | web — alvo do proxy `/api` e `/files` |

Scripts npm: `npm run dev` (watch), `npm start` (api, sem watch),
`npm run build` / `npm run preview` (web), `npm run typecheck` (ambos).

---

## Privacidade (LGPD)

Biometria é dado pessoal sensível (LGPD art. 5º II / art. 11). O que o MVP faz:

- **Embeddings existem só enquanto a bike está estacionada.** Na retirada, depois da comparação,
  `deposit_embeddings` vira `NULL` na mesma transação.
- **Fotos de sessões normais são apagadas** após `retention_hours` (default 24) — purga no boot
  e a cada hora.
- **O alerta é um pedido de verificação, não uma acusação.** Humano no loop, sempre: a tela da
  portaria mostra as duas fotos e diz isso com essas palavras.
- **No modo edge nenhuma imagem de rosto sai do dispositivo** exceto nos eventos.
- Em produção faltariam sinalização no local, base legal e a política de retenção da universidade.

---

## Estado atual

Implementado e verificado: passos 1–6 do §10 do `CLAUDE.md` (inferência, agente, api, web,
troca de modo com fallback, métricas), testado ponta a ponta com os vídeos reais do bicicletário
em `vision/samples/`.

**Cenário completo, em vídeo real** (P1 estaciona → P1 retira, mesma vaga S3):

```
[DEPOSIT]    vaga=S3  rostos=5  → sessão parked
[WITHDRAWAL] vaga=S3  rostos=5  → similaridade 0.340  → ok, sem alerta
```

E com a pessoa errada retirando (P1 deixou, P2 levou): similaridade **0.151** → `alert`
`low_similarity`, com as duas fotos na Portaria.

| | |
|---|---|
| Detector, 129 frames dos 3 vídeos | **rfdetr**: bike em 96% dos frames, conf 0.81, 43 ms · **yolo26**: 55%, conf 0.58, 24 ms |
| Rostos | 73 válidos, score médio 0.65, lado médio **42 px** (22–55) |
| Cobertura da vaga com a bike estacionada | 0.30–0.41 na vaga certa, 0.00 nas outras (limiar 0.25) |
| Agente | 45 ms de inferência, 51 ms de RTT, **138 KB/frame** (~0.41 MB/s a 3 FPS) |
| Fallback com o fog derrubado | 41/41 frames refeitos no edge, `fallback_pct` 100 |
| Limiar facial | genuínos 0.32–0.34 × impostores 0.15 → `similarity_threshold` **0.23** |

**O modo edge não fecha com os pesos COCO.** O YOLO26n-seg perde a bicicleta em 45% dos frames,
a vaga nunca alcança os 70% da janela de debounce e **nenhum evento é emitido**. Subir para
`imgsz=960` com `bike_conf=0.15` faz os eventos saírem, mas nos instantes errados. Por isso
`detector.edge` está em `rfdetr` por enquanto — é este o problema que os pesos com fine-tuning
precisam resolver.

Faltando:

- **Recalibrar o limiar com mais gente.** A amostra tem 2 pessoas; a separação entre genuínos e
  impostores é estreita (histograma em `vision/samples/calibracao.png`).
- **Refazer o `slots.json` se a câmera for remontada** — a geometria atual é a dos vídeos.
- Passos 7 (deploy cloud) e 8 (export NCNN/TensorRT) continuam fora.
