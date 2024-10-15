# server.py
import os
from dotenv import load_dotenv
import uuid
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from statistics import mean
from redis import Redis
import json

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(24)

redis_url = os.environ.get('REDIS_URL')
try:
    redis_client = Redis.from_url(redis_url)
    redis_client.ping() 
except ConnectionError:
    print("Warning: Could not connect to Redis.")

socketio = SocketIO(app, async_mode='eventlet')

rooms_key = "rooms" 

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_room', methods=['POST'])
def create_room():
    room_id = str(uuid.uuid4())
    name = request.form['name']
    session['name'] = name
    session['room'] = room_id

    room_data = {
        'users': {},
        'votes': {}
    }
    redis_client.set(room_id, json.dumps(room_data))
    return jsonify({'room': room_id})

@app.route('/room/<room_id>', methods=['GET', 'POST'])
def room(room_id):
    if request.method == 'POST':
        name = request.form['name']
        if not name:
            return render_template('join.html', room=room_id, error="Name is required.")
        session['name'] = name
        session['room'] = room_id
        if not redis_client.exists(room_id):
            room_data = {
                'users': {},
                'votes': {}
            }
            redis_client.set(room_id, json.dumps(room_data))
        return redirect(url_for('room', room_id=room_id))
    
    name = session.get('name')
    room = session.get('room')

    if room == room_id and name:
        return render_template('room.html', room=room_id, name=name)
    else:
        if redis_client.exists(room_id):
            return render_template('join.html', room=room_id)
        else:
            return render_template('join.html', room=room_id, error="Room does not exist.")

@socketio.on('join')
def on_join(data):
    room_id = data['room']
    name = data['name']
    join_room(room_id)
    
    room_data = redis_client.get(room_id)
    if room_data:
        room_data = json.loads(room_data)
    else:
        room_data = {'users': {}, 'votes': {}}
    
    room_data['users'][request.sid] = name
    redis_client.set(room_id, json.dumps(room_data))
    
    emit('user_joined', {'name': name}, room=room_id)
    emit('update_users', {'users': list(room_data['users'].values())}, room=room_id)

@socketio.on('leave')
def on_leave(data):
    room_id = data['room']
    leave_room(room_id)
    
    room_data = redis_client.get(room_id)
    if room_data:
        room_data = json.loads(room_data)
        if request.sid in room_data['users']:
            name = room_data['users'].pop(request.sid)
            redis_client.set(room_id, json.dumps(room_data))
            emit('user_left', {'name': name}, room=room_id)
            emit('update_users', {'users': list(room_data['users'].values())}, room=room_id)

@socketio.on('vote')
def on_vote(data):
    room_id = data['room']
    vote = data['vote']
    
    room_data = redis_client.get(room_id)
    if room_data:
        room_data = json.loads(room_data)
        name = room_data['users'].get(request.sid)
        if name:
            room_data['votes'][name] = vote
            redis_client.set(room_id, json.dumps(room_data))
            emit('vote_update', {'name': name, 'vote': vote}, room=room_id)

@socketio.on('reveal_votes')
def on_reveal_votes(data):
    room_id = data['room']
    
    room_data = redis_client.get(room_id)
    if room_data:
        room_data = json.loads(room_data)
        votes = room_data.get('votes', {})
        numeric_votes = [int(v) for v in votes.values() if isinstance(v, (int, str)) and str(v).isdigit()]
        average = round(mean(numeric_votes), 2) if numeric_votes else 0
        emit('votes_revealed', {'votes': votes, 'average': average}, room=room_id)

@socketio.on('reset_votes')
def on_reset_votes(data):
    room_id = data['room']
    
    room_data = redis_client.get(room_id)
    if room_data:
        room_data = json.loads(room_data)
        room_data['votes'] = {}
        redis_client.set(room_id, json.dumps(room_data))
        emit('votes_reset', room=room_id)

@socketio.on('disconnect')
def on_disconnect():
    for key in redis_client.scan_iter():
        room_id = key.decode('utf-8')
        room_data = redis_client.get(room_id)
        if room_data:
            room_data = json.loads(room_data)
            if request.sid in room_data['users']:
                name = room_data['users'].pop(request.sid)
                redis_client.set(room_id, json.dumps(room_data))
                emit('user_left', {'name': name}, room=room_id)
                emit('update_users', {'users': list(room_data['users'].values())}, room=room_id)
                break
            

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')
