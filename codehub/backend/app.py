from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import os
import uuid
import re
import threading
import time
from werkzeug.utils import secure_filename
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

CORS(app, supports_credentials=True)

# Serve uploaded files
@app.route('/uploads/<path:folder>/<filename>')
def uploaded_file(folder, filename):
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], folder), filename)

# Create uploads directory
os.makedirs('uploads', exist_ok=True)
os.makedirs('uploads/images', exist_ok=True)
os.makedirs('uploads/videos', exist_ok=True)
os.makedirs('uploads/code', exist_ok=True)

# Data storage files
DATA_DIR = 'data'
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
POSTS_FILE = os.path.join(DATA_DIR, 'posts.json')
COMMENTS_FILE = os.path.join(DATA_DIR, 'comments.json')
CHATS_FILE = os.path.join(DATA_DIR, 'chats.json')
CHAT_MESSAGES_FILE = os.path.join(DATA_DIR, 'chat_messages.json')
NOTIFICATIONS_FILE = os.path.join(DATA_DIR, 'notifications.json')

# Load data from files
def load_data():
    global users, posts, comments, chats, chat_messages, notifications
    users = {}
    posts = []
    comments = defaultdict(list)
    chats = defaultdict(list)
    chat_messages = defaultdict(list)
    notifications = defaultdict(list)
    
    # Load users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users = json.load(f)
        except:
            users = {}
    
    # Load posts
    if os.path.exists(POSTS_FILE):
        try:
            with open(POSTS_FILE, 'r', encoding='utf-8') as f:
                posts = json.load(f)
        except:
            posts = []
    
    # Load comments
    if os.path.exists(COMMENTS_FILE):
        try:
            with open(COMMENTS_FILE, 'r', encoding='utf-8') as f:
                comments_data = json.load(f)
                comments = defaultdict(list, comments_data)
        except:
            comments = defaultdict(list)
    
    # Load chats
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, 'r', encoding='utf-8') as f:
                chats_data = json.load(f)
                chats = defaultdict(list, chats_data)
        except:
            chats = defaultdict(list)
    
    # Load chat messages
    if os.path.exists(CHAT_MESSAGES_FILE):
        try:
            with open(CHAT_MESSAGES_FILE, 'r', encoding='utf-8') as f:
                messages_data = json.load(f)
                chat_messages = defaultdict(list, messages_data)
        except:
            chat_messages = defaultdict(list)
    
    # Load notifications
    if os.path.exists(NOTIFICATIONS_FILE):
        try:
            with open(NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
                notifications_data = json.load(f)
                notifications = defaultdict(list, notifications_data)
        except:
            notifications = defaultdict(list)

def save_data():
    """Save all data to files"""
    # Save users
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    
    # Save posts
    with open(POSTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    
    # Save comments
    with open(COMMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(dict(comments), f, ensure_ascii=False, indent=2)
    
    # Save chats
    with open(CHATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(dict(chats), f, ensure_ascii=False, indent=2)
    
    # Save chat messages
    with open(CHAT_MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(dict(chat_messages), f, ensure_ascii=False, indent=2)
    
    # Save notifications
    with open(NOTIFICATIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(dict(notifications), f, ensure_ascii=False, indent=2)

# Initialize data
load_data()
user_sessions = {}  # For real-time updates

# Validation functions
def validate_username(username):
    """Validate username: 4-20 letters, latin only, no numbers at start, no special chars"""
    if not username:
        return False, "Username is required"
    if len(username) < 4:
        return False, "Username must be at least 4 characters"
    if len(username) > 20:
        return False, "Username must be at most 20 characters"
    if not username[0].isalpha():
        return False, "Username must start with a letter"
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "Username can only contain letters, numbers and underscores"
    if not re.match(r'^[a-zA-Z]', username):
        return False, "Username must start with a letter"
    # Check for Cyrillic
    if re.search(r'[а-яА-ЯёЁ]', username):
        return False, "Username cannot contain Russian letters"
    return True, ""

def validate_password(password):
    """Validate password: min 9 chars, 1 digit, 1 special char"""
    if not password:
        return False, "Password is required"
    if len(password) < 9:
        return False, "Password must be at least 9 characters"
    if not re.search(r'\d', password):
        return False, "Password must contain at least 1 digit"
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?]', password):
        return False, "Password must contain at least 1 special character"
    return True, ""

def validate_email(email):
    """Validate email format"""
    if not email:
        return False, "Email is required"
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, "Invalid email format"
    return True, ""

# Languages
LANGUAGES = {
    'javascript': 'JavaScript',
    'python': 'Python',
    'java': 'Java',
    'cpp': 'C++',
    'go': 'Go',
    'rust': 'Rust',
    'php': 'PHP',
    'ruby': 'Ruby',
    'typescript': 'TypeScript',
    'swift': 'Swift',
    'kotlin': 'Kotlin',
}

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    email = data.get('email', '').strip()
    language = data.get('language', 'javascript')
    name = data.get('name', username)
    
    # Validate username
    valid, error = validate_username(username)
    if not valid:
        return jsonify({'error': error}), 400
    
    # Validate password
    valid, error = validate_password(password)
    if not valid:
        return jsonify({'error': error}), 400
    
    # Validate email
    valid, error = validate_email(email)
    if not valid:
        return jsonify({'error': error}), 400
    
    if username in users:
        return jsonify({'error': 'Username already exists'}), 400
    
    user_id = str(uuid.uuid4())
    users[username] = {
        'id': user_id,
        'username': username,
        'name': name,
        'email': email,
        'password': password,  # В продакшене хешировать!
        'language': language,
        'avatar': None,
        'bio': '',
        'created_at': datetime.now().isoformat(),
        'followers': 0,
        'following': 0,
        'posts_count': 0,
        'theme': 'dark',
        'notifications': True,
        'show_code_preview': True
    }
    
    session['user_id'] = user_id
    session['username'] = username
    
    save_data()
    
    return jsonify({
        'success': True,
        'user': {
            'id': user_id,
            'username': username,
            'name': name,
            'language': language,
            'theme': 'dark'
        }
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if username not in users or users[username]['password'] != password:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    user = users[username]
    session['user_id'] = user['id']
    session['username'] = username
    
    save_data()
    
    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'name': user['name'],
            'language': user['language'],
            'avatar': user['avatar'],
            'bio': user['bio'],
            'theme': user.get('theme', 'dark')
        }
    })

@app.route('/api/logout', methods=['POST'])
def logout():
    if 'username' in session:
        username = session['username']
        if username in user_sessions:
            del user_sessions[username]
    session.clear()
    return jsonify({'success': True})

@app.route('/api/user', methods=['GET'])
def get_user():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    if username not in users:
        session.clear()
        return jsonify({'error': 'User not found'}), 404
    
    user = users[username]
    
    return jsonify({
        'id': user['id'],
        'username': user['username'],
        'name': user['name'],
        'language': user['language'],
        'avatar': user['avatar'],
        'bio': user['bio'],
        'followers': user['followers'],
        'following': user['following'],
        'posts_count': user['posts_count'],
        'theme': user.get('theme', 'dark')
    })

@app.route('/api/user/<username>', methods=['GET'])
def get_user_profile(username):
    """Get user profile by username"""
    if username not in users:
        return jsonify({'error': 'User not found'}), 404
    
    user = users[username]
    return jsonify({
        'id': user['id'],
        'username': user['username'],
        'name': user['name'],
        'avatar': user['avatar'],
        'bio': user['bio'],
        'language': user['language'],
        'followers': user['followers'],
        'following': user['following'],
        'posts_count': user['posts_count'],
        'created_at': user['created_at']
    })

@app.route('/api/user/update', methods=['POST'])
def update_user():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    data = request.json
    
    if 'name' in data:
        users[username]['name'] = data['name']
    if 'bio' in data:
        users[username]['bio'] = data['bio']
    if 'language' in data:
        users[username]['language'] = data['language']
    if 'avatar' in data:
        users[username]['avatar'] = data['avatar']
    
    save_data()
    
    return jsonify({'success': True, 'user': users[username]})

@app.route('/api/search/users', methods=['GET'])
def search_users():
    """Search users by username"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    query = request.args.get('q', '').strip().lower()
    if not query or len(query) < 2:
        return jsonify([])
    
    results = []
    for username, user in users.items():
        if query in username.lower() or query in user.get('name', '').lower():
            results.append({
                'username': username,
                'name': user['name'],
                'avatar': user['avatar']
            })
            if len(results) >= 20:  # Limit results
                break
    
    return jsonify(results)

@app.route('/api/posts', methods=['GET'])
def get_posts():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user_lang = users[username]['language']
    
    # Filter posts by user's language
    filtered_posts = []
    for post in sorted(posts, key=lambda x: x['created_at'], reverse=True):
        post_lang = post.get('language', 'javascript')
        if post_lang == user_lang:
            filtered_posts.append(post)
    
    return jsonify(filtered_posts)

@app.route('/api/posts', methods=['POST'])
def create_post():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user = users[username]
    
    data = request.json
    post_id = str(uuid.uuid4())
    
    post = {
        'id': post_id,
        'user_id': user['id'],
        'username': username,
        'name': user['name'],
        'avatar': user['avatar'],
        'content': data.get('content', ''),
        'language': user['language'],
        'files': data.get('files', []),
        'created_at': datetime.now().isoformat(),
        'likes': 0,
        'comments_count': 0,
        'liked_by': []
    }
    
    posts.append(post)
    users[username]['posts_count'] += 1
    save_data()
    
    # Notify all users for real-time update
    notify_users('new_post', post)
    
    return jsonify({'success': True, 'post': post})

@app.route('/api/posts/<post_id>', methods=['GET'])
def get_post(post_id):
    post = next((p for p in posts if p['id'] == post_id), None)
    if not post:
        return jsonify({'error': 'Post not found'}), 404
    
    return jsonify(post)

@app.route('/api/posts/<post_id>', methods=['PUT'])
def update_post(post_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    post = next((p for p in posts if p['id'] == post_id), None)
    
    if not post:
        return jsonify({'error': 'Post not found'}), 404
    
    if post['username'] != username:
        return jsonify({'error': 'Not authorized'}), 403
    
    data = request.json
    if 'content' in data:
        post['content'] = data['content']
    
    return jsonify({'success': True, 'post': post})

@app.route('/api/posts/<post_id>', methods=['DELETE'])
def delete_post(post_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    post = next((p for p in posts if p['id'] == post_id), None)
    
    if not post:
        return jsonify({'error': 'Post not found'}), 404
    
    if post['username'] != username:
        return jsonify({'error': 'Not authorized'}), 403
    
    posts.remove(post)
    users[username]['posts_count'] = max(0, users[username]['posts_count'] - 1)
    
    save_data()
    
    return jsonify({'success': True})

@app.route('/api/posts/<post_id>/comments', methods=['GET'])
def get_comments(post_id):
    post_comments = comments.get(post_id, [])
    return jsonify(post_comments)

@app.route('/api/posts/<post_id>/comments', methods=['POST'])
def add_comment(post_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user = users[username]
    data = request.json
    
    comment_id = str(uuid.uuid4())
    comment = {
        'id': comment_id,
        'post_id': post_id,
        'user_id': user['id'],
        'username': username,
        'name': user['name'],
        'avatar': user['avatar'],
        'content': data.get('content', ''),
        'parent_id': data.get('parent_id'),
        'files': data.get('files', []),
        'created_at': datetime.now().isoformat(),
        'likes': 0,
        'liked_by': []
    }
    
    if post_id not in comments:
        comments[post_id] = []
    comments[post_id].append(comment)
    
    # Update post comments count
    post = next((p for p in posts if p['id'] == post_id), None)
    if post:
        post['comments_count'] = len(comments[post_id])
    
    save_data()
    
    # Notify for real-time update
    notify_users('new_comment', {'post_id': post_id, 'comment': comment})
    
    return jsonify({'success': True, 'comment': comment})

@app.route('/api/posts/<post_id>/comments/<comment_id>/like', methods=['POST'])
def like_comment(post_id, comment_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    post_comments = comments.get(post_id, [])
    comment = next((c for c in post_comments if c['id'] == comment_id), None)
    
    if not comment:
        return jsonify({'error': 'Comment not found'}), 404
    
    if 'liked_by' not in comment:
        comment['liked_by'] = []
    
    if username in comment['liked_by']:
        comment['liked_by'].remove(username)
        comment['likes'] = max(0, comment.get('likes', 1) - 1)
    else:
        comment['liked_by'].append(username)
        comment['likes'] = comment.get('likes', 0) + 1
    
    return jsonify({
        'likes': comment['likes'],
        'liked': username in comment['liked_by']
    })

@app.route('/api/posts/<post_id>/like', methods=['POST'])
def like_post(post_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    post = next((p for p in posts if p['id'] == post_id), None)
    
    if not post:
        return jsonify({'error': 'Post not found'}), 404
    
    if username in post['liked_by']:
        post['liked_by'].remove(username)
        post['likes'] -= 1
    else:
        post['liked_by'].append(username)
        post['likes'] += 1
    
    # Notify for real-time update
    notify_users('post_liked', {'post_id': post_id, 'likes': post['likes'], 'liked': username in post['liked_by']})
    
    return jsonify({'likes': post['likes'], 'liked': username in post['liked_by']})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    filename = secure_filename(file.filename)
    file_id = str(uuid.uuid4())
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    # Determine file type
    if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
        folder = 'images'
    elif ext in ['mp4', 'webm', 'mov']:
        folder = 'videos'
    else:
        folder = 'code'
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], folder, f"{file_id}_{filename}")
    file.save(filepath)
    
    return jsonify({
        'success': True,
        'file': {
            'id': file_id,
            'filename': filename,
            'type': folder,
            'url': f'/uploads/{folder}/{file_id}_{filename}',
            'ext': ext
        }
    })

@app.route('/api/chats', methods=['GET'])
def get_chats():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user_chats = chats.get(username, [])
    
    # Update last message info
    for chat in user_chats:
        chat_id = chat['id']
        messages = chat_messages.get(chat_id, [])
        if messages:
            last_msg = messages[-1]
            chat['last_message'] = last_msg['text'][:50]
            chat['last_message_time'] = last_msg['timestamp']
    
    return jsonify(user_chats)

@app.route('/api/chats/<chat_id>/messages', methods=['GET'])
def get_chat_messages(chat_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    messages = chat_messages.get(chat_id, [])
    return jsonify(messages)

@app.route('/api/chats/<chat_id>/messages', methods=['POST'])
def send_chat_message(chat_id):
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user = users[username]
    data = request.json
    
    message = {
        'id': str(uuid.uuid4()),
        'from': username,
        'fromName': user['name'],
        'text': data.get('text', ''),
        'timestamp': datetime.now().isoformat(),
        'time': datetime.now().strftime('%H:%M')
    }
    
    if chat_id not in chat_messages:
        chat_messages[chat_id] = []
    
    chat_messages[chat_id].append(message)
    
    # Update chat last message
    for user_chats in chats.values():
        for chat in user_chats:
            if chat['id'] == chat_id:
                chat['last_message'] = message['text'][:50]
                chat['last_message_time'] = message['timestamp']
                break
    
    save_data()
    
    # Notify recipient
    usernames = chat_id.split('_')
    recipient = usernames[1] if usernames[0] == username else usernames[0]
    if recipient in users:
        add_notification(recipient, {
            'type': 'new_message',
            'from': username,
            'fromName': user['name'],
            'chat_id': chat_id,
            'message': message['text'][:50],
            'timestamp': message['timestamp']
        })
    
    return jsonify({'success': True, 'message': message})

@app.route('/api/chats', methods=['POST'])
def create_chat():
    """Create a new chat with a user"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    data = request.json
    other_username = data.get('username')
    
    if other_username not in users:
        return jsonify({'error': 'User not found'}), 404
    
    if other_username == username:
        return jsonify({'error': 'Cannot chat with yourself'}), 400
    
    # Create chat_id in sorted order
    usernames = sorted([username, other_username])
    chat_id = f"{usernames[0]}_{usernames[1]}"
    
    other_user = users[other_username]
    chat = {
        'id': chat_id,
        'username': other_username,
        'name': other_user['name'],
        'avatar': other_user['avatar'],
        'last_message': '',
        'last_message_time': datetime.now().isoformat(),
        'unread': 0
    }
    
    # Add to both users' chat lists
    if username not in chats:
        chats[username] = []
    if other_username not in chats:
        chats[other_username] = []
    
    # Check if chat exists
    existing = next((c for c in chats[username] if c['id'] == chat_id), None)
    if not existing:
        chats[username].append(chat)
        chats[other_username].append({
            'id': chat_id,
            'username': username,
            'name': users[username]['name'],
            'avatar': users[username]['avatar'],
            'last_message': '',
            'last_message_time': datetime.now().isoformat(),
            'unread': 0
        })
    
    save_data()
    
    return jsonify({'success': True, 'chat': chat})

@app.route('/api/themes', methods=['GET'])
def get_themes():
    """Get available themes"""
    themes = {
        'dark': {
            'name': 'Dark',
            'bg': '#000000',
            'text': '#ffffff',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#ffffff',
            'secondary': '#cccccc'
        },
        'light': {
            'name': 'Light',
            'bg': '#ffffff',
            'text': '#000000',
            'glass': 'rgba(0, 0, 0, 0.05)',
            'border': 'rgba(0, 0, 0, 0.1)',
            'hover': 'rgba(0, 0, 0, 0.08)',
            'primary': '#000000',
            'secondary': '#333333'
        },
        'serika-dark': {
            'name': 'Serika Dark',
            'bg': '#323437',
            'text': '#e2e4e6',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#e2e4e6',
            'secondary': '#999999'
        },
        'botanical': {
            'name': 'Botanical',
            'bg': '#162329',
            'text': '#c0c5ce',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#c0c5ce',
            'secondary': '#7a828e'
        },
        'nord': {
            'name': 'Nord',
            'bg': '#2e3440',
            'text': '#eceff4',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#eceff4',
            'secondary': '#88c0d0'
        },
        'dracula': {
            'name': 'Dracula',
            'bg': '#282a36',
            'text': '#f8f8f2',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#f8f8f2',
            'secondary': '#bd93f9'
        },
        'monokai': {
            'name': 'Monokai',
            'bg': '#272822',
            'text': '#f8f8f2',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#f8f8f2',
            'secondary': '#a6e22e'
        },
        'github-dark': {
            'name': 'GitHub Dark',
            'bg': '#0d1117',
            'text': '#c9d1d9',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#c9d1d9',
            'secondary': '#58a6ff'
        },
        'one-dark': {
            'name': 'One Dark',
            'bg': '#282c34',
            'text': '#abb2bf',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#abb2bf',
            'secondary': '#61afef'
        },
        'solarized-dark': {
            'name': 'Solarized Dark',
            'bg': '#002b36',
            'text': '#839496',
            'glass': 'rgba(255, 255, 255, 0.05)',
            'border': 'rgba(255, 255, 255, 0.1)',
            'hover': 'rgba(255, 255, 255, 0.08)',
            'primary': '#839496',
            'secondary': '#2aa198'
        }
    }
    return jsonify(themes)

@app.route('/api/settings', methods=['GET'])
def get_settings():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user = users[username]
    
    settings = {
        'theme': user.get('theme', 'dark'),
        'language': user['language'],
        'notifications': user.get('notifications', True),
        'show_code_preview': user.get('show_code_preview', True)
    }
    
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def update_settings():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    data = request.json
    
    if 'theme' in data:
        users[username]['theme'] = data['theme']
    if 'language' in data:
        users[username]['language'] = data['language']
    if 'notifications' in data:
        users[username]['notifications'] = data['notifications']
    if 'show_code_preview' in data:
        users[username]['show_code_preview'] = data['show_code_preview']
    
    save_data()
    
    return jsonify({'success': True})

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    """Get user notifications"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user_notifications = notifications.get(username, [])
    # Return unread notifications first, then sorted by timestamp
    unread = [n for n in user_notifications if not n.get('read', False)]
    read = [n for n in user_notifications if n.get('read', False)]
    return jsonify({
        'notifications': unread + read,
        'unread_count': len(unread)
    })

@app.route('/api/notifications/<notification_id>/read', methods=['POST'])
def mark_notification_read(notification_id):
    """Mark notification as read"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user_notifications = notifications.get(username, [])
    for notification in user_notifications:
        if notification.get('id') == notification_id:
            notification['read'] = True
            save_data()
            return jsonify({'success': True})
    
    return jsonify({'error': 'Notification not found'}), 404

@app.route('/api/notifications/read-all', methods=['POST'])
def mark_all_notifications_read():
    """Mark all notifications as read"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    user_notifications = notifications.get(username, [])
    for notification in user_notifications:
        notification['read'] = True
    save_data()
    return jsonify({'success': True})

@app.route('/api/updates', methods=['GET'])
def get_updates():
    """Polling endpoint for real-time updates"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['username']
    last_update = request.args.get('last_update', '0')
    
    # Store session for notifications
    user_sessions[username] = datetime.now().isoformat()
    
    # Return empty for now (polling will be handled by frontend)
    return jsonify({'updates': [], 'timestamp': datetime.now().isoformat()})

def add_notification(username, notification):
    """Add notification for user"""
    if username not in notifications:
        notifications[username] = []
    notification['id'] = str(uuid.uuid4())
    notification['read'] = False
    notifications[username].append(notification)
    # Keep only last 100 notifications per user
    if len(notifications[username]) > 100:
        notifications[username] = notifications[username][-100:]
    save_data()

def notify_users(event_type, data):
    """Notify users about updates"""
    if event_type == 'new_post':
        # Notify all users who follow this language
        post = data
        for username, user in users.items():
            if user.get('language') == post.get('language') and user.get('notifications', True):
                if username != post.get('username'):
                    add_notification(username, {
                        'type': 'new_post',
                        'from': post.get('username'),
                        'fromName': post.get('name'),
                        'post_id': post.get('id'),
                        'content': post.get('content', '')[:50],
                        'timestamp': datetime.now().isoformat()
                    })
    elif event_type == 'new_comment':
        # Notify post author
        post_id = data.get('post_id')
        comment = data.get('comment')
        post = next((p for p in posts if p['id'] == post_id), None)
        if post and post.get('username') != comment.get('username'):
            post_author = post.get('username')
            if post_author in users and users[post_author].get('notifications', True):
                add_notification(post_author, {
                    'type': 'new_comment',
                    'from': comment.get('username'),
                    'fromName': comment.get('name'),
                    'post_id': post_id,
                    'comment_id': comment.get('id'),
                    'content': comment.get('content', '')[:50],
                    'timestamp': datetime.now().isoformat()
                })

# Health check endpoint
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok', 
        'message': 'Kvoxy API is running',
        'users_count': len(users),
        'posts_count': len(posts)
    })

# Root endpoint
@app.route('/', methods=['GET'])
def root():
    return jsonify({
        'message': 'Kvoxy API', 
        'version': '1.0.0', 
        'endpoints': '/api/*',
        'health': '/api/health'
    }), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='127.0.0.1')
