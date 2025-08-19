from flask import Flask, render_template, request, jsonify, send_file
import os
import sys
import subprocess
import re
import threading
import json
from pathlib import Path
from datetime import datetime
import tempfile
import shutil

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Global variable to store download status
download_status = {}

def install_required_packages():
    """Install required packages if not available"""
    packages = ['yt-dlp', 'requests']
    
    for package in packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def check_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False

def detect_platform(url):
    """Detect which platform the URL belongs to"""
    youtube_patterns = [
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/',
        r'(https?://)?(www\.)?youtu\.be/',
    ]
    
    instagram_patterns = [
        r'(https?://)?(www\.)?instagram\.com/',
        r'(https?://)?(www\.)?instagr\.am/',
    ]
    
    tiktok_patterns = [
        r'(https?://)?(www\.)?tiktok\.com/',
        r'(https?://)?(vm\.)?tiktok\.com/',
    ]
    
    twitter_patterns = [
        r'(https?://)?(www\.)?(twitter|x)\.com/',
    ]
    
    facebook_patterns = [
        r'(https?://)?(www\.)?facebook\.com/',
        r'(https?://)?(www\.)?fb\.watch/',
    ]
    
    for pattern in youtube_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return 'youtube'
    
    for pattern in instagram_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return 'instagram'
    
    for pattern in tiktok_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return 'tiktok'
    
    for pattern in twitter_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return 'twitter'
    
    for pattern in facebook_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return 'facebook'
    
    return 'unknown'

def download_media_async(download_id, url, platform, download_type, quality='192'):
    """Download media asynchronously"""
    try:
        import yt_dlp
        
        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Starting download...',
            'filename': None
        }
        
        # Create temporary download folder
        temp_dir = tempfile.mkdtemp()
        
        # Base configuration
        ydl_opts = {
            'writeinfojson': False,
            'writethumbnail': False,
        }
        
        # Platform-specific filename templates
        if platform == 'youtube':
            ydl_opts['outtmpl'] = str(Path(temp_dir) / 'YT_%(title)s_%(id)s.%(ext)s')
        elif platform == 'instagram':
            ydl_opts['outtmpl'] = str(Path(temp_dir) / 'IG_%(uploader)s_%(title)s_%(id)s.%(ext)s')
        elif platform == 'tiktok':
            ydl_opts['outtmpl'] = str(Path(temp_dir) / 'TT_%(uploader)s_%(title)s_%(id)s.%(ext)s')
        elif platform == 'twitter':
            ydl_opts['outtmpl'] = str(Path(temp_dir) / 'TW_%(uploader)s_%(title)s_%(id)s.%(ext)s')
        elif platform == 'facebook':
            ydl_opts['outtmpl'] = str(Path(temp_dir) / 'FB_%(uploader)s_%(title)s_%(id)s.%(ext)s')
        else:
            ydl_opts['outtmpl'] = str(Path(temp_dir) / '%(uploader)s_%(title)s_%(id)s.%(ext)s')
        
        # Progress hook
        def progress_hook(d):
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    download_status[download_id]['progress'] = int(percent)
                    download_status[download_id]['message'] = f'Downloading... {percent:.1f}%'
                else:
                    download_status[download_id]['message'] = 'Downloading...'
            elif d['status'] == 'finished':
                download_status[download_id]['progress'] = 100
                download_status[download_id]['message'] = 'Download completed!'
                download_status[download_id]['filename'] = d['filename']
        
        ydl_opts['progress_hooks'] = [progress_hook]
        
        # Configure download type
        if download_type == "video":
            ydl_opts['format'] = 'best[ext=mp4]/best'
        elif download_type == "audio":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'mp3',
                'audioquality': quality,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': quality,
                }],
            })
        else:  # best
            ydl_opts['format'] = 'best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get media info first
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            uploader = info.get('uploader', 'Unknown')
            
            download_status[download_id]['title'] = title
            download_status[download_id]['uploader'] = uploader
            download_status[download_id]['platform'] = platform
            
            # Download the media
            ydl.download([url])
            
            # Find the downloaded file
            files = list(Path(temp_dir).glob('*'))
            if files:
                # Get the main media file (not .info.json)
                media_files = [f for f in files if not f.name.endswith('.info.json')]
                if media_files:
                    download_status[download_id]['filename'] = str(media_files[0])
                    download_status[download_id]['temp_dir'] = temp_dir
            
            download_status[download_id]['status'] = 'completed'
            download_status[download_id]['progress'] = 100
            download_status[download_id]['message'] = 'Download completed successfully!'
            
    except Exception as e:
        download_status[download_id]['status'] = 'error'
        download_status[download_id]['message'] = f'Download failed: {str(e)}'

