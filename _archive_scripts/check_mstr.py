
import os
import django
import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from updatedata.models import PriceHistory

def check_mstr():
    count = PriceHistory.objects.filter(symbol__symbol='MSTR').count()
    with open("/Users/jiwanlee/Code/stockweb/mstr_count.txt", "w") as f:
        f.write(str(count))

if __name__ == "__main__":
    check_mstr()
