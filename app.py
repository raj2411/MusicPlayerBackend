from flask import Flask, jsonify, request
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
import requests
import base64
import datetime
import os
import json


app = Flask(__name__)
# Initialize Firebase
firebase_admin_credentials_json = os.environ.get('FIREBASE_ADMIN_CREDENTIALS_JSON')

if firebase_admin_credentials_json:
    firebase_credentials = json.loads(firebase_admin_credentials_json)
    cred = credentials.Certificate(firebase_credentials)
    initialize_app(cred)
    db = firestore.client()
else:
    raise ValueError("Firebase Admin SDK credentials secret not found in environment variable.")

# Spotify API Credentials
SPOTIFY_CLIENT_ID = '3fc01929fd794962a67ba60a333a53f5'
SPOTIFY_CLIENT_SECRET = '96f81760c72c47d887784b4dea60d887'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_RECOMMENDATIONS_URL = 'https://api.spotify.com/v1/recommendations'


# Function to get Spotify Access Token
def get_spotify_access_token():
    client_creds = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    client_creds_b64 = base64.b64encode(client_creds.encode())
    headers = {
        "Authorization": f"Basic {client_creds_b64.decode()}"
    }
    payload = {
        "grant_type": "client_credentials"
    }
    response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=payload)
    access_token = response.json().get("access_token")
    print("Spotify Access Token:", access_token)
    return access_token

@app.route('/check-favorite', methods=['POST'])
def check_favorite():
    data = request.json
    user_id = data.get('userId')
    track_id = data.get('trackId')

    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    if user_doc.exists:
        user_data = user_doc.to_dict()
        favorites = user_data.get('favorites', [])
        return jsonify({'isFavorite': track_id in favorites})
    return jsonify({'error': 'User not found'}), 404


@app.route('/toggle-favorite', methods=['POST'])
def toggle_favorite():
    data = request.json
    user_id = data.get('userId')
    track_id = data.get('trackId')

    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    if user_doc.exists:
        user_data = user_doc.to_dict()
        favorites = user_data.get('favorites', [])
        if track_id in favorites:
            favorites.remove(track_id)
        else:
            favorites.append(track_id)
        user_ref.update({'favorites': favorites})
        return jsonify({'success': True, 'isFavorite': track_id in favorites})
    return jsonify({'error': 'User not found'}), 404


# Function to fetch user preferences from Firestore
def fetch_user_preferences(userId):
     print("Fetching preferences for:", userId)
     user_ref = db.collection('users').document(userId)
     user_doc = user_ref.get()
     print(user_doc)     
     if user_doc.exists:
         preferences_str = user_doc.to_dict().get('preferences','')
         print("User Preferences String:", preferences_str)
         print([preference.strip() for preference in preferences_str.split(',')])
         return [preference.strip() for preference in preferences_str.split(',')]
     else:
         print("User document does not exist")
         return []

# Use static preferences for testing

# def fetch_user_preferences(userId):
#     return ['pop', 'rock', 'electro', 'indie']


@app.route('/recommendedsongs', methods=['GET'])
def recommendedsongs():
    userId = request.args.get('userId')
    genre = request.args.get('genre').replace('_', ' ')  # Add this line to accept genre as a parameter
    spotify_token = get_spotify_access_token()
    songs = fetch_songs_from_spotify([genre], spotify_token)  # Use genre in fetch_songs_from_spotify
    print(songs)
    if save_songs_to_firestore(songs):
        return jsonify(songs)
    else:
            return jsonify({"error": "Failed to save songs to database"}), 500

@app.route('/user-preferences', methods=['GET'])
def user_preferences():
    user_id = request.args.get('userId')
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()

    if user_doc.exists:
        user_data = user_doc.to_dict()
        preferences = user_data.get('preferences', '')
        return jsonify({'preferences': preferences.split(', ')}), 200
    else:
        return jsonify({'error': 'User not found'}), 404


