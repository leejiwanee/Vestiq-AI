import yfinance as yf

# Symbols from user's screenshot
symbols = ['LEN.B', 'NIQ', 'BF.A', 'USD', 'UHALB', 'GLIBR']

print("Checking sector/industry data for NULL symbols...\n")

for sym in symbols:
    print(f"{'='*60}")
    print(f"Symbol: {sym}")
    try:
        ticker = yf.Ticker(sym)
        info = ticker.info
        
        sector = info.get('sector', 'NOT FOUND')
        industry = info.get('industry', 'NOT FOUND')
        quote_type = info.get('quoteType', 'NOT FOUND')
        
        print(f"  Quote Type: {quote_type}")
        print(f"  Sector: {sector}")
        print(f"  Industry: {industry}")
        
        # Additional context
        if sector == 'NOT FOUND':
            print(f"  ⚠️  YFinance has NO sector data")
        else:
            print(f"  ✅ Sector exists!")
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
    print()
