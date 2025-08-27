from flask import Flask, jsonify
import os
import time
import json
from pull_data import get_data  # your existing script logic
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes and origins
CACHE_FILE = 'cached.json'
CACHE_DURATION = 3600  # seconds (1 hour)

@app.route('/data')
def return_data():
    if not os.path.exists(CACHE_FILE) or (time.time() - os.path.getmtime(CACHE_FILE)) > CACHE_DURATION:
        print("Running expensive script to update cache...")
        data = get_data()
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f)
    else:
        print("Using cached data.")
        with open(CACHE_FILE) as f:
            data = json.load(f)
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True)
