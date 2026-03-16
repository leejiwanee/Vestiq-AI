import datetime
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

def is_trading_day(date_obj=None):
    """
    Checks if the given date (default Today) is a valid trading day.
    - Not Weekend (Sat/Sun)
    - Not US Federal Holiday
    """
    if date_obj is None:
        date_obj = datetime.date.today()
        
    # 1. Check Weekend
    # weekday(): 0=Mon, 4=Fri, 5=Sat, 6=Sun
    if date_obj.weekday() >= 5:
        return False
        
    # 2. Check Holidays
    # Using USFederalHolidayCalendar as approximation for NYSE
    cal = USFederalHolidayCalendar()
    holidays = cal.holidays(start=date_obj, end=date_obj)
    
    if not holidays.empty:
        return False
        
    return True
