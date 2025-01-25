from flask import Flask, request, jsonify, render_template
import os
from dotenv import load_dotenv
import requests
from flask_cors import CORS
import logging
import re

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

API_KEY = "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"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

# Predefined Make.com webhook URL
MAKE_WEBHOOK_URL = "https://hook.us2.make.com/q8wargi9oygw7qti14dz79yl9jh8v3sr"

def strip_markdown(text):
    # Remove bold/italic markdown
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\_\_(.+?)\_\_', r'\1', text)
    text = re.sub(r'\_(.+?)\_', r'\1', text)
    # Remove headers
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    return text

@app.route('/')
def home():
    return render_template('index.html', title='FunTimes Research')

@app.route('/search', methods=['POST'])
def search():
    try:
        data = request.json
        query = data.get('query')
        logger.info(f"Received search query: {query}")
        
        if not query:
            return jsonify({"error": "Query is required"}), 400

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "sonar",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful search assistant. Provide information in plain text only. Use simple paragraphs. For bullet points, use a simple dash and space. For section titles, write them in plain text followed by a colon."
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            "temperature": 0.2,
            "top_p": 0.9
        }

        logger.debug(f"Sending request to Perplexity API with payload: {payload}")
        response = requests.post(PERPLEXITY_URL, headers=headers, json=payload)
        
        # Log the response for debugging
        logger.debug(f"Perplexity API response status: {response.status_code}")
        logger.debug(f"Perplexity API response: {response.text}")
        
        response.raise_for_status()
        response_data = response.json()
        
        result = response_data['choices'][0]['message']['content']
        # Strip any markdown formatting from the result
        result = strip_markdown(result)
        citations = response_data.get('citations', [])
        
        return jsonify({
            "result": result,
            "citations": citations
        })
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({"error": f"API request failed: {str(e)}"}), 500
    except KeyError as e:
        logger.error(f"Response parsing error: {str(e)}")
        return jsonify({"error": "Invalid response format from API"}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/send-to-make', methods=['POST'])
def send_to_make():
    try:
        data = request.json
        search_result = data.get('result')
        citations = data.get('citations', [])  # Get citations from request
        
        if not search_result:
            return jsonify({"error": "Missing search result"}), 400
        
        response = requests.post(MAKE_WEBHOOK_URL, json={
            "search_result": search_result,
            "citations": citations  # Include citations in the payload
        })
        response.raise_for_status()
        return jsonify({"message": "Successfully sent to Make.com"})
    except Exception as e:
        logger.error(f"Make.com error: {str(e)}")
        return jsonify({"error": f"Failed to send to Make.com: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='127.0.0.1') 