# AI Lightning — Node (Windows)

Client nodo per Windows per la piattaforma AI Lightning.  
Si connette al server via WebSocket, riceve richieste di inferenza e le esegue localmente con llama.cpp / Ollama.

## Funzionalità

- Connessione WebSocket al server AI Lightning
- Esecuzione locale di modelli LLM (llama.cpp, Ollama, HuggingFace)
- Gestione automatica download e aggiornamento modelli
- RAG (Retrieval-Augmented Generation) su documenti locali
- Interfaccia grafica (tray icon)
- Pagamenti Lightning Network diretti (opzionale, via LND locale)
- Auto-updater integrato

## Requisiti

- Windows 10/11 (64-bit)
- Python 3.10+ **oppure** usa il file `.exe` pre-compilato
- GPU NVIDIA consigliata (funziona anche su CPU)
- llama.cpp installato (o Ollama)

## Installazione

### Opzione A — Eseguibile pre-compilato

1. Scarica l'ultima release da [Releases](../../releases)
2. Esegui `AILightningNode-Setup.exe`
3. Inserisci il tuo token nodo durante l'installazione

### Opzione B — Da sorgente (Python)

```bash
# 1. Clona il repo
git clone https://github.com/your-org/ai-lightning-node.git
cd ai-lightning-node

# 2. Crea virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Installa dipendenze
pip install -r requirements.txt

# 4. Configura
copy config.ini.example config.ini
# Modifica config.ini con il tuo token

# 5. Avvia
python node_client.py
```

## Configurazione

Copia `config.ini.example` in `config.ini` e modifica:

```ini
[Node]
token = IL_TUO_TOKEN_NODO
name = NomeNodo (opzionale)
restricted_models = false

[Server]
URL = https://lightphon.com

[Lightning]
; Lascia disabilitato se non hai un wallet LND locale
enabled = false
```

Ottieni il token registrandoti su [lightphon.com](https://lightphon.com) e creando un nodo dal pannello.

## Build eseguibile Windows

```bash
# Assicurati che PyInstaller sia installato
pip install pyinstaller

# Build
build.bat

# L'exe verrà creato in dist/
```

Per creare l'installer `.exe` completo usa [Inno Setup](https://jrsoftware.org/isinfo.php) con `installer.iss`.

## Struttura

```
.
├── node_client.py      # Entry point principale
├── gui.py              # Interfaccia grafica (tray)
├── model_manager.py    # Download e gestione modelli
├── rag_manager.py      # RAG su documenti locali
├── hardware_detect.py  # Rilevamento GPU/CPU
├── updater.py          # Auto-updater
├── version.py          # Versione corrente
├── config.ini.example  # Template configurazione
├── models_config.json  # Configurazione modelli supportati
├── docker/             # Dockerfile (Linux)
└── build.bat           # Script build Windows
```

## Licenza

Proprietario — tutti i diritti riservati.
