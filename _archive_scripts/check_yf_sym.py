
import yfinance as yf
import pandas as pd

def test_syms():
    # Test Dot vs Hyphen
    pairs = [
        ('BRK.B', 'BRK-B'),
        ('BF.B', 'BF-B'),
        ('CWEN.A', 'CWEN-A'),
        ('LEN.B', 'LEN-B')
    ]
    
    for dot, hyp in pairs:
        print(f"Testing {dot} vs {hyp}...")
        
        # Test Dot
        d_dot = yf.download(dot, period="1d", progress=False, threads=False)
        if d_dot.empty:
            print(f"  [FAIL] {dot} returned empty.")
        else:
            print(f"  [PASS] {dot} returned data.")
            
        # Test Hyphen
        d_hyp = yf.download(hyp, period="1d", progress=False, threads=False)
        if d_hyp.empty:
            print(f"  [FAIL] {hyp} returned empty.")
        else:
            print(f"  [PASS] {hyp} returned data.")

if __name__ == "__main__":
    test_syms()
