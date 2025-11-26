from flask import Flask, request, jsonify
import openai
from openai import OpenAI
from flask_cors import CORS
import math
import requests
import os
import json
import re
from typing import List, Dict, Any
from groq import Groq

app = Flask(__name__)
CORS(app)

# Groq API Configuration
openai.api_key = ""
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY_PATH = os.path.join(BASE_DIR, "../groq_api_key.txt")

if os.path.exists(API_KEY_PATH):
    with open(API_KEY_PATH, "r", encoding="utf-8") as f:
        openai.api_key = f.read().strip()
else:
    print(f"Warning: {API_KEY_PATH} not found. Groq API features will not work.")

openai.api_base = "https://api.groq.com/openai/v1"
MODEL_NAME = "llama3-70b-8192"
MODEL_NAME = "llama-3.1-8b-instant"

# Initialize new OpenAI client (compatible with openai>=1.0.0)
# Set environment variables to configure the client properly
os.environ["OPENAI_API_KEY"] = openai.api_key
os.environ["GROQ_API_KEY"] = openai.api_key
os.environ["OPENAI_API_BASE"] = openai.api_base
#client = OpenAI()


client = Groq(
    # This is the default and can be omitted
    api_key=os.environ.get("GROQ_API_KEY"),
)

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    """
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    """
    Perform reverse geocoding using Nominatim API.
    """
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "zoom": 18,
                "addressdetails": 1
            },
            headers={"User-Agent": "GeoLabelerBot/1.0"},
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        return {}
    except Exception as e:
        print(f"Nominatim error: {e}")
        return {}

def extract_json_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Extract JSON array from text, handling markdown code blocks.
    """
    try:
        # Try to find JSON array pattern
        match = re.search(r"\[\s*{.*}\s*\]", text, re.DOTALL)
        if match:
            json_text = match.group()
            return json.loads(json_text)
        
        # If no array found, try to parse the whole text if it looks like JSON
        return json.loads(text)
    except Exception as e:
        print(f"JSON extraction error: {e}")
        return []

@app.route('/autolabel', methods=['POST'])
def autolabel():
    """
    Endpoint to automatically label geographic points using Groq API.
    """
    try:
        points = request.get_json()
        if not points:
            return jsonify([])

        labeled = []

        for i, point in enumerate(points):
            lat, lng = point.get("lat"), point.get("lng")
            if lat is None or lng is None:
                continue

            geo_info = reverse_geocode(lat, lng)
            address = geo_info.get("display_name", "Unknown")
            road = geo_info.get("address", {}).get("road", "")
            category = geo_info.get("category", "")
            type_ = geo_info.get("type", "")

            labeled.append({
                "id": i + 1,
                "lat": lat,
                "lng": lng,
                "road": road,
                "address": address,
                "category": category,
                "type": type_,
                "labels": []
            })

        if not labeled:
            return jsonify([])

        # Prompt Construction
        prompt = (
            "You are an expert in geographic data labeling based on OpenStreetMap.\n"
            "Analyze the following location data and assign labels based on their characteristics.\n"
            "Labels to assign:\n"
            "- 'Urban area': Dense residential/commercial area\n"
            "- 'Intersection': Near an intersection (within 50m)\n"
            "- 'Bridge': On a bridge or road name contains 'bridge'/'橋'\n"
            "- 'Highway': Highway, motorway, freeway\n\n"
            "Output Format:\n"
            "Return ONLY a valid JSON array. Do not include any markdown formatting or explanation.\n"
            "Example: [{\"id\": 1, \"labels\": [\"Urban area\"]}]\n\n"
            "Data:\n"
        )

        for p in labeled:
            prompt += (
                f"ID: {p['id']}, lat: {p['lat']}, lng: {p['lng']}, "
                f"address: {p['address']}, road: {p['road']}, "
                f"category: {p['category']}, type: {p['type']}\n"
            )

        if not openai.api_key:
             print("Groq API key missing, skipping LLM labeling.")
             return jsonify(labeled)

        # Use new client API for chat completions
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs only JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )

        # Access reply text from the new response structure
        try:
            reply = response.choices[0].message.content
        except Exception:
            # Fallback to dict-style access if needed
            reply = response["choices"][0]["message"]["content"]
        print(f"LLM Reply: {reply[:100]}...") # Log first 100 chars

        parsed_results = extract_json_from_text(reply)
        
        # Map results back to labeled data
        result_map = {item['id']: item.get('labels', []) for item in parsed_results if 'id' in item}
        
        for p in labeled:
            if p['id'] in result_map:
                p['labels'] = result_map[p['id']]

        return jsonify(labeled)

    except Exception as e:
        print(f"Autolabel error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
