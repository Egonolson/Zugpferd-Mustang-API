from flask import Flask, request, send_file, abort, jsonify
import subprocess
import tempfile
import os
import logging

app = Flask(__name__)

# Konfiguriere den Flask Logger (wie zuvor)
app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)
app.logger.propagate = False

ICC_PROFILE_PATH = '/opt/mustang/sRGB.icc' # Wird für diesen Endpunkt nicht direkt verwendet, aber global definiert
MUSTANG_CLI_JAR = '/opt/mustang/Mustang-CLI-2.16.4.jar' # Ihre Version

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
            '--attachments', '""' 
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)