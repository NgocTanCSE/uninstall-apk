"""
ADB App Manager - Native Windows Desktop Application
Full-featured ADB tool with advanced app management and device controls.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import os
import sys
import re
import tempfile
import shutil
import threading
import time

# ═══════════════════════════════════════════════════════════
#  PATH CONFIGURATION
# ═══════════════════════════════════════════════════════════

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_dir():
    """Where bundled data files live (inside exe temp or script dir)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
RESOURCE_DIR = get_resource_dir()

# ADB: look in bundled resources first, then next to exe
_adb_bundled = os.path.join(RESOURCE_DIR, "platform-tools", "adb.exe")
_adb_local = os.path.join(BASE_DIR, "platform-tools", "adb.exe")
ADB_PATH = _adb_bundled if os.path.isfile(_adb_bundled) else _adb_local

TEMP_DIR = os.path.join(tempfile.gettempdir(), "adb_app_manager")
os.makedirs(TEMP_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════
#  ADB UTILITIES
# ═══════════════════════════════════════════════════════════

def run_adb(args, timeout=30):
    cmd = [ADB_PATH] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Timeout", 1
    except FileNotFoundError:
        return "", f"ADB not found: {ADB_PATH}", 1
    except Exception as e:
        return "", str(e), 1


def get_device_info():
    stdout, _, code = run_adb(["devices", "-l"])
    if code != 0:
        return None
    for line in stdout.split("\n")[1:]:
        line = line.strip()
        if not line or "offline" in line:
            continue
        if "device" in line and "List" not in line:
            parts = line.split()
            serial = parts[0]
            model, _, _ = run_adb(["shell", "getprop", "ro.product.model"])
            brand, _, _ = run_adb(["shell", "getprop", "ro.product.brand"])
            android_ver, _, _ = run_adb(["shell", "getprop", "ro.build.version.release"])
            sdk_ver, _, _ = run_adb(["shell", "getprop", "ro.build.version.sdk"])
            return {
                "serial": serial,
                "model": model.strip(),
                "brand": brand.strip().title(),
                "android": android_ver.strip(),
                "sdk": sdk_ver.strip(),
            }
    return None


# Global user ID for --user flag (default 0)
CURRENT_USER_ID = "0"

def list_all_packages():
    stdout, _, code = run_adb(["shell", "pm", "list", "packages", "-f"])
    if code != 0:
        return []
    sys_out, _, _ = run_adb(["shell", "pm", "list", "packages", "-s"])
    system_pkgs = {l.replace("package:", "").strip() for l in sys_out.split("\n") if l.strip()}
    dis_out, _, _ = run_adb(["shell", "pm", "list", "packages", "-d"])
    disabled_pkgs = {l.replace("package:", "").strip() for l in dis_out.split("\n") if l.strip()}

    packages = []
    for line in stdout.split("\n"):
        line = line.strip()
        if not line.startswith("package:"):
            continue
        content = line[len("package:"):]
        # Use rsplit to split at the LAST '=' — APK paths on newer Android
        # contain '=' (e.g. /data/app/~~hash=/base.apk=com.example)
        idx = content.rfind("=")
        if idx <= 0:
            continue
        apk_path = content[:idx]
        pkg = content[idx + 1:]
        if not pkg or "." not in pkg:
            continue
        packages.append({
            "package": pkg,
            "apk_path": apk_path,
            "label": _format_name(pkg),
            "is_system": pkg in system_pkgs,
            "is_enabled": pkg not in disabled_pkgs,
        })
    return packages


def _format_name(pkg):
    parts = pkg.split(".")
    name = parts[-1] if len(parts) > 1 else pkg
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    return name.replace("_", " ").replace("-", " ").title()


def get_app_detail(pkg):
    stdout, _, code = run_adb(["shell", "dumpsys", "package", pkg], timeout=15)
    if code != 0:
        return {}
    info = {"version": "", "version_code": "", "installed": "", "updated": "",
            "target_sdk": "", "min_sdk": "", "apk_path": "", "installer": "",
            "size": 0, "permissions": [], "uid": "", "data_dir": ""}
    in_perms = False
    for line in stdout.split("\n"):
        s = line.strip()
        if "versionName=" in s:
            m = re.search(r"versionName=(\S+)", s)
            if m: info["version"] = m.group(1)
        elif "versionCode=" in s:
            m = re.search(r"versionCode=(\d+)", s)
            if m: info["version_code"] = m.group(1)
        elif "firstInstallTime=" in s:
            m = re.search(r"firstInstallTime=(.*)", s)
            if m: info["installed"] = m.group(1).strip()
        elif "lastUpdateTime=" in s:
            m = re.search(r"lastUpdateTime=(.*)", s)
            if m: info["updated"] = m.group(1).strip()
        elif "targetSdk=" in s:
            m = re.search(r"targetSdk=(\d+)", s)
            if m: info["target_sdk"] = m.group(1)
        elif "minSdk=" in s:
            m = re.search(r"minSdk=(\d+)", s)
            if m: info["min_sdk"] = m.group(1)
        elif "codePath=" in s:
            m = re.search(r"codePath=(.*)", s)
            if m: info["apk_path"] = m.group(1).strip()
        elif "dataDir=" in s:
            m = re.search(r"dataDir=(.*)", s)
            if m: info["data_dir"] = m.group(1).strip()
        elif "userId=" in s:
            m = re.search(r"userId=(\d+)", s)
            if m: info["uid"] = m.group(1)
        elif "installerPackageName=" in s:
            m = re.search(r"installerPackageName=(.*)", s)
            if m: info["installer"] = m.group(1).strip()
        # Permissions
        if "requested permissions:" in s:
            in_perms = True
            continue
        if in_perms:
            if s.startswith("android.permission.") or s.startswith("com."):
                info["permissions"].append(s)
            elif s and not s.startswith(" "):
                in_perms = False

    path_out, _, _ = run_adb(["shell", "pm", "path", pkg])
    if path_out:
        apk = path_out.replace("package:", "").strip().split("\n")[0].replace("package:", "").strip()
        sz, _, _ = run_adb(["shell", "stat", "-c", "%s", apk])
        try:
            info["size"] = int(sz.strip())
        except:
            pass
    return info


# ═══════════════════════════════════════════════════════════
#  ALL APP ACTION DEFINITIONS
# ═══════════════════════════════════════════════════════════

# Each action: (id, label, emoji, color, hover_color, confirm, adb_func)
# adb_func takes (pkg) and returns (success: bool, message: str)

def _uid():
    return CURRENT_USER_ID

def _act_uninstall(pkg):
    """Uninstall but keep data."""
    out, err, code = run_adb(["shell", "pm", "uninstall", "-k", "--user", _uid(), pkg])
    return "Success" in out, out or err

def _act_uninstall_delete(pkg):
    """Uninstall and delete data."""
    out, err, code = run_adb(["shell", "pm", "uninstall", "--user", _uid(), pkg])
    return "Success" in out, out or err

def _act_uninstall_full(pkg):
    """Fully remove (for all users, root may be needed)."""
    out, err, code = run_adb(["uninstall", pkg])
    return "Success" in out or code == 0, out or err

def _act_disable(pkg):
    out, err, code = run_adb(["shell", "pm", "disable-user", "--user", _uid(), pkg])
    return "disabled" in out.lower() or "new state" in out.lower(), out or err

def _act_enable(pkg):
    out, err, code = run_adb(["shell", "pm", "enable", "--user", _uid(), pkg])
    return "enabled" in out.lower() or "new state" in out.lower(), out or err

def _act_hide(pkg):
    out, err, code = run_adb(["shell", "pm", "hide", "--user", _uid(), pkg])
    ok = code == 0 or "true" in out.lower()
    return ok, out or err or ("Đã ẩn" if ok else "Thất bại")

def _act_unhide(pkg):
    out, err, code = run_adb(["shell", "pm", "unhide", "--user", _uid(), pkg])
    ok = code == 0 or "true" in out.lower()
    return ok, out or err or ("Đã bỏ ẩn" if ok else "Thất bại")

def _act_suspend(pkg):
    out, err, code = run_adb(["shell", "pm", "suspend", "--user", _uid(), pkg])
    ok = code == 0 or "suspend" in out.lower()
    return ok, out or err or ("Đã tạm ngưng" if ok else "Thất bại")

def _act_unsuspend(pkg):
    out, err, code = run_adb(["shell", "pm", "unsuspend", "--user", _uid(), pkg])
    ok = code == 0 or "unsuspend" in out.lower()
    return ok, out or err or ("Đã bỏ tạm ngưng" if ok else "Thất bại")

def _act_clear(pkg):
    out, err, code = run_adb(["shell", "pm", "clear", "--user", _uid(), pkg])
    return "Success" in out, out or err

def _act_force_stop(pkg):
    out, err, code = run_adb(["shell", "am", "force-stop", "--user", _uid(), pkg])
    return code == 0, "Đã dừng" if code == 0 else err

def _act_launch(pkg):
    out, err, code = run_adb(["shell", "monkey", "-p", pkg, "-c",
                               "android.intent.category.LAUNCHER", "1"])
    return code == 0, "Đã khởi chạy" if code == 0 else err

def _act_reinstall(pkg):
    out, err, code = run_adb(["shell", "cmd", "package", "install-existing", "--user", _uid(), pkg])
    ok = "installed" in out.lower() or code == 0
    return ok, out or err

def _act_reset_permissions(pkg):
    out, err, code = run_adb(["shell", "pm", "reset-permissions", pkg])
    return code == 0, out or err or ("Đã đặt lại quyền" if code == 0 else "Thất bại")

def _act_trim_cache(pkg):
    out, err, code = run_adb(["shell", "pm", "trim-caches", "999999999999", pkg])
    return code == 0, out or err or "Đã dọn cache"

def _act_grant_all(pkg):
    info = get_app_detail(pkg)
    granted = 0
    runtime_perms = [p for p in info.get("permissions", [])
                     if "permission." in p]
    for perm in runtime_perms:
        out, err, code = run_adb(["shell", "pm", "grant", "--user", _uid(), pkg, perm])
        if code == 0:
            granted += 1
    return granted > 0 or len(runtime_perms) == 0, f"Đã cấp {granted}/{len(runtime_perms)} quyền"

def _act_revoke_all(pkg):
    info = get_app_detail(pkg)
    revoked = 0
    runtime_perms = [p for p in info.get("permissions", [])
                     if "permission." in p]
    for perm in runtime_perms:
        out, err, code = run_adb(["shell", "pm", "revoke", "--user", _uid(), pkg, perm])
        if code == 0:
            revoked += 1
    return revoked > 0 or len(runtime_perms) == 0, f"Đã thu hồi {revoked}/{len(runtime_perms)} quyền"

def _act_compile_speed(pkg):
    out, err, code = run_adb(["shell", "cmd", "package", "compile", "-m", "speed", "-f", pkg])
    return code == 0, out or err or "Đã tối ưu"

def _act_clear_compiled(pkg):
    out, err, code = run_adb(["shell", "cmd", "package", "compile", "--reset", pkg])
    return code == 0, out or err or "Đã xóa bản biên dịch"

def _act_default_state(pkg):
    out, err, code = run_adb(["shell", "pm", "default-state", "--user", _uid(), pkg])
    return code == 0, out or err or "Đã đặt về mặc định"

def _act_set_stopped(pkg):
    out, err, code = run_adb(["shell", "am", "set-stopped-state", "--user", _uid(), pkg, "true"])
    return code == 0, out or err or "Đã đặt trạng thái dừng"


# ═══════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════

class ADBAppManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("ADB App Manager")
        self.geometry("1200x750")
        self.minsize(950, 580)

        self.all_apps = []
        self.filtered_apps = []
        self.current_filter = "all"
        self.current_sort = "name_asc"
        self.device_info = None
        self.device_connected = False
        self.checked_pkgs = set()  # Checkbox state
        self.user_id = "0"
        self._stop_event = threading.Event()

        self._build_ui()
        self._start_device_monitor()

    def _build_ui(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_toolbar()
        self._build_table()
        self._build_actionbar()

    # ─── HEADER ─────────────────────────────────────────

    def _build_header(self):
        header = ctk.CTkFrame(self, height=70, corner_radius=0, fg_color="#111827")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        # Logo + Title
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=0, padx=16, pady=8, sticky="w")
        ctk.CTkLabel(title_frame, text="📱", font=("Segoe UI Emoji", 28)).pack(side="left", padx=(0, 10))
        text_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        text_frame.pack(side="left")
        ctk.CTkLabel(text_frame, text="ADB App Manager",
                     font=("Segoe UI", 18, "bold"), text_color="#818cf8").pack(anchor="w")
        ctk.CTkLabel(text_frame, text="Advanced Android Manager",
                     font=("Segoe UI", 10), text_color="#64748b").pack(anchor="w")

        # ── Device Control Buttons (center) ──
        dev_ctrl = ctk.CTkFrame(header, fg_color="transparent")
        dev_ctrl.grid(row=0, column=1, padx=8, pady=8)

        dev_btns = [
            ("🔄 Reboot", "#475569", self._reboot_normal),
            ("🛠️ Recovery", "#6366f1", self._reboot_recovery),
            ("⚡ Bootloader", "#f59e0b", self._reboot_bootloader),
            ("🔌 Fastboot", "#06b6d4", self._reboot_fastboot),
            ("⏻ Tắt nguồn", "#ef4444", self._power_off),
            ("📸 Chụp màn hình", "#10b981", self._screenshot),
        ]
        for text, color, cmd in dev_btns:
            ctk.CTkButton(dev_ctrl, text=text, width=105, height=28,
                          font=("Segoe UI", 10), corner_radius=6,
                          fg_color=color, hover_color="#1e293b",
                          command=cmd).pack(side="left", padx=2)

        # ── Device Status (right) ──
        self.device_frame = ctk.CTkFrame(header, fg_color="#1a2035", corner_radius=10,
                                          border_width=1, border_color="#2d3748")
        self.device_frame.grid(row=0, column=2, padx=16, pady=8, sticky="e")

        self.status_dot = ctk.CTkLabel(self.device_frame, text="●", font=("Segoe UI", 14),
                                        text_color="#ef4444", width=20)
        self.status_dot.pack(side="left", padx=(12, 6), pady=8)

        dev_text = ctk.CTkFrame(self.device_frame, fg_color="transparent")
        dev_text.pack(side="left", padx=(0, 12), pady=8)
        self.device_label = ctk.CTkLabel(dev_text, text="Chưa kết nối",
                                          font=("Segoe UI", 12, "bold"), text_color="#e2e8f0")
        self.device_label.pack(anchor="w")
        self.device_sublabel = ctk.CTkLabel(dev_text, text="Cắm USB & bật USB Debugging",
                                             font=("Segoe UI", 9), text_color="#64748b")
        self.device_sublabel.pack(anchor="w")

    # ─── TOOLBAR ────────────────────────────────────────

    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=50, corner_radius=0, fg_color="#0f1524")
        toolbar.grid(row=1, column=0, sticky="ew")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filters())
        search = ctk.CTkEntry(toolbar, placeholder_text="🔍 Tìm kiếm...",
                              textvariable=self.search_var, width=240,
                              font=("Segoe UI", 12), corner_radius=8,
                              fg_color="#1a2035", border_color="#2d3748")
        search.pack(side="left", padx=(16, 12), pady=8)

        self.filter_btns = {}
        filters = [("all", "Tất cả"), ("user", "Người dùng"), ("system", "Hệ thống"), ("disabled", "Đã tắt")]
        for key, text in filters:
            btn = ctk.CTkButton(toolbar, text=text, width=85, height=30,
                                font=("Segoe UI", 11), corner_radius=6,
                                fg_color="#6366f1" if key == "all" else "#1a2035",
                                hover_color="#4f46e5",
                                border_width=1, border_color="#2d3748",
                                command=lambda k=key: self._set_filter(k))
            btn.pack(side="left", padx=2, pady=8)
            self.filter_btns[key] = btn

        self.count_label = ctk.CTkLabel(toolbar, text="0 ứng dụng",
                                         font=("Segoe UI", 11), text_color="#64748b")
        self.count_label.pack(side="left", padx=10)

        # Right side
        self.sort_var = ctk.StringVar(value="Tên A→Z")
        ctk.CTkOptionMenu(toolbar, values=["Tên A→Z", "Tên Z→A", "Package A→Z", "Loại"],
                          variable=self.sort_var, width=120, height=30,
                          font=("Segoe UI", 11), corner_radius=6,
                          fg_color="#1a2035", button_color="#2d3748",
                          dropdown_fg_color="#1a2035",
                          command=self._on_sort_changed).pack(side="right", padx=16, pady=8)

        # Install APK button
        ctk.CTkButton(toolbar, text="📦 Cài APK", width=85, height=30,
                       font=("Segoe UI", 11), corner_radius=6,
                       fg_color="#10b981", hover_color="#059669",
                       command=self._install_apk).pack(side="right", padx=2, pady=8)

        ctk.CTkButton(toolbar, text="🔄 Làm mới", width=85, height=30,
                       font=("Segoe UI", 11), corner_radius=6,
                       fg_color="#1a2035", hover_color="#2d3748",
                       border_width=1, border_color="#2d3748",
                       command=self._refresh_apps).pack(side="right", padx=2, pady=8)

        # User ID selector
        user_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        user_frame.pack(side="right", padx=(2, 8), pady=8)
        ctk.CTkLabel(user_frame, text="User:", font=("Segoe UI", 10),
                      text_color="#64748b").pack(side="left", padx=(0, 4))
        self.user_var = ctk.StringVar(value="0")
        user_entry = ctk.CTkEntry(user_frame, textvariable=self.user_var,
                                   width=40, height=28, font=("Segoe UI", 11),
                                   fg_color="#1a2035", border_color="#2d3748",
                                   corner_radius=6, justify="center")
        user_entry.pack(side="left")
        self.user_var.trace_add("write", self._on_user_changed)

    # ─── TABLE ──────────────────────────────────────────

    def _build_table(self):
        table_frame = ctk.CTkFrame(self, fg_color="#0a0e17", corner_radius=0)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("App.Treeview", background="#111827", foreground="#e2e8f0",
                         fieldbackground="#111827", borderwidth=0,
                         font=("Segoe UI", 11), rowheight=34)
        style.configure("App.Treeview.Heading", background="#1a2035", foreground="#94a3b8",
                         borderwidth=0, font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("App.Treeview",
                   background=[("selected", "#312e81")],
                   foreground=[("selected", "#c7d2fe")])
        style.map("App.Treeview.Heading", background=[("active", "#1f2847")])

        columns = ("check", "name", "package", "type", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                  style="App.Treeview", selectmode="extended")

        self.tree.heading("check", text="☑", anchor="center")
        self.tree.heading("name", text="Tên ứng dụng", anchor="w")
        self.tree.heading("package", text="Package", anchor="w")
        self.tree.heading("type", text="Loại", anchor="center")
        self.tree.heading("status", text="Trạng thái", anchor="center")

        self.tree.column("check", width=40, minwidth=40, stretch=False, anchor="center")
        self.tree.column("name", width=200, minwidth=140)
        self.tree.column("package", width=320, minwidth=200)
        self.tree.column("type", width=100, minwidth=80, anchor="center")
        self.tree.column("status", width=90, minwidth=70, anchor="center")

        scrollbar = ctk.CTkScrollbar(table_frame, command=self.tree.yview,
                                      fg_color="#111827", button_color="#2d3748",
                                      button_hover_color="#4f46e5")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<Double-1>", lambda e: self._show_detail())
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Button-3>", self._on_right_click)

        # Click on ☑ heading = toggle all
        self.tree.heading("check", command=self._toggle_all_checks)

        # ── Context Menu (comprehensive) ──
        self.context_menu = tk.Menu(self, tearoff=0, bg="#1a2035", fg="#e2e8f0",
                                     activebackground="#4f46e5", activeforeground="white",
                                     font=("Segoe UI", 10), relief="flat", bd=1)

        self.context_menu.add_command(label="📋  Chi tiết", command=self._show_detail)
        self.context_menu.add_command(label="🚀  Khởi chạy", command=lambda: self._do_action("launch"))
        self.context_menu.add_separator()

        # Cài đặt & Gỡ
        self.context_menu.add_command(label="🗑️  Gỡ cài đặt (giữ data)", command=lambda: self._do_action("uninstall"))
        self.context_menu.add_command(label="�️  Gỡ + xóa dữ liệu", command=lambda: self._do_action("uninstall_delete"))
        self.context_menu.add_command(label="�💥  Gỡ hoàn toàn (all users)", command=lambda: self._do_action("uninstall_full"))
        self.context_menu.add_command(label="♻️  Cài lại (reinstall)", command=lambda: self._do_action("reinstall"))
        self.context_menu.add_separator()

        # Bật / Tắt / Ẩn / Đóng băng
        self.context_menu.add_command(label="🚫  Vô hiệu hóa", command=lambda: self._do_action("disable"))
        self.context_menu.add_command(label="✅  Bật lại", command=lambda: self._do_action("enable"))
        self.context_menu.add_command(label="👻  Ẩn (Hide)", command=lambda: self._do_action("hide"))
        self.context_menu.add_command(label="👁️  Bỏ ẩn (Unhide)", command=lambda: self._do_action("unhide"))
        self.context_menu.add_command(label="⏸️  Tạm ngưng (Suspend)", command=lambda: self._do_action("suspend"))
        self.context_menu.add_command(label="▶️  Bỏ tạm ngưng", command=lambda: self._do_action("unsuspend"))
        self.context_menu.add_separator()

        # Dữ liệu & Quyền
        self.context_menu.add_command(label="🧹  Xóa dữ liệu", command=lambda: self._do_action("clear"))
        self.context_menu.add_command(label="⏹️  Buộc dừng", command=lambda: self._do_action("force_stop"))
        self.context_menu.add_command(label="🛑  Đặt trạng thái dừng", command=lambda: self._do_action("set_stopped"))
        self.context_menu.add_command(label="🔓  Cấp tất cả quyền", command=lambda: self._do_action("grant_all"))
        self.context_menu.add_command(label="🔒  Thu hồi tất cả quyền", command=lambda: self._do_action("revoke_all"))
        self.context_menu.add_command(label="🔄  Đặt lại quyền", command=lambda: self._do_action("reset_permissions"))
        self.context_menu.add_separator()

        # Tối ưu & Sao lưu
        self.context_menu.add_command(label="⚡  Tối ưu (dexopt)", command=lambda: self._do_action("compile_speed"))
        self.context_menu.add_command(label="🧼  Xóa bản biên dịch", command=lambda: self._do_action("clear_compiled"))
        self.context_menu.add_command(label="🔙  Đặt về mặc định", command=lambda: self._do_action("default_state"))
        self.context_menu.add_command(label="💾  Sao lưu APK", command=lambda: self._do_action("backup"))

    # ─── ACTION BAR ─────────────────────────────────────

    def _build_actionbar(self):
        actionbar = ctk.CTkFrame(self, height=55, corner_radius=0, fg_color="#111827",
                                  border_width=1, border_color="#1a2035")
        actionbar.grid(row=3, column=0, sticky="ew")

        self.sel_label = ctk.CTkLabel(actionbar, text="Chọn ứng dụng để thao tác",
                                       font=("Segoe UI", 11), text_color="#64748b")
        self.sel_label.pack(side="left", padx=16)

        # Select All / Deselect All buttons
        ctk.CTkButton(actionbar, text="☐ Bỏ chọn", width=75, height=30,
                       font=("Segoe UI", 10), corner_radius=6,
                       fg_color="#1a2035", hover_color="#2d3748",
                       border_width=1, border_color="#2d3748",
                       command=self._deselect_all).pack(side="left", padx=2, pady=10)
        ctk.CTkButton(actionbar, text="☑ Chọn tất cả", width=85, height=30,
                       font=("Segoe UI", 10), corner_radius=6,
                       fg_color="#1a2035", hover_color="#2d3748",
                       border_width=1, border_color="#2d3748",
                       command=self._select_all).pack(side="left", padx=2, pady=10)

        # Primary actions (right to left)
        btn_configs = [
            ("💾 Sao lưu", "#6366f1", "#4f46e5", "backup"),
            ("⏹️ Dừng", "#3b82f6", "#2563eb", "force_stop"),
            ("🧹 Xóa data", "#64748b", "#475569", "clear"),
            ("▶️ Bỏ ngưng", "#06b6d4", "#0891b2", "unsuspend"),
            ("⏸️ Ngưng", "#8b5cf6", "#7c3aed", "suspend"),
            ("👁️ Bỏ ẩn", "#06b6d4", "#0891b2", "unhide"),
            ("👻 Ẩn", "#8b5cf6", "#7c3aed", "hide"),
            ("✅ Bật", "#10b981", "#059669", "enable"),
            ("🚫 Tắt", "#f59e0b", "#d97706", "disable"),
            ("🗑️ Gỡ+Xóa", "#ef4444", "#dc2626", "uninstall_delete"),
            ("🗑️ Gỡ", "#f97316", "#ea580c", "uninstall"),
            ("🚀 Mở", "#3b82f6", "#2563eb", "launch"),
        ]
        for text, color, hover, action in btn_configs:
            ctk.CTkButton(actionbar, text=text, width=75, height=30,
                           font=("Segoe UI", 10), corner_radius=6,
                           fg_color=color, hover_color=hover,
                           command=lambda a=action: self._do_action(a)).pack(side="right", padx=2, pady=10)

    # ─── DEVICE MONITORING ──────────────────────────────

    def _start_device_monitor(self):
        def monitor():
            prev_connected = None
            while not self._stop_event.is_set():
                info = get_device_info()
                connected = info is not None
                if connected != prev_connected or (connected and self.device_info != info):
                    self.device_info = info
                    self.device_connected = connected
                    self.after(0, self._update_device_ui)
                    if connected and prev_connected is not True:
                        self.after(100, self._refresh_apps)
                prev_connected = connected
                self._stop_event.wait(3)
        threading.Thread(target=monitor, daemon=True).start()

    def _update_device_ui(self):
        if self.device_connected and self.device_info:
            d = self.device_info
            self.status_dot.configure(text_color="#10b981")
            self.device_label.configure(text=f"{d['brand']} {d['model']}")
            self.device_sublabel.configure(text=f"Android {d['android']} • SDK {d['sdk']}")
            self.device_frame.configure(border_color="#10b981")
        else:
            self.status_dot.configure(text_color="#ef4444")
            self.device_label.configure(text="Chưa kết nối")
            self.device_sublabel.configure(text="Cắm USB & bật USB Debugging")
            self.device_frame.configure(border_color="#2d3748")
            if not self.device_connected:
                self.all_apps = []
                self.filtered_apps = []
                self._render_tree()
                self.count_label.configure(text="0 ứng dụng")

    def _on_user_changed(self, *args):
        """Update global user ID when user changes the field."""
        global CURRENT_USER_ID
        val = self.user_var.get().strip()
        if val.isdigit():
            CURRENT_USER_ID = val

    # ─── DEVICE ACTIONS ─────────────────────────────────

    def _device_action(self, label, adb_args):
        if not self.device_connected:
            messagebox.showwarning("Lỗi", "Chưa kết nối thiết bị.", parent=self)
            return
        if not messagebox.askyesno("Xác nhận", f"Bạn muốn {label}?", parent=self, icon="warning"):
            return
        def run():
            out, err, code = run_adb(adb_args, timeout=15)
            msg = out or err or ("Thành công" if code == 0 else "Thất bại")
            self.after(0, lambda: messagebox.showinfo(label, msg, parent=self))
        threading.Thread(target=run, daemon=True).start()

    def _reboot_normal(self):
        self._device_action("Khởi động lại", ["reboot"])

    def _reboot_recovery(self):
        self._device_action("Vào Recovery", ["reboot", "recovery"])

    def _reboot_bootloader(self):
        self._device_action("Vào Bootloader", ["reboot", "bootloader"])

    def _reboot_fastboot(self):
        self._device_action("Vào Fastboot", ["reboot", "fastboot"])

    def _power_off(self):
        self._device_action("Tắt nguồn", ["shell", "reboot", "-p"])

    def _screenshot(self):
        if not self.device_connected:
            messagebox.showwarning("Lỗi", "Chưa kết nối thiết bị.", parent=self)
            return
        save_path = filedialog.asksaveasfilename(
            title="Lưu ảnh chụp màn hình",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png")],
            initialfile=f"screenshot_{int(time.time())}.png",
            parent=self
        )
        if not save_path:
            return
        def capture():
            remote = "/sdcard/screenshot_temp.png"
            run_adb(["shell", "screencap", "-p", remote], timeout=10)
            _, err, code = run_adb(["pull", remote, save_path], timeout=15)
            run_adb(["shell", "rm", remote])
            if code == 0:
                self.after(0, lambda: messagebox.showinfo("Chụp màn hình",
                    f"Đã lưu:\n{save_path}", parent=self))
            else:
                self.after(0, lambda: messagebox.showerror("Lỗi",
                    f"Không thể chụp:\n{err}", parent=self))
        threading.Thread(target=capture, daemon=True).start()

    def _install_apk(self):
        if not self.device_connected:
            messagebox.showwarning("Lỗi", "Chưa kết nối thiết bị.", parent=self)
            return
        apk_path = filedialog.askopenfilename(
            title="Chọn file APK để cài đặt",
            filetypes=[("APK files", "*.apk")],
            parent=self
        )
        if not apk_path:
            return
        self.sel_label.configure(text=f"⏳ Đang cài đặt APK...", text_color="#f59e0b")
        def install():
            out, err, code = run_adb(["install", "-r", apk_path], timeout=120)
            ok = "Success" in out or code == 0
            self.after(0, lambda: self._on_install_done(ok, out or err))
        threading.Thread(target=install, daemon=True).start()

    def _on_install_done(self, success, msg):
        if success:
            messagebox.showinfo("Cài đặt APK", f"Cài đặt thành công!\n{msg}", parent=self)
            self._refresh_apps()
        else:
            messagebox.showerror("Cài đặt APK", f"Thất bại:\n{msg}", parent=self)
        self._on_selection_changed()

    # ─── APP LOADING ────────────────────────────────────

    def _refresh_apps(self):
        if not self.device_connected:
            return
        self.count_label.configure(text="⏳ Đang tải...")
        def load():
            apps = list_all_packages()
            self.after(0, lambda: self._on_apps_loaded(apps))
        threading.Thread(target=load, daemon=True).start()

    def _on_apps_loaded(self, apps):
        self.all_apps = apps
        self.checked_pkgs.clear()
        self._apply_filters()
        self._update_check_count()

    # ─── FILTERING & SORTING ────────────────────────────

    def _set_filter(self, filter_key):
        self.current_filter = filter_key
        for key, btn in self.filter_btns.items():
            btn.configure(fg_color="#6366f1" if key == filter_key else "#1a2035")
        self._apply_filters()

    def _on_sort_changed(self, value):
        sort_map = {"Tên A→Z": "name_asc", "Tên Z→A": "name_desc",
                     "Package A→Z": "pkg_asc", "Loại": "type"}
        self.current_sort = sort_map.get(value, "name_asc")
        self._apply_filters()

    def _apply_filters(self):
        apps = list(self.all_apps)
        if self.current_filter == "user":
            apps = [a for a in apps if not a["is_system"]]
        elif self.current_filter == "system":
            apps = [a for a in apps if a["is_system"]]
        elif self.current_filter == "disabled":
            apps = [a for a in apps if not a["is_enabled"]]

        q = self.search_var.get().strip().lower()
        if q:
            apps = [a for a in apps if q in a["label"].lower() or q in a["package"].lower()]

        if self.current_sort == "name_asc":
            apps.sort(key=lambda a: a["label"].lower())
        elif self.current_sort == "name_desc":
            apps.sort(key=lambda a: a["label"].lower(), reverse=True)
        elif self.current_sort == "pkg_asc":
            apps.sort(key=lambda a: a["package"].lower())
        elif self.current_sort == "type":
            apps.sort(key=lambda a: (a["is_system"], a["label"].lower()))

        self.filtered_apps = apps
        self._render_tree()
        total = len(self.all_apps)
        shown = len(apps)
        txt = f"{shown} / {total} ứng dụng" if shown != total else f"{total} ứng dụng"
        self.count_label.configure(text=txt)

    def _render_tree(self):
        self.tree.delete(*self.tree.get_children())
        for app in self.filtered_apps:
            pkg = app["package"]
            check_mark = "☑" if pkg in self.checked_pkgs else "☐"
            type_text = "🔒 Hệ thống" if app["is_system"] else "👤 User"
            status_text = "✅ Bật" if app["is_enabled"] else "⛔ Tắt"
            self.tree.insert("", "end", values=(check_mark, app["label"], pkg, type_text, status_text))

    # ─── CHECKBOX LOGIC ─────────────────────────────────

    def _on_tree_click(self, event):
        """Handle click on the checkbox column."""
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#1":  # First column = checkbox
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        values = self.tree.item(item, "values")
        if not values or len(values) < 3:
            return
        pkg = values[2]  # package is column index 2
        if pkg in self.checked_pkgs:
            self.checked_pkgs.discard(pkg)
            new_check = "☐"
        else:
            self.checked_pkgs.add(pkg)
            new_check = "☑"
        new_values = (new_check,) + values[1:]
        self.tree.item(item, values=new_values)
        self._update_check_count()
        return "break"

    def _toggle_all_checks(self):
        """Toggle all checkboxes (click on column header)."""
        visible_pkgs = {a["package"] for a in self.filtered_apps}
        all_checked = visible_pkgs.issubset(self.checked_pkgs)
        if all_checked:
            self.checked_pkgs -= visible_pkgs
        else:
            self.checked_pkgs |= visible_pkgs
        self._render_tree()
        self._update_check_count()

    def _select_all(self):
        for app in self.filtered_apps:
            self.checked_pkgs.add(app["package"])
        self._render_tree()
        self._update_check_count()

    def _deselect_all(self):
        self.checked_pkgs.clear()
        self._render_tree()
        self._update_check_count()

    def _update_check_count(self):
        count = len(self.checked_pkgs)
        if count > 0:
            self.sel_label.configure(text=f"✔️ Đã chọn {count} ứng dụng", text_color="#818cf8")
        else:
            self.sel_label.configure(text="Chọn ứng dụng để thao tác", text_color="#64748b")

    # ─── SELECTION ──────────────────────────────────────

    def _get_selected_packages(self):
        """Return checked packages. Falls back to tree selection if nothing checked."""
        if self.checked_pkgs:
            return list(self.checked_pkgs)
        pkgs = []
        for item_id in self.tree.selection():
            values = self.tree.item(item_id, "values")
            if values and len(values) >= 3:
                pkgs.append(values[2])
        return pkgs

    # ─── RIGHT CLICK ────────────────────────────────────

    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            # Also check the item
            values = self.tree.item(item, "values")
            if values and len(values) >= 3:
                pkg = values[2]
                if pkg not in self.checked_pkgs:
                    self.checked_pkgs.add(pkg)
                    new_values = ("☑",) + values[1:]
                    self.tree.item(item, values=new_values)
                    self._update_check_count()
            self.context_menu.tk_popup(event.x_root, event.y_root)

    # ─── DETAIL WINDOW ──────────────────────────────────

    def _show_detail(self):
        pkgs = self._get_selected_packages()
        if not pkgs:
            return
        pkg = pkgs[0]
        app = next((a for a in self.all_apps if a["package"] == pkg), None)
        if not app:
            return

        w = ctk.CTkToplevel(self)
        w.title(f"Chi tiết: {app['label']}")
        w.geometry("550x600")
        w.transient(self)
        w.grab_set()
        w.after(10, w.lift)

        main = ctk.CTkFrame(w, fg_color="#111827", corner_radius=0)
        main.pack(fill="both", expand=True)

        # Header
        hdr = ctk.CTkFrame(main, fg_color="#1a2035", corner_radius=0)
        hdr.pack(fill="x")
        tf = ctk.CTkFrame(hdr, fg_color="transparent")
        tf.pack(side="left", fill="x", expand=True, pady=14, padx=20)
        ctk.CTkLabel(tf, text=app["label"], font=("Segoe UI", 16, "bold"),
                      text_color="#e2e8f0").pack(anchor="w")
        ctk.CTkLabel(tf, text=pkg, font=("Consolas", 10),
                      text_color="#64748b").pack(anchor="w")

        loading = ctk.CTkLabel(main, text="⏳ Đang tải chi tiết...",
                                font=("Segoe UI", 12), text_color="#64748b")
        loading.pack(pady=20)

        def load():
            info = get_app_detail(pkg)
            self.after(0, lambda: show(info))

        def show(info):
            loading.destroy()
            scroll = ctk.CTkScrollableFrame(main, fg_color="#111827")
            scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))

            def row(label, value):
                r = ctk.CTkFrame(scroll, fg_color="#1a2035", corner_radius=8)
                r.pack(fill="x", pady=2)
                ctk.CTkLabel(r, text=label, font=("Segoe UI", 10), text_color="#64748b",
                              width=130, anchor="w").pack(side="left", padx=12, pady=7)
                ctk.CTkLabel(r, text=str(value) if value else "N/A", font=("Segoe UI", 11),
                              text_color="#e2e8f0", anchor="w", wraplength=320).pack(
                    side="left", fill="x", expand=True, padx=(0, 12), pady=7)

            row("Package", pkg)
            row("Phiên bản", info.get("version"))
            row("Mã version", info.get("version_code"))
            size = info.get("size", 0)
            row("Kích thước", f"{size/1048576:.1f} MB" if size > 1048576 else f"{size/1024:.1f} KB" if size > 1024 else "N/A")
            row("Loại", "🔒 Hệ thống" if app["is_system"] else "👤 Người dùng")
            row("Trạng thái", "✅ Bật" if app["is_enabled"] else "⛔ Tắt")
            row("UID", info.get("uid"))
            row("Target SDK", info.get("target_sdk"))
            row("Min SDK", info.get("min_sdk"))
            row("Ngày cài", info.get("installed"))
            row("Cập nhật", info.get("updated"))
            row("Nguồn cài", info.get("installer"))
            row("Đường dẫn", info.get("apk_path"))
            row("Data dir", info.get("data_dir"))

            perms = info.get("permissions", [])
            if perms:
                perm_text = "\n".join(perms[:20])
                if len(perms) > 20:
                    perm_text += f"\n... +{len(perms) - 20} quyền khác"
                row(f"Quyền ({len(perms)})", perm_text)

        threading.Thread(target=load, daemon=True).start()

    # ─── ALL ACTIONS ────────────────────────────────────

    def _do_action(self, action):
        pkgs = self._get_selected_packages()
        if not pkgs:
            messagebox.showinfo("Thông báo", "Chọn ít nhất 1 ứng dụng.", parent=self)
            return

        # Action mapping
        actions = {
            "launch":            ("Khởi chạy",             _act_launch,            False),
            "uninstall":         ("Gỡ cài đặt (giữ data)", _act_uninstall,         True),
            "uninstall_delete":  ("Gỡ + xóa dữ liệu",       _act_uninstall_delete,  True),
            "uninstall_full":    ("Gỡ hoàn toàn",          _act_uninstall_full,    True),
            "reinstall":         ("Cài lại",               _act_reinstall,         False),
            "disable":           ("Vô hiệu hóa",          _act_disable,           True),
            "enable":            ("Bật lại",               _act_enable,            False),
            "hide":              ("Ẩn ứng dụng",           _act_hide,              True),
            "unhide":            ("Bỏ ẩn",                 _act_unhide,            False),
            "suspend":           ("Tạm ngưng",             _act_suspend,           True),
            "unsuspend":         ("Bỏ tạm ngưng",         _act_unsuspend,         False),
            "clear":             ("Xóa dữ liệu",          _act_clear,             True),
            "force_stop":        ("Buộc dừng",             _act_force_stop,        False),
            "set_stopped":       ("Đặt trạng thái dừng",  _act_set_stopped,       False),
            "grant_all":         ("Cấp tất cả quyền",     _act_grant_all,         False),
            "revoke_all":        ("Thu hồi quyền",         _act_revoke_all,        True),
            "reset_permissions": ("Đặt lại quyền",        _act_reset_permissions, False),
            "compile_speed":     ("Tối ưu (dexopt)",       _act_compile_speed,     False),
            "clear_compiled":    ("Xóa bản biên dịch",    _act_clear_compiled,    False),
            "default_state":     ("Đặt về mặc định",      _act_default_state,     True),
            "trim_cache":        ("Dọn cache",             _act_trim_cache,        False),
            "backup":            ("Sao lưu APK",           None,                   False),  # special
        }

        if action not in actions:
            return

        label, func, need_confirm = actions[action]

        # Confirm dangerous actions
        if need_confirm:
            count = len(pkgs)
            if count == 1:
                app = next((a for a in self.all_apps if a["package"] == pkgs[0]), None)
                name = app["label"] if app else pkgs[0]
                msg = f"Bạn muốn {label.lower()}:\n\n{name}\n({pkgs[0]})?"
            else:
                msg = f"Bạn muốn {label.lower()} {count} ứng dụng đã chọn?"
            if not messagebox.askyesno(f"Xác nhận {label}", msg, parent=self, icon="warning"):
                return

        # Backup: special handling (needs directory)
        backup_dir = None
        if action == "backup":
            backup_dir = filedialog.askdirectory(title="Chọn thư mục lưu APK", parent=self)
            if not backup_dir:
                return

        self.sel_label.configure(text=f"⏳ Đang {label.lower()}...", text_color="#f59e0b")

        def execute():
            results = []
            for pkg in pkgs:
                try:
                    if action == "backup":
                        path_out, _, pc = run_adb(["shell", "pm", "path", pkg])
                        if pc == 0 and path_out:
                            apk = path_out.replace("package:", "").strip().split("\n")[0].replace("package:", "").strip()
                            dst = os.path.join(backup_dir, f"{pkg}.apk")
                            _, err, code = run_adb(["pull", apk, dst], timeout=120)
                            results.append((pkg, code == 0, f"Đã lưu: {dst}" if code == 0 else err))
                        else:
                            results.append((pkg, False, "Không tìm thấy APK"))
                    else:
                        ok, msg = func(pkg)
                        results.append((pkg, ok, msg))
                except Exception as e:
                    results.append((pkg, False, str(e)))
            self.after(0, lambda: self._on_action_done(action, label, results))
        threading.Thread(target=execute, daemon=True).start()

    def _on_action_done(self, action, label, results):
        success = sum(1 for _, ok, _ in results if ok)
        total = len(results)
        if success == total:
            messagebox.showinfo("Thành công", f"{label}: {success}/{total} thành công.", parent=self)
        elif success > 0:
            fails = "\n".join(f"❌ {p}: {m}" for p, ok, m in results if not ok)
            messagebox.showwarning("Một phần", f"{success}/{total} thành công\n\n{fails}", parent=self)
        else:
            fails = "\n".join(f"❌ {p}: {m}" for p, ok, m in results if not ok)
            messagebox.showerror("Thất bại", f"{label}\n\n{fails}", parent=self)

        # Refresh list for state-changing actions
        state_actions = ("uninstall", "uninstall_delete", "uninstall_full", "reinstall", "disable", "enable",
                         "hide", "unhide", "suspend", "unsuspend", "default_state")
        if action in state_actions and success > 0:
            self._refresh_apps()
        self._on_selection_changed()

    # ─── CLEANUP ────────────────────────────────────────

    def destroy(self):
        self._stop_event.set()
        try:
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
        except:
            pass
        super().destroy()


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not os.path.isfile(ADB_PATH):
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Không tìm thấy ADB tại:\n{ADB_PATH}\n\n"
            f"Đặt folder 'platform-tools' cùng thư mục với ứng dụng.",
            "ADB App Manager - Lỗi", 0x10
        )
        sys.exit(1)

    app = ADBAppManager()
    app.mainloop()
