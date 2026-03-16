# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
import os
import sys
import atexit

# Store subprocess references for cleanup
_celery_processes = []

def _start_celery():
    """Start Celery worker and beat as background processes."""
    import subprocess
    
    # Only start in runserver mode, not in other commands
    if 'runserver' not in sys.argv:
        return
    
    # Check if Celery is installed
    try:
        import celery
    except ImportError:
        print("[Celery] Not installed, skipping auto-start")
        return
    
    # Check if Redis is running
    try:
        import redis
        r = redis.Redis()
        r.ping()
    except Exception:
        print("[Celery] Redis not running, skipping auto-start")
        print("[Celery] Run: brew services start redis")
        return
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Start Celery Worker
    worker_cmd = ['celery', '-A', 'stockweb', 'worker', '-l', 'info', '--concurrency=2']
    worker = subprocess.Popen(
        worker_cmd,
        cwd=base_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _celery_processes.append(worker)
    print(f"[Celery] Worker started (PID: {worker.pid})")
    
    # Start Celery Beat
    beat_cmd = ['celery', '-A', 'stockweb', 'beat', '-l', 'info']
    beat = subprocess.Popen(
        beat_cmd,
        cwd=base_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _celery_processes.append(beat)
    print(f"[Celery] Beat started (PID: {beat.pid})")

def _cleanup_celery():
    """Cleanup Celery processes on exit."""
    for proc in _celery_processes:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    if _celery_processes:
        print("[Celery] Processes stopped")

# Register cleanup
atexit.register(_cleanup_celery)

# Import Celery app
try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
    
    # Auto-start Celery in development
    _start_celery()
except ImportError:
    # Celery not installed yet
    pass