def search_and_download_async(download_id, query, download_type, quality='192'):
    """Search and download asynchronously"""
    try:
        import yt_dlp
        
        download_status[download_id] = {
            'status': 'searching',
            'progress': 0,
            'message': 'Searching...',
            'filename': None
        }
        
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'outtmpl': str(Path(temp_dir) / 'YT_SEARCH_%(title)s_%(id)s.%(ext)s'),
            'writeinfojson': False,
        }
        
        def progress_hook(d):
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    download_status[download_id]['progress'] = int(percent)
                    download_status[download_id]['message'] = f'Downloading... {percent:.1f}%'
                else:
                    download_status[download_id]['message'] = 'Downloading...'
            elif d['status'] == 'finished':
                download_status[download_id]['progress'] = 100
                download_status[download_id]['message'] = 'Download completed!'
                download_status[download_id]['filename'] = d['filename']
        
        ydl_opts['progress_hooks'] = [progress_hook]
        
        if download_type == "video":
            # Always get the highest quality video and audio, merge with ffmpeg
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
            search_query = f"ytsearch1:{query}"
        else:  # audio
            ydl_opts.update({
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'mp3',
                'audioquality': quality,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': quality,
                }],
            })
            search_query = f"ytsearch1:{query}"
        
        download_status[download_id]['status'] = 'downloading'
        download_status[download_id]['message'] = 'Found result, downloading...'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=True)
            
            if info and 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
                title = entry.get('title', 'Unknown')
                uploader = entry.get('uploader', 'Unknown')
                
                download_status[download_id]['title'] = title
                download_status[download_id]['uploader'] = uploader
                download_status[download_id]['platform'] = 'youtube'
                
                # Find the downloaded file
                files = list(Path(temp_dir).glob('*'))
                if files:
                    media_files = [f for f in files if not f.name.endswith('.info.json')]
                    if media_files:
                        download_status[download_id]['filename'] = str(media_files[0])
                        download_status[download_id]['temp_dir'] = temp_dir
                
                download_status[download_id]['status'] = 'completed'
                download_status[download_id]['progress'] = 100
                download_status[download_id]['message'] = 'Download completed successfully!'
            else:
                download_status[download_id]['status'] = 'error'
                download_status[download_id]['message'] = 'No results found'
                
    except Exception as e:
        download_status[download_id]['status'] = 'error'
        download_status[download_id]['message'] = f'Search failed: {str(e)}'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/download', methods=['POST'])
def api_download():
    data = request.json
    url = data.get('url')
    download_type = data.get('type', 'best')
    quality = data.get('quality', '192')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    platform = detect_platform(url)
    if platform == 'unknown':
        return jsonify({'error': 'Unsupported platform or invalid URL'}), 400
    
    # Generate download ID
    download_id = f"dl_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    
    # Start download in background
    thread = threading.Thread(
        target=download_media_async,
        args=(download_id, url, platform, download_type, quality)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'download_id': download_id, 'platform': platform})

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    query = data.get('query')
    download_type = data.get('type', 'video')
    quality = data.get('quality', '192')
    
    if not query:
        return jsonify({'error': 'Search query is required'}), 400
    
    # Generate download ID
    download_id = f"search_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    
    # Start search and download in background
    thread = threading.Thread(
        target=search_and_download_async,
        args=(download_id, query, download_type, quality)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'download_id': download_id, 'platform': 'youtube'})

@app.route('/api/status/<download_id>')
def api_status(download_id):
    status = download_status.get(download_id, {'status': 'not_found'})
    return jsonify(status)

@app.route('/api/download-file/<download_id>')
def api_download_file(download_id):
    status = download_status.get(download_id)
    if not status or status['status'] != 'completed' or not status.get('filename'):
        return jsonify({'error': 'File not ready'}), 404
    
    filename = status['filename']
    if not os.path.exists(filename):
        return jsonify({'error': 'File not found'}), 404
    
    # Get original filename
    original_name = os.path.basename(filename)
    
    def cleanup_temp():
        # Clean up temp directory after download
        temp_dir = status.get('temp_dir')
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        # Remove from status
        if download_id in download_status:
            del download_status[download_id]
    
    # Schedule cleanup after sending file
    threading.Timer(1.0, cleanup_temp).start()
    
    return send_file(filename, as_attachment=True, download_name=original_name)

@app.route('/api/check-ffmpeg')
def api_check_ffmpeg():
    return jsonify({'ffmpeg_available': check_ffmpeg()})

if __name__ == '__main__':
    # Install required packages on startup
    install_required_packages()
    app.run(debug=True, host='0.0.0.0', port=8000)