# Guida: Configurare LM Studio con OMNIA

## Indice

- [1. Installare e configurare LM Studio](#1-installare-e-configurare-lm-studio)
- [2. Configurare OMNIA per LM Studio](#2-configurare-omnia-per-lm-studio)
- [3. Passare da Ollama a LM Studio (e viceversa)](#3-passare-da-ollama-a-lm-studio-e-viceversa)
- [4. Differenze tra Ollama e LM Studio](#4-differenze-tra-ollama-e-lm-studio)
- [5. Troubleshooting](#5-troubleshooting)

---

## 1. Installare e configurare LM Studio

### 1.1 — Scaricare LM Studio

1. Vai su [lmstudio.ai](https://lmstudio.ai) e scarica l'installer per Windows.
2. Esegui l'installer e completa l'installazione.
3. Avvia LM Studio.

### 1.2 — Scaricare un modello

1. Nella barra di ricerca in alto, cerca il modello desiderato (es. `Qwen/Qwen2.5-7B-Instruct-GGUF`).
2. Scegli una quantizzazione adatta alla tua VRAM (es. `Q4_K_M` per ~6 GB VRAM, `Q8_0` per ~10 GB).
3. Clicca **Download** e attendi il completamento.

### 1.3 — Avviare il server API locale

1. Vai nella sezione **Developer** (icona `<>` nella barra laterale sinistra).
2. Seleziona il modello scaricato dal menu a tendina in alto.
3. Clicca **Start Server**. Il server si avvierà su `http://localhost:1234`.
4. Verifica che lo stato mostri **Server running** con l'indicatore verde.

> **Nota:** LM Studio carica il modello in memoria solo quando avvii il server (o la chat). Assicurati che il modello sia effettivamente caricato prima di usare OMNIA.

### 1.4 — Trovare il nome esatto del modello

Il nome del modello in LM Studio è visibile in due modi:

- **Nella UI:** nella sezione Developer, il nome del modello è mostrato nel menu a tendina (es. `qwen2.5-7b-instruct`).
- **Via API:** apri un terminale ed esegui:
  ```bash
  curl http://localhost:1234/v1/models
  ```
  La risposta JSON conterrà il campo `id` con il nome esatto da usare nella configurazione OMNIA.

---

## 2. Configurare OMNIA per LM Studio

Apri il file `config/default.yaml` nella root del progetto e modifica la sezione `llm`:

### Prima (Ollama):
```yaml
llm:
  provider: "openai-compatible"
  base_url: "http://localhost:11434"
  model: "qwen3.5:9b"
  temperature: 0.7
  max_tokens: 4096
  supports_thinking: false
  supports_vision: true
```

### Dopo (LM Studio):
```yaml
llm:
  provider: "openai-compatible"
  base_url: "http://localhost:1234"           # Porta di LM Studio
  model: "qwen2.5-7b-instruct"               # Nome esatto da /v1/models
  temperature: 0.7
  max_tokens: 4096
  supports_thinking: false                    # true solo per modelli reasoning
  supports_vision: false                      # true solo per modelli multimodali
```

### Parametri da aggiornare

| Parametro | Cosa cambiare | Note |
|---|---|---|
| `base_url` | `http://localhost:1234` | Porta default di LM Studio |
| `model` | Il nome esatto del modello | Ottenuto da `/v1/models` o dalla UI |
| `supports_vision` | `true` / `false` | Attivare solo con modelli multimodali (es. LLaVA, Qwen2-VL) |
| `supports_thinking` | `true` / `false` | Attivare solo con modelli reasoning (es. QwQ, DeepSeek-R1) |

> **Attenzione:** Se il modello non è nella lista `KNOWN_MODELS` di OMNIA, i flag `supports_vision` e `supports_thinking` **non vengono auto-rilevati**. Devi impostarli manualmente nel YAML.

### Riavviare il backend

Dopo aver salvato il file, riavvia il backend OMNIA:

```powershell
cd omnia
.\backend\.venv\Scripts\python.exe -m uvicorn backend.core.app:create_app --factory --reload --reload-dir backend --host 0.0.0.0 --port 8000
```

---

## 3. Passare da Ollama a LM Studio (e viceversa)

Il cambio è semplice: OMNIA usa il protocollo **OpenAI-compatible** per entrambi. Basta modificare due campi in `config/default.yaml`:

| | Ollama | LM Studio |
|---|---|---|
| `base_url` | `http://localhost:11434` | `http://localhost:1234` |
| `model` | Tag Ollama (es. `qwen3.5:9b`) | Nome da `/v1/models` (es. `qwen2.5-7b-instruct`) |

**Procedura:**

1. Assicurati che il server del provider scelto sia in esecuzione.
2. Modifica `base_url` e `model` nel YAML.
3. Aggiorna `supports_vision` e `supports_thinking` se il modello cambia.
4. Riavvia il backend OMNIA.

> **Alternativa con variabili d'ambiente** (senza modificare il YAML):
> ```powershell
> $env:OMNIA_LLM__BASE_URL = "http://localhost:1234"
> $env:OMNIA_LLM__MODEL = "qwen2.5-7b-instruct"
> ```

---

## 4. Differenze tra Ollama e LM Studio

| Aspetto | Ollama | LM Studio |
|---|---|---|
| **Porta default** | `11434` | `1234` |
| **Formato nome modello** | Tag registry (es. `qwen3.5:9b`) | Nome file/percorso (es. `qwen2.5-7b-instruct`) |
| **Endpoint API** | `/v1/chat/completions` | `/v1/chat/completions` |
| **Gestione modelli** | CLI (`ollama pull`, `ollama list`) | GUI integrata |
| **Avvio server** | Automatico (`ollama serve`) | Manuale (Developer → Start Server) |
| **Multi-modello** | Sì (carica/scarica dinamicamente) | Un modello alla volta nel server |
| **GPU offloading** | Automatico | Configurabile dalla UI (slider n_gpu_layers) |
| **Formato modelli** | Proprietario (basato su GGUF) | GGUF diretto da HuggingFace |

**Entrambi** supportano il protocollo OpenAI-compatible, quindi OMNIA funziona senza modifiche al codice.

---

## 5. Troubleshooting

### Il server è attivo?

```bash
curl http://localhost:1234/v1/models
```

Se ricevi una risposta JSON con la lista dei modelli, il server è attivo. Se ricevi un errore di connessione:
- Verifica che LM Studio sia aperto
- Verifica che il server sia avviato (Developer → Start Server)
- Controlla che la porta non sia bloccata da firewall

### Nome modello sbagliato

Errore tipico: **404 Not Found** o **Model not found**.

Soluzione: verifica il nome esatto con:
```bash
curl http://localhost:1234/v1/models
```
Copia il valore del campo `"id"` e incollalo nel campo `model` del YAML.

### Il modello non risponde / timeout

- Verifica che il modello sia **effettivamente caricato** in LM Studio (indicatore nella barra in basso)
- Se il modello è troppo grande per la tua VRAM, LM Studio potrebbe andare in swap CPU — prova una quantizzazione più piccola

### Porta già in uso

Se la porta 1234 è occupata, puoi cambiarla in LM Studio (impostazioni del server) e aggiornare `base_url`:
```yaml
base_url: "http://localhost:NUOVA_PORTA"
```

### Il tool calling non funziona

Non tutti i modelli supportano il function calling. In LM Studio:
- Scegli modelli `instruct` o `chat` recenti
- Verifica che il preset di prompt sia compatibile (ChatML, Llama-3, ecc.)

### Errore di connessione dal backend

Se nel log OMNIA vedi `ConnectionRefusedError`:
1. Verifica che il server LM Studio sia in esecuzione
2. Verifica che la porta nel YAML corrisponda a quella di LM Studio
3. Se usi WSL o Docker, `localhost` potrebbe non risolvere — usa l'IP locale
