from google import genai
from flask import Flask, render_template, request, jsonify, send_file
import io
import pdfkit
import traceback
import os


# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
client = genai.Client(api_key=API_KEY) if API_KEY else None
MODEL_NAME = "gemini-flash-lite-latest"

app = Flask(__name__)

# Configure PDFKit paths based on OS
WKHTMLTOPDF_PATH = None
if os.name == 'posix':  # Linux/Mac
    WKHTMLTOPDF_PATH = '/usr/bin/wkhtmltopdf'
elif os.name == 'nt':  # Windows
    WKHTMLTOPDF_PATH = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'

# Verify wkhtmltopdf installation
try:
    config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
    test_pdf = pdfkit.from_string('<html><body><h1>Test</h1></body></html>', False, configuration=config)
except Exception as e:
    print(f"wkhtmltopdf verification failed: {str(e)}")
    WKHTMLTOPDF_PATH = None


# --- Routes ---
@app.route("/")
def index():
    """Home page - redirects to resume builder"""
    return render_template("resume.html")


@app.route('/resume')
def resume():
    return render_template('resume.html')


@app.route("/generate_ai_content", methods=["POST"])
def generate_ai_content():
    try:
        if client is None:
            return jsonify({"error": "Gemini API key is not configured."}), 503

        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({"error": "Prompt is required"}), 400

        prompt = data['prompt']
        app.logger.info(f"Generating content for prompt length: {len(prompt)}")
        
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        
        if not response.text:
            return jsonify({"error": "Model returned empty response"}), 500

        cleaned_text = response.text.replace("*", "").replace("#", "")
        return jsonify({"text": cleaned_text})

    except Exception as e:
        error_msg = str(e)
        app.logger.error(f"AI Generation Error: {error_msg}")
        traceback.print_exc()
        
        # Check if it's a quota error to give a better message
        if "429" in error_msg or "quota" in error_msg.lower():
            return jsonify({"error": "API Quota Exceeded. Please try again later or use a different API key.", "raw_error": error_msg}), 429
            
        return jsonify({"error": error_msg}), 500


@app.route('/download_pdf', methods=['POST'])
def download_pdf():
    try:
        data = request.get_json()
        if not data or 'html_content' not in data:
            return jsonify({'error': 'HTML content is required'}), 400

        # Create PDF configuration
        if not WKHTMLTOPDF_PATH:
            return jsonify({'error': 'wkhtmltopdf not properly installed or configured'}), 500

        options = {
            'page-size': 'A4',
            'margin-top': '0.3in',
            'margin-right': '0.3in',
            'margin-bottom': '0.3in',
            'margin-left': '0.3in',
            'encoding': "UTF-8",
            'no-outline': None
        }

        config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
        pdf_bytes = pdfkit.from_string(
            data['html_content'],
            False,
            options=options,
            configuration=config
        )

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='resume.pdf'
        )

    except Exception as e:
        app.logger.error(f"PDF Generation Error: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
