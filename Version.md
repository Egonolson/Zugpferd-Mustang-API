## Versionierung

Schema: `YYYY.MM.DD` (Datum der Änderung) + optionaler Suffix für Hotfixes.

## 2025.12.19

- **Mustang-CLI (Auto-Latest)**: Mustang-CLI wird beim Docker-Build automatisch aus dem neuesten GitHub Release-Tag `core-*` gebaut (Repo-Clone + Maven/JDK21). Pinning via `MUSTANG_TAG=core-x.y.z` möglich. Referenz: [`ZUGFeRD/mustangproject`](https://github.com/ZUGFeRD/mustangproject)
- **Docker Runtime (Java 21)**: Java 21 Runtime wird aus der Build-Stage ins Runtime-Image übernommen (keine apt-OpenJDK Abhängigkeit, arm64-sicher).
- **Validation API**: `/validate` parst den Mustang-XML-Report robust (kein String-Matching mehr) und liefert strukturierte JSON-Findings.
- **Healthcheck**: `/health` ergänzt und `docker-compose.yml` von obsoletem `version:` Feld bereinigt.
- **Security**: Alle Endpunkte sind jetzt per **Bearer Token** abgesichert (ENV `API_BEARER_TOKEN`), inkl. authentifiziertem Healthcheck.
- **PDF/A**: PDF/A-Validierung via **veraPDF** (`POST /validate_pdfa`) ergänzt. Zusätzlich gibt es `GET /version` für Laufzeit-Versionen.


