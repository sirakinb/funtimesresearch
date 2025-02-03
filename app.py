from flask import Flask, request, jsonify, render_template, Response
import os
from dotenv import load_dotenv
import requests
from flask_cors import CORS
import logging
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure retry strategy
retry_strategy = Retry(
    total=3,  # number of retries
    backoff_factor=1,  # wait 1, 2, 4 seconds between retries
    status_forcelist=[429, 500, 502, 503, 504]  # status codes to retry on
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

API_KEY = "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"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

# Model configurations
MODELS = {
    "pro": {
        "name": "sonar-pro",  # 200k context length, 8k output limit
        "timeout": 30,  # 30 second timeout
        "max_tokens": 8192,
        "system_prompt": "You are a helpful search assistant. Provide information in plain text only. Use simple paragraphs. For bullet points, use a simple dash and space. For section titles, write them in plain text followed by a colon."
    },
    "reasoning": {
        "name": "sonar-reasoning",  # 127k context length, includes Chain of Thought
        "timeout": 60,  # 60 second timeout for CoT processing
        "max_tokens": 4096,
        "system_prompt": "You are a helpful search assistant. First, explain your chain of thought in analyzing the query, wrapping it in <think> tags. Then, provide your final answer in a clear, organized format. Use simple paragraphs for main text. Use dashes (-) for bullet points. Use clear headings followed by a colon. Do not use markdown formatting."
    }
}

# Predefined Make.com webhook URL
MAKE_WEBHOOK_URL = "https://hook.us2.make.com/jt9nict16gd1p893oklj5ej54hnwk824"

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
        model_type = data.get('model', 'pro')  # Default to pro if not specified
        logger.info(f"Received search query: {query} with model: {model_type}")
        
        if not query:
            logger.error("No query provided")
            return jsonify({"error": "Query is required"}), 400

        # Log API key presence (without revealing the key)
        logger.info(f"API Key configured: {'Yes' if API_KEY else 'No'}")
        
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Get model configuration
        model_config = MODELS.get(model_type, MODELS['pro'])
        logger.info(f"Using model configuration: {model_config['name']}")
        
        # Set system prompt based on model type
        system_prompt = model_config.get('system_prompt', "You are a helpful search assistant. Provide information in plain text only. Use simple paragraphs. For bullet points, use a simple dash and space. For section titles, write them in plain text followed by a colon.")
        
        payload = {
            "model": model_config['name'],
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            "max_tokens": model_config['max_tokens'],
            "temperature": 0.2,
            "top_p": 0.9,
            "stream": True
        }

        logger.debug(f"Sending request to Perplexity API with payload: {payload}")
        
        def generate():
            try:
                # Log the full request details (except API key)
                logger.info(f"Making request to: {PERPLEXITY_URL}")
                logger.info(f"Request headers (sanitized): {{'Accept': '{headers['Accept']}', 'Content-Type': '{headers['Content-Type']}'}}")
                
                # Use session with retry logic and model-specific timeout
                with http.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=model_config['timeout'], stream=True) as response:
                    logger.info(f"Initial response status: {response.status_code}")
                    response.raise_for_status()
                    
                    accumulated_text = ""
                    citations = []
                    
                    for line in response.iter_lines():
                        if line:
                            line = line.decode('utf-8')
                            if line.startswith('data: '):
                                try:
                                    json_str = line[6:]  # Remove 'data: ' prefix
                                    if json_str.strip() == '[DONE]':
                                        logger.info("Stream completed successfully")
                                        break
                                    
                                    chunk = json.loads(json_str)
                                    if chunk.get('citations'):
                                        citations = chunk['citations']
                                    
                                    if chunk['choices'][0].get('delta', {}).get('content'):
                                        text_chunk = chunk['choices'][0]['delta']['content']
                                        accumulated_text += text_chunk
                                        
                                        # Strip markdown from the chunk
                                        clean_chunk = strip_markdown(text_chunk)
                                        
                                        yield json.dumps({
                                            'chunk': clean_chunk,
                                            'citations': citations if citations else []
                                        }) + '\n'
                                        
                                except json.JSONDecodeError as e:
                                    logger.error(f"JSON decode error: {str(e)} for line: {line}")
                                    continue
                    
                    # Send final accumulated citations if any
                    if citations:
                        yield json.dumps({
                            'chunk': '',
                            'citations': citations,
                            'done': True
                        }) + '\n'
                    
            except requests.exceptions.Timeout as e:
                logger.error(f"Request timeout: {str(e)}")
                yield json.dumps({
                    'error': 'Request timed out. Please try again.'
                }) + '\n'
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {str(e)}")
                yield json.dumps({
                    'error': f'API request failed: {str(e)}'
                }) + '\n'
            except Exception as e:
                logger.error(f"Unexpected streaming error: {str(e)}")
                yield json.dumps({
                    'error': str(e)
                }) + '\n'

        return Response(generate(), mimetype='text/event-stream')
        
    except Exception as e:
        logger.error(f"Setup error: {str(e)}", exc_info=True)
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
    app.run(debug=True, port=5001, host='0.0.0.0') 