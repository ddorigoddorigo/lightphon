"""
Auto-updater module for the node-client.
Handles version checking, downloading, and applying updates.
"""

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import tempfile
import threading
import subprocess
import urllib.request
from pathlib import Path

from version import VERSION, is_newer

logger = logging.getLogger(__name__)

# Server URL for updates
UPDATE_SERVER = "https://lightphon.com"
CHECK_INTERVAL = 3600  # Check every hour (in seconds)


class AutoUpdater:
    """Handles automatic updates for the node-client."""
    
    def __init__(self, callback=None):
        """
        Initialize the auto-updater.
        
        Args:
            callback: Function to call when update is available.
                      Signature: callback(version, changelog, download_url)
        """
        self.current_version = VERSION
        self.callback = callback
        self.check_thread = None
        self.running = False
        self.update_available = False
        self.latest_version = None
        self.download_url = None
        self.changelog = None
        self.checksum = None
        
    def start_checking(self, interval=CHECK_INTERVAL):
        """Start periodic version checking in background."""
        self.running = True
        self.check_thread = threading.Thread(
            target=self._check_loop,
            args=(interval,),
            daemon=True
        )
        self.check_thread.start()
        logger.info(f"Auto-updater started (checking every {interval}s)")
        
    def stop_checking(self):
        """Stop the background version checking."""
        self.running = False
        if self.check_thread:
            self.check_thread.join(timeout=5)
        logger.info("Auto-updater stopped")
        
    def _check_loop(self, interval):
        """Background loop for checking updates."""
        # Initial check after 10 seconds
        time.sleep(10)
        
        while self.running:
            try:
                self.check_for_updates()
            except Exception as e:
                logger.error(f"Error checking for updates: {e}")
            
            # Sleep in small intervals to allow quick shutdown
            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)
    
    def check_for_updates(self):
        """
        Check if a new version is available.
        
        Returns:
            dict with update info if available, None otherwise
        """
        try:
            url = f"{UPDATE_SERVER}/api/version"
            logger.debug(f"Checking for updates at {url}")
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', f'LightPhon-Node/{self.current_version}')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
            
            remote_version = data.get('version', '0.0.0')
            
            if is_newer(remote_version, self.current_version):
                self.update_available = True
                self.latest_version = remote_version
                self.download_url = data.get('download_url')
                self.changelog = data.get('changelog', '')
                self.checksum = data.get('checksum')
                
                logger.info(f"Update available: {self.current_version} -> {remote_version}")
                
                # Notify callback
                if self.callback:
                    self.callback(
                        self.latest_version,
                        self.changelog,
                        self.download_url
                    )
                
                return {
                    'version': remote_version,
                    'changelog': self.changelog,
                    'download_url': self.download_url,
                    'checksum': self.checksum
                }
            else:
                logger.debug(f"No update available (current: {self.current_version}, remote: {remote_version})")
                return None
                
        except urllib.error.URLError as e:
            logger.warning(f"Could not check for updates: {e}")
            return None
        except Exception as e:
            logger.error(f"Update check failed: {e}")
            return None
    
    def download_update(self, progress_callback=None):
        """
        Download the update file.
        
        Args:
            progress_callback: Function called with (downloaded, total) bytes
            
        Returns:
            Path to downloaded file, or None on failure
        """
        if not self.download_url:
            logger.error("No download URL available")
            return None
        
        try:
            # Create temp directory for download
            temp_dir = tempfile.mkdtemp(prefix='lightphon_update_')
            
            # Determine filename from URL or use default
            filename = self.download_url.split('/')[-1]
            if not filename.endswith('.exe'):
                filename = f'LightPhon-Node-{self.latest_version}.exe'
            
            download_path = os.path.join(temp_dir, filename)
            
            logger.info(f"Downloading update from {self.download_url}")
            
            # Download with progress
            req = urllib.request.Request(self.download_url)
            req.add_header('User-Agent', f'LightPhon-Node/{self.current_version}')
            
            with urllib.request.urlopen(req, timeout=300) as response:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                chunk_size = 8192
                
                with open(download_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            
            # Verify checksum if provided
            if self.checksum:
                file_hash = self._calculate_checksum(download_path)
                if file_hash != self.checksum:
                    logger.error(f"Checksum mismatch: expected {self.checksum}, got {file_hash}")
                    os.remove(download_path)
                    return None
                logger.info("Checksum verified")
            
            logger.info(f"Update downloaded to {download_path}")
            return download_path
            
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None
    
    def _calculate_checksum(self, filepath):
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def apply_update(self, update_path):
        """
        Apply the downloaded update.
        
        This creates a batch script that:
        1. Waits for current process to exit
        2. Replaces the old executable
        3. Starts the new version
        
        Args:
            update_path: Path to the downloaded update file
            
        Returns:
            True if update process started, False on error
        """
        if not os.path.exists(update_path):
            logger.error(f"Update file not found: {update_path}")
            return False
        
        try:
            # Get current executable path
            if getattr(sys, 'frozen', False):
                # Running as compiled exe
                current_exe = sys.executable
            else:
                # Running as script - for testing
                logger.info("Running as script, simulating update...")
                current_exe = os.path.abspath(sys.argv[0])
            
            current_dir = os.path.dirname(current_exe)
            backup_path = current_exe + '.backup'
            
            # Create update batch script
            batch_content = f'''@echo off
echo Updating LightPhon Node...
echo Waiting for application to close...

:waitloop
timeout /t 1 /nobreak >nul
tasklist /FI "PID eq {os.getpid()}" 2>NUL | find /I /N "{os.getpid()}" >NUL
if "%ERRORLEVEL%"=="0" goto waitloop

echo Application closed, applying update...

REM Backup current version
if exist "{current_exe}" (
    if exist "{backup_path}" del /F /Q "{backup_path}"
    move /Y "{current_exe}" "{backup_path}"
)

REM Copy new version
copy /Y "{update_path}" "{current_exe}"

if %ERRORLEVEL% EQU 0 (
    echo Update successful!
    REM Clean up
    del /F /Q "{update_path}"
    rmdir /S /Q "{os.path.dirname(update_path)}" 2>nul
    
    echo Starting new version...
    start "" "{current_exe}"
) else (
    echo Update failed! Restoring backup...
    if exist "{backup_path}" move /Y "{backup_path}" "{current_exe}"
)

REM Self-delete this batch file
del "%~f0"
'''
            
            batch_path = os.path.join(tempfile.gettempdir(), 'lightphon_update.bat')
            with open(batch_path, 'w') as f:
                f.write(batch_content)
            
            logger.info(f"Created update script: {batch_path}")
            
            # Start the update script
            subprocess.Popen(
                ['cmd', '/c', batch_path],
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                close_fds=True
            )
            
            logger.info("Update script started, exiting application...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply update: {e}")
            return False


def check_for_updates_sync():
    """
    Synchronous check for updates.
    Returns update info dict or None.
    """
    updater = AutoUpdater()
    return updater.check_for_updates()


if __name__ == '__main__':
    # Test the updater
    logging.basicConfig(level=logging.DEBUG)
    
    print(f"Current version: {VERSION}")
    
    updater = AutoUpdater()
    update = updater.check_for_updates()
    
    if update:
        print(f"Update available: {update['version']}")
        print(f"Changelog: {update['changelog']}")
    else:
        print("No updates available")
