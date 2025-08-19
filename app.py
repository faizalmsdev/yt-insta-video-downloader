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

# Cookies file path
COOKIES_FILE = 'cookies.txt'

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

def check_cookies_file():
    """Check if cookies file exists and is readable"""
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, 'r') as f:
                content = f.read().strip()
                return len(content) > 0
        except Exception:
            return False
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

def get_ydl_opts_with_cookies(temp_dir, platform):
    """Get yt-dlp options with cookies configuration"""
    ydl_opts = {
        'writeinfojson': False,
        'writethumbnail': False,
    }
    
    # Add cookies if available
    if check_cookies_file():
        ydl_opts['cookiefile'] = COOKIES_FILE
        print(f"Using cookies file: {COOKIES_FILE}")
    
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
    
    # Additional options to avoid bot detection
    ydl_opts.update({
        'sleep_interval': 1,  # Sleep between downloads
        'max_sleep_interval': 5,  # Random sleep up to 5 seconds
        'sleep_interval_requests': 1,  # Sleep between requests
        'sleep_interval_subtitles': 1,  # Sleep between subtitle requests
    })
    
    return ydl_opts

def download_media_async(download_id, url, platform, download_type, quality='192'):
    """Download media asynchronously"""
    try:
        import yt_dlp
        
        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Starting download...',
            'filename': None,
            'cookies_used': check_cookies_file()
        }
        
        # Create temporary download folder
        temp_dir = tempfile.mkdtemp()
        
        # Get base configuration with cookies
        ydl_opts = get_ydl_opts_with_cookies(temp_dir, platform)
        
        # Progress hook
        def progress_hook(d):
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    download_status[download_id]['progress'] = int(percent)
                    download_status[download_id]['message'] = f'Downloading... {percent:.1f}%'
                elif 'downloaded_bytes' in d:
                    download_status[download_id]['message'] = f'Downloading... {d["downloaded_bytes"]} bytes'
                else:
                    download_status[download_id]['message'] = 'Downloading...'
            elif d['status'] == 'finished':
                download_status[download_id]['progress'] = 100
                download_status[download_id]['message'] = 'Processing...'
                download_status[download_id]['filename'] = d['filename']
            elif d['status'] == 'error':
                download_status[download_id]['message'] = f'Error: {d.get("error", "Unknown error")}'
        
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
            download_status[download_id]['message'] = 'Extracting media info...'
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            uploader = info.get('uploader', 'Unknown')
            
            download_status[download_id]['title'] = title
            download_status[download_id]['uploader'] = uploader
            download_status[download_id]['platform'] = platform
            download_status[download_id]['message'] = 'Starting download...'
            
            # Download the media
            ydl.download([url])
            
            # Find the downloaded file
            files = list(Path(temp_dir).glob('*'))
            if files:
                # Get the main media file (not .info.json)
                media_files = [f for f in files if not f.name.endswith('.info.json') and not f.name.endswith('.part')]
                if media_files:
                    download_status[download_id]['filename'] = str(media_files[0])
                    download_status[download_id]['temp_dir'] = temp_dir
            
            download_status[download_id]['status'] = 'completed'
            download_status[download_id]['progress'] = 100
            download_status[download_id]['message'] = 'Download completed successfully!'
            
    except Exception as e:
        download_status[download_id]['status'] = 'error'
        download_status[download_id]['message'] = f'Download failed: {str(e)}'
        print(f"Download error for {download_id}: {str(e)}")

def search_and_download_async(download_id, query, download_type, quality='192'):
    """Search and download asynchronously"""
    try:
        import yt_dlp
        
        download_status[download_id] = {
            'status': 'searching',
            'progress': 0,
            'message': 'Searching...',
            'filename': None,
            'cookies_used': check_cookies_file()
        }
        
        temp_dir = tempfile.mkdtemp()
        
        # Get base configuration with cookies
        ydl_opts = get_ydl_opts_with_cookies(temp_dir, 'youtube')
        ydl_opts['outtmpl'] = str(Path(temp_dir) / 'YT_SEARCH_%(title)s_%(id)s.%(ext)s')
        
        def progress_hook(d):
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    download_status[download_id]['progress'] = int(percent)
                    download_status[download_id]['message'] = f'Downloading... {percent:.1f}%'
                elif 'downloaded_bytes' in d:
                    download_status[download_id]['message'] = f'Downloading... {d["downloaded_bytes"]} bytes'
                else:
                    download_status[download_id]['message'] = 'Downloading...'
            elif d['status'] == 'finished':
                download_status[download_id]['progress'] = 100
                download_status[download_id]['message'] = 'Processing...'
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
                    media_files = [f for f in files if not f.name.endswith('.info.json') and not f.name.endswith('.part')]
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
        print(f"Search error for {download_id}: {str(e)}")

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
    
    return jsonify({
        'download_id': download_id, 
        'platform': platform,
        'cookies_available': check_cookies_file()
    })

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
    
    return jsonify({
        'download_id': download_id, 
        'platform': 'youtube',
        'cookies_available': check_cookies_file()
    })

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

@app.route('/api/check-cookies')
def api_check_cookies():
    cookies_available = check_cookies_file()
    return jsonify({
        'cookies_available': cookies_available,
        'cookies_file': COOKIES_FILE,
        'message': 'Cookies loaded successfully' if cookies_available else 'No cookies file found or empty'
    })

@app.route('/api/system-status')
def api_system_status():
    return jsonify({
        'ffmpeg_available': check_ffmpeg(),
        'cookies_available': check_cookies_file(),
        'cookies_file': COOKIES_FILE
    })

if __name__ == '__main__':
    # Check system requirements on startup
    print("Checking system requirements...")
    print(f"FFmpeg available: {check_ffmpeg()}")
    print(f"Cookies file available: {check_cookies_file()}")
    if check_cookies_file():
        print(f"Using cookies from: {COOKIES_FILE}")
    else:
        print(f"No cookies file found at: {COOKIES_FILE}")
        print("Consider adding cookies.txt file to avoid bot detection")
    
    # Install required packages on startup
    install_required_packages()
    app.run(debug=True, host='0.0.0.0', port=8000)