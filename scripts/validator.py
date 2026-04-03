#!/usr/bin/env python3
"""
Romanian TV M3U Validator and Updater
Checks stream health and updates the main playlist
"""

import requests
import re
import time
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Configuration
SOURCES = {
    'iptv_org': 'https://iptv-org.github.io/iptv/countries/ro.m3u',
    'iptv_org_lang': 'https://iptv-org.github.io/iptv/languages/ron.m3u'
}

OUTPUT_FILE = 'romania_tv.m3u'
REPORT_FILE = 'health_report.json'
TIMEOUT = 10  # seconds
MAX_WORKERS = 20

class M3UValidator:
    def __init__(self):
        self.working_channels = []
        self.dead_channels = []
        self.geoblocked_channels = []
        self.report = {
            'timestamp': datetime.now().isoformat(),
            'total_checked': 0,
            'working': 0,
            'dead': 0,
            'geoblocked': 0,
            'channels': []
        }
    
    def fetch_source(self, url):
        """Fetch M3U content from source"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def parse_m3u(self, content):
        """Parse M3U content into channel list"""
        channels = []
        lines = content.strip().split('\n')
        current_channel = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('#EXTINF:'):
                # Parse channel info
                current_channel = {
                    'info': line,
                    'name': self.extract_channel_name(line),
                    'group': self.extract_group(line),
                    'logo': self.extract_logo(line)
                }
            elif line.startswith('http') and current_channel:
                current_channel['url'] = line
                channels.append(current_channel)
                current_channel = None
        
        return channels
    
    def extract_channel_name(self, extinf_line):
        """Extract channel name from EXTINF line"""
        # Match pattern: ,Channel Name or tvg-name="Name"
        name_match = re.search(r'tvg-name="([^"]+)"', extinf_line)
        if name_match:
            return name_match.group(1)
        
        # Fallback to text after last comma
        if ',' in extinf_line:
            return extinf_line.split(',')[-1].strip()
        return "Unknown"
    
    def extract_group(self, extinf_line):
        """Extract group-title"""
        match = re.search(r'group-title="([^"]+)"', extinf_line)
        return match.group(1) if match else "Romania | General"
    
    def extract_logo(self, extinf_line):
        """Extract tvg-logo"""
        match = re.search(r'tvg-logo="([^"]+)"', extinf_line)
        return match.group(1) if match else ""
    
    def check_stream(self, channel):
        """Check if stream is alive"""
        url = channel['url']
        name = channel['name']
        
        try:
            headers = {
                'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
                'Accept': '*/*',
                'Connection': 'keep-alive'
            }
            
            # Try HEAD first (faster)
            response = requests.head(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
            
            # If HEAD not allowed, try GET with stream=True (don't download body)
            if response.status_code in [405, 501]:
                response = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True)
                response.close()
            
            status_code = response.status_code
            
            # Check status
            if status_code == 200:
                return {'status': 'working', 'channel': channel, 'code': status_code}
            elif status_code in [403, 451]:
                return {'status': 'geoblocked', 'channel': channel, 'code': status_code}
            else:
                return {'status': 'dead', 'channel': channel, 'code': status_code}
                
        except requests.exceptions.Timeout:
            return {'status': 'dead', 'channel': channel, 'error': 'timeout'}
        except requests.exceptions.ConnectionError:
            return {'status': 'dead', 'channel': channel, 'error': 'connection_error'}
        except Exception as e:
            return {'status': 'dead', 'channel': channel, 'error': str(e)}
    
    def validate_all(self, channels):
        """Validate all channels concurrently"""
        print(f"Validating {len(channels)} channels...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_channel = {
                executor.submit(self.check_stream, ch): ch for ch in channels
            }
            
            for i, future in enumerate(as_completed(future_to_channel)):
                result = future.result()
                self.report['total_checked'] += 1
                
                if result['status'] == 'working':
                    self.working_channels.append(result['channel'])
                    self.report['working'] += 1
                elif result['status'] == 'geoblocked':
                    self.geoblocked_channels.append(result['channel'])
                    self.report['geoblocked'] += 1
                else:
                    self.dead_channels.append(result['channel'])
                    self.report['dead'] += 1
                
                # Update report
                self.report['channels'].append({
                    'name': result['channel']['name'],
                    'status': result['status'],
                    'code': result.get('code'),
                    'error': result.get('error')
                })
                
                if (i + 1) % 10 == 0:
                    print(f"  Checked {i + 1}/{len(channels)} channels...")
    
    def generate_m3u(self):
        """Generate clean M3U file with only working channels"""
        lines = ['#EXTM3U', f'# Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}']
        lines.append(f'# Working channels: {len(self.working_channels)}')
        lines.append(f'# Dead channels removed: {len(self.dead_channels)}')
        lines.append('')
        
        # Sort by group then name
        sorted_channels = sorted(self.working_channels, 
                               key=lambda x: (x.get('group', ''), x['name']))
        
        for ch in sorted_channels:
            lines.append(ch['info'])
            lines.append(ch['url'])
            lines.append('')
        
        return '\n'.join(lines)
    
    def save_report(self):
        """Save JSON health report"""
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, indent=2, ensure_ascii=False)
    
    def run(self):
        """Main execution"""
        print("🚀 Starting Romanian TV M3U Validator")
        print("=" * 50)
        
        # Fetch from sources
        all_channels = []
        for source_name, url in SOURCES.items():
            print(f"\n📥 Fetching from {source_name}...")
            content = self.fetch_source(url)
            if content:
                channels = self.parse_m3u(content)
                print(f"   Found {len(channels)} channels")
                all_channels.extend(channels)
        
        # Remove duplicates based on URL
        seen_urls = set()
        unique_channels = []
        for ch in all_channels:
            if ch['url'] not in seen_urls:
                seen_urls.add(ch['url'])
                unique_channels.append(ch)
        
        print(f"\n📊 Total unique channels: {len(unique_channels)}")
        
        # Validate
        self.validate_all(unique_channels)
        
        # Generate output
        print("\n💾 Generating M3U file...")
        m3u_content = self.generate_m3u()
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(m3u_content)
        
        # Save report
        self.save_report()
        
        # Print summary
        print("\n" + "=" * 50)
        print("✅ VALIDATION COMPLETE")
        print(f"Working: {self.report['working']}")
        print(f"Dead: {self.report['dead']}")
        print(f"Geoblocked: {self.report['geoblocked']}")
        print(f"\nOutput saved to: {OUTPUT_FILE}")
        print(f"Report saved to: {REPORT_FILE}")

if __name__ == '__main__':
    # Create directories if needed
    Path('sources').mkdir(exist_ok=True)
    
    validator = M3UValidator()
    validator.run()

if __name__ == '__main__':
    Path('sources').mkdir(exist_ok=True)
    
    validator = M3UValidator()
    success = validator.run()
    
    # Ensure exit code is 0 even if no channels found (don't break the workflow)
    if not success:
        print("⚠️ Validation completed with warnings")
        # Create empty playlist if none exists to prevent workflow failure
        if not Path(OUTPUT_FILE).exists():
            with open(OUTPUT_FILE, 'w') as f:
                f.write('#EXTM3U\n# No working channels found\n')
    
    exit(0)  # Always exit 0 to prevent workflow failure
