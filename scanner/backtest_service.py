import pandas as pd
import numpy as np
from datetime import timedelta
from django.utils import timezone
from django.db.models import F
from scanner.models import ScanBatch # Keep ScanBatch if needed, remove DailyPrice
from updatedata.models import Ticker, PriceHistory

class BacktestEngine:
    def __init__(self, strategy_config):
        """
        strategy_config: {
            'rsi_threshold': 30,
            'volume_multiplier': 2.0, # vs 20-day avg
            'profit_target_pct': 5.0,
            'max_hold_days': 5,
            'initial_capital': 10000
        }
        """
        self.config = strategy_config
        self.capital = strategy_config.get('initial_capital', 10000)
        self.results = {
            'trades': [],
            'equity_curve': [],
            'stats': {}
        }

    def fetch_data(self, days=365):
        """Fetch PriceHistory data for active tickers"""
        try:
            end_date = timezone.localdate()
        except ValueError:
            # Fallback for naive datetime (USE_TZ=False)
            end_date = timezone.now().date()
            
        start_date = end_date - timedelta(days=days + 60) # Extra buffer for indicators

        # Get active tickers only to optimize
        # active_symbols = list(Ticker.objects.filter(is_active=True).values_list('symbol', flat=True))
        # [Fix] Ticker model doesn't have is_active. Use all tickers or filter by market.
        active_symbols = list(Ticker.objects.values_list('symbol', flat=True))
        
        # Fetch prices from PriceHistory (updatedata app)
        qs = PriceHistory.objects.filter(
            symbol__symbol__in=active_symbols, 
            date__gte=start_date,
            date__lte=end_date
        ).values('symbol__symbol', 'date', 'close', 'volume')
        
        df = pd.DataFrame(list(qs))
        if df.empty:
            return None
            
        df['date'] = pd.to_datetime(df['date'])
        
        # Rename symbol__symbol to symbol for compatibility
        df.rename(columns={'symbol__symbol': 'symbol'}, inplace=True)
        
        df = df.sort_values(['symbol', 'date'])
        return df

    def calculate_indicators(self, df):
        """Calculate RSI and Volume MA using Pandas"""
        # Group by symbol to calculate indicators per stock
        grouped = df.groupby('symbol')
        
        # RSI Calculation
        def calc_rsi(series, period=14):
            delta = series.diff()
            gain = delta.clip(lower=0)
            loss = (-delta).clip(lower=0)
            avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
            avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            return 100 - (100 / (1 + rs))

        df['rsi'] = grouped['close'].transform(lambda x: calc_rsi(x))
        
        # Volume MA (20 days)
        df['vol_ma'] = grouped['volume'].transform(lambda x: x.rolling(window=20).mean())
        
        # Drop NaN values created by indicators
        df = df.dropna()
        return df

    def run(self):
        # 1. Fetch Data
        raw_df = self.fetch_data()
        if raw_df is None or raw_df.empty:
            return {'error': 'No data found'}

        # 2. Calculate Indicators
        df = self.calculate_indicators(raw_df)
        
        # 3. Simulate
        trades = []
        open_positions = [] # [{'symbol': 'AAPL', 'buy_date': date, 'buy_price': 100, 'days_held': 0}]
        
        # Unique dates sorted
        dates = sorted(df['date'].unique())
        
        # Parameters
        rsi_limit = float(self.config.get('rsi_threshold', 30))
        vol_mult = float(self.config.get('volume_multiplier', 1.5))
        profit_target = float(self.config.get('profit_target_pct', 5.0)) / 100.0
        max_hold = int(self.config.get('max_hold_days', 5))
        
        current_equity = self.capital
        equity_curve = []

        # Pivot for faster access by date? 
        # Actually, iterating by date is safer for simulation.
        # But for speed, we can pre-calculate signals.
        
        # Identify Buy Signals
        # Condition: RSI < Limit AND Volume > MA * Mult
        df['buy_signal'] = (df['rsi'] < rsi_limit) & (df['volume'] > df['vol_ma'] * vol_mult)
        
        # We need to iterate day by day to manage positions
        # To optimize, we can pivot the dataframe: Index=Date, Columns=(Symbol, Close, BuySignal)
        # But simpler loop might be enough for 1 year data.
        
        # Let's group by date for iteration
        df_by_date = dict(tuple(df.groupby('date')))
        
        for d in dates:
            day_data = df_by_date.get(d)
            if day_data is None: continue
            
            # 1. Check Sell Conditions for Open Positions
            # We use today's Close price for selling (simplified)
            # In reality, we might sell at Open or High, but Close is conservative/simple.
            
            # Create a map of today's prices for quick lookup
            price_map = day_data.set_index('symbol')['close'].to_dict()
            
            remaining_positions = []
            for pos in open_positions:
                sym = pos['symbol']
                if sym not in price_map:
                    # No data today, keep holding
                    pos['days_held'] += 1
                    remaining_positions.append(pos)
                    continue
                
                curr_price = price_map[sym]
                buy_price = pos['buy_price']
                pnl_pct = (curr_price - buy_price) / buy_price
                
                # Sell Rules
                is_profit = pnl_pct >= profit_target
                is_timeout = pos['days_held'] >= max_hold
                
                if is_profit or is_timeout:
                    # Execute Sell
                    trades.append({
                        'symbol': sym,
                        'buy_date': pos['buy_date'].strftime('%Y-%m-%d'),
                        'buy_price': buy_price,
                        'sell_date': d.strftime('%Y-%m-%d'),
                        'sell_price': curr_price,
                        'pnl_pct': round(pnl_pct * 100, 2),
                        'pnl_amount': round(pos['invested'] * pnl_pct, 2),
                        'reason': 'Profit Target' if is_profit else 'Time Limit'
                    })
                    current_equity += pos['invested'] * (1 + pnl_pct)
                else:
                    pos['days_held'] += 1
                    remaining_positions.append(pos)
            
            open_positions = remaining_positions
            
            # 2. Check Buy Signals
            # Only buy if we have capital (simplified: fixed amount per trade or max positions)
            # Let's say we invest fixed $1000 per trade, or split capital.
            # For simplicity: $1000 per trade.
            trade_size = 1000
            
            buys = day_data[day_data['buy_signal']]
            for _, row in buys.iterrows():
                if current_equity >= trade_size:
                    open_positions.append({
                        'symbol': row['symbol'],
                        'buy_date': d,
                        'buy_price': row['close'],
                        'invested': trade_size,
                        'days_held': 0
                    })
                    current_equity -= trade_size
            
            # Record Equity
            # Equity = Cash + Value of Open Positions
            open_pos_value = 0
            for pos in open_positions:
                # Use today's price if available, else buy price (conservative)
                sym = pos['symbol']
                price = price_map.get(sym, pos['buy_price'])
                shares = pos['invested'] / pos['buy_price']
                open_pos_value += shares * price
                
            total_equity = current_equity + open_pos_value
            equity_curve.append({
                'date': d.strftime('%Y-%m-%d'),
                'equity': round(total_equity, 2)
            })

        # Generate Stats
        win_trades = [t for t in trades if t['pnl_pct'] > 0]
        win_rate = (len(win_trades) / len(trades) * 100) if trades else 0
        total_return = ((equity_curve[-1]['equity'] - self.capital) / self.capital * 100) if equity_curve else 0
        
        return {
            'trades': trades[-50:], # Return last 50 trades
            'equity_curve': equity_curve, # Sampled if too large? 250 points is fine.
            'stats': {
                'total_trades': len(trades),
                'win_rate': round(win_rate, 1),
                'total_return': round(total_return, 2),
                'final_equity': round(equity_curve[-1]['equity'], 2) if equity_curve else self.capital
            }
        }
