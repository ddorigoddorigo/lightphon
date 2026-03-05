"""
LightPhon Node Client - GUI

Graphical interface for the host node with hardware detection and model management.
"""
import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from pathlib import Path
from configparser import ConfigParser
from datetime import datetime
import base64

# Debug info for compiled exe
print(f"[STARTUP] Python executable: {sys.executable}")
print(f"[STARTUP] Working directory: {os.getcwd()}")
print(f"[STARTUP] Frozen: {getattr(sys, 'frozen', False)}")
if getattr(sys, 'frozen', False):
    print(f"[STARTUP] Executable dir: {os.path.dirname(sys.executable)}")

# Windows autostart
try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

try:
    import requests
except ImportError:
    requests = None

# System tray support
try:
    import pystray
    from PIL import Image
    HAS_TRAY = True
except ImportError:
    pystray = None
    HAS_TRAY = False

# Add path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from node_client import NodeClient, detect_gpu, find_llama_binary
from hardware_detect import get_system_info, format_system_info
from model_manager import ModelManager, ModelInfo
from version import VERSION
from updater import AutoUpdater


class NodeGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"LightPhon Node - Host GPU v{VERSION}")
        self.root.geometry("800x650")
        self.root.resizable(True, True)
        
        # Icon (if available)
        try:
            self.root.iconbitmap('icon.ico')
        except:
            pass
        
        # Variables
        self.client = None
        # Use absolute path for config file
        # For PyInstaller exe, use the directory where the exe is located
        if getattr(sys, 'frozen', False):
            # Running as compiled exe - use AppData for config (Program Files is read-only)
            script_dir = os.path.dirname(sys.executable)
            config_dir = os.path.join(os.environ.get('LOCALAPPDATA', script_dir), 'LightPhon')
            os.makedirs(config_dir, exist_ok=True)
        else:
            # Running as script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_dir = script_dir
        self.script_dir = script_dir  # Save for later use
        self.config_path = os.path.join(config_dir, 'node_config.ini')
        self.config = ConfigParser()
        self.system_info = None
        self.model_manager = None
        self.config_loaded = False  # Flag to prevent premature config saves
        
        # Auto-updater
        self.updater = AutoUpdater(callback=self._on_update_available)
        self.update_pending = False
        
        # System tray
        self.tray_icon = None
        self.is_hidden = False
        
        # Style
        style = ttk.Style()
        style.configure('Connected.TLabel', foreground='green', font=('Arial', 12, 'bold'))
        style.configure('Disconnected.TLabel', foreground='red', font=('Arial', 12, 'bold'))
        style.configure('Header.TLabel', font=('Arial', 10, 'bold'))
        style.configure('Info.TLabel', font=('Arial', 9))
        style.configure('Update.TButton', foreground='orange')
        
        self._create_ui()
        self._load_config()
        self.config_loaded = True  # Now it's safe to save config
        
        # Detect hardware at startup
        self.root.after(100, self._detect_hardware)
        
        # Start auto-updater
        self.root.after(5000, self._start_updater)
        
        # Complete startup sequence after 1 second (models, settings, then connection)
        self.root.after(1000, self._complete_startup_sequence)
    
    def _complete_startup_sequence(self):
        """Complete the startup sequence in correct order"""
        print("[STARTUP] Starting complete initialization sequence...")
        
        # Step 1: Load models folder and models
        self._startup_load_models()
        
        # Step 2: Apply restricted mode settings (after 500ms)
        self.root.after(500, self._startup_apply_restricted)
        
        # Step 3: Auto-login if configured (after 1000ms)
        self.root.after(1000, self._startup_auto_login)
    
    def _startup_load_models(self):
        """Step 1: Load models folder and models"""
        print("[STARTUP] Step 1: Loading models...")
        
        folder = self.models_folder.get()
        if folder and os.path.exists(folder):
            print(f"[STARTUP] Models folder: {folder}")
            
            # Initialize model manager if not done
            if not self.model_manager:
                self._init_model_manager(folder, auto_load=False)
            
            # Load models from saved config or scan
            if self.model_manager:
                if self.model_manager.models:
                    models = list(self.model_manager.models.values())
                    self._update_models_list(models)
                    self.log(f"✓ Loaded {len(models)} models from saved configuration")
                    print(f"[STARTUP] Loaded {len(models)} models from config")
                else:
                    # No saved models, do a scan
                    self.log("No saved models, scanning folder...")
                    print("[STARTUP] No saved models, will scan...")
                    self._scan_models()
        else:
            print(f"[STARTUP] No models folder configured or doesn't exist: {folder}")
    
    def _startup_apply_restricted(self):
        """Step 2: Apply restricted mode settings"""
        print("[STARTUP] Step 2: Applying restricted mode settings...")
        
        if hasattr(self, 'restricted_mode') and self.restricted_mode.get():
            print(f"[STARTUP] Restricted mode is ON, allowed models: {self.allowed_models}")
            self.log(f"Restricted mode enabled, {len(self.allowed_models)} allowed models")
        else:
            print("[STARTUP] Restricted mode is OFF")
    
    def _startup_auto_login(self):
        """Step 3: Auto-login if configured"""
        print("[STARTUP] Step 3: Checking auto-login...")
        
        if hasattr(self, 'auth_token') and self.auth_token:
            print("[STARTUP] Auth token found, attempting auto-login...")
            self._try_auto_login()
        else:
            print("[STARTUP] No auth token, manual login required")
    
    def _create_ui(self):
        """Create the interface"""
        
        # Notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # === Tab 0: Account ===
        self.account_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.account_frame, text="👤 Account")
        self._create_account_tab()
        
        # === Tab 1: Hardware ===
        self.hw_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.hw_frame, text="🖥️ Hardware")
        self._create_hardware_tab()
        
        # === Tab 2: Connection ===
        self.conn_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.conn_frame, text="🔌 Connection")
        self._create_connection_tab()
        
        # === Tab 3: Models ===
        self.models_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.models_frame, text="🧠 Models")
        self._create_models_tab()
        
        # === Tab 4: Sessions ===
        self.sessions_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.sessions_frame, text="📊 Sessions")
        self._create_sessions_tab()
        
        # === Tab 5: Log ===
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="📝 Log")
        self._create_log_tab()
        
        # === Tab 6: LLM Output ===
        self.llm_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.llm_frame, text="🤖 LLM Output")
        self._create_llm_tab()
        
        # === Tab 7: RAG Knowledge Base ===
        self.rag_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.rag_frame, text="📚 RAG")
        self._create_rag_tab()
        
        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_var = tk.StringVar(value="Starting...")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.status_label.pack(fill=tk.X, side=tk.LEFT, expand=True)
        
        # Settings button
        self.settings_btn = ttk.Button(status_frame, text="Settings", width=8, command=self.open_settings)
        self.settings_btn.pack(side=tk.RIGHT, padx=2)
        
        # Update check button
        self.update_btn = ttk.Button(status_frame, text="Update", width=8, command=self.check_update_manual)
        self.update_btn.pack(side=tk.RIGHT, padx=2)
        
        # Version label
        version_label = ttk.Label(status_frame, text=f"v{VERSION}", font=('Arial', 8))
        version_label.pack(side=tk.RIGHT, padx=5)
        
        self.conn_indicator = ttk.Label(status_frame, text="● Disconnected", style='Disconnected.TLabel')
        self.conn_indicator.pack(side=tk.RIGHT, padx=10)
        
        # Save config on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def _create_account_tab(self):
        """Tab Account - Login and Registration"""
        
        # Account variables
        self.logged_in = False
        self.auth_token = None
        self.user_info = {}
        
        # Frame principale
        main_frame = ttk.Frame(self.account_frame, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header = ttk.Label(main_frame, text="👤 LightPhon Account", font=('Arial', 16, 'bold'))
        header.pack(pady=(0, 20))
        
        # === Login Frame (default visible) ===
        self.login_frame = ttk.LabelFrame(main_frame, text="🔐 Login", padding=15)
        self.login_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(self.login_frame, text="Email/Username:").grid(row=0, column=0, sticky='w', pady=5)
        self.login_username = tk.StringVar()
        ttk.Entry(self.login_frame, textvariable=self.login_username, width=40).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.login_frame, text="Password:").grid(row=1, column=0, sticky='w', pady=5)
        self.login_password = tk.StringVar()
        ttk.Entry(self.login_frame, textvariable=self.login_password, show='*', width=40).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        
        # Options frame
        options_frame = ttk.Frame(self.login_frame)
        options_frame.grid(row=2, column=0, columnspan=2, pady=5)
        
        self.save_password = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="💾 Save Password", variable=self.save_password).pack(side=tk.LEFT, padx=10)
        
        self.auto_connect = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="🔌 Auto-Connect on Login", variable=self.auto_connect).pack(side=tk.LEFT, padx=10)
        
        self.autostart_windows = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="🚀 Start with Windows", variable=self.autostart_windows, 
                       command=self._toggle_autostart).pack(side=tk.LEFT, padx=10)
        
        btn_frame = ttk.Frame(self.login_frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=15)
        
        self.login_btn = ttk.Button(btn_frame, text="🔑 Login", command=self._do_login, width=15)
        self.login_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="📝 Register", command=self._show_register, width=15).pack(side=tk.LEFT, padx=5)
        
        self.login_status = tk.StringVar(value="")
        ttk.Label(self.login_frame, textvariable=self.login_status, foreground='red').grid(row=4, column=0, columnspan=2, pady=5)
        
        self.login_frame.columnconfigure(1, weight=1)
        
        # === Registration Frame (hidden by default) ===
        self.register_frame = ttk.LabelFrame(main_frame, text="📝 Registration", padding=15)
        # Don't pack, will be shown with _show_register
        
        ttk.Label(self.register_frame, text="Username:").grid(row=0, column=0, sticky='w', pady=5)
        self.reg_username = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_username, width=40).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Email:").grid(row=1, column=0, sticky='w', pady=5)
        self.reg_email = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_email, width=40).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Password:").grid(row=2, column=0, sticky='w', pady=5)
        self.reg_password = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_password, show='*', width=40).grid(row=2, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Confirm Password:").grid(row=3, column=0, sticky='w', pady=5)
        self.reg_confirm = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_confirm, show='*', width=40).grid(row=3, column=1, padx=10, pady=5, sticky='ew')
        
        reg_btn_frame = ttk.Frame(self.register_frame)
        reg_btn_frame.grid(row=4, column=0, columnspan=2, pady=15)
        
        ttk.Button(reg_btn_frame, text="✓ Register", command=self._do_register, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(reg_btn_frame, text="← Back to Login", command=self._show_login, width=15).pack(side=tk.LEFT, padx=5)
        
        self.register_status = tk.StringVar(value="")
        ttk.Label(self.register_frame, textvariable=self.register_status, foreground='red').grid(row=5, column=0, columnspan=2, pady=5)
        
        self.register_frame.columnconfigure(1, weight=1)
        
        # === Connected Account Frame (hidden by default) ===
        self.account_info_frame = ttk.LabelFrame(main_frame, text="✓ Connected Account", padding=15)
        # Don't pack, will be shown after login
        
        self.account_user_var = tk.StringVar(value="")
        ttk.Label(self.account_info_frame, text="👤 User:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_user_var, font=('Arial', 11)).grid(row=0, column=1, sticky='w', padx=10, pady=5)
        
        self.account_email_var = tk.StringVar(value="")
        ttk.Label(self.account_info_frame, text="📧 Email:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_email_var, font=('Arial', 10)).grid(row=1, column=1, sticky='w', padx=10, pady=5)
        
        self.account_balance_var = tk.StringVar(value="0 sats")
        ttk.Label(self.account_info_frame, text="⚡ Balance:", font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_balance_var, font=('Arial', 11, 'bold'), foreground='orange').grid(row=2, column=1, sticky='w', padx=10, pady=5)
        
        self.account_earnings_var = tk.StringVar(value="0 sats")
        ttk.Label(self.account_info_frame, text="💰 Node Earnings:", font=('Arial', 10, 'bold')).grid(row=3, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_earnings_var, font=('Arial', 11, 'bold'), foreground='green').grid(row=3, column=1, sticky='w', padx=10, pady=5)
        
        account_btn_frame = ttk.Frame(self.account_info_frame)
        account_btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        
        ttk.Button(account_btn_frame, text="🔄 Refresh", command=self._refresh_account, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(account_btn_frame, text="🚪 Logout", command=self._do_logout, width=12).pack(side=tk.LEFT, padx=5)
        
        self.account_info_frame.columnconfigure(1, weight=1)
        
        # Note
        note_frame = ttk.Frame(main_frame)
        note_frame.pack(fill=tk.X, pady=20)
        
        note_text = (
            "ℹ️ Log in with the same account you use on lightphon.com\n"
            "   Your node earnings will be credited to your balance.\n"
            "   You can then withdraw satoshis via Lightning Network."
        )
        ttk.Label(note_frame, text=note_text, font=('Arial', 9), foreground='gray', justify='left').pack(anchor='w')
        
        # Load saved credentials
        self._load_account_config()
    
    def _show_register(self):
        """Show registration form"""
        self.login_frame.pack_forget()
        self.register_frame.pack(fill=tk.X, pady=10)
    
    def _show_login(self):
        """Show login form"""
        self.register_frame.pack_forget()
        self.login_frame.pack(fill=tk.X, pady=10)
    
    def _load_account_config(self):
        """Load saved credentials"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            saved_username = self.config.get('Account', 'username', fallback='')
            saved_token = self.config.get('Account', 'token', fallback='')
            saved_password_enc = self.config.get('Account', 'saved_password', fallback='')
            
            # Load options
            self.save_password.set(self.config.getboolean('Account', 'save_password', fallback=False))
            self.auto_connect.set(self.config.getboolean('Account', 'auto_connect', fallback=False))
            
            # Check Windows autostart status
            self.autostart_windows.set(self._check_autostart())
            
            if saved_username:
                self.login_username.set(saved_username)
            
            # Load saved password if enabled
            if saved_password_enc and self.save_password.get():
                try:
                    self.login_password.set(base64.b64decode(saved_password_enc).decode('utf-8'))
                except:
                    pass
            
            # Save auth token for startup sequence (don't auto-login here)
            if saved_token:
                self.auth_token = saved_token
    
    def _try_auto_login(self):
        """Try automatic login with saved token"""
        if not self.auth_token:
            return
        
        self.login_status.set("Auto-login in progress...")
        
        def do_auto():
            try:
                server_url = "https://lightphon.com"
                response = requests.get(
                    f"{server_url}/api/me",
                    headers={'Authorization': f'Bearer {self.auth_token}'},
                    timeout=10
                )
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        self.root.after(0, lambda: self._on_login_success(data, auto=True))
                    except (ValueError, requests.exceptions.JSONDecodeError):
                        self.auth_token = None
                        self.root.after(0, lambda: self.login_status.set("Server error, please login manually"))
                else:
                    # Token expired/invalid
                    self.auth_token = None
                    self.root.after(0, lambda: self.login_status.set("Session expired, please login"))
            except requests.exceptions.ConnectionError:
                self.root.after(0, lambda: self.login_status.set("Cannot connect to server"))
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: self.login_status.set(f"Error: {msg}"))
        
        threading.Thread(target=do_auto, daemon=True).start()
    
    def _do_login(self):
        """Execute login"""
        username = self.login_username.get().strip()
        password = self.login_password.get()
        
        if not username or not password:
            self.login_status.set("Enter username and password")
            return
        
        self.login_status.set("Logging in...")
        self.login_btn.config(state='disabled')
        
        def do_login():
            try:
                server_url = "https://lightphon.com"
                response = requests.post(
                    f"{server_url}/api/login",
                    json={'username': username, 'password': password},
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                
                # Try to parse JSON response
                try:
                    data = response.json()
                except (ValueError, requests.exceptions.JSONDecodeError) as json_err:
                    # Response is not valid JSON - log for debugging
                    print(f"[LOGIN DEBUG] Status: {response.status_code}")
                    print(f"[LOGIN DEBUG] Headers: {dict(response.headers)}")
                    print(f"[LOGIN DEBUG] Response text: {response.text[:500]}")
                    print(f"[LOGIN DEBUG] JSON error: {json_err}")
                    self.root.after(0, lambda: self.login_status.set(f"❌ Server error (invalid response)"))
                    self.root.after(0, lambda: self.login_btn.config(state='normal'))
                    return
                
                if response.status_code == 200:
                    self.auth_token = data.get('token')
                    self.root.after(0, lambda: self._on_login_success(data))
                else:
                    error = data.get('error', 'Login failed')
                    self.root.after(0, lambda: self.login_status.set(f"❌ {error}"))
                    self.root.after(0, lambda: self.login_btn.config(state='normal'))
            except requests.exceptions.ConnectionError:
                self.root.after(0, lambda: self.login_status.set("❌ Cannot connect to server"))
                self.root.after(0, lambda: self.login_btn.config(state='normal'))
            except requests.exceptions.Timeout:
                self.root.after(0, lambda: self.login_status.set("❌ Connection timeout"))
                self.root.after(0, lambda: self.login_btn.config(state='normal'))
            except Exception as e:
                self.root.after(0, lambda: self.login_status.set(f"❌ Error: {e}"))
                self.root.after(0, lambda: self.login_btn.config(state='normal'))
        
        threading.Thread(target=do_login, daemon=True).start()
    
    def _on_login_success(self, data, auto=False):
        """Login success callback"""
        self.logged_in = True
        self.user_info = data
        
        # For normal login, update auth_token from response
        # For auto-login, keep existing token (it was already used successfully)
        if not auto and data.get('token'):
            self.auth_token = data.get('token')
        
        # Save token, username and optionally password
        if 'Account' not in self.config:
            self.config['Account'] = {}
        self.config['Account']['username'] = self.login_username.get() or data.get('username', '')
        self.config['Account']['token'] = self.auth_token or ''
        self.config['Account']['save_password'] = str(self.save_password.get()).lower()
        self.config['Account']['auto_connect'] = str(self.auto_connect.get()).lower()
        
        # Save password if enabled (encoded in base64)
        if self.save_password.get() and self.login_password.get():
            encoded = base64.b64encode(self.login_password.get().encode('utf-8')).decode('utf-8')
            self.config['Account']['saved_password'] = encoded
        else:
            self.config['Account']['saved_password'] = ''
        
        self._save_config()
        
        # Update UI
        self.account_user_var.set(data.get('username', ''))
        self.account_email_var.set(data.get('email', ''))
        balance = data.get('balance', 0)
        self.account_balance_var.set(f"{balance:,} sats".replace(',', '.'))
        
        # Hide login, show account info
        self.login_frame.pack_forget()
        self.register_frame.pack_forget()
        self.account_info_frame.pack(fill=tk.X, pady=10)
        
        self.login_btn.config(state='normal')
        self.login_status.set("")
        
        self.log(f"Logged in: {data.get('username')}")
        self.update_status(f"Connected as: {data.get('username')}")
        
        # Load node earnings
        self._load_node_earnings()
        
        # After login, ensure models are loaded and apply settings before connecting
        if self.auto_connect.get():
            self.root.after(500, self._prepare_and_connect)
    
    def _do_register(self):
        """Execute registration"""
        username = self.reg_username.get().strip()
        email = self.reg_email.get().strip()
        password = self.reg_password.get()
        confirm = self.reg_confirm.get()
        
        if not username or not email or not password:
            self.register_status.set("Fill in all fields")
            return
        
        if password != confirm:
            self.register_status.set("Passwords do not match")
            return
        
        if len(password) < 8:
            self.register_status.set("Password must be at least 8 characters")
            return
        
        self.register_status.set("Registering...")
        
        def do_register():
            try:
                server_url = "https://lightphon.com"
                response = requests.post(
                    f"{server_url}/api/register",
                    json={'username': username, 'email': email, 'password': password},
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                
                if response.status_code == 201:
                    self.root.after(0, lambda: self.register_status.set(""))
                    self.root.after(0, lambda: messagebox.showinfo("Registration", "✓ Registration completed!\nYou can now login."))
                    self.root.after(0, self._show_login)
                    self.root.after(0, lambda: self.login_username.set(username))
                else:
                    try:
                        error = response.json().get('error', 'Registration failed')
                    except (ValueError, requests.exceptions.JSONDecodeError):
                        error = f"Server error ({response.status_code})"
                    self.root.after(0, lambda: self.register_status.set(f"❌ {error}"))
            except requests.exceptions.ConnectionError:
                self.root.after(0, lambda: self.register_status.set("❌ Cannot connect to server"))
            except Exception as e:
                self.root.after(0, lambda: self.register_status.set(f"❌ Error: {e}"))
        
        threading.Thread(target=do_register, daemon=True).start()
    
    def _do_logout(self):
        """Execute logout"""
        self.logged_in = False
        self.auth_token = None
        self.user_info = {}
        
        # Remove saved token
        if 'Account' in self.config:
            self.config['Account']['token'] = ''
            self._save_config()
        
        # Show login
        self.account_info_frame.pack_forget()
        self.login_frame.pack(fill=tk.X, pady=10)
        self.login_password.set('')
        
        self.log("Logged out")
        self.update_status("Disconnected from account")
    
    def _refresh_account(self):
        """Refresh account info"""
        if not self.auth_token:
            return
        
        def do_refresh():
            try:
                server_url = "https://lightphon.com"
                response = requests.get(
                    f"{server_url}/api/me",
                    headers={'Authorization': f'Bearer {self.auth_token}'},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.user_info = data
                    self.root.after(0, lambda: self.account_user_var.set(data.get('username', '')))
                    self.root.after(0, lambda: self.account_email_var.set(data.get('email', '')))
                    balance = data.get('balance', 0)
                    self.root.after(0, lambda: self.account_balance_var.set(f"{balance:,} sats".replace(',', '.')))
                    self.root.after(0, lambda: self.update_status("Account updated"))
                    self.root.after(0, self._load_node_earnings)
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Error updating account: {e}"))
        
        threading.Thread(target=do_refresh, daemon=True).start()
    
    def _load_node_earnings(self):
        """Load node earnings from account"""
        # Earnings are already in balance, but we might want to show separately
        # For now show that balance includes node earnings
        self.account_earnings_var.set("Included in balance ⬆️")
    
    def _check_autostart(self):
        """Check if autostart is enabled in Windows registry"""
        if not HAS_WINREG:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                               r"Software\Microsoft\Windows\CurrentVersion\Run", 
                               0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "LightPhonNode")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except:
            return False
    
    def _toggle_autostart(self):
        """Toggle Windows autostart"""
        if not HAS_WINREG:
            messagebox.showwarning("Not Available", "Windows autostart is not available on this system.")
            self.autostart_windows.set(False)
            return
        
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                               r"Software\Microsoft\Windows\CurrentVersion\Run", 
                               0, winreg.KEY_SET_VALUE)
            
            if self.autostart_windows.get():
                # Add to autostart
                exe_path = sys.executable
                self.log(f"Executable path: {exe_path}")
                
                if exe_path.endswith('python.exe') or exe_path.endswith('pythonw.exe'):
                    # Running from Python, use script path
                    script_path = os.path.abspath(__file__)
                    value = f'"{exe_path}" "{script_path}"'
                else:
                    # Running as exe (PyInstaller)
                    value = f'"{exe_path}"'
                
                self.log(f"Setting autostart registry value: {value}")
                winreg.SetValueEx(key, "LightPhonNode", 0, winreg.REG_SZ, value)
                self.log("✓ Added to Windows autostart")
                messagebox.showinfo("Autostart", "✓ LightPhon Node will start automatically with Windows.")
            else:
                # Remove from autostart
                try:
                    winreg.DeleteValue(key, "LightPhonNode")
                    self.log("✓ Removed from Windows autostart")
                    messagebox.showinfo("Autostart", "LightPhon Node removed from autostart.")
                except FileNotFoundError:
                    pass
            
            winreg.CloseKey(key)
        except Exception as e:
            self.log(f"Error setting autostart: {e}")
            messagebox.showerror("Error", f"Could not modify autostart: {e}")
            self.autostart_windows.set(not self.autostart_windows.get())
    
    def _auto_connect_to_server(self):
        """Auto-connect to server after login"""
        self.log("Auto-connecting to server...")
        # Switch to Connection tab
        self.notebook.select(2)
        # Trigger connection
        self.root.after(500, self.connect)
    
    def _prepare_and_connect(self):
        """Ensure models and settings are ready, then connect"""
        print("[AUTO-CONNECT] Preparing for auto-connect...")
        self.log("Preparing for connection...")
        
        # Step 1: Ensure models folder is loaded
        folder = self.models_folder.get()
        if folder and os.path.exists(folder):
            if not self.model_manager:
                self._init_model_manager(folder, auto_load=False)
            
            # Load models if not already loaded
            if self.model_manager and not self.model_manager.models:
                self.log("Loading models before connection...")
                models = self.model_manager.scan_models()
                if models:
                    self._update_models_list(models)
            elif self.model_manager and self.model_manager.models:
                # Update UI with existing models
                models = list(self.model_manager.models.values())
                self._update_models_list(models)
        
        # Step 2: Apply restricted mode settings
        if hasattr(self, 'restricted_mode') and self.restricted_mode.get():
            self.log(f"Restricted mode: ON ({len(self.allowed_models)} allowed models)")
            print(f"[AUTO-CONNECT] Restricted mode ON, allowed: {self.allowed_models}")
        
        # Step 3: Connect to server
        self.root.after(500, self._auto_connect_to_server)
    
    def _create_hardware_tab(self):
        """Hardware information tab"""
        
        # System info frame
        info_frame = ttk.LabelFrame(self.hw_frame, text="System Information", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Text area for hardware info
        self.hw_text = scrolledtext.ScrolledText(info_frame, height=15, font=('Consolas', 10))
        self.hw_text.pack(fill=tk.BOTH, expand=True)
        self.hw_text.insert(tk.END, "Detecting hardware...")
        self.hw_text.config(state='disabled')
        
        # Buttons
        btn_frame = ttk.Frame(self.hw_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_frame, text="🔄 Detect Hardware", command=self._detect_hardware).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📋 Copy Info", command=self._copy_hw_info).pack(side=tk.LEFT, padx=5)
        
        # Quick summary
        summary_frame = ttk.LabelFrame(self.hw_frame, text="Quick Summary", padding=10)
        summary_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Grid info
        self.hw_summary = {}
        labels = [
            ('cpu', 'CPU:', 0, 0),
            ('cores', 'Cores:', 0, 2),
            ('ram', 'RAM:', 1, 0),
            ('gpu', 'GPU:', 2, 0),
            ('vram', 'VRAM:', 2, 2),
            ('max_model', 'Max Model:', 3, 0),
        ]
        
        for key, text, row, col in labels:
            ttk.Label(summary_frame, text=text, style='Header.TLabel').grid(row=row, column=col, sticky='w', padx=5, pady=2)
            self.hw_summary[key] = tk.StringVar(value="-")
            ttk.Label(summary_frame, textvariable=self.hw_summary[key], style='Info.TLabel').grid(row=row, column=col+1, sticky='w', padx=5, pady=2)
        
        # Configura colonne
        for i in range(4):
            summary_frame.columnconfigure(i, weight=1)
    
    def _create_connection_tab(self):
        """Connection tab"""
        
        # Server info (fixed)
        server_frame = ttk.LabelFrame(self.conn_frame, text="LightPhon Server", padding=10)
        server_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Fixed server URL - not editable
        # Use direct IP until DNS is properly configured
        self.server_url = tk.StringVar(value="https://lightphon.com")
        ttk.Label(server_frame, text="Server:", font=('Arial', 10)).grid(row=0, column=0, sticky='w', pady=5)
        ttk.Label(server_frame, text="lightphon.com", font=('Arial', 10, 'bold'), foreground='green').grid(row=0, column=1, sticky='w', padx=10, pady=5)
        
        ttk.Label(server_frame, text="Node Name:").grid(row=1, column=0, sticky='w', pady=5)
        self.node_name = tk.StringVar(value="")
        ttk.Entry(server_frame, textvariable=self.node_name, width=50).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(optional, to identify the node)", font=('Arial', 8)).grid(row=1, column=2, sticky='w')
        
        ttk.Label(server_frame, text="Token:").grid(row=2, column=0, sticky='w', pady=5)
        self.token = tk.StringVar()
        ttk.Entry(server_frame, textvariable=self.token, width=50, show='*').grid(row=2, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(optional, for authentication)", font=('Arial', 8)).grid(row=2, column=2, sticky='w')
        
        server_frame.columnconfigure(1, weight=1)
        
        # Pricing settings
        pricing_frame = ttk.LabelFrame(self.conn_frame, text="💰 Price per Minute", padding=10)
        pricing_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(pricing_frame, text="Satoshi/minute:", font=('Arial', 10)).grid(row=0, column=0, sticky='w', pady=5)
        self.price_per_minute = tk.StringVar(value="100")
        self.price_per_minute.trace_add('write', self._on_price_changed)
        price_spin = ttk.Spinbox(pricing_frame, textvariable=self.price_per_minute, from_=1, to=100000, width=15, font=('Arial', 12))
        price_spin.grid(row=0, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(pricing_frame, text="sats", font=('Arial', 10, 'bold')).grid(row=0, column=2, sticky='w')
        
        # Price suggestions
        price_hints = ttk.Frame(pricing_frame)
        price_hints.grid(row=1, column=0, columnspan=4, sticky='w', pady=10)
        
        ttk.Label(price_hints, text="Suggestions:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        ttk.Button(price_hints, text="50 sats (budget)", command=lambda: self.price_per_minute.set("50"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="100 sats (standard)", command=lambda: self.price_per_minute.set("100"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="500 sats (premium)", command=lambda: self.price_per_minute.set("500"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="1000 sats (high-end)", command=lambda: self.price_per_minute.set("1000"), width=15).pack(side=tk.LEFT, padx=3)
        
        ttk.Label(pricing_frame, text="⚡ Users will pay this amount for each minute of using your node", 
                  font=('Arial', 9), foreground='gray').grid(row=2, column=0, columnspan=4, sticky='w', pady=5)
        
        pricing_frame.columnconfigure(1, weight=1)
        
        # Connection buttons
        btn_frame = ttk.Frame(self.conn_frame)
        btn_frame.pack(pady=20)
        
        self.connect_btn = ttk.Button(btn_frame, text="🔌 Connect", command=self.connect, width=15)
        self.connect_btn.pack(side=tk.LEFT, padx=10)
        
        self.disconnect_btn = ttk.Button(btn_frame, text="❌ Disconnect", command=self.disconnect, state='disabled', width=15)
        self.disconnect_btn.pack(side=tk.LEFT, padx=10)
        
        # Connection status
        status_frame = ttk.LabelFrame(self.conn_frame, text="Connection Status", padding=10)
        status_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.conn_status = tk.StringVar(value="Not connected to server")
        ttk.Label(status_frame, textvariable=self.conn_status, font=('Arial', 11)).pack(anchor='w')
        
        self.conn_details = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.conn_details, font=('Arial', 9)).pack(anchor='w', pady=5)
        
        # Hidden variables for llama-server (configured via command line)
        self.llama_command = tk.StringVar(value="llama-server")
        self.gpu_layers = tk.StringVar(value="-1")
    
    def _create_models_tab(self):
        """Models management tab"""
        
        # Restricted Mode Frame
        restricted_frame = ttk.LabelFrame(self.models_frame, text="🔒 Restricted Mode", padding=5)
        restricted_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Top row with checkbox
        restricted_top = ttk.Frame(restricted_frame)
        restricted_top.pack(fill=tk.X)
        
        self.restricted_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            restricted_top, 
            text="Enable Restricted Mode (only allow selected models, block HuggingFace on-demand)", 
            variable=self.restricted_mode,
            command=self._on_restricted_mode_change
        ).pack(side=tk.LEFT, padx=5)
        
        # Apply button (visible and prominent)
        self.apply_restricted_btn = ttk.Button(
            restricted_top, 
            text="⚡ Apply to Server", 
            command=self._apply_restricted_settings
        )
        self.apply_restricted_btn.pack(side=tk.RIGHT, padx=10)
        
        ttk.Label(restricted_frame, text="ℹ️ When enabled, users can only use models marked with ✓ in 'Allowed' column. Click 'Apply to Server' after changes.", 
                  font=('Arial', 8)).pack(side=tk.LEFT, padx=10)
        
        # Toolbar
        toolbar = ttk.Frame(self.models_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="📁 Select Models Folder", command=self._select_models_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🔄 Scan", command=self._scan_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🤗 Add HuggingFace", command=self._add_huggingface_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="☁️ Sync with Server", command=self._sync_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🗑️ Remove", command=self._remove_selected_model).pack(side=tk.LEFT, padx=5)
        
        # Disk space info
        disk_frame = ttk.LabelFrame(self.models_frame, text="📊 Disk Space", padding=5)
        disk_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.disk_info_var = tk.StringVar(value="Checking disk space...")
        self.disk_info_label = ttk.Label(disk_frame, textvariable=self.disk_info_var, font=('Arial', 9))
        self.disk_info_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(disk_frame, text="🔄", command=self._update_disk_info, width=3).pack(side=tk.RIGHT, padx=5)
        
        # Models folder
        folder_frame = ttk.Frame(self.models_frame)
        folder_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(folder_frame, text="Models folder:").pack(side=tk.LEFT)
        self.models_folder = tk.StringVar(value="")
        ttk.Label(folder_frame, textvariable=self.models_folder, font=('Arial', 9)).pack(side=tk.LEFT, padx=10)
        
        # Models list with checkboxes
        list_frame = ttk.LabelFrame(self.models_frame, text="Available Models (Local and HuggingFace)", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Treeview for models
        columns = ('enabled', 'allowed', 'source', 'name', 'params', 'quant', 'size', 'vram', 'context', 'uses')
        self.models_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        self.models_tree.heading('enabled', text='✓')
        self.models_tree.heading('allowed', text='🔒')
        self.models_tree.heading('source', text='Source')
        self.models_tree.heading('name', text='Name / Filename')
        self.models_tree.heading('params', text='Parameters')
        self.models_tree.heading('quant', text='Quantiz.')
        self.models_tree.heading('size', text='Size')
        self.models_tree.heading('vram', text='VRAM Min')
        self.models_tree.heading('context', text='Context')
        self.models_tree.heading('uses', text='Uses')
        
        self.models_tree.column('enabled', width=30, anchor='center')
        self.models_tree.column('allowed', width=30, anchor='center')
        self.models_tree.column('source', width=60, anchor='center')
        self.models_tree.column('name', width=260)
        self.models_tree.column('params', width=70, anchor='center')
        self.models_tree.column('quant', width=70, anchor='center')
        self.models_tree.column('size', width=70, anchor='center')
        self.models_tree.column('vram', width=70, anchor='center')
        self.models_tree.column('context', width=70, anchor='center')
        self.models_tree.column('uses', width=50, anchor='center')
        
        self.models_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.models_tree.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.models_tree.config(yscrollcommand=scrollbar.set)
        
        # Bind click per toggle
        self.models_tree.bind('<Double-1>', self._toggle_model)
        
        # Selected model details
        details_frame = ttk.LabelFrame(self.models_frame, text="Model Details", padding=5)
        details_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.model_details = tk.StringVar(value="Select a model to see details")
        ttk.Label(details_frame, textvariable=self.model_details, font=('Arial', 9)).pack(anchor='w')
        
        # Note about context
        ttk.Label(details_frame, text="ℹ️ Context length is set by the user when creating a session", 
                  font=('Arial', 8), foreground='gray').pack(anchor='w', pady=5)
        
        self.models_tree.bind('<<TreeviewSelect>>', self._on_model_select)
    
    def _create_sessions_tab(self):
        """Active sessions tab"""
        
        # Toolbar
        toolbar = ttk.Frame(self.sessions_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🔄 Refresh", command=self._refresh_sessions).pack(side=tk.LEFT, padx=5)
        
        # Statistics
        stats_frame = ttk.LabelFrame(self.sessions_frame, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.X, padx=10, pady=5)
        
        stats_grid = ttk.Frame(stats_frame)
        stats_grid.pack(fill=tk.X)
        
        self.stats = {
            'total_sessions': tk.StringVar(value="0"),
            'active_sessions': tk.StringVar(value="0"),
            'completed_requests': tk.StringVar(value="0"),
            'total_tokens': tk.StringVar(value="0"),
            'earnings': tk.StringVar(value="0 sats")
        }
        
        labels = [
            ('Total Sessions:', 'total_sessions'),
            ('Active Sessions:', 'active_sessions'),
            ('Completed Requests:', 'completed_requests'),
            ('Generated Tokens:', 'total_tokens'),
            ('Earnings:', 'earnings')
        ]
        
        for i, (label, key) in enumerate(labels):
            ttk.Label(stats_grid, text=label, font=('Arial', 9, 'bold')).grid(row=0, column=i*2, padx=10, pady=5)
            ttk.Label(stats_grid, textvariable=self.stats[key], font=('Arial', 9)).grid(row=0, column=i*2+1, padx=5, pady=5)
        
        # Sessions list
        list_frame = ttk.LabelFrame(self.sessions_frame, text="Active Sessions", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        columns = ('id', 'model', 'status', 'started', 'requests', 'tokens')
        self.sessions_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        self.sessions_tree.heading('id', text='Session ID')
        self.sessions_tree.heading('model', text='Model')
        self.sessions_tree.heading('status', text='Status')
        self.sessions_tree.heading('started', text='Started')
        self.sessions_tree.heading('requests', text='Requests')
        self.sessions_tree.heading('tokens', text='Tokens')
        
        self.sessions_tree.column('id', width=100)
        self.sessions_tree.column('model', width=150)
        self.sessions_tree.column('status', width=80, anchor='center')
        self.sessions_tree.column('started', width=150)
        self.sessions_tree.column('requests', width=80, anchor='center')
        self.sessions_tree.column('tokens', width=80, anchor='center')
        
        self.sessions_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.sessions_tree.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.sessions_tree.config(yscrollcommand=scrollbar.set)
    
    def _create_log_tab(self):
        """Log tab"""
        
        toolbar = ttk.Frame(self.log_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🗑️ Clear Log", command=self._clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="💾 Save Log", command=self._save_log).pack(side=tk.LEFT, padx=5)
        
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=20, font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.log_text.config(state='disabled')
    
    def _create_llm_tab(self):
        """Tab to display real-time LLM output"""
        
        # Info frame
        info_frame = ttk.Frame(self.llm_frame)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.llm_session_var = tk.StringVar(value="No active session")
        ttk.Label(info_frame, text="Session:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)
        ttk.Label(info_frame, textvariable=self.llm_session_var, font=('Arial', 9)).pack(side=tk.LEFT, padx=10)
        
        self.llm_tokens_var = tk.StringVar(value="Tokens: 0")
        ttk.Label(info_frame, textvariable=self.llm_tokens_var, font=('Arial', 9)).pack(side=tk.RIGHT, padx=10)
        
        # Toolbar
        toolbar = ttk.Frame(self.llm_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🗑️ Clear", command=self._clear_llm_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="📋 Copy", command=self._copy_llm_output).pack(side=tk.LEFT, padx=5)
        
        self.llm_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.llm_autoscroll).pack(side=tk.LEFT, padx=10)
        
        # Prompt section
        prompt_frame = ttk.LabelFrame(self.llm_frame, text="📥 Received Prompt", padding=5)
        prompt_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.llm_prompt_text = scrolledtext.ScrolledText(prompt_frame, height=4, font=('Consolas', 9), wrap=tk.WORD)
        self.llm_prompt_text.pack(fill=tk.X, expand=False)
        self.llm_prompt_text.config(state='disabled', bg='#2a2a3a', fg='#aaaaaa')
        
        # Output section
        output_frame = ttk.LabelFrame(self.llm_frame, text="📤 LLM Output (Token by Token)", padding=5)
        output_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.llm_output_text = scrolledtext.ScrolledText(output_frame, height=15, font=('Consolas', 10), wrap=tk.WORD)
        self.llm_output_text.pack(fill=tk.BOTH, expand=True)
        self.llm_output_text.config(state='disabled', bg='#1a1a2a', fg='#00ff00')
        
        # Token counter per sessione
        self.llm_token_count = 0

    def _clear_llm_output(self):
        """Clear LLM output"""
        self.llm_prompt_text.config(state='normal')
        self.llm_prompt_text.delete('1.0', tk.END)
        self.llm_prompt_text.config(state='disabled')
        
        self.llm_output_text.config(state='normal')
        self.llm_output_text.delete('1.0', tk.END)
        self.llm_output_text.config(state='disabled')
        
        self.llm_token_count = 0
        self.llm_tokens_var.set("Tokens: 0")
        self.llm_session_var.set("No active session")
    
    def _copy_llm_output(self):
        """Copy LLM output to clipboard"""
        output = self.llm_output_text.get('1.0', tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(output)
        self.update_status("LLM output copied to clipboard")
    
    def llm_set_prompt(self, session_id, prompt):
        """Set the displayed prompt"""
        def update():
            self.llm_session_var.set(f"Session: {session_id}")
            self.llm_token_count = 0
            self.llm_tokens_var.set("Tokens: 0")
            
            self.llm_prompt_text.config(state='normal')
            self.llm_prompt_text.delete('1.0', tk.END)
            self.llm_prompt_text.insert(tk.END, prompt[-2000:] if len(prompt) > 2000 else prompt)  # Limita a 2000 char
            self.llm_prompt_text.config(state='disabled')
            
            self.llm_output_text.config(state='normal')
            self.llm_output_text.delete('1.0', tk.END)
            self.llm_output_text.config(state='disabled')
            
            # Switch to LLM tab
            self.notebook.select(self.llm_frame)
        
        self.root.after(0, update)
    
    def llm_add_token(self, token, is_final=False):
        """Aggiunge un token all'output"""
        def update():
            self.llm_token_count += 1
            self.llm_tokens_var.set(f"Token: {self.llm_token_count}")
            
            self.llm_output_text.config(state='normal')
            self.llm_output_text.insert(tk.END, token)
            self.llm_output_text.config(state='disabled')
            
            if self.llm_autoscroll.get():
                self.llm_output_text.see(tk.END)
            
            if is_final:
                self.llm_output_text.config(state='normal')
                self.llm_output_text.insert(tk.END, "\n\n--- Generation complete ---\n")
                self.llm_output_text.config(state='disabled')
        
        self.root.after(0, update)
    
    def llm_session_ended(self, session_id):
        """Callback when a session is terminated by user"""
        def update():
            self.llm_output_text.config(state='normal')
            self.llm_output_text.insert(tk.END, f"\n\n🛑 Session {session_id} terminated by user.\n")
            self.llm_output_text.insert(tk.END, "The model has been unloaded from memory.\n")
            self.llm_output_text.config(state='disabled')
            
            if self.llm_autoscroll.get():
                self.llm_output_text.see(tk.END)
            
            # Reset prompt state
            self.llm_prompt_text.config(state='normal')
            self.llm_prompt_text.delete('1.0', tk.END)
            self.llm_prompt_text.insert(tk.END, "(Waiting for new session...)")
            self.llm_prompt_text.config(state='disabled')
            
            # Reset token counter
            self.llm_token_count = 0
            self.llm_tokens_var.set("Tokens: 0")
        
        self.root.after(0, update)

    # === RAG Tab ===
    
    def _create_rag_tab(self):
        """Tab for RAG (Retrieval-Augmented Generation) document management"""
        
        # Enable/Disable frame
        toggle_frame = ttk.LabelFrame(self.rag_frame, text="RAG Settings", padding=10)
        toggle_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.rag_enabled_var = tk.BooleanVar(value=True)  # RAG enabled by default
        ttk.Checkbutton(
            toggle_frame, 
            text="Enable RAG (Augment prompts with knowledge base)", 
            variable=self.rag_enabled_var,
            command=self._toggle_rag
        ).pack(side=tk.LEFT)
        
        ttk.Label(toggle_frame, text="Context chunks:").pack(side=tk.LEFT, padx=(20, 5))
        self.rag_topk_var = tk.StringVar(value="3")
        topk_spin = ttk.Spinbox(toggle_frame, from_=1, to=10, width=5, textvariable=self.rag_topk_var)
        topk_spin.pack(side=tk.LEFT)
        
        # Add document frame
        add_frame = ttk.LabelFrame(self.rag_frame, text="Add Document", padding=10)
        add_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(add_frame, text="📄 Add File", command=self._rag_add_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(add_frame, text="📋 Add Text", command=self._rag_add_text).pack(side=tk.LEFT, padx=5)
        
        self.rag_status_var = tk.StringVar(value="")
        ttk.Label(add_frame, textvariable=self.rag_status_var, foreground='blue').pack(side=tk.LEFT, padx=20)
        
        # Documents list
        docs_frame = ttk.LabelFrame(self.rag_frame, text="Indexed Documents", padding=10)
        docs_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Treeview for documents
        columns = ('filename', 'chunks', 'doc_id')
        self.rag_tree = ttk.Treeview(docs_frame, columns=columns, show='headings', height=10)
        self.rag_tree.heading('filename', text='Filename')
        self.rag_tree.heading('chunks', text='Chunks')
        self.rag_tree.heading('doc_id', text='Document ID')
        self.rag_tree.column('filename', width=300)
        self.rag_tree.column('chunks', width=80)
        self.rag_tree.column('doc_id', width=150)
        
        scrollbar = ttk.Scrollbar(docs_frame, orient=tk.VERTICAL, command=self.rag_tree.yview)
        self.rag_tree.configure(yscrollcommand=scrollbar.set)
        
        self.rag_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Buttons frame
        btn_frame = ttk.Frame(self.rag_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_frame, text="🗑️ Remove Selected", command=self._rag_remove_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 Refresh", command=self._rag_refresh_list).pack(side=tk.LEFT, padx=5)
        
        # Stats frame
        self.rag_stats_var = tk.StringVar(value="Documents: 0 | Chunks: 0")
        ttk.Label(btn_frame, textvariable=self.rag_stats_var, foreground='gray').pack(side=tk.RIGHT, padx=10)
        
        # Load initial state
        self._rag_refresh_list()
    
    def _toggle_rag(self):
        """Toggle RAG on/off"""
        enabled = self.rag_enabled_var.get()
        top_k = int(self.rag_topk_var.get())
        
        if self.client:
            self.client.rag_enabled = enabled
            self.client.rag_top_k = top_k
            self.log(f"RAG {'enabled' if enabled else 'disabled'}, top_k={top_k}")
            self.rag_status_var.set(f"RAG {'enabled' if enabled else 'disabled'}")
    
    def _rag_add_file(self):
        """Add a file to RAG knowledge base"""
        from tkinter import filedialog
        
        filetypes = [
            ('Text files', '*.txt'),
            ('Markdown', '*.md'),
            ('PDF', '*.pdf'),
            ('Word', '*.docx'),
            ('Python', '*.py'),
            ('All files', '*.*')
        ]
        
        filepath = filedialog.askopenfilename(
            title="Select document to add",
            filetypes=filetypes
        )
        
        if not filepath:
            return
        
        self.rag_status_var.set(f"Processing {os.path.basename(filepath)}...")
        
        def process():
            try:
                from rag_manager import read_document
                content, filename = read_document(filepath)
                
                if not self.client:
                    self.root.after(0, lambda: self.rag_status_var.set("Error: Node not connected"))
                    return
                
                # Need active session for embeddings
                if not self.client.active_sessions:
                    self.root.after(0, lambda: self.rag_status_var.set("Error: Load a model first"))
                    return
                
                # Get first active session's port
                session_id = list(self.client.active_sessions.keys())[0]
                llama = self.client.active_sessions[session_id]
                self.client.rag_manager.set_llama_port(llama.port)
                
                def progress_cb(current, total, msg):
                    self.root.after(0, lambda: self.rag_status_var.set(msg))
                
                success, message = self.client.rag_manager.add_document(content, filename, progress_cb)
                
                def update_ui():
                    self.rag_status_var.set(message)
                    self._rag_refresh_list()
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                self.root.after(0, lambda: self.rag_status_var.set(f"Error: {str(e)}"))
        
        threading.Thread(target=process, daemon=True).start()
    
    def _rag_add_text(self):
        """Add raw text to RAG knowledge base"""
        # Simple dialog for text input
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Text to Knowledge Base")
        dialog.geometry("600x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Document name:").pack(padx=10, pady=(10, 0), anchor='w')
        name_entry = ttk.Entry(dialog, width=50)
        name_entry.pack(padx=10, pady=5, fill=tk.X)
        name_entry.insert(0, "custom_document.txt")
        
        ttk.Label(dialog, text="Content:").pack(padx=10, anchor='w')
        text_area = scrolledtext.ScrolledText(dialog, height=15)
        text_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        
        def add():
            content = text_area.get('1.0', tk.END).strip()
            filename = name_entry.get() or "document.txt"
            
            if not content:
                messagebox.showerror("Error", "Please enter some text")
                return
            
            dialog.destroy()
            self.rag_status_var.set(f"Processing {filename}...")
            
            def process():
                try:
                    if not self.client or not self.client.active_sessions:
                        self.root.after(0, lambda: self.rag_status_var.set("Error: Load a model first"))
                        return
                    
                    session_id = list(self.client.active_sessions.keys())[0]
                    llama = self.client.active_sessions[session_id]
                    self.client.rag_manager.set_llama_port(llama.port)
                    
                    success, message = self.client.rag_manager.add_document(content, filename)
                    
                    def update_ui():
                        self.rag_status_var.set(message)
                        self._rag_refresh_list()
                    
                    self.root.after(0, update_ui)
                    
                except Exception as e:
                    self.root.after(0, lambda: self.rag_status_var.set(f"Error: {str(e)}"))
            
            threading.Thread(target=process, daemon=True).start()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Add", command=add).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def _rag_remove_selected(self):
        """Remove selected document from knowledge base"""
        selected = self.rag_tree.selection()
        if not selected:
            return
        
        item = self.rag_tree.item(selected[0])
        doc_id = item['values'][2]
        filename = item['values'][0]
        
        if messagebox.askyesno("Confirm", f"Remove '{filename}' from knowledge base?"):
            if self.client:
                success, message = self.client.rag_manager.remove_document(doc_id)
                self.rag_status_var.set(message)
                self._rag_refresh_list()
    
    def _rag_refresh_list(self):
        """Refresh the documents list"""
        # Clear existing
        for item in self.rag_tree.get_children():
            self.rag_tree.delete(item)
        
        if not self.client:
            return
        
        # Get documents from RAG manager
        docs = self.client.rag_manager.list_documents()
        stats = self.client.rag_manager.get_stats()
        
        for doc in docs:
            self.rag_tree.insert('', tk.END, values=(
                doc['filename'],
                doc['chunk_count'],
                doc['doc_id']
            ))
        
        self.rag_stats_var.set(f"Documents: {stats['document_count']} | Chunks: {stats['total_chunks']}")
        
        # Update enabled state from client
        if self.client:
            self.rag_enabled_var.set(self.client.rag_enabled)
            self.rag_topk_var.set(str(self.client.rag_top_k))

    # === Hardware Detection ===
    
    def _detect_hardware(self):
        """Detect system hardware"""
        self.update_status("Detecting hardware...")
        
        def detect():
            try:
                self.system_info = get_system_info()
                self.root.after(0, self._update_hw_display)
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Error detecting hardware: {e}"))
        
        threading.Thread(target=detect, daemon=True).start()
    
    def _update_hw_display(self):
        """Update hardware display"""
        if not self.system_info:
            return
        
        # Update text area
        self.hw_text.config(state='normal')
        self.hw_text.delete('1.0', tk.END)
        self.hw_text.insert(tk.END, format_system_info(self.system_info))
        self.hw_text.config(state='disabled')
        
        # Update summary
        info = self.system_info
        self.hw_summary['cpu'].set(info['cpu']['name'][:40] + '...' if len(info['cpu']['name']) > 40 else info['cpu']['name'])
        self.hw_summary['cores'].set(f"{info['cpu']['cores_physical']} physical / {info['cpu']['cores_logical']} logical")
        self.hw_summary['ram'].set(f"{info['ram']['total_gb']} GB")
        
        if info['gpus']:
            gpu_names = ', '.join([g['name'] for g in info['gpus'][:2]])
            if len(info['gpus']) > 2:
                gpu_names += f" (+{len(info['gpus'])-2})"
            self.hw_summary['gpu'].set(gpu_names[:50])
            self.hw_summary['vram'].set(f"{info['total_vram_mb']} MB")
        else:
            self.hw_summary['gpu'].set("No dedicated GPU")
            self.hw_summary['vram'].set("-")
        
        self.hw_summary['max_model'].set(f"~{info['max_model_params_b']}B params (Q4)")
        
        self.update_status(f"Hardware detected: {len(info['gpus'])} GPU, {info['total_vram_mb']} MB VRAM")
        self.log(f"Hardware detected: CPU {info['cpu']['cores_logical']} cores, {info['ram']['total_gb']} GB RAM, {len(info['gpus'])} GPU")
    
    def _copy_hw_info(self):
        """Copy hardware info to clipboard"""
        self.root.clipboard_clear()
        self.root.clipboard_append(format_system_info(self.system_info))
        self.update_status("Hardware info copied to clipboard")
    
    # === Models Management ===
    
    def _select_models_folder(self):
        """Select models folder"""
        folder = filedialog.askdirectory(title="Select GGUF models folder")
        if folder:
            self.models_folder.set(folder)
            self._save_config()  # Save folder immediately
            self.log(f"Models folder set to: {folder}")
            self._init_model_manager(folder, auto_load=False)  # Don't auto-load, will scan
            self._scan_models()
    
    def _init_model_manager(self, folder, auto_load=True):
        """Initialize model manager and optionally load saved models"""
        self.model_manager = ModelManager(folder)
        print(f"[DEBUG] ModelManager initialized with folder: {folder}")
        print(f"[DEBUG] Loaded {len(self.model_manager.models)} models from config")
        
        # Load saved models into the UI immediately if requested
        if auto_load and self.model_manager.models:
            # Load immediately instead of with after() - UI should be ready
            models = list(self.model_manager.models.values())
            if models and hasattr(self, 'models_tree'):
                self._update_models_list(models)
                print(f"[DEBUG] Models list updated with {len(models)} models")
    
    def _load_saved_models(self):
        """Load previously saved models into the UI without rescanning"""
        if not self.model_manager:
            return
        
        models = list(self.model_manager.models.values())
        if models:
            self.log(f"Loading {len(models)} saved models from config...")
            self._update_models_list(models)
            self.log(f"✓ Loaded {len(models)} models from saved configuration")
        else:
            self.log("No saved models found. Click 'Scan' to find models in the folder.")
    
    def _on_restricted_mode_change(self):
        """Handle restricted mode checkbox change"""
        is_restricted = self.restricted_mode.get()
        self._save_config()
        self.log(f"Restricted mode: {'enabled' if is_restricted else 'disabled'}")
        
        # Update client settings
        if self.client:
            self.client.restricted_models = is_restricted
        
        if is_restricted and not self.allowed_models:
            messagebox.showinfo("Restricted Mode", 
                "Restricted mode enabled!\n\n"
                "Now double-click on the 🔒 column to select which models\n"
                "are allowed when users connect to your node.\n\n"
                "Users will NOT be able to request HuggingFace models on-demand.\n\n"
                "Click '⚡ Apply to Server' to send changes to the server.")
    
    def _apply_restricted_settings(self):
        """Force sync restricted mode settings to server"""
        if not self.client:
            messagebox.showerror("Error", "Not connected. Please connect first.")
            return
            
        if not self.client.is_connected():
            messagebox.showerror("Error", "Not connected to server. Please reconnect.")
            return
        
        # Update client with current settings
        is_restricted = self.restricted_mode.get()
        allowed_list = list(self.allowed_models)
        
        self.client.restricted_models = is_restricted
        self.client.allowed_models_list = allowed_list
        
        self.log(f"Applying restricted settings to server...")
        self.log(f"  - Restricted mode: {is_restricted}")
        self.log(f"  - Allowed models: {allowed_list}")
        
        # Sync settings
        success = self.client.sync_settings()
        
        if success:
            self.log("✓ Settings applied to server successfully!")
            messagebox.showinfo("Success", 
                f"Settings applied to server!\n\n"
                f"Restricted Mode: {'ON' if is_restricted else 'OFF'}\n"
                f"Allowed Models: {len(allowed_list)}")
        else:
            self.log("✗ Failed to apply settings to server")
            messagebox.showerror("Error", "Failed to sync settings. Check connection.")
    
    def _save_restricted_config(self):
        """Save restricted mode settings to config"""
        self._save_config()
        
        allowed_list = list(self.allowed_models)
        is_restricted = self.restricted_mode.get() if hasattr(self, 'restricted_mode') else False
        
        self.log(f"Restricted config saved locally: restricted={is_restricted}, {len(allowed_list)} models allowed")
        
        # Update client settings (but don't sync - user will click Apply)
        if self.client:
            self.client.allowed_models_list = allowed_list
            self.client.restricted_models = is_restricted
            self.log("ℹ️ Click '⚡ Apply to Server' to send changes to the server")
    
    def _on_price_changed(self, *args):
        """Handle price per minute change"""
        try:
            price = int(self.price_per_minute.get())
            self._save_config()
            
            # Sync settings to server if connected
            if self.client and self.client.is_connected():
                self.client.price_per_minute = price
                self.client.sync_settings()
        except ValueError:
            pass  # Invalid value, ignore
    
    def _scan_models(self):
        """Scan models"""
        if not self.model_manager:
            folder = self.models_folder.get()
            if not folder:
                messagebox.showwarning("Warning", "Select a models folder first")
                return
            self._init_model_manager(folder, auto_load=False)
        
        self.update_status("Scanning models...")
        
        def scan():
            try:
                models = self.model_manager.scan_models()
                self.root.after(0, lambda: self._update_models_list(models))
                self.root.after(0, self._update_disk_info)  # Also update disk space
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Scan error: {e}"))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _update_models_list(self, models):
        """Update models list"""
        # Clear list
        for item in self.models_tree.get_children():
            self.models_tree.delete(item)
        
        # Sort models: unused first (use_count = 0), then by use_count ascending
        sorted_models = sorted(models, key=lambda m: (getattr(m, 'use_count', 0) > 0, getattr(m, 'use_count', 0)))
        
        # Initialize allowed_models set if not exists
        if not hasattr(self, 'allowed_models'):
            self.allowed_models = set()
        
        # Add models
        unused_count = 0
        for model in sorted_models:
            enabled = '✓' if model.enabled else '✗'
            # Check if model is allowed in restricted mode
            allowed = '✓' if model.id in self.allowed_models else '✗'
            # Indicate if HuggingFace or local
            source = '🤗 HF' if getattr(model, 'is_huggingface', False) else '📁 Local'
            # Use filename as display name (full GGUF filename)
            display_name = model.filename if model.filename else model.name
            use_count = getattr(model, 'use_count', 0)
            
            # Tag unused models
            tags = ()
            if use_count == 0:
                tags = ('unused',)
                unused_count += 1
            
            self.models_tree.insert('', 'end', iid=model.id, values=(
                enabled,
                allowed,
                source,
                display_name,
                model.parameters,
                model.quantization,
                f"{model.size_gb:.2f} GB",
                f"{model.min_vram_mb} MB",
                model.context_length,
                use_count
            ), tags=tags)
        
        # Configure tag colors
        self.models_tree.tag_configure('unused', foreground='#ff6b6b')
        
        status_msg = f"Found {len(models)} models"
        if unused_count > 0:
            status_msg += f" ({unused_count} never used - highlighted in red)"
        self.update_status(status_msg)
        self.log(f"Scan completed: {len(models)} models found, {unused_count} never used")
    
    def _toggle_model(self, event):
        """Toggle model enabled state"""
        item = self.models_tree.selection()
        if not item:
            return
        
        model_id = item[0]
        if self.model_manager:
            model = self.model_manager.get_model_by_id(model_id)
            if model:
                # Check which column was clicked
                column = self.models_tree.identify_column(event.x)
                
                if column == '#1':  # Enabled column
                    new_state = not model.enabled
                    self.model_manager.set_model_enabled(model_id, new_state)
                    
                    # Update UI (first column is enabled)
                    enabled = '✓' if new_state else '✗'
                    values = list(self.models_tree.item(model_id, 'values'))
                    values[0] = enabled
                    self.models_tree.item(model_id, values=values)
                    
                elif column == '#2':  # Allowed column (for restricted mode)
                    if not hasattr(self, 'allowed_models'):
                        self.allowed_models = set()
                    
                    if model_id in self.allowed_models:
                        self.allowed_models.discard(model_id)
                        self.log(f"Model '{model_id}' removed from allowed list")
                    else:
                        self.allowed_models.add(model_id)
                        self.log(f"Model '{model_id}' added to allowed list")
                    
                    # Update UI (second column is allowed)
                    allowed = '✓' if model_id in self.allowed_models else '✗'
                    values = list(self.models_tree.item(model_id, 'values'))
                    values[1] = allowed
                    self.models_tree.item(model_id, values=values)
                    
                    # Save to config and sync to server
                    self._save_restricted_config()
    
    def _on_model_select(self, event):
        """Model selection"""
        item = self.models_tree.selection()
        if not item or not self.model_manager:
            return
        
        model = self.model_manager.get_model_by_id(item[0])
        if model:
            if getattr(model, 'is_huggingface', False):
                details = f"🤗 HuggingFace: {model.hf_repo}\n"
            else:
                details = f"📁 File: {model.filename}\n"
            details += f"Architecture: {model.architecture}\n"
            details += f"VRAM: {model.min_vram_mb} MB min, {model.recommended_vram_mb} MB recommended\n"
            # Add usage stats
            use_count = getattr(model, 'use_count', 0)
            last_used = getattr(model, 'last_used', '')
            if use_count > 0:
                details += f"📊 Usage: {use_count} times"
                if last_used:
                    details += f" | Last used: {last_used[:10]}"
            else:
                details += f"⚠️ Never used - consider removing to save disk space"
            self.model_details.set(details)
    
    def _add_huggingface_model(self):
        """Open dialog to add HuggingFace model"""
        # Create model_manager if it doesn't exist (use current directory for config)
        if not self.model_manager:
            self._init_model_manager(os.getcwd(), auto_load=False)
        
        dialog = HuggingFaceModelDialog(self.root, self.model_manager)
        if dialog.result:
            # Model added, update list
            if self.model_manager:
                models = list(self.model_manager.models.values())
                self._update_models_list(models)
                self.log(f"Added HuggingFace model: {dialog.result.name}")
    
    def _remove_selected_model(self):
        """Remove the selected model"""
        item = self.models_tree.selection()
        if not item:
            messagebox.showwarning("Warning", "Select a model to remove")
            return
        
        model_id = item[0]
        if self.model_manager:
            model = self.model_manager.get_model_by_id(model_id)
            if model:
                if messagebox.askyesno("Confirm", f"Remove model '{model.name}' from list?\n\n(This does not delete the file from disk)"):
                    self.model_manager.remove_model(model_id)
                    self.models_tree.delete(model_id)
                    self.log(f"Removed model: {model.name}")
    
    def _sync_models(self):
        """Sync models with server"""
        if not self.client or not self.client.is_connected():
            messagebox.showwarning("Warning", "Connect to server first")
            return
        
        if not self.model_manager:
            messagebox.showwarning("Warning", "Scan models first")
            return
        
        self.update_status("Syncing models...")
        
        def sync():
            try:
                models = self.model_manager.get_models_for_server()
                # Send via WebSocket
                self.client.sync_models(models)
                self.root.after(0, lambda: self.update_status(f"Synced {len(models)} models"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Sync error: {e}"))
        
        threading.Thread(target=sync, daemon=True).start()
    
    def _update_disk_info(self):
        """Update disk space information"""
        if not self.model_manager:
            self.disk_info_var.set("Select a models folder first")
            return
        
        status = self.model_manager.get_disk_space_status()
        
        status_icon = "✅" if status['status'] == 'ok' else "⚠️" if status['status'] == 'warning' else "❌"
        status_text = (
            f"{status_icon} Free: {status['free_gb']:.1f} GB / {status['total_gb']:.1f} GB | "
            f"Models: {status['models_size_gb']:.1f} GB"
        )
        self.disk_info_var.set(status_text)
        
        # Color based on status
        if status['status'] == 'critical':
            self.disk_info_label.config(foreground='red')
            # Warn user
            if messagebox.askyesno("⚠️ Critical Disk Space",
                f"Disk space almost exhausted: only {status['free_gb']:.1f} GB free.\n\n"
                "Do you want to delete old/unused models to free up space?"):
                self._cleanup_old_models()
        elif status['status'] == 'warning':
            self.disk_info_label.config(foreground='orange')
        else:
            self.disk_info_label.config(foreground='green')
    
    def _cleanup_old_models(self):
        """Clean old/unused models"""
        if not self.model_manager:
            messagebox.showwarning("Warning", "Select a models folder first")
            return
        
        # Get unused models
        unused = self.model_manager.get_unused_models(days_threshold=30)
        
        if not unused:
            messagebox.showinfo("Model Cleanup", "No models to clean.\n\nAll models have been used in the last 30 days.")
            return
        
        # Calculate space to be freed
        total_size = sum(m.size_bytes for m in unused if not m.is_huggingface)
        total_size_gb = total_size / (1024 ** 3)
        
        # Show model list
        models_list = "\n".join([f"• {m.name} ({m.size_gb:.2f} GB)" for m in unused[:10]])
        if len(unused) > 10:
            models_list += f"\n... and {len(unused) - 10} more models"
        
        if messagebox.askyesno("🧹 Model Cleanup",
            f"Found {len(unused)} unused models in the last 30 days.\n\n"
            f"Models to delete:\n{models_list}\n\n"
            f"Space to be freed: {total_size_gb:.2f} GB\n\n"
            "Do you want to delete them?"):
            
            deleted = []
            for model in unused:
                if not model.is_huggingface:  # Don't delete HF models (no local file)
                    if self.model_manager.delete_model(model.id, delete_file=True):
                        deleted.append(model.name)
            
            # Update UI
            self._scan_models()
            self._update_disk_info()
            
            if deleted:
                messagebox.showinfo("Cleanup Complete",
                    f"Deleted {len(deleted)} models:\n" + "\n".join([f"• {n}" for n in deleted[:10]]))
                self.log(f"Cleanup: deleted {len(deleted)} models, freed {total_size_gb:.2f} GB")
            else:
                messagebox.showinfo("Cleanup", "No models deleted")
    
    def _delete_unused_models(self):
        """Delete models that have NEVER been used (use_count = 0)"""
        if not self.model_manager:
            messagebox.showwarning("Warning", "Select a models folder first")
            return
        
        # Get models with use_count = 0
        unused = [m for m in self.model_manager.models.values() 
                  if getattr(m, 'use_count', 0) == 0 and not m.is_huggingface]
        
        if not unused:
            messagebox.showinfo("No Unused Models", 
                "All your models have been used at least once!\n\n"
                "✓ Your model collection is optimized.")
            return
        
        # Calculate space to be freed
        total_size = sum(m.size_bytes for m in unused)
        total_size_gb = total_size / (1024 ** 3)
        
        # Show model list with filenames
        models_list = "\n".join([f"• {m.filename} ({m.size_gb:.2f} GB)" for m in unused[:10]])
        if len(unused) > 10:
            models_list += f"\n... and {len(unused) - 10} more models"
        
        if messagebox.askyesno("⚠️ Delete Unused Models",
            f"Found {len(unused)} models that have NEVER been used.\n\n"
            f"Models to delete:\n{models_list}\n\n"
            f"Space to be freed: {total_size_gb:.2f} GB\n\n"
            "These models take up disk space but no user has ever requested them.\n"
            "Do you want to delete them?"):
            
            deleted = []
            freed_space = 0
            for model in unused:
                size_gb = model.size_gb
                if self.model_manager.delete_model(model.id, delete_file=True):
                    deleted.append(model.filename)
                    freed_space += size_gb
            
            # Update UI
            self._scan_models()
            self._update_disk_info()
            
            if deleted:
                messagebox.showinfo("Cleanup Complete",
                    f"✓ Deleted {len(deleted)} unused models\n"
                    f"✓ Freed {freed_space:.2f} GB of disk space\n\n"
                    f"Deleted:\n" + "\n".join([f"• {n}" for n in deleted[:10]]))
                self.log(f"Deleted {len(deleted)} unused models, freed {freed_space:.2f} GB")
            else:
                messagebox.showinfo("Cleanup", "No models deleted")
    
    # === Connection ===
    
    def _load_config(self):
        """Load configuration"""
        # Fixed server - use direct IP
        self.server_url.set("https://lightphon.com")
        
        # Initialize restricted mode variables
        if not hasattr(self, 'allowed_models'):
            self.allowed_models = set()
        
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            
            self.node_name.set(self.config.get('Node', 'name', fallback=''))
            self.token.set(self.config.get('Node', 'token', fallback=''))
            self.price_per_minute.set(self.config.get('Node', 'price_per_minute', fallback='100'))
            
            # Load restricted mode settings
            restricted = self.config.getboolean('Node', 'restricted_models', fallback=False)
            if hasattr(self, 'restricted_mode'):
                self.restricted_mode.set(restricted)
            
            # Load allowed models list
            allowed_str = self.config.get('Node', 'allowed_models_list', fallback='')
            if allowed_str:
                self.allowed_models = set(m.strip() for m in allowed_str.split(',') if m.strip())
                print(f"Loaded {len(self.allowed_models)} allowed models: {self.allowed_models}")
            
            # Supporta sia il nuovo 'command' che il vecchio 'bin'
            llama_cmd = self.config.get('LLM', 'command', fallback='')
            if not llama_cmd:
                llama_cmd = self.config.get('LLM', 'bin', fallback='llama-server')
            self.llama_command.set(llama_cmd)
            self.gpu_layers.set(self.config.get('LLM', 'gpu_layers', fallback='99'))
            
            models_dir = self.config.get('Models', 'directory', fallback='')
            print(f"[DEBUG] Models directory from config: '{models_dir}'")
            if models_dir:
                # Normalize path for Windows
                models_dir = os.path.normpath(models_dir)
                print(f"[DEBUG] Normalized path: '{models_dir}'")
                print(f"[DEBUG] Path exists: {os.path.exists(models_dir)}")
                
                if os.path.exists(models_dir):
                    self.models_folder.set(models_dir)
                    # Initialize and auto-load saved models
                    self._init_model_manager(models_dir, auto_load=True)
                    self.log(f"Models folder loaded: {models_dir}")
                else:
                    print(f"[DEBUG] Models directory does not exist: {models_dir}")
        else:
            # Auto-rileva llama-server
            llama_cmd = find_llama_binary()
            if llama_cmd:
                self.llama_command.set(llama_cmd)
    
    def _save_config(self):
        """Save configuration"""
        # Don't save if config hasn't been fully loaded yet
        if not getattr(self, 'config_loaded', False):
            print("[SAVE_CONFIG] Skipping save - config not fully loaded yet")
            return
        
        for section in ['Node', 'Server', 'LLM', 'Models', 'Account']:
            if section not in self.config:
                self.config[section] = {}
        
        # Server always fixed
        self.config['Server']['URL'] = "https://lightphon.com"
        self.config['Node']['name'] = self.node_name.get()
        self.config['Node']['token'] = self.token.get()
        self.config['Node']['price_per_minute'] = self.price_per_minute.get()
        
        # Save restricted mode settings (only if values are meaningful)
        if hasattr(self, 'restricted_mode'):
            self.config['Node']['restricted_models'] = str(self.restricted_mode.get()).lower()
        if hasattr(self, 'allowed_models') and self.allowed_models:
            self.config['Node']['allowed_models_list'] = ','.join(self.allowed_models)
        # Don't clear allowed_models_list if self.allowed_models is empty but config has values
        
        self.config['LLM']['command'] = self.llama_command.get()
        self.config['LLM']['gpu_layers'] = self.gpu_layers.get()
        
        # Only save models directory if it has a value (don't overwrite with empty)
        current_models_dir = self.models_folder.get()
        if current_models_dir:
            self.config['Models']['directory'] = current_models_dir
        # If empty but config has a value, keep the config value (don't overwrite)
        
        # Save account credentials (if variables exist)
        if hasattr(self, 'login_username'):
            self.config['Account']['username'] = self.login_username.get()
        if hasattr(self, 'auth_token') and self.auth_token:
            self.config['Account']['token'] = self.auth_token
        
        with open(self.config_path, 'w') as f:
            self.config.write(f)
    
    def connect(self):
        """Connect to server"""
        # Verify login
        if not hasattr(self, 'logged_in') or not self.logged_in:
            messagebox.showwarning("Login required", 
                "You must login before connecting the node.\n\n"
                "Go to the 'Account' tab and login with your credentials.")
            self.notebook.select(0)  # Go to Account tab
            return
        
        self._save_config()
        
        self.update_status("Connecting...")
        self.connect_btn.config(state='disabled')
        self.log(f"Attempting connection to {self.server_url.get()}...")
        
        def do_connect():
            try:
                self.client = NodeClient(self.config_path)
                self.client.server_url = self.server_url.get()
                self.client.node_name = self.node_name.get()
                
                # Pass restricted mode settings
                if hasattr(self, 'restricted_mode'):
                    self.client.restricted_models = self.restricted_mode.get()
                    self.log(f"Restricted mode: {self.client.restricted_models}")
                if hasattr(self, 'allowed_models') and self.allowed_models:
                    self.client.allowed_models_list = list(self.allowed_models)
                    self.log(f"Allowed models: {self.client.allowed_models_list}")
                else:
                    self.log(f"No allowed models configured")
                
                # Pass user authentication token
                self.client.auth_token = self.auth_token
                self.client.user_id = self.user_info.get('user_id')
                
                # Collega callbacks GUI per visualizzare output LLM
                self.client.gui_prompt_callback = self.llm_set_prompt
                self.client.gui_token_callback = self.llm_add_token
                self.client.gui_session_ended_callback = self.llm_session_ended
                
                # Collega callback per log nella GUI
                self.client.gui_log_callback = self.log
                
                # Collega callback per refresh RAG quando modello cambia
                self.client.gui_rag_refresh_callback = lambda: self.root.after(0, self._rag_refresh_list)
                
                # Pass hardware and models info
                if self.system_info:
                    self.client.hardware_info = self.system_info
                if self.model_manager:
                    self.client.models = self.model_manager.get_models_for_server()
                    self.client.model_manager = self.model_manager  # For local file paths
                
                if self.client.connect():
                    self.root.after(0, self._on_connected)
                else:
                    self.root.after(0, lambda: self._on_connection_failed("Connection failed"))
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                self.root.after(0, lambda: self.log(f"Error:\n{err}"))
                self.root.after(0, lambda: self._on_connection_failed(str(e)))
                self.root.after(0, lambda: self._on_connection_failed(str(e)))
        
        threading.Thread(target=do_connect, daemon=True).start()
    
    def _on_connected(self):
        """Connection success callback"""
        self.conn_status.set("✓ Connected to server")
        self.conn_indicator.config(text="● Connected", style='Connected.TLabel')
        self.connect_btn.config(state='disabled')
        self.disconnect_btn.config(state='normal')
        self.conn_details.set(f"Server: {self.server_url.get()}")
        self.update_status("Connected to server")
        self.log("Connection established!")
        
        # Sync models automatically
        if self.model_manager and self.model_manager.models:
            self._sync_models()
    
    def _on_connection_failed(self, error):
        """Connection failed callback"""
        self.conn_status.set("✗ Not connected")
        self.conn_indicator.config(text="● Disconnected", style='Disconnected.TLabel')
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.update_status(f"Error: {error}")
        messagebox.showerror("Connection Error", f"Connection failed:\n{error}")
    
    def disconnect(self):
        """Disconnect"""
        if self.client:
            self.client.disconnect()
            self.client = None
        
        self.conn_status.set("Not connected")
        self.conn_indicator.config(text="● Disconnected", style='Disconnected.TLabel')
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.conn_details.set("")
        self.update_status("Disconnected")
        self.log("Disconnected from server")
    
    def browse_llama(self):
        """Browse for llama-server (optional, can be in PATH)"""
        filetypes = [("Executable", "*.exe"), ("All files", "*.*")] if sys.platform == 'win32' else [("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.llama_command.set(path)
    
    # === Sessions ===
    
    def _refresh_sessions(self):
        """Refresh sessions list"""
        if not self.client:
            return
        # TODO: Implement session request from server
    
    # === Log ===
    
    def update_status(self, msg):
        """Update status bar"""
        self.status_var.set(msg)
    
    def log(self, msg):
        """Add to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
    
    def _clear_log(self):
        """Clear log"""
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state='disabled')
    
    def _save_log(self):
        """Save log to file"""
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.log_text.config(state='normal')
            with open(path, 'w') as f:
                f.write(self.log_text.get('1.0', tk.END))
            self.log_text.config(state='disabled')
            self.update_status(f"Log saved to {path}")
    
    # === Settings ===
    
    def open_settings(self):
        """Open the settings dialog."""
        # Get server URL from config
        server_url = None
        if self.config.has_option('server', 'url'):
            server_url = self.config.get('server', 'url')
        
        # Open settings dialog with config for saving preferences
        SettingsDialog(
            self.root,
            self.updater,
            server_url=server_url,
            auth_token=self.auth_token,
            config=self.config,
            config_path=self.config_path
        )
    
    # === Auto-Updater ===
    
    def _start_updater(self):
        """Start auto-update check"""
        self.updater.start_checking(interval=3600)  # Every hour
        self.log("Auto-updater started")
    
    def _on_update_available(self, version, changelog, download_url):
        """Callback when an update is available"""
        self.update_pending = True
        # Update UI from main thread
        self.root.after(0, lambda: self._show_update_notification(version, changelog))
    
    def _show_update_notification(self, version, changelog):
        """Show update notification"""
        self.log(f"🔄 Update available: v{version}")
        self.status_var.set(f"Update available: v{version}")
        
        # Show dialog
        response = messagebox.askyesno(
            "Update Available",
            f"Version {version} of LightPhon Node is available.\n\n"
            f"Changelog:\n{changelog[:500]}...\n\n"
            f"Do you want to update now?\n"
            f"(The application will be restarted)",
            icon='info'
        )
        
        if response:
            self._download_and_apply_update()
    
    def _download_and_apply_update(self):
        """Download and apply the update"""
        self.log("Downloading update...")
        self.status_var.set("Downloading update...")
        
        def download_thread():
            try:
                # Progress callback
                def progress(downloaded, total):
                    if total > 0:
                        percent = int((downloaded / total) * 100)
                        self.root.after(0, lambda p=percent: self.status_var.set(f"Download: {p}%"))
                
                # Download
                update_path = self.updater.download_update(progress_callback=progress)
                
                if update_path:
                    self.root.after(0, lambda: self._apply_update(update_path))
                else:
                    self.root.after(0, lambda: self._update_failed("Download failed"))
                    
            except Exception as e:
                self.root.after(0, lambda: self._update_failed(str(e)))
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def _apply_update(self, update_path):
        """Apply the downloaded update"""
        self.log(f"Applying update from {update_path}...")
        
        response = messagebox.askyesno(
            "Apply Update",
            "The update has been downloaded.\n"
            "The application will close and restart.\n\n"
            "Continue?",
            icon='question'
        )
        
        if response:
            # Disconnect before update
            if self.client:
                self.client.disconnect()
            
            # Apply update
            if self.updater.apply_update(update_path):
                self.log("Updating, closing application...")
                self.root.after(1000, self.root.destroy)
            else:
                self._update_failed("Unable to apply the update")
    
    def _update_failed(self, error):
        """Handle update error"""
        self.log(f"❌ Update failed: {error}")
        self.status_var.set("Update failed")
        messagebox.showerror("Update Error", f"Unable to update:\n{error}")
    
    def check_update_manual(self):
        """Manual update check"""
        self.log("Checking for updates...")
        self.status_var.set("Checking for updates...")
        
        def check_thread():
            update = self.updater.check_for_updates()
            if update:
                self.root.after(0, lambda: self._show_update_notification(
                    update['version'], 
                    update.get('changelog', '')
                ))
            else:
                self.root.after(0, lambda: (
                    self.log("✓ No updates available"),
                    self.status_var.set(f"Version {VERSION} is up to date"),
                    messagebox.showinfo("Updates", f"You are using the latest version (v{VERSION})")
                ))
        
        threading.Thread(target=check_thread, daemon=True).start()
    
    # === App Lifecycle ===
    
    def on_close(self):
        """Minimize to system tray instead of closing"""
        if HAS_TRAY:
            self._hide_to_tray()
        else:
            # No tray support, ask user
            if messagebox.askyesno("Exit", "Do you want to exit the application?\n\nClick 'No' to minimize to taskbar."):
                self._quit_app()
            else:
                self.root.iconify()
    
    def _hide_to_tray(self):
        """Hide window to system tray"""
        self.root.withdraw()
        self.is_hidden = True
        
        if not self.tray_icon:
            self._create_tray_icon()
    
    def _create_tray_icon(self):
        """Create system tray icon"""
        if not HAS_TRAY:
            return
        
        # Create icon image
        try:
            # Try to load icon file
            icon_path = os.path.join(self.script_dir, 'icon.ico')
            if os.path.exists(icon_path):
                image = Image.open(icon_path)
            else:
                # Create a simple colored icon
                image = Image.new('RGB', (64, 64), color=(0, 120, 212))
        except Exception:
            # Fallback: create simple icon
            image = Image.new('RGB', (64, 64), color=(0, 120, 212))
        
        # Create menu
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._show_from_tray, default=True),
            pystray.MenuItem("Status", self._show_status_notification),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._quit_from_tray)
        )
        
        # Determine status for icon title
        status = "Connected" if self.client and self.client.sio and self.client.sio.connected else "Disconnected"
        
        self.tray_icon = pystray.Icon(
            "LightPhon Node",
            image,
            f"LightPhon Node v{VERSION} - {status}",
            menu
        )
        
        # Run tray icon in background thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
    
    def _show_from_tray(self, icon=None, item=None):
        """Show window from tray"""
        self.is_hidden = False
        self.root.after(0, self._restore_window)
    
    def _restore_window(self):
        """Restore the window (called from main thread)"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
    
    def _show_status_notification(self, icon=None, item=None):
        """Show status notification"""
        if self.client and self.client.sio and self.client.sio.connected:
            status = f"Connected to server\nNode: {self.node_name.get() or 'Unnamed'}"
        else:
            status = "Disconnected"
        
        if self.tray_icon:
            self.tray_icon.notify(status, "LightPhon Node")
    
    def _quit_from_tray(self, icon=None, item=None):
        """Quit application from tray"""
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
            self.tray_icon = None
        self.root.after(0, self._quit_app)
    
    def _quit_app(self):
        """Actually quit the application"""
        self._save_config()
        # Stop auto-updater
        if self.updater:
            try:
                self.updater.stop_checking()
            except:
                pass
        # Disconnect client
        if self.client:
            try:
                self.client.disconnect()
            except:
                pass
        # Stop tray icon
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
            self.tray_icon = None
        # Destroy window
        try:
            self.root.destroy()
        except:
            pass
        # Force exit to kill any remaining threads
        import os
        os._exit(0)
    
    def run(self):
        """Start GUI"""
        self.root.mainloop()


class HuggingFaceModelDialog:
    """Dialog for adding a HuggingFace model"""
    
    def __init__(self, parent, model_manager):
        self.result = None
        self.model_manager = model_manager
        self.verified = False
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Add HuggingFace Model")
        self.dialog.geometry("600x500")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Instructions
        info_frame = ttk.LabelFrame(self.dialog, text="Instructions", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        info_text = """Enter the HuggingFace repository in the format:
owner/repo:quantization

⚠️ IMPORTANT: Only repositories with GGUF files are supported!

Examples:
• bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M
• unsloth/Llama-3.2-3B-Instruct-GGUF:Q4_K_M
• Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M

The model will be downloaded automatically from HuggingFace when you start a session."""
        
        ttk.Label(info_frame, text=info_text, justify=tk.LEFT, font=('Arial', 9)).pack(anchor='w')
        
        # Disk space
        disk_frame = ttk.LabelFrame(self.dialog, text="📊 Disk Space", padding=10)
        disk_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.disk_status_var = tk.StringVar(value="Checking disk space...")
        self.disk_status_label = ttk.Label(disk_frame, textvariable=self.disk_status_var, font=('Arial', 9))
        self.disk_status_label.pack(anchor='w')
        
        # Update disk info
        self._update_disk_status()
        
        # Input
        input_frame = ttk.LabelFrame(self.dialog, text="HuggingFace Repository", padding=10)
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(input_frame, text="Repo (owner/model:quant):").pack(anchor='w')
        self.repo_var = tk.StringVar()
        self.repo_entry = ttk.Entry(input_frame, textvariable=self.repo_var, width=60)
        self.repo_entry.pack(fill=tk.X, pady=5)
        self.repo_entry.focus_set()
        
        # GGUF note
        ttk.Label(input_frame, text="⚠️ Only .gguf files supported!", foreground='red', font=('Arial', 9, 'bold')).pack(anchor='w')
        
        # Bind for reset verification when text changes
        self.repo_var.trace_add('write', self._on_repo_changed)
        
        # Note about context
        ttk.Label(input_frame, text="ℹ️ Context length will be set by the user when creating a session", 
                  font=('Arial', 8), foreground='gray').pack(anchor='w', pady=(10, 0))
        
        # Status verifica
        self.verify_status_var = tk.StringVar(value="")
        self.verify_status_label = ttk.Label(input_frame, textvariable=self.verify_status_var, font=('Arial', 9))
        self.verify_status_label.pack(anchor='w', pady=5)
        
        # Preset popular models
        preset_frame = ttk.LabelFrame(self.dialog, text="Popular Models (click to use)", padding=10)
        preset_frame.pack(fill=tk.X, padx=10, pady=10)
        
        presets = [
            ("Llama 3.2 1B", "bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M"),
            ("Llama 3.2 3B", "unsloth/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"),
            ("Qwen 2.5 1.5B", "Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M"),
            ("SmolLM2 1.7B", "HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF:Q4_K_M"),
            ("Phi-3 Mini", "bartowski/Phi-3.5-mini-instruct-GGUF:Q4_K_M"),
        ]
        
        for name, repo in presets:
            btn = ttk.Button(preset_frame, text=name, 
                           command=lambda r=repo: self._set_preset(r))
            btn.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=20)
        
        self.verify_btn = ttk.Button(btn_frame, text="🔍 Verify Model", command=self._verify_model, width=18)
        self.verify_btn.pack(side=tk.LEFT, padx=5)
        
        self.add_btn = ttk.Button(btn_frame, text="✅ Add", command=self._add_model, width=15, state='disabled')
        self.add_btn.pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(btn_frame, text="Cancel", command=self.dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)
        
        # Bind Enter
        self.repo_entry.bind('<Return>', lambda e: self._verify_model())
        
        # Wait for close
        self.dialog.wait_window()
    
    def _update_disk_status(self):
        """Update disk space info"""
        if self.model_manager:
            status = self.model_manager.get_disk_space_status()
            status_icon = "✅" if status['status'] == 'ok' else "⚠️" if status['status'] == 'warning' else "❌"
            self.disk_status_var.set(
                f"{status_icon} Free space: {status['free_gb']:.1f} GB / {status['total_gb']:.1f} GB | "
                f"Models: {status['models_size_gb']:.1f} GB"
            )
            
            if status['status'] == 'critical':
                self.disk_status_label.config(foreground='red')
            elif status['status'] == 'warning':
                self.disk_status_label.config(foreground='orange')
            else:
                self.disk_status_label.config(foreground='green')
    
    def _set_preset(self, repo):
        """Set a preset and reset verification"""
        self.repo_var.set(repo)
        self.verified = False
        self.add_btn.config(state='disabled')
        self.verify_status_var.set("")
    
    def _on_repo_changed(self, *args):
        """Callback when repo changes - reset verification"""
        self.verified = False
        self.add_btn.config(state='disabled')
        self.verify_status_var.set("")
    
    def _verify_model(self):
        """Verify the HuggingFace model exists"""
        repo = self.repo_var.get().strip()
        if not repo:
            messagebox.showwarning("Warning", "Enter a HuggingFace repository", parent=self.dialog)
            return
        
        # Verify basic format
        if '/' not in repo:
            messagebox.showwarning("Warning", 
                "Invalid format. Use: owner/repo:quantization\nEx: bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M", 
                parent=self.dialog)
            return
        
        # Show verification status
        self.verify_status_var.set("🔄 Verifying repository on HuggingFace...")
        self.verify_btn.config(state='disabled')
        self.dialog.update()
        
        # Verify in thread
        import threading
        def verify_thread():
            try:
                import requests
                
                # Parse repo
                if ':' in repo:
                    repo_name, quant = repo.rsplit(':', 1)
                else:
                    repo_name = repo
                    quant = None
                
                # Verify the repo exists on HuggingFace
                api_url = f"https://huggingface.co/api/models/{repo_name}"
                response = requests.get(api_url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    model_id = data.get('id', repo_name)
                    
                    # Check if there are GGUF files
                    siblings = data.get('siblings', [])
                    gguf_files = [f for f in siblings if f.get('rfilename', '').endswith('.gguf')]
                    
                    if gguf_files:
                        # Find file with specified quantization
                        if quant:
                            matching = [f for f in gguf_files if quant.upper() in f.get('rfilename', '').upper()]
                            if matching:
                                file_info = matching[0]
                                size_bytes = file_info.get('size', 0)
                                size_gb = size_bytes / (1024**3) if size_bytes else 0
                                
                                self.dialog.after(0, lambda: self._verify_success(
                                    f"✅ Model found: {model_id}\n"
                                    f"   File: {file_info.get('rfilename', 'N/A')}\n"
                                    f"   Size: {size_gb:.2f} GB"
                                ))
                            else:
                                self.dialog.after(0, lambda: self._verify_warning(
                                    f"⚠️ Repository found but quantization '{quant}' not found.\n"
                                    f"   GGUF files available: {len(gguf_files)}"
                                ))
                        else:
                            self.dialog.after(0, lambda: self._verify_success(
                                f"✅ Model found: {model_id}\n"
                                f"   GGUF files available: {len(gguf_files)}"
                            ))
                    else:
                        self.dialog.after(0, lambda: self._verify_error(
                            f"❌ Repository found but does not contain GGUF files"
                        ))
                elif response.status_code == 404:
                    self.dialog.after(0, lambda: self._verify_error(
                        f"❌ Repository not found: {repo_name}"
                    ))
                else:
                    self.dialog.after(0, lambda: self._verify_error(
                        f"❌ HuggingFace error: HTTP {response.status_code}"
                    ))
                    
            except requests.exceptions.Timeout:
                self.dialog.after(0, lambda: self._verify_error(
                    "❌ Timeout: HuggingFace not responding"
                ))
            except Exception as e:
                self.dialog.after(0, lambda: self._verify_error(
                    f"❌ Error: {str(e)}"
                ))
        
        threading.Thread(target=verify_thread, daemon=True).start()
    
    def _verify_success(self, message):
        """Verification successful"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='green')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='normal')
        self.verified = True
    
    def _verify_warning(self, message):
        """Verification with warning"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='orange')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='normal')  # Allow adding anyway
        self.verified = True
    
    def _verify_error(self, message):
        """Verification failed"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='red')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='disabled')
        self.verified = False
    
    def _add_model(self):
        """Add the model"""
        if not self.verified:
            messagebox.showwarning("Warning", 
                "First verify the model exists by clicking '🔍 Verify Model'", 
                parent=self.dialog)
            return
        
        repo = self.repo_var.get().strip()
        
        # Check disk space
        if self.model_manager:
            disk_status = self.model_manager.get_disk_space_status()
            if disk_status['status'] == 'critical':
                if not messagebox.askyesno("Critical Disk Space",
                    f"Disk space almost full ({disk_status['free_gb']:.1f} GB free).\n\n"
                    "Continue anyway?",
                    parent=self.dialog):
                    return
        
        try:
            context = 128000  # Default context, actual value set by user when creating session
        except ValueError:
            context = 128000
        
        if self.model_manager:
            self.result = self.model_manager.add_huggingface_model(repo, context)
            if self.result:
                messagebox.showinfo("Success", 
                    f"Model added: {self.result.name}\n\n"
                    "The model will be downloaded automatically when you start a session.\n"
                    "NOTE: Download may take several minutes.",
                    parent=self.dialog)
                self.dialog.destroy()
            else:
                messagebox.showerror("Error", "Unable to add the model", parent=self.dialog)
        else:
            messagebox.showerror("Error", "Model Manager not initialized", parent=self.dialog)


class SettingsDialog:
    """Settings dialog window showing version info and update options."""
    
    def __init__(self, parent, updater, server_url=None, auth_token=None, config=None, config_path=None):
        self.parent = parent
        self.updater = updater
        self.server_url = server_url
        self.auth_token = auth_token
        self.config = config
        self.config_path = config_path
        self.min_version = "Unknown"
        self.latest_version = "Unknown"
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("⚙️ Settings")
        self.dialog.geometry("450x520")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Main frame with padding
        main_frame = ttk.Frame(self.dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === Notifications Section ===
        notif_frame = ttk.LabelFrame(main_frame, text="📧 Email Notifications", padding=15)
        notif_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Load current settings
        self.email_offline_var = tk.BooleanVar(value=False)
        if self.config and self.config.has_option('Notifications', 'email_on_offline'):
            self.email_offline_var.set(self.config.getboolean('Notifications', 'email_on_offline', fallback=False))
        
        # Email when offline checkbox
        self.email_offline_cb = ttk.Checkbutton(
            notif_frame, 
            text="Send email when node goes offline",
            variable=self.email_offline_var,
            command=self._on_notification_change
        )
        self.email_offline_cb.pack(anchor='w', pady=5)
        
        ttk.Label(notif_frame, text="ℹ️ Email will be sent to the address linked to your account", 
                  font=('Arial', 8), foreground='gray').pack(anchor='w')
        
        # === Version Info Section ===
        version_frame = ttk.LabelFrame(main_frame, text="📋 Software Version", padding=15)
        version_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Current version
        current_row = ttk.Frame(version_frame)
        current_row.pack(fill=tk.X, pady=5)
        ttk.Label(current_row, text="Current Version:", font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        self.current_label = ttk.Label(current_row, text=f"v{VERSION}", font=('Arial', 10), foreground='#4caf50')
        self.current_label.pack(side=tk.RIGHT)
        
        # Minimum version required
        min_row = ttk.Frame(version_frame)
        min_row.pack(fill=tk.X, pady=5)
        ttk.Label(min_row, text="Minimum Required:", font=('Arial', 10)).pack(side=tk.LEFT)
        self.min_label = ttk.Label(min_row, text="Loading...", font=('Arial', 10), foreground='#ff9800')
        self.min_label.pack(side=tk.RIGHT)
        
        # Latest available version
        latest_row = ttk.Frame(version_frame)
        latest_row.pack(fill=tk.X, pady=5)
        ttk.Label(latest_row, text="Latest Available:", font=('Arial', 10)).pack(side=tk.LEFT)
        self.latest_label = ttk.Label(latest_row, text="Loading...", font=('Arial', 10), foreground='#94c5f9')
        self.latest_label.pack(side=tk.RIGHT)
        
        # Version status
        self.status_var = tk.StringVar(value="Checking version status...")
        self.status_label = ttk.Label(version_frame, textvariable=self.status_var, font=('Arial', 9), foreground='gray')
        self.status_label.pack(pady=(10, 0))
        
        # === Update Section ===
        update_frame = ttk.LabelFrame(main_frame, text="🔄 Updates", padding=15)
        update_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Update button
        self.update_btn = ttk.Button(update_frame, text="Check for Updates", command=self._check_updates, width=25)
        self.update_btn.pack(pady=10)
        
        # Progress info
        self.progress_var = tk.StringVar(value="")
        ttk.Label(update_frame, textvariable=self.progress_var, font=('Arial', 9)).pack()
        
        # === About Section ===
        about_frame = ttk.LabelFrame(main_frame, text="ℹ️ About", padding=15)
        about_frame.pack(fill=tk.X, pady=(0, 15))
        
        about_text = f"""LightPhon Node Client v{VERSION}

Host your GPU and earn Bitcoin via Lightning Network.
Provide AI inference services to users worldwide.

© 2025 LightPhon - Decentralized AI Marketplace"""
        
        ttk.Label(about_frame, text=about_text, justify=tk.CENTER, font=('Arial', 9)).pack()
        
        # Close button
        ttk.Button(main_frame, text="Close", command=self.dialog.destroy, width=15).pack(pady=10)
        
        # Fetch version info
        self.dialog.after(100, self._fetch_version_info)
        
        # Wait for close
        self.dialog.wait_window()
    
    def _fetch_version_info(self):
        """Fetch version info from server."""
        def fetch_thread():
            try:
                import urllib.request
                
                # Build URL - use server from config if available
                server_url = self.server_url or "https://lightphon.com"
                url = f"{server_url}/api/version"
                
                req = urllib.request.Request(url)
                req.add_header('User-Agent', f'LightPhon-Node/{VERSION}')
                
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())
                
                self.min_version = data.get('min_version', 'Unknown')
                self.latest_version = data.get('version', 'Unknown')
                
                # Update UI from main thread
                self.dialog.after(0, lambda: self._update_version_display(self.min_version, self.latest_version))
                
            except Exception as e:
                self.dialog.after(0, lambda: self._update_version_display("Error", "Error"))
                self.dialog.after(0, lambda: self.status_var.set(f"Unable to fetch version info: {str(e)[:50]}"))
        
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _update_version_display(self, min_ver, latest_ver):
        """Update the version labels with fetched data."""
        self.min_label.config(text=f"v{min_ver}")
        self.latest_label.config(text=f"v{latest_ver}")
        
        # Compare versions and show status
        from version import is_newer
        
        # Check if current version meets minimum
        if min_ver != "Error" and min_ver != "Unknown":
            try:
                if is_newer(min_ver, VERSION):
                    self.status_var.set("⚠️ Your version is BELOW the minimum required! Update needed.")
                    self.status_label.config(foreground='red')
                    self.current_label.config(foreground='red')
                elif is_newer(latest_ver, VERSION):
                    self.status_var.set("ℹ️ A newer version is available.")
                    self.status_label.config(foreground='orange')
                else:
                    self.status_var.set("✅ You are running the latest version!")
                    self.status_label.config(foreground='green')
            except:
                self.status_var.set("✅ Version check complete.")
    
    def _check_updates(self):
        """Check for available updates."""
        self.update_btn.config(state='disabled')
        self.progress_var.set("Checking for updates...")
        
        def check_thread():
            try:
                if self.updater:
                    update = self.updater.check_for_updates()
                    if update:
                        self.dialog.after(0, lambda: self._show_update_available(update))
                    else:
                        self.dialog.after(0, lambda: self._no_update_available())
                else:
                    self.dialog.after(0, lambda: self.progress_var.set("Updater not available"))
            except Exception as e:
                self.dialog.after(0, lambda: self.progress_var.set(f"Error: {str(e)[:40]}"))
            finally:
                self.dialog.after(0, lambda: self.update_btn.config(state='normal'))
        
        threading.Thread(target=check_thread, daemon=True).start()
    
    def _show_update_available(self, update):
        """Show that an update is available."""
        version = update.get('version', 'Unknown')
        self.progress_var.set(f"Update available: v{version}")
        
        response = messagebox.askyesno(
            "Update Available",
            f"Version {version} is available!\n\n"
            f"Changelog:\n{update.get('changelog', '')[:300]}...\n\n"
            "Do you want to download and install the update?",
            parent=self.dialog
        )
        
        if response:
            self.progress_var.set("Starting download...")
            # Trigger the main app's update mechanism
            if self.updater and self.updater.callback:
                self.updater.callback(version, update.get('changelog', ''), update.get('download_url'))
            self.dialog.destroy()
    
    def _no_update_available(self):
        """Show that no update is available."""
        self.progress_var.set(f"✅ You have the latest version (v{VERSION})")
        messagebox.showinfo("No Updates", f"You are running the latest version (v{VERSION}).", parent=self.dialog)
    
    def _on_notification_change(self):
        """Save notification settings when changed."""
        if not self.config or not getattr(self, 'config_loaded', False):
            return
        
        # Ensure Notifications section exists
        if 'Notifications' not in self.config:
            self.config['Notifications'] = {}
        
        # Save settings
        self.config['Notifications']['email_on_offline'] = str(self.email_offline_var.get()).lower()
        
        # Write to file
        if self.config_path:
            try:
                with open(self.config_path, 'w') as f:
                    self.config.write(f)
            except Exception as e:
                print(f"Error saving notification settings: {e}")


if __name__ == '__main__':
    import signal
    import atexit
    
    app = NodeGUI()
    
    # Cleanup function
    def cleanup():
        if app.client:
            print("Cleaning up llama-server processes...")
            app.client.cleanup_all_sessions()
            app.client.disconnect()
    
    # Signal handler per Ctrl+C
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, cleaning up...")
        cleanup()
        sys.exit(0)
    
    # Registra handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup)
    
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        cleanup()