# Function to fetch songs from Spotify and extract specific details including album cover and audio URL
def fetch_songs_from_spotify(preferences, token):
    print("Fetching songs from Spotify with preferences:", preferences)
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # Joining preferences with commas without removing spaces within genre names
    genre_string = ','.join(preferences).replace('',"")


    query_params = {
        "seed_genres": genre_string,
        "limit": 20  # Increased limit to have a better chance of getting tracks with previews
    }

    print("Query parameters being sent:", query_params)
    response = requests.get(SPOTIFY_RECOMMENDATIONS_URL, headers=headers, params=query_params)
    raw_songs = response.json().get("tracks", [])
    print(raw_songs)

    # Extract specific details from each track and filter out tracks without audio previews
    songs = []
    for item in raw_songs:
        if item.get('preview_url'):
            track_info = {
                'track_id': item['id'],
                'track_name': item['name'],
                'artist_names': [artist['name'] for artist in item['artists']],
                'album_name': item['album']['name'],
                'album_id': item['album']['id'],
                'album_cover': item['album']['images'][0]['url'] if item['album']['images'] else None,
                'audio_preview_url': item['preview_url']
            }
            songs.append(track_info)

    return songs


def save_songs_to_firestore(songs):
    try:
        song_collection = db.collection('song')
        for song in songs:
            song_collection.document(song['track_id']).set(song)
        return True
    except Exception as e:
        print(f"Error saving songs to Firestore: {e}")
        return False
    
@app.route('/recommended-songs', methods=['GET'])
def recommended_songs():
    userId = request.args.get('userId')
    print("Received request for id:", userId)
    user_preferences = fetch_user_preferences(userId)
    spotify_token = get_spotify_access_token()
    songs = fetch_songs_from_spotify(user_preferences, spotify_token)

    # Save songs to Firestore and check if successful
    if save_songs_to_firestore(songs):
        return jsonify(songs)
    else:
        return jsonify({"error": "Failed to save songs to database"}), 500


# Endpoint to fetch a user's favorite songs with details
@app.route('/favorite-songs', methods=['GET'])
def get_favorite_songs_with_details():
    user_id = request.args.get('userId')
    
    # Retrieve the user's favorite songs IDs from Firestore
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if user_doc.exists:
        user_data = user_doc.to_dict()
        favorite_song_ids = user_data.get('favorites', [])
        
        # Fetch the details of each favorite song
        favorite_songs_details = []
        for song_id in favorite_song_ids:
            song_ref = db.collection('song').document(song_id)
            song_doc = song_ref.get()
            if song_doc.exists:
                song_data = song_doc.to_dict()
                favorite_songs_details.append(song_data)
        
        return jsonify(favorite_songs_details)
    else:
        return jsonify([])

@app.route('/submit-rating', methods=['POST'])
def submit_rating():
    data = request.json
    user_id = data['userId']
    track_id = data['trackId']
    rating = data['rating']
    image_url = data.get('imageUrl', '')

    # Generate a unique rating ID
    rating_id = f"{user_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

    print(f"Received rating submission for User ID: {user_id}, Track ID: {track_id}, Rating: {rating}, Image URL: {image_url}")

    # Perform facial emotion recognition
    facial_emotion_url = "https://api-inference.huggingface.co/models/Rajaram1996/FacialEmoRecog"
    facial_emotion_headers = {
        "Authorization": "Bearer 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",  # Replace with your API key
        "Content-Type": "application/json"
    }
    facial_emotion_payload = {
        "image": image_url
    }

    print("Performing facial emotion recognition...")

    # Make a POST request to the facial emotion recognition model
    response = requests.post(
        facial_emotion_url,
        headers=facial_emotion_headers,
        json=facial_emotion_payload
    )

    if response.status_code == 200:
        facial_emotion_data = response.json()
        print("Facial Emotion Recognition Data:", facial_emotion_data)

        # Extract emotion scores and labels
        emotions = facial_emotion_data if isinstance(facial_emotion_data, list) else []

        # Calculate satisfaction score based on emotion scores
        emotion_label = calculate_satisfaction_score(emotions)

        print(f"User was : {emotion_label}")

        # Update User's Rating
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            user_ratings = user_data.get('ratings', {})
            user_ratings[track_id] = {
                'ratingId': rating_id,
                'rating': rating,
                'imageUrl': image_url,
                'emotion_label': emotion_label  # Include emotion_label in user's rating
            }
            user_ref.update({'ratings': user_ratings})
            print("User rating updated.")
        else:
            print("Error: User not found")

        # Update Song's Rating
        song_ref = db.collection('song').document(track_id)
        song_doc = song_ref.get()
        if song_doc.exists:
            song_data = song_doc.to_dict()
            song_ratings = song_data.get('userRatings', {})
            song_ratings[user_id] = {
                'ratingId': rating_id,
                'rating': rating,
                'imageUrl': image_url,
                'emotion_label': emotion_label  # Include emotion_label in user's rating
            }
            song_ref.update({'userRatings': song_ratings})
            print("Song rating updated with user's ID.")
            print(track_id)
        else:
            print("Error: Song not found")

        # Save image data with emotion_label in the image document
        image_ref = db.collection('images').document(rating_id)
        image_ref.set({'imageUrl': image_url, 'rating': rating, 'emotion_label': emotion_label})
        print("Image data stored.")

        return jsonify({'success': True})

    elif response.status_code == 503:
        estimated_time = response.json().get('estimated_time', 20)
        print(f"Facial emotion recognition model is currently loading. Estimated time: {estimated_time} seconds.")
        return jsonify({'error': 'Model Rajaram1996/FacialEmoRecog is currently loading', 'estimated_time': estimated_time}), 503

    else:
        print(f"Facial emotion recognition failed. Status code: {response.status_code}")
        return jsonify({'error': 'Facial emotion recognition failed'}),

