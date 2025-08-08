import random
import string
import logging
import os
import time
from redis import Redis
from flask import Flask, jsonify, request

# --- Configuration ---
SECRET_REFRESH_INTERVAL_SECONDS = 60

# --- Vercel KV (Redis) Setup ---
# The app will be stateless. State is stored in Vercel KV.
try:
    kv = Redis.from_url(os.environ.get("KV_URL"))
except Exception as e:
    logging.error(f"Could not connect to Vercel KV (Redis): {e}")
    kv = None

app = Flask(__name__)

def get_or_refresh_secret():
    """
    Checks if the secret is stale and refreshes it if needed.
    This replaces the background thread for a serverless environment.
    """
    if not kv:
        return "KV_NOT_AVAILABLE"
        
    last_update_time = kv.get('secret_timestamp') or 0
    is_stale = (time.time() - float(last_update_time)) > SECRET_REFRESH_INTERVAL_SECONDS

    if is_stale:
        logging.info("Secret is stale, generating a new one.")
        new_secret = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # Use a pipeline for atomic operations
        pipe = kv.pipeline()
        pipe.set('secret_code', new_secret)
        pipe.set('secret_timestamp', time.time())
        pipe.delete('attendance_log') # Clear the attendance log
        pipe.execute()
        return new_secret
    else:
        return kv.get('secret_code').decode('utf-8')

@app.route('/api/get-current-code', methods=['GET'])
def get_current_code():
    """The endpoint for students to fetch the current secret code."""
    secret = get_or_refresh_secret()
    return jsonify({"secret_code": secret})

@app.route('/api/verify-attendance', methods=['POST'])
def verify_attendance():
    """The endpoint for students to submit the code and mark themselves present."""
    data = request.get_json()
    student_id = data.get('student_id')
    submitted_code = data.get('code')

    if not student_id or not submitted_code:
        return jsonify({"status": "FAILED", "message": "Missing student_id or code."}), 400

    current_secret = kv.get('secret_code').decode('utf-8')

    if submitted_code == current_secret:
        kv.sadd('attendance_log', student_id) # Add student to a set in Redis
        return jsonify({"status": "SUCCESS", "message": f"Welcome, {student_id}. Your attendance is confirmed."})
    else:
        return jsonify({"status": "FAILED", "message": "Incorrect or expired code. Proxy attempt detected?"}), 403

@app.route('/api/get-attendance-log', methods=['GET'])
def get_attendance_log():
    """An endpoint for the 'professor' to see who is present."""
    # Fetch all members of the set from Redis and decode them from bytes to strings
    present_students_bytes = kv.smembers('attendance_log')
    present_students = sorted([s.decode('utf-8') for s in present_students_bytes])
    return jsonify({"present_students": present_students})

@app.route('/')
def index():
    """A simple welcome page to show the server is running and list endpoints."""
    return jsonify({
        "status": "online",
        "message": "Welcome to the Vercel-hosted TrueAttendance Simulator API!",
        "kv_status": "connected" if kv else "disconnected",
        "endpoints": {
            "GET /api/get-current-code": "Fetch the current secret code for attendance.",
            "POST /api/verify-attendance": "Submit a student_id and code to be marked present.",
            "GET /api/get-attendance-log": "View the list of students currently marked as present."
        }
    })