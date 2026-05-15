
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

print("Verifying Celery Task Imports...")

# 1. Check Expected Tasks
expected_tasks = [
    ('updatedata.tasks', 'celery_update_daily_close'),
    ('updatedata.tasks', 'celery_update_fundamentals'),
    ('insight.tasks', 'celery_update_sector_leaders'),
    ('news.tasks', 'celery_collect_news')
]

all_passed = True
for module, task_name in expected_tasks:
    try:
        mod = __import__(module, fromlist=[task_name])
        task = getattr(mod, task_name)
        print(f"✅ Found {task_name} in {module}")
    except ImportError:
        print(f"❌ ImportError: Could not import {module}")
        all_passed = False
    except AttributeError:
        print(f"❌ AttributeError: {task_name} not found in {module}")
        all_passed = False
    except Exception as e:
        print(f"❌ Error checking {task_name}: {e}")
        all_passed = False

# 2. Check Removed Task (Should NOT exist)
try:
    from updatedata.tasks import celery_intraday_update
    print("❌ Error: celery_intraday_update SHOULD be gone, but it was found!")
    all_passed = False
except ImportError:
    print("✅ celery_intraday_update is correctly removed (ImportError as expected).")
except Exception as e:
    print(f"✅ celery_intraday_update check raised {type(e).__name__} (likely expected).")


if all_passed:
    print("\n🎉 Verification SUCCESS: All tasks match the implementation plan.")
    sys.exit(0)
else:
    print("\n⚠️ Verification FAILED: Check errors above.")
    sys.exit(1)