def calculate_satisfaction_score(emotions):
    # Define weights for different emotions (you can adjust these weights as needed)
    emotion_weights = {
        "happy": 1.0,
        "contempt": -0.5,
        "disgust": -0.5,
        "anger": -0.5,
        "neutral": 0.0
    }

    total_weighted_score = 0.0
    total_weight = 0.0

    for emotion in emotions:
        label = emotion.get("label", "")
        score = emotion.get("score", 0.0)

        # Use the defined weight for the emotion label
        weight = emotion_weights.get(label, 0.0)

        # Calculate the weighted score for this emotion
        weighted_score = weight * score

        total_weighted_score += weighted_score
        total_weight += abs(weight)

    if total_weight > 0:
        # Calculate the overall satisfaction score
        satisfaction_score = total_weighted_score / total_weight
    else:
        # Default satisfaction score if no emotions detected
        satisfaction_score = 0.0

    # Determine satisfaction status based on the satisfaction score
    if satisfaction_score >= 0:
        return "satisfied"
    else:
        return "not satisfied"

@app.route('/update-history', methods=['POST'])
def update_history():
    data = request.get_json()  # Get data as JSON
    user_id = data.get('userId')
    track_id = data.get('songId')
    
    # Print incoming data
    print(f"User ID: {user_id}, Track ID: {track_id}")

    # Convert current timestamp to string in desired format
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Timestamp: {timestamp}")

    user_ref = db.collection('users').document(user_id) 
    user_doc = user_ref.get()

    # Print the user document data
    if user_doc.exists:
        print("User document found.")
        print(f"User Data: {user_doc.to_dict()}")
        user_data = user_doc.to_dict()
        
        history = user_data.get('history', [])
        print(f"Current History: {history}")

        history.append({'trackId': track_id, 'timestamp': timestamp})
        print(f"Updated History: {history}")

        # Keep only the last 20 entries
        history = history[-20:]

        user_ref.update({'history': history})
        return jsonify({'success': True}), 200
    else:
        print("User document not found.")
        return jsonify({'error': 'User not found'}), 404

@app.route('/history', methods=['GET'])
def get_user_history():
    user_id = request.args.get('userId')
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if user_doc.exists:
        user_data = user_doc.to_dict()
        history = user_data.get('history', [])
        
        # Fetch each song's details
        song_details = []
        for entry in history:
            track_id = entry.get('trackId')
            song_ref = db.collection('song').document(track_id)
            song_doc = song_ref.get()
            if song_doc.exists:
                song_details.append(song_doc.to_dict())
        
        return jsonify(song_details), 200
    else:
        return jsonify({'error': 'User not found'}), 404



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
