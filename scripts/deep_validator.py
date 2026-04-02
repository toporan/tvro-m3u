#!/usr/bin/env python3
"""
Deep validation using ffprobe to check actual video streams
"""

import subprocess
import json
from concurrent.futures import ThreadPoolExecutor
import sys

def check_with_ffprobe(url, timeout=15):
    """Use ffprobe to check if stream is actually playable"""
    cmd = [
        'ffprobe', 
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,avg_frame_rate',
        '-of', 'json',
        '-timeout', str(timeout * 1000000),  # microseconds
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('streams'):
                stream = data['streams'][0]
                return {
                    'status': 'working',
                    'codec': stream.get('codec_name'),
                    'resolution': f"{stream.get('width')}x{stream.get('height')}",
                    'fps': eval(stream.get('avg_frame_rate', '0/1'))  # Convert fraction to float
                }
        return {'status': 'dead', 'error': 'No video stream found'}
    except subprocess.TimeoutExpired:
        return {'status': 'dead', 'error': 'ffprobe timeout'}
    except Exception as e:
        return {'status': 'dead', 'error': str(e)}

# Use this in validator.py for critical channels
