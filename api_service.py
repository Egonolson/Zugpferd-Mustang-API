from flask import Flask, request, send_file, abort, jsonify
import subprocess
import tempfile
import os
import logging
import xml.etree.ElementTree as ET
import hmac
from typing import Optional

app = Flask(__name__)

# Konfiguriere den Flask Logger (wie zuvor)
app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)
app.logger.propagate = False

ICC_PROFILE_PATH = '/opt/mustang/sRGB.icc' # Wird für diesen Endpunkt nicht direkt verwendet, aber global definiert
# Stable symlink created in Dockerfile (points to the actual versioned jar)
MUSTANG_CLI_JAR = '/opt/mustang/Mustang-CLI.jar'
MUSTANG_TAG_PATH = '/opt/mustang/mustang_tag.txt'
MUSTANG_HELP_PATH = '/opt/mustang/mustang_help.txt'

def _safe_read_text(path: str, max_bytes: int = 32_000) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes).strip()
    except FileNotFoundError:
        return None
    except OSError as e:
        app.logger.warning(f"Could not read {path}: {e}")
        return None

def _run_version_cmd(cmd: list[str], timeout: int = 3) -> Optional[str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        # Some tools (java -version) print to stderr
        merged = "\n".join([x for x in [out, err] if x])
        return merged if merged else None
    except Exception as e:
        app.logger.warning(f"Version cmd failed ({cmd}): {e}")
        return None

def _try_parse_json(text: str) -> Optional[dict]:
    try:
        import json
        return json.loads(text)
    except Exception:
        return None

# ───── Auth (Bearer Token) ─────
API_BEARER_TOKEN = os.environ.get("API_BEARER_TOKEN")
if not API_BEARER_TOKEN:
    # Hard fail: Service is intended to be publicly reachable.
    raise RuntimeError("API_BEARER_TOKEN is not set. Refusing to start.")

def _is_authorized(auth_header: Optional[str]) -> bool:
    if not auth_header:
        return False
    if not auth_header.startswith("Bearer "):
        return False
    provided = auth_header[len("Bearer "):].strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, API_BEARER_TOKEN)

@app.before_request
def require_bearer_token():
    auth = request.headers.get("Authorization")
    if not _is_authorized(auth):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

# ───── Healthcheck ─────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"ok": True, "status": "healthy"}), 200

@app.route('/version', methods=['GET'])
def version():
    """
    Returns runtime version information for debugging/compliance:
    - Mustang tag used during build
    - Java runtime version
    - Ghostscript version
    - veraPDF CLI version (if installed)
    """
    return jsonify({
        "ok": True,
        "mustang": {
            "tag": _safe_read_text(MUSTANG_TAG_PATH),
            "helpUsageLine": (_safe_read_text(MUSTANG_HELP_PATH) or "").splitlines()[0:1]
        },
        "java": {
            "version": _run_version_cmd(["java", "-version"])
        },
        "ghostscript": {
            "version": _run_version_cmd(["gs", "--version"])
        },
        "verapdf": {
            "version": _run_version_cmd(["verapdf", "--version"]),
            "helpUsageLine": (_run_version_cmd(["verapdf", "--help"], timeout=2) or "").splitlines()[0:1]
        }
    }), 200

def _tail(text: str, max_len: int = 8000) -> str:
    if not text:
        return ""
    return text[-max_len:] if len(text) > max_len else text

def _extract_validation_xml(text: str) -> Optional[str]:
    """
    Mustang CLI prints an XML report to stdout, but may also emit log lines before/after.
    We extract the first XML declaration and the last closing </validation> tag.
    """
    if not text:
        return None
    start = text.find("<?xml")
    if start < 0:
        return None
    end = text.rfind("</validation>")
    if end < 0 or end <= start:
        return None
    end += len("</validation>")
    return text[start:end]

def _parse_mustang_validation_report(xml_report: str) -> dict:
    root = ET.fromstring(xml_report)

    # Prefer the summary inside <xml>, fall back to the top-level summary
    summary_el = root.find("./xml/summary") or root.find("./summary") or root.find(".//summary")
    status = summary_el.get("status") if summary_el is not None else None

    findings = []
    # Findings can appear under <xml><messages> and/or top-level <messages>
    for path in ("./xml/messages", "./messages"):
        msgs = root.find(path)
        if msgs is None:
            continue
        for item in list(msgs):
            findings.append({
                "tag": item.tag,
                "attributes": dict(item.attrib),
                "text": (item.text or "").strip()
            })

    return {
        "filename": root.get("filename"),
        "datetime": root.get("datetime"),
        "status": status,
        "findings": findings
    }

