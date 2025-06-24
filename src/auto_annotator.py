from flask import Flask, request, jsonify
import openai
from flask_cors import CORS
import math
import requests
import os
import json
import re

app = Flask(__name__)
CORS(app)

# Groq API設定（外部ファイルからキー読み込み）
openai.api_key = ""
with open("../groq_api_key.txt", "r", encoding="utf-8") as f:
    openai.api_key = f.read().strip()

openai.api_base = "https://api.groq.com/openai/v1"
MODEL_NAME = "llama3-70b-8192"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def reverse_geocode(lat, lon):
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
            headers={"User-Agent": "GeoLabelerBot/1.0"}
        )
        if response.status_code == 200:
            return response.json()
        return {}
    except Exception as e:
        print("Nominatim error:", str(e))
        return {}

@app.route('/autolabel', methods=['POST'])
def autolabel():
    points = request.get_json()
    labeled = []

    for i, point in enumerate(points):
        lat, lng = point["lat"], point["lng"]
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

    # プロンプト構築
    prompt = (
        "以下の地点情報に対して、OpenStreetMapのデータや地図に基づいて、"
        "それぞれの地点がどのような特徴に該当するかを判定してください。\n"
        "付与すべきラベルは以下の通り：\n"
        "- 'Urban area': 市街地（住宅・商店・公共施設が密集）\n"
        "- 'Intersection': 交差点近傍（50m以内）\n"
        "- 'Bridge': 橋の上、または道路名にbridge/橋が含まれる\n"
        "- 'Highway': 高速道路・専用道路・Freewayなど\n\n"
        "各地点の出力は以下の形式でお願いします：\n"
        "地点情報：\n"
        "出力は **Python辞書** ではなく **JSON配列形式** にしてください（例：[{\"id\": 1, \"labels\": [\"Urban area\"]}])。\n"
    )

    for p in labeled:
        prompt += (
            f"ID: {p['id']}, lat: {p['lat']}, lng: {p['lng']}, "
            f"address: {p['address']}, road: {p['road']}, "
            f"category: {p['category']}, type: {p['type']}\n"
        )

    response = openai.ChatCompletion.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are an expert in geographic data labeling based on OpenStreetMap."},
            {"role": "user", "content": prompt}
        ]
    )

    reply = response["choices"][0]["message"]["content"]

    try:
        # 正規表現で最初の [ から最後の ] までを抽出（JSON部分だけ）
        json_text = re.search(r"\[\s*{.*}\s*\]", reply, re.DOTALL).group()
        parsed = json.loads(json_text)
        for r in parsed:
            for p in labeled:
                if p["id"] == r["id"]:
                    p["labels"] = r["labels"]
    except Exception as e:
        print("LLM結果の解析に失敗:", str(e))
    
    return jsonify(labeled)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
