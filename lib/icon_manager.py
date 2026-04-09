import os
import subprocess
import shutil
from PIL import Image

class IconManager:
    def __init__(self, adb_path, cache_dir):
        self.adb_path = adb_path
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self._default_icon = None

    def get_icon_path(self, pkg_name):
        return os.path.join(self.cache_dir, f"{pkg_name}.png")

    def is_cached(self, pkg_name):
        return os.path.exists(self.get_icon_path(pkg_name))

    def fetch_icon(self, pkg_name):
        """Attempts to fetch the icon from the device using Android 11+ dump-icon."""
        local_path = self.get_icon_path(pkg_name)
        if os.path.exists(local_path):
            return local_path

        # We use a temporary file on the device for the icon extraction
        remote_temp = f"/sdcard/.tmp_{pkg_name}_icon.png"
        
        try:
            # 1. Try modern Android dump-icon (Android 11+)
            # cmd package dump-icon [--user <USER_ID>] <PACKAGE> <FILE>
            # Note: We use user 0 by default for now
            cmd_dump = [self.adb_path, "shell", "cmd", "package", "dump-icon", pkg_name, remote_temp]
            subprocess.run(cmd_dump, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            
            # 2. Pull the generated icon
            cmd_pull = [self.adb_path, "pull", remote_temp, local_path]
            subprocess.run(cmd_pull, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            
            # 3. Cleanup remote
            subprocess.run([self.adb_path, "shell", "rm", remote_temp], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                # Post-process: resize for consistent UI look
                self._process_image(local_path)
                return local_path
        except Exception:
            if os.path.exists(local_path):
                os.remove(local_path)
        
        return None

    def _process_image(self, path):
        """Resizes the image to a standard 32x32 size for the UI."""
        try:
            with Image.open(path) as img:
                # Convert to RGBA if needed
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                img = img.resize((32, 32), Image.Resampling.LANCZOS)
                img.save(path, "PNG")
        except Exception:
            pass

    def clear_cache(self):
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir)