# ───── MustangCLI-Endpunkt (Diagrammerstellung - wie zuvor) ─────
@app.route('/generate', methods=['POST'])
def generate():
    java_src = request.data
    if not java_src:
        app.logger.error("MustangCLI /generate: Keine Daten im Request Body.")
        abort(400, "Keine Daten im Request Body für /generate.")

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'Input.java')
        out = os.path.join(tmp, 'diagram.png')
        with open(src, 'wb') as f:
            f.write(java_src)

        if os.path.getsize(src) == 0:
            app.logger.error("MustangCLI /generate: Geschriebene Input.java Datei ist leer.")
            abort(500, "Temporäre Input.java Datei ist leer.")

        # Annahme: Die 'generate'-Aktion von MustangCLI hat eine andere Syntax
        cmd = ['java', '-jar', MUSTANG_CLI_JAR, 'generate', src, '--output', out]
        app.logger.info(f"MustangCLI /generate: Führe Befehl aus: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=True, timeout=60, capture_output=True, text=True)
            app.logger.info(f"MustangCLI /generate STDOUT: {result.stdout}")
            if result.stderr:
                app.logger.info(f"MustangCLI /generate STDERR: {result.stderr}")
        except subprocess.CalledProcessError as e:
            error_message = f"MustangCLI-Fehler (Code {e.returncode}): {e}\nBefehl: {' '.join(e.cmd)}\nStdout: {e.stdout}\nStderr: {e.stderr}"
            app.logger.error(f"MustangCLI /generate Fehler: {error_message}")
            abort(500, error_message)
        except subprocess.TimeoutExpired as e:
            error_message = f"MustangCLI Timeout: {e}\nBefehl: {' '.join(e.cmd)}\nStdout: {e.stdout}\nStderr: {e.stderr}"
            app.logger.error(f"MustangCLI /generate Timeout: {error_message}")
            abort(500, error_message)

        if not os.path.exists(out) or os.path.getsize(out) == 0:
            app.logger.error("MustangCLI /generate: Ausgabedatei wurde nicht erstellt oder ist leer.")
            abort(500, "MustangCLI Ausgabedatei wurde nicht erstellt oder ist leer.")
        return send_file(out, mimetype='image/png')

# ───── PDF → PDF/A-3-Konvertierung (Ghostscript - wie zuvor) ─────
@app.route('/convert_pdfa3', methods=['POST'])
def convert_pdfa3():
    ctype = request.content_type or ''
    pdf_data = None

    if ctype.startswith('multipart/form-data'):
        if 'file' not in request.files:
            app.logger.error("PDF/A-3 /convert_pdfa3: Kein File-Feld 'file'.")
            abort(400, "Kein File-Feld 'file' gefunden")
        pdf_file_storage = request.files['file']
        pdf_data = pdf_file_storage.read()
        if not pdf_data:
            app.logger.error("PDF/A-3 /convert_pdfa3: Hochgeladene PDF ist leer.")
            abort(400, "Hochgeladene PDF-Datei ist leer.")
    elif ctype == 'application/pdf':
        pdf_data = request.get_data()
        if not pdf_data:
            app.logger.error("PDF/A-3 /convert_pdfa3: Gesendete PDF-Daten sind leer.")
            abort(400, "Gesendete PDF-Daten sind leer.")
    else:
        app.logger.error(f"PDF/A-3 /convert_pdfa3: Ungültiger CT: {ctype}")
        abort(400, f"Content-Type muss application/pdf oder multipart/form-data sein, war aber '{ctype}'")

    with tempfile.TemporaryDirectory() as tmp:
        inp = os.path.join(tmp, 'in.pdf')
        out = os.path.join(tmp, 'out_pdfa3.pdf')
        with open(inp, 'wb') as f:
            f.write(pdf_data)
        if os.path.getsize(inp) == 0:
            abort(500, "Temporäre Eingabe-PDF ist leer.")
        
        # ICC Profil Pfad prüfen, aber nur wenn er nicht leer ist
        # if ICC_PROFILE_PATH and not os.path.exists(ICC_PROFILE_PATH):
        #     error_message = f"ICC-Profil nicht gefunden: {ICC_PROFILE_PATH}"
        #     app.logger.error(error_message)
        #     abort(500, error_message)

        gs_cmd = [
            'gs', '-dPDFA=3', '-dPDFACompatibilityPolicy=1', '-dBATCH',
            '-dNOPAUSE', '-sDEVICE=pdfwrite', '-dEmbedAllFonts=true',
            '-dSubsetFonts=true', '-sProcessColorModel=DeviceRGB',
            # Wenn Sie das ICC-Profil Problem gelöst haben, können Sie es wieder einkommentieren:
            # f'-sOutputICCProfile={ICC_PROFILE_PATH}',
            f'-sOutputFile={out}', inp
        ]
        app.logger.info(f"Ghostscript /convert_pdfa3: Befehl: {' '.join(gs_cmd)}")
        try:
            result = subprocess.run(gs_cmd, check=True, timeout=120, capture_output=True, text=True)
            if result.stdout: app.logger.info(f"GS STDOUT: {result.stdout}")
            if result.stderr: app.logger.info(f"GS STDERR: {result.stderr}")
        except subprocess.CalledProcessError as e:
            error_message = f"GS-Fehler (Code {e.returncode}): {e}\nBefehl: {' '.join(e.cmd)}\nStdout: {e.stdout}\nStderr: {e.stderr}"
            app.logger.error(error_message)
            abort(500, error_message)
        except subprocess.TimeoutExpired as e:
            error_message = f"GS Timeout: {e}\nBefehl: {' '.join(e.cmd)}\nStdout: {e.stdout}\nStderr: {e.stderr}"
            app.logger.error(error_message)
            abort(500, error_message)
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            abort(500, "GS Ausgabedatei nicht erstellt/leer.")
        return send_file(out, mimetype='application/pdf', as_attachment=True, download_name='output_pdfa3.pdf')

# ───── Endpunkt: XML in PDF einbetten (ZUGFeRD/Factur-X mit MustangCLI) - ANGEPASST ─────
@app.route('/embed_xml', methods=['POST'])
def embed_xml():
    if 'pdf_file' not in request.files or 'xml_file' not in request.files:
        app.logger.error("MustangCLI /embed_xml: Fehlende Dateien. 'pdf_file' und 'xml_file' werden benötigt.")
        abort(400, "Fehlende Dateien: 'pdf_file' und 'xml_file' werden benötigt.")

    pdf_file_storage = request.files['pdf_file']
    xml_file_storage = request.files['xml_file']

    # ZUGFeRD-spezifische Parameter aus der Query-String lesen
    # Die Default-Werte hier sollten mit der Hilfeausgabe der MustangCLI übereinstimmen
    # Hilfe sagt für --version <1|2>. '2' ist hier für ZUGFeRD 2.x.
    zugferd_version_param = request.args.get('version', '2') 
    
    # Sicherstellen, dass der Profilname exakt einem der gültigen Werte entspricht
    # z.B. "XRechnung", "EN16931", "COMFORT" etc. (Groß-/Kleinschreibung beachten!)
    # Als Default nehmen wir einen gängigen Wert für Deutschland.
    zugferd_profile_param = request.args.get('profile', 'XRechnung') 
    
    # Format-Parameter, 'zf' für ZUGFeRD oder 'fx' für Factur-X.
    zugferd_format_param = request.args.get('format', 'zf')

    pdf_data = pdf_file_storage.read()
    xml_data = xml_file_storage.read()

    if not pdf_data:
        app.logger.error("MustangCLI /embed_xml: Hochgeladene PDF-Datei ist leer.")
        abort(400, "Hochgeladene PDF-Datei ist leer.")
    if not xml_data:
        app.logger.error("MustangCLI /embed_xml: Hochgeladene XML-Datei ist leer.")
        abort(400, "Hochgeladene XML-Datei ist leer.")

    with tempfile.TemporaryDirectory() as tmp:
        temp_pdf_path = os.path.join(tmp, 'source.pdf')
        temp_xml_path = os.path.join(tmp, 'invoice.xml')
        temp_output_pdf_path = os.path.join(tmp, 'output_with_xml.pdf')

        with open(temp_pdf_path, 'wb') as f_pdf:
            f_pdf.write(pdf_data)
        with open(temp_xml_path, 'wb') as f_xml:
            f_xml.write(xml_data)

        # Angepasster MustangCLI Befehl basierend auf der --help Ausgabe
        mustang_cmd = [
            'java', '-jar', MUSTANG_CLI_JAR,
            '--action', 'combine',           # Korrekte Aktion
            '--source', temp_pdf_path,       # Eingabe-PDF
            '--source-xml', temp_xml_path,   # Eingabe-XML
            '--out', temp_output_pdf_path,   # Ausgabe-PDF
            '--format', zugferd_format_param,# z.B. 'zf' oder 'fx'
            '--version', zugferd_version_param, # z.B. '2'
            '--profile', zugferd_profile_param,  # z.B. 'XRechnung'
            # Avoid interactive prompts: pass a single empty attachment filename and disable prompting.
            '--attachments', '',
            '--no-additional-attachments'
        ]

        app.logger.info(f"MustangCLI /embed_xml: Führe Befehl aus: {' '.join(mustang_cmd)}")
        try:
            result = subprocess.run(mustang_cmd, check=True, timeout=120, capture_output=True, text=True)
            app.logger.info(f"MustangCLI /embed_xml STDOUT: {result.stdout}")
            if result.stderr:
                 app.logger.info(f"MustangCLI /embed_xml STDERR: {result.stderr}")
        except subprocess.CalledProcessError as e:
            error_message = f"MustangCLI Fehler (Code {e.returncode}) beim Einbetten: {e}\nBefehl: {' '.join(e.cmd)}\nStdout: {e.stdout}\nStderr: {e.stderr}"
            app.logger.error(error_message)
            abort(500, error_message)
        except subprocess.TimeoutExpired as e:
            error_message = f"MustangCLI Timeout beim Einbetten: {e}\nBefehl: {' '.join(e.cmd)}\nStdout: {e.stdout}\nStderr: {e.stderr}"
            app.logger.error(error_message)
            abort(500, error_message)
        
        if not os.path.exists(temp_output_pdf_path) or os.path.getsize(temp_output_pdf_path) == 0:
             app.logger.error("MustangCLI /embed_xml: Ausgabedatei wurde nicht erstellt oder ist leer.")
             abort(500, "MustangCLI Ausgabedatei mit eingebettetem XML wurde nicht erstellt oder ist leer.")
            
        download_filename = f"zugferd_fmt-{zugferd_format_param}_v{zugferd_version_param}_{zugferd_profile_param}.pdf"
        return send_file(temp_output_pdf_path, mimetype='application/pdf', as_attachment=True, download_name=download_filename)

@app.route('/validate', methods=['POST'])
def validate():
    """
    Erwartet:
      - multipart/form-data mit Feldname 'file' (empfohlen), ODER
      - application/pdf   (Rohdaten im Body), ODER
      - application/xml   (Rohdaten im Body)

    Ruft Mustang-CLI 'validate <datei>' auf und liefert stdout/stderr/returncode zurück.
    """
    ctype = request.content_type or ''
    uploaded_bytes = None
    filename = 'invoice'

    if ctype.startswith('multipart/form-data'):
        if 'file' not in request.files:
            app.logger.error("MustangCLI /validate: Kein File-Feld 'file'.")
            abort(400, "Kein File-Feld 'file' gefunden")
        f = request.files['file']
        uploaded_bytes = f.read()
        filename = f.filename or filename
    elif ctype in ('application/pdf', 'application/xml', 'text/xml'):
        uploaded_bytes = request.get_data()
        # Dateiendung für temp-Datei ableiten
        if ctype == 'application/pdf':
            filename += '.pdf'
        else:
            filename += '.xml'
    else:
        app.logger.error(f"MustangCLI /validate: Unsupported Content-Type: {ctype}")
        abort(400, f"Content-Type muss multipart/form-data, application/pdf oder application/xml sein (war: '{ctype}').")

    if not uploaded_bytes:
        abort(400, "Upload ist leer.")

    with tempfile.TemporaryDirectory() as tmp:
        # sinnvolle Endung, falls nicht vorhanden
        if not (filename.endswith('.pdf') or filename.endswith('.xml')):
            # einfacher Heuristik-Fallback
            filename += '.pdf' if uploaded_bytes[:5] == b'%PDF-' else '.xml'

        input_path = os.path.join(tmp, filename)
        with open(input_path, 'wb') as f:   
            f.write(uploaded_bytes)

        cmd = [
            "java", "-jar", MUSTANG_CLI_JAR,
            "--action", "validate",
            "--source", input_path,
            "--no-notices"
        ]
        app.logger.info(f"MustangCLI /validate: Führe Befehl aus: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            msg = f"MustangCLI /validate Timeout: {e}"
            app.logger.error(msg)
            return jsonify({"ok": False, "error": "timeout", "message": msg}), 504
        except FileNotFoundError:
            # Java nicht im PATH
            msg = "Java nicht gefunden. Ist openjdk-17-jre-headless installiert und 'java' im PATH?"
            app.logger.error(f"MustangCLI /validate: {msg}")
            return jsonify({"ok": False, "error": "java_not_found", "message": msg}), 500

        stdout = (result.stdout or "")
        stderr = (result.stderr or "")

        xml_report = _extract_validation_xml(stdout)
        if not xml_report:
            # Fallback: sometimes the report might be on stderr (rare)
            xml_report = _extract_validation_xml(stderr)

        if not xml_report:
            msg = "Konnte keinen Mustang-XML-Validierungsreport aus stdout/stderr extrahieren."
            app.logger.error(f"MustangCLI /validate: {msg}")
            return jsonify({
                "ok": False,
                "error": "no_xml_report",
                "message": msg,
                "returncode": result.returncode,
                "stdout_tail": _tail(stdout),
                "stderr_tail": _tail(stderr)
            }), 500

        try:
            report = _parse_mustang_validation_report(xml_report)
        except ET.ParseError as e:
            msg = f"XML-Report konnte nicht geparst werden: {e}"
            app.logger.error(f"MustangCLI /validate: {msg}")
            return jsonify({
                "ok": False,
                "error": "xml_parse_error",
                "message": msg,
                "returncode": result.returncode,
                "stdout_tail": _tail(stdout),
                "stderr_tail": _tail(stderr)
            }), 500

        status = (report.get("status") or "").lower()
        is_valid = (status == "valid")

        return jsonify({
            "ok": is_valid,
            "status": report.get("status"),
            "returncode": result.returncode,
            "report": {
                "filename": report.get("filename"),
                "datetime": report.get("datetime")
            },
            "findings": report.get("findings", [])
        }), (200 if is_valid else 422)

@app.route('/validate_pdfa', methods=['POST'])
def validate_pdfa():
    """
    PDF/A validation using veraPDF CLI.

    Accepts:
      - multipart/form-data with field 'file'
      - application/pdf raw body

    Returns:
      - 200 if PDF/A conform
      - 422 if not conform
      - full veraPDF report parsed as JSON (format=json)
    """
    ctype = request.content_type or ''
    pdf_data = None

    if ctype.startswith('multipart/form-data'):
        if 'file' not in request.files:
            abort(400, "Kein File-Feld 'file' gefunden")
        pdf_data = request.files['file'].read()
    elif ctype == 'application/pdf':
        pdf_data = request.get_data()
    else:
        abort(400, f"Content-Type muss application/pdf oder multipart/form-data sein (war: '{ctype}')")

    if not pdf_data:
        abort(400, "Upload ist leer.")

    with tempfile.TemporaryDirectory() as tmp:
        input_path = os.path.join(tmp, 'input.pdf')
        with open(input_path, 'wb') as f:
            f.write(pdf_data)

        # veraPDF JSON report to stdout
        cmd = [
            "verapdf",
            "--format", "json",
            input_path
        ]
        app.logger.info(f"veraPDF /validate_pdfa: Führe Befehl aus: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as e:
            msg = f"veraPDF Timeout: {e}"
            app.logger.error(msg)
            return jsonify({"ok": False, "error": "timeout", "message": msg}), 504
        except FileNotFoundError:
            msg = "veraPDF CLI nicht gefunden. Ist 'verapdf' im Container installiert?"
            app.logger.error(msg)
            return jsonify({"ok": False, "error": "verapdf_not_found", "message": msg}), 500

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        report_json = _try_parse_json(stdout)
        if report_json is None:
            # Some versions might write to stderr; try that as fallback
            report_json = _try_parse_json(stderr)

        if report_json is None:
            msg = "veraPDF Report konnte nicht als JSON geparst werden."
            app.logger.error(f"veraPDF /validate_pdfa: {msg}")
            return jsonify({
                "ok": False,
                "error": "report_parse_error",
                "message": msg,
                "returncode": result.returncode,
                "stdout_tail": _tail(stdout),
                "stderr_tail": _tail(stderr)
            }), 500

        # Determine overall validity: be defensive with schema differences
        ok = False
        try:
            report = report_json.get("report", report_json)
            jobs = report.get("jobs") or []
            if jobs and isinstance(jobs, list):
                vr = jobs[0].get("validationResult")
                if isinstance(vr, dict) and "isCompliant" in vr:
                    ok = bool(vr.get("isCompliant"))
                else:
                    # If validationResult is absent, fall back to batch summary counts
                    vs = (report.get("batchSummary") or {}).get("validationSummary") or {}
                    total = vs.get("totalJobCount")
                    compliant = vs.get("compliantPdfaCount")
                    failed = vs.get("failedJobCount")
                    parse_failed = (report.get("batchSummary") or {}).get("failedParsingJobs")
                    if total == 1:
                        ok = (compliant == 1) and (failed in (0, None)) and (parse_failed in (0, None))
        except Exception:
            ok = False

        return jsonify({
            "ok": ok,
            "returncode": result.returncode,
            "verapdf": report_json
        }), (200 if ok else 422)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)