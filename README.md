# What is Vestiq?

Vestiq is a stock market analysis platform I built to move beyond standard price charts and simple screeners. While most stock apps just throw raw data and moving averages at you, Vestiq uses AI to help interpret *why* a stock or the market is moving.

I wanted a tool that would automatically scan the market for technical setups, read through SEC 10-K and 10-Q filings, pull the latest relevant news, and actually synthesize all of that information into something readable using Google's Gemini AI.

## How it works

The core idea is to automate the fundamental and technical research that a human trader would normally do by hand:
- **It scans for technicals:** It continually filters the stock universe looking for specific patterns—volume spikes, momentum changes, and value setups.
- **It reads the news and filings:** Instead of just linking to SEC filings and news articles, Vestiq actively pulls them and parses the text.
- **It summarizes the mood:** It looks at the S&P 500, NASDAQ, and VIX alongside daily headlines to generate a broad "market sentiment" check (basically a dynamic bull/bear gauge).
- **It writes reports:** When you look at a specific stock, Vestiq takes the technical data, recent news, and fundamental metrics, and uses Gemini to write a plain-English briefing on the stock.

Ultimately, Vestiq is designed to save time researching individual stocks and to give a clearer, data-backed picture of what the market is actually doing on any given day.
