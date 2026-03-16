import yfinance as yf
import json

def check_news():
    ticker = yf.Ticker("AAPL")
    news = ticker.news
    print(json.dumps(news, indent=2))

if __name__ == "__main__":
    check_news()
