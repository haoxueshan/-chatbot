"""The direct script must start from a different cwd without paid providers."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def test_direct_main_script_starts_from_another_directory(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'main.py'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env = {**os.environ, 'ENVIRONMENT': 'development', 'TASK_MODE': 'disabled',
           'DATABASE_URL': f'sqlite:///{(tmp_path / "launch.db").as_posix()}',
           'DATA_DIR': str(tmp_path / 'files'), 'DASHSCOPE_API_KEY': '',
           'DASHSCOPE_WORKSPACE_ID': ''}
    opener = build_opener(ProxyHandler({}))
    with (tmp_path / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(script), '--port', str(port)],
                                   cwd=tmp_path, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert process.poll() is None, 'Direct startup process exited unexpectedly'
                try:
                    with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                        state = json.load(response)
                    assert state['status'] == 'ok'
                    assert state['database'] == 'connected'
                    break
                except (URLError, TimeoutError):
                    time.sleep(.1)
            else:
                raise AssertionError('Direct startup did not become healthy')
        finally:
            if os.name == 'nt' and process.poll() is None:
                # Windows venv's launcher may own a Python child process.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            elif process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
