### API Dokumentation (mustang-api)

Diese Datei beschreibt die öffentlich verfügbaren HTTP-Endpunkte des Services inkl. Authentifizierung, Request/Response-Formate und Statuscodes.

### Base URL

- Lokal (Docker Compose): `http://localhost:3296`
- Produktion: `http(s)://<host>:3296`

### Authentifizierung (Bearer Token)

Alle Endpunkte sind abgesichert (inkl. `/health`).

- **Header**: `Authorization: Bearer <API_BEARER_TOKEN>`
- **Konfiguration**: ENV `API_BEARER_TOKEN` muss gesetzt sein, sonst startet der Service nicht.

Beispiel:

```bash
curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" http://localhost:3296/health
```

### Gemeinsame Fehlercodes

- **401 Unauthorized**: Fehlender oder ungültiger Bearer-Token.
- **400 Bad Request**: Ungültige Eingaben / fehlende Felder / falscher Content-Type.
- **422 Unprocessable Entity**: Validierung lief, Ergebnis ist „invalid“ (fachlich).
- **500 Internal Server Error**: Unerwarteter Fehler (z.B. CLI/GS Fehler, Parsingfehler).
- **504 Gateway Timeout**: Timeout bei CLI-Aufrufen.

---

### GET `/health`

Healthcheck-Endpunkt für Docker/Portainer.

#### Request

- **Headers**: `Authorization: Bearer <token>`

#### Response `200`

```json
{ "ok": true, "status": "healthy" }
```

---

### GET `/version`

Gibt Laufzeit-/Build-Informationen zurück, um Deployment und Compliance zu prüfen.

#### Request

- **Headers**: `Authorization: Bearer <token>`

#### Response `200`

Beispiel:

```json
{
  "ok": true,
  "mustang": { "tag": "core-2.21.0" },
  "java": { "version": "..." },
  "ghostscript": { "version": "10.05.1" },
  "verapdf": { "version": "veraPDF 1.28.2 ..." }
}
```

---

### POST `/validate`

Validiert **XML oder PDF** via Mustang-CLI (`--action validate`).  
Die Mustang-CLI gibt einen **XML-Report** aus; der Service extrahiert und parst diesen und liefert eine stabile JSON-Struktur.

#### Request (empfohlen)

- **Content-Type**: `multipart/form-data`
- **Form-Field**: `file` (PDF oder XML)
- **Headers**: `Authorization: Bearer <token>`

Beispiel (XML):

```bash
curl -sS \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -X POST \
  -F "file=@invoice.xml;type=application/xml" \
  http://localhost:3296/validate
```

Beispiel (PDF):

```bash
curl -sS \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -X POST \
  -F "file=@invoice.pdf;type=application/pdf" \
  http://localhost:3296/validate
```

#### Alternativ (Raw Body)

- **Content-Type**: `application/pdf` oder `application/xml`
- Body enthält die Rohdaten

#### Response `200` (valid)

```json
{
  "ok": true,
  "status": "valid",
  "returncode": 0,
  "report": { "filename": "invoice.xml", "datetime": "YYYY-MM-DD HH:mm:ss" },
  "findings": []
}
```

#### Response `422` (invalid)

```json
{
  "ok": false,
  "status": "invalid",
  "returncode": 255,
  "report": { "filename": "invoice.xml", "datetime": "YYYY-MM-DD HH:mm:ss" },
  "findings": [
    { "tag": "exception", "attributes": { "type": "22" }, "text": "..." }
  ]
}
```

Hinweis: `findings[].tag/attributes/text` spiegeln die Struktur des Mustang-Reports wider.

---

### POST `/validate_pdfa`

Validiert ein PDF gegen PDF/A mit **veraPDF**.

#### Request (multipart)

- **Content-Type**: `multipart/form-data`
- **Form-Field**: `file` (PDF)
- **Headers**: `Authorization: Bearer <token>`

Beispiel:

```bash
curl -fsS \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -X POST \
  -F "file=@in.pdf;type=application/pdf" \
  http://localhost:3296/validate_pdfa
```

#### Request (raw)

- **Content-Type**: `application/pdf`
- Body enthält das PDF

#### Response `200` (PDF/A konform)

```json
{ "ok": true, "returncode": 0, "verapdf": { "...": "full report" } }
```

#### Response `422` (nicht konform / Parse-Fehler)

```json
{ "ok": false, "returncode": 7, "verapdf": { "...": "full report" } }
```

Hinweis: Das Feld `verapdf` enthält den **vollen veraPDF JSON-Report** (`--format json`).

---

### POST `/convert_pdfa3`

Konvertiert ein PDF nach PDF/A-3 via Ghostscript.

#### Request (multipart)

- **Content-Type**: `multipart/form-data`
- **Form-Field**: `file` (PDF)
- **Headers**: `Authorization: Bearer <token>`

Beispiel:

```bash
curl -fsS \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -X POST \
  -F "file=@in.pdf;type=application/pdf" \
  http://localhost:3296/convert_pdfa3 \
  -o output_pdfa3.pdf
```

#### Request (raw)

- **Content-Type**: `application/pdf`
- Body enthält das PDF

#### Response `200`

- `application/pdf` (Binary), Downloadname `output_pdfa3.pdf`

---

### POST `/embed_xml`

Betttet eine XML-Rechnung in ein PDF ein (ZUGFeRD/Factur-X), via Mustang-CLI `--action combine`.

#### Request

- **Content-Type**: `multipart/form-data`
- **Form-Fields**:
  - `pdf_file` (PDF)
  - `xml_file` (XML)
- **Headers**: `Authorization: Bearer <token>`

#### Query-Parameter

- `format`: `zf` (ZUGFeRD) oder `fx` (Factur-X) — Default: `zf`
- `version`: `1` oder `2` — Default: `2`
- `profile`: z.B. `XRechnung`, `EN16931`, `BASIC`, … — Default: `XRechnung`

Beispiel:

```bash
curl -fsS \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -X POST \
  -F "pdf_file=@in.pdf;type=application/pdf" \
  -F "xml_file=@invoice.xml;type=application/xml" \
  "http://localhost:3296/embed_xml?format=zf&version=2&profile=XRechnung" \
  -o zugferd.pdf
```

#### Response `200`

- `application/pdf` (Binary), Downloadname enthält `format/version/profile`

---

### POST `/generate`

Interner/experimenteller Endpoint (bestehend): erzeugt aus Request-Body eine Datei über die Mustang-CLI Aktion `generate`.

#### Request

- **Content-Type**: beliebig (Body wird als Bytes übernommen)
- **Headers**: `Authorization: Bearer <token>`

#### Response

- `image/png`

Hinweis: Dieser Endpoint hängt von der CLI-Unterstützung ab und ist nicht Bestandteil des Standard-Workflows für ZUGFeRD/XRechnung.

---

### n8n Hinweise

#### Auth Header

- Header setzen: `Authorization` → `Bearer <dein_token>`

#### Form-Field Namen

- Für `multipart/form-data` muss der Feldname exakt passen:
  - `/validate` → `file`
  - `/convert_pdfa3` → `file`
  - `/embed_xml` → `pdf_file` und `xml_file`


