
import os
import sys
import django
import logging

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

# Configure logging to console for visibility
logging.basicConfig(level=logging.INFO)

print(">>> Manually Triggering Startup Recovery...")

from updatedata.tasks import run_startup_recovery

try:
    # This checks Is Trading Day -> Checks Time > 16:xx -> Runs Updates Sequentially
    run_startup_recovery()
    print(">>> Recovery Function Completed Successfully.")
except Exception as e:
    print(f"!!! Recovery Failed: {e}")
    import traceback
    traceback.print_exc()
