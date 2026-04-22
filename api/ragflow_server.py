#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
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

# from beartype import BeartypeConf
# from beartype.claw import beartype_all  # <-- you didn't sign up for this
# beartype_all(conf=BeartypeConf(violation_type=UserWarning))    # <-- emit warnings from all code

import time
start_ts = time.time()

import logging
import os
import signal
import sys
import traceback
import threading
import uuid
import faulthandler

from api.apps import app
from api.db.runtime_config import RuntimeConfig
from api.db.services.document_service import DocumentService
from common.file_utils import get_project_base_directory
from common import settings
from api.db.db_models import init_database_tables as init_web_db
from api.db.init_data import init_web_data, init_superuser
from common.versions import get_ragflow_version
from common.config_utils import show_configs
from common.mcp_tool_call_conn import shutdown_all_mcp_sessions
from common.log_utils import init_root_logger
from agent.plugin import GlobalPluginManager
from rag.utils.redis_conn import RedisDistributedLock

stop_event = threading.Event()
bootstrap_lock = threading.Lock()
bootstrap_done = False
bootstrap_logged = False
update_progress_started = False

RAGFLOW_DEBUGPY_LISTEN = int(os.environ.get('RAGFLOW_DEBUGPY_LISTEN', "0"))


def _log_boot_banner():
    global bootstrap_logged
    if bootstrap_logged:
        return
    bootstrap_logged = True
    logging.info(r"""
        ____   ___    ______ ______ __
       / __ \ /   |  / ____// ____// /____  _      __
      / /_/ // /| | / / __ / /_   / // __ \| | /| / /
     / _, _// ___ |/ /_/ // __/  / // /_/ /| |/ |/ /
    /_/ |_|/_/  |_|\____//_/    /_/ \____/ |__/|__/

    """)
    logging.info(f'RAGFlow version: {get_ragflow_version()}')
    logging.info(f'project base: {get_project_base_directory()}')


def _start_update_progress_thread():
    global update_progress_started
    if update_progress_started:
        return
    update_progress_started = True
    logging.info("Starting update_progress thread")
    stop_event.clear()
    t = threading.Thread(target=update_progress, daemon=True)
    t.start()


def ensure_server_bootstrapped(debug: bool = False, init_superuser_flag: bool = False):
    global bootstrap_done
    with bootstrap_lock:
        if bootstrap_done:
            return

        faulthandler.enable()
        init_root_logger("ragflow_server")
        _log_boot_banner()
        show_configs()
        settings.init_settings()
        settings.print_rag_settings()

        if RAGFLOW_DEBUGPY_LISTEN > 0:
            logging.info(f"debugpy listen on {RAGFLOW_DEBUGPY_LISTEN}")
            import debugpy
            debugpy.listen(("0.0.0.0", RAGFLOW_DEBUGPY_LISTEN))

        init_web_db()
        init_web_data()

        if init_superuser_flag:
            init_superuser()

        RuntimeConfig.DEBUG = debug
        if RuntimeConfig.DEBUG:
            logging.info("run on debug mode")
        RuntimeConfig.init_env()
        RuntimeConfig.init_config(
            JOB_SERVER_HOST=settings.HOST_IP,
            HTTP_PORT=settings.HOST_PORT,
        )

        GlobalPluginManager.load_plugins()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

        _start_update_progress_thread()
        logging.info(
            "RAGFlow bootstrap completed after %.2fs initialization.",
            time.time() - start_ts,
        )
        bootstrap_done = True

def update_progress():
    lock_value = str(uuid.uuid4())
    redis_lock = RedisDistributedLock("update_progress", lock_value=lock_value, timeout=60)
    logging.info(f"update_progress lock_value: {lock_value}")
    while not stop_event.is_set():
        try:
            if redis_lock.acquire():
                DocumentService.update_progress()
                redis_lock.release()
        except Exception:
            logging.exception("update_progress exception")
        finally:
            try:
                redis_lock.release()
            except Exception:
                logging.exception("update_progress exception")
            stop_event.wait(6)

def signal_handler(sig, frame):
    logging.info("Received interrupt signal, shutting down...")
    shutdown_all_mcp_sessions()
    stop_event.set()
    stop_event.wait(1)
    sys.exit(0)


@app.before_serving
async def _bootstrap_before_serving():
    ensure_server_bootstrapped()


@app.after_serving
async def _shutdown_after_serving():
    shutdown_all_mcp_sessions()
    stop_event.set()

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version", default=False, help="RAGFlow version", action="store_true"
    )
    parser.add_argument(
        "--debug", default=False, help="debug mode", action="store_true"
    )
    parser.add_argument(
        "--init-superuser", default=False, help="init superuser", action="store_true"
    )
    args = parser.parse_args()
    if args.version:
        print(get_ragflow_version())
        sys.exit(0)

    ensure_server_bootstrapped(
        debug=args.debug,
        init_superuser_flag=args.init_superuser,
    )

    # start http server
    try:
        logging.info(f"RAGFlow server is ready after {time.time() - start_ts}s initialization.")
        app.run(host=settings.HOST_IP, port=settings.HOST_PORT)
    except Exception:
        traceback.print_exc()
        stop_event.set()
        stop_event.wait(1)
        os.kill(os.getpid(), signal.SIGKILL)
