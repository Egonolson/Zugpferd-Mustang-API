# mustang-api

Docker-basierter Microservice (Flask), der die **Mustangproject CLI** kapselt, um ZUGFeRD/Factur-X/XRechnung Workflows auszuführen:

- Validierung von PDF/XML über Mustang-CLI
- PDF/A-3 Konvertierung via Ghostscript
- Einbetten von XML in PDF (ZUGFeRD/Factur-X) via Mustang-CLI

Referenzprojekt Mustang: [`ZUGFeRD/mustangproject`](https://github.com/ZUGFeRD/mustangproject)

## Start (Docker Compose)

```bash
docker compose up -d --build
```

### Auto-Latest beim Build

Beim Docker-Build wird **automatisch das neueste Mustang-Release** (GitHub Release-Tag `core-*`) ermittelt, das Repo geklont und die Mustang-CLI mit **Maven + JDK 21** gebaut. Dadurch werden Validator-Logik/Artefakte aus dem Mustang-Projekt (inkl. [`validator`](https://github.com/ZUGFeRD/mustangproject/tree/master/validator)) automatisch mitgezogen.

Wichtig: Damit „latest“ wirklich neu gezogen wird, musst du **ohne Cache bauen** (Docker würde sonst den Build-Step cachen).

```bash
docker compose build --no-cache --pull
docker compose up -d --force-recreate
```

### Pinning (empfohlen für Audits)

Du kannst ein konkretes Mustang-Tag pinnen (z.B. `core-2.21.0`), indem du beim Build ein Argument setzt:

```bash
docker compose build --no-cache --pull --build-arg MUSTANG_TAG=core-2.21.0
docker compose up -d --force-recreate
```

Welche Version tatsächlich im Image gelandet ist, steht in `/opt/mustang/mustang_tag.txt`.

### No-Cache Build (für Updates/Container-Recreate)

```bash
docker compose build --no-cache --pull
docker compose up -d --force-recreate
```

Service läuft standardmäßig auf `http://localhost:3296`.

## Endpunkte

### Health

- **GET** `/health`

Beispiel:

```bash
curl -fsS http://localhost:3296/health
```

### Validierung (PDF oder XML)

- **POST** `/validate`
- Upload als `multipart/form-data` Feld **`file`** (PDF oder XML).

Die API ruft intern Mustang-CLI `--action validate --source ...` auf und **parst den XML-Report**, um ein stabiles JSON-Ergebnis zurückzugeben.

Beispiel (XML via stdin):

```bash
curl -sS -X POST -F 'file=@-;filename=invoice.xml;type=application/xml' http://localhost:3296/validate << 'EOF'
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" />
EOF
```

Antwort (Beispiel):

- `ok`: `true|false`
- `status`: `valid|invalid` (aus dem Mustang-Report)
- `findings`: Liste der Findings aus dem Report (z.B. `<exception>`, `<error>`, …)

### XML in PDF einbetten (ZUGFeRD/Factur-X)

- **POST** `/embed_xml`
- `multipart/form-data` mit:
  - `pdf_file`: PDF
  - `xml_file`: XML (CII/Factur-X/ZUGFeRD je nach Profil)
- Query-Parameter:
  - `format`: `zf` (ZUGFeRD) oder `fx` (Factur-X)
  - `version`: `1` oder `2`
  - `profile`: z.B. `XRechnung`, `EN16931`, `BASIC`, …

Hinweis: `--no-additional-attachments` ist aktiv, damit die CLI niemals interaktiv nach Attachments fragt.

### PDF → PDF/A-3 Konvertierung (Ghostscript)

- **POST** `/convert_pdfa3`
- `application/pdf` im Body oder `multipart/form-data` Feld `file`

## Hinweise zur Rechtskonformität

- Die Mustang-CLI liefert Validierungsergebnisse, Profile und Regeln je nach Version. Für Details zur CLI siehe die Mustang-Dokumentation: `https://www.mustangproject.org/commandline/`.
- Für PDF/A-Konformität kann eine zusätzliche Prüfung mit externen Tools (z.B. veraPDF) sinnvoll sein, je nach Compliance-Anforderung.


