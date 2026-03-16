from django.apps import AppConfig
import sys
import os
import threading
import time
from datetime import date

class UpdatedataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'updatedata'

    def ready(self):
        # Prevent running twice with auto-reloader
        # Django runserver with reload starts two processes. 
        # RUN_MAIN is set in the second (child) process.
        # We only want to run in the actual server process.
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return
            
        # Avoid running during migrations or shell
        if any(x in sys.argv for x in ['makemigrations', 'migrate', 'shell', 'dbshell']):
            return

        def startup_check():
            # Wait for DB to be potentially ready
            time.sleep(10)
            
            from .tasks import run_startup_recovery
            try:
                run_startup_recovery()
            except Exception as e:
                print(f"[STARTUP] Error during recovery check: {e}")


        # Start background thread
        t = threading.Thread(target=startup_check, daemon=True)
        t.start()

