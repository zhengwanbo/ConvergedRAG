#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import os
import signal
import logging
import time
import threading
import traceback

from flask import Flask
from flask_login import LoginManager
from werkzeug.serving import run_simple
from common.log_utils import init_root_logger
from common.constants import SERVICE_CONF
from common.config_utils import show_configs
from common import settings
from flask_session import Session
from common.versions import get_ragflow_version

# Use absolute imports with PYTHONPATH
from admin.server.routes import admin_bp
from admin.server.config import load_configurations, SERVICE_CONFIGS
from admin.server.auth import init_default_admin, setup_auth

stop_event = threading.Event()

# Create Flask app at module level for Hypercorn
app = Flask(__name__)
app.register_blueprint(admin_bp)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["MAX_CONTENT_LENGTH"] = int(
    os.environ.get("MAX_CONTENT_LENGTH", 1024 * 1024 * 1024)
)

# Initialize session
Session(app)

# Initialize login manager
login_manager = LoginManager()

def create_app():
    """Factory function to create and configure the app."""
    # This function is for WSGI servers that use app factories
    return app

def initialize_app():
    """Initialize app components."""
    logging.info(f'RAGFlow version: {get_ragflow_version()}')
    show_configs()
    login_manager.init_app(app)
    settings.init_settings()
    setup_auth(login_manager)
    init_default_admin()
    SERVICE_CONFIGS.configs = load_configurations(SERVICE_CONF)

# Initialize app when module is imported (for Hypercorn)
# But only if we're not running as __main__ (to avoid double initialization)
if not __name__ == '__main__':
    # Set up basic logging for module import
    import sys
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        initialize_app()
        logging.info("Admin app initialized for Hypercorn")
    except Exception as e:
        logging.error(f"Failed to initialize app on import: {e}")
        # Don't raise, let Hypercorn start anyway

if __name__ == '__main__':
    # 添加更多调试信息
    import signal
    def debug_signal_handler(sig, frame):
        logging.info(f"Received signal {sig} in admin service")
        import traceback
        traceback.print_stack(frame)
        os._exit(1)
    
    signal.signal(signal.SIGTERM, debug_signal_handler)
    signal.signal(signal.SIGINT, debug_signal_handler)
    # Note: SIGKILL cannot be caught
    
    init_root_logger("admin_service")
    logging.info("Starting admin service initialization...")
    logging.info(r"""
        ____  ___   ______________                 ___       __          _     
       / __ \/   | / ____/ ____/ /___ _      __   /   | ____/ /___ ___  (_)___ 
      / /_/ / /| |/ / __/ /_  / / __ \ | /| / /  / /| |/ __  / __ `__ \/ / __ \
     / _, _/ ___ / /_/ / __/ / / /_/ / |/ |/ /  / ___ / /_/ / / / / / / / / / /
    /_/ |_/_/  |_\____/_/   /_/\____/|__/|__/  /_/  |_\__,_/_/ /_/ /_/_/_/ /_/ 
    """)
    
    # Initialize app components
    initialize_app()

    try:
        logging.info("RAGFlow Admin service start...")
        run_simple(
            hostname="0.0.0.0",
            port=9381,
            application=app,
            threaded=True,
            use_reloader=False,
            use_debugger=True,
        )
    except Exception:
        traceback.print_exc()
        stop_event.set()
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGKILL)
else:
    # When imported as module (e.g., by Hypercorn), initialize components
    # But be careful: this runs on import, which might be too early
    # We'll initialize lazily or in a startup hook
    pass
