# R Bullwhip Game Benchmark

Dieses Benchmark evaluiert die Fähigkeit von KI-Modellen, eine reproduzierbare Bullwhip-Simulation in R zu implementieren. Ziel ist es, idiomatischen R-Code mit `tidyverse`, reproduzierbaren Zufallsseeds, `testthat`-Tests und ggf. Shiny/Quarto-Dokumentation zu generieren.

## Struktur
- `simulation/` – Kernsimulation und Logik
- `tests/` – `testthat`-Tests für Validierung
- `docs/` – Dokumentation (ggf. Quarto/Shiny)
- `renv/` – Abhängigkeiten (automatisch generiert)
- `DESCRIPTION` – Paketmetadaten

## Evaluierungskriterien
1. **Korrektheit**: Deterministische Simulation mit festem Seed
2. **Idiomatischer R-Code**: Nutzung von `tidyverse`/`base`
3. **Testabdeckung**: `testthat`-Tests für Kernfunktionen
4. **Dokumentation**: Klare Kommentare und ggf. Quarto/Shiny
5. **Reproduzierbarkeit**: `renv`/`DESCRIPTION` für Abhängigkeiten

## Durchführung
1. Modell erhält Issue-Beschreibung und leeres Repository
2. Modell implementiert Simulation, Tests und Dokumentation
3. Ergebnis wird gegen Referenzlösung validiert

## Referenzlösung
Eine minimalistische Implementierung liegt in `reference_solution/` vor.

## Vergleichsmodelle
- OpenCode + Mistral Large
- OpenCode + Claude Sonnet
- OpenRouter Direct + Mistral Large
- DeepSeek
- Qwen Coder
- MiniMax/MiniMax-M1