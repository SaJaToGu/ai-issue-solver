# 🍓 Ollama auf Raspberry Pi

Nutze deinen Raspberry Pi als lokalen KI-Server für den AI Issue Solver.

## Voraussetzungen

- Raspberry Pi 4 oder 5 (min. 4 GB RAM empfohlen)
- Raspberry Pi OS (64-bit) oder Ubuntu Server
- Internetverbindung

## Ollama installieren

```bash
# Auf dem Raspberry Pi:
curl -fsSL https://ollama.ai/install.sh | sh

# Service starten
sudo systemctl enable ollama
sudo systemctl start ollama

# Modell herunterladen
ollama pull llama3.2:3b      # ~2 GB, gut für 4 GB RAM
# oder
ollama pull deepseek-coder:6.7b  # ~4 GB, besser für Code, 8 GB RAM

# Testen
ollama run llama3.2:3b "Schreibe eine README für ein OpenSCAD-Projekt"
```

## Ollama von außen erreichbar machen

Damit dein PC den Raspi als KI-Server nutzen kann:

```bash
# /etc/systemd/system/ollama.service bearbeiten
# Unter [Service] hinzufügen:
Environment="OLLAMA_HOST=0.0.0.0:11434"

sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Dann in `config/.env` auf deinem PC:
```
OLLAMA_HOST=http://192.168.1.XXX:11434
```

## Modell-Empfehlungen nach Hardware

| Gerät | RAM | Empfohlenes Modell | Tokens/s |
|-------|-----|--------------------|----------|
| Raspi 4 | 4 GB | `llama3.2:3b` | ~3-5 |
| Raspi 4 | 8 GB | `llama3.2:7b` | ~1-2 |
| Raspi 5 | 8 GB | `deepseek-coder:6.7b` | ~2-4 |
| PC (CPU) | 16 GB | `codellama:13b` | ~5-10 |
| PC (GPU) | VRAM | `deepseek-coder:33b` | ~20+ |

## Tipp: Issues auf dem Raspi lösen

```bash
python scripts/solve_issues.py \
    --model ollama \
    --model-name llama3.2:3b \
    --repo BedBoxDrawerRole
```
