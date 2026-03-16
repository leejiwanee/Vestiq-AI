import websocket
import json
import threading
import time
import logging
import ssl
from django.conf import settings
from django.utils import timezone
from updatedata.models import Ticker

logger = logging.getLogger(__name__)

class TiingoWebsocketClient:
    def __init__(self):
        self.api_key = settings.TIINGO_API_KEY
        if self.api_key:
            masked = self.api_key[:4] + "*" * 4 if len(self.api_key) > 4 else "INVALID"
            print(f"[TiingoWS] API Key loaded: {masked}")
        else:
            print("[TiingoWS] API Key is MISSING!")

        # self.ws_url = "wss://api.tiingo.com/iex"
        # Append token to URL for handshake auth
        self.ws_url = f"wss://api.tiingo.com/iex?token={self.api_key}"
        self.ws = None
        self.keep_running = True
        self.buffer = {} # symbol -> {price, timestamp}
        self.lock = threading.Lock()
        self.last_flush = time.time()
        self.flush_interval = 2.0 # Flush to DB every 2 seconds

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            message_type = data.get('messageType')
            
            if message_type == 'A': # Data update
                payload = data.get('data') # List of updates
                if payload:
                    # print(f"[TiingoWS] Received updates for {len(payload)} tickers")
                    with self.lock:
                        for item in payload:
                            ticker = item.get('ticker')
                            price = item.get('last')
                            
                            if ticker and price:
                                self.buffer[ticker] = price
            
            elif message_type == 'H': # Heartbeat
                print("[TiingoWS] Heartbeat received")
                                
        except Exception as e:
            logger.error(f"[TiingoWS] Parse error: {e}")

    def on_error(self, ws, error):
        logger.error(f"[TiingoWS] Error: {error}")
        print(f"[TiingoWS] Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.info("[TiingoWS] Closed")
        print("[TiingoWS] Connection Closed")

    def on_open(self, ws):
        logger.info("[TiingoWS] Connected. Subscribing...")
        print("[TiingoWS] Connected! Subscribing to tickers...")
        
        try:
            tickers = list(Ticker.objects.all().values_list('symbol', flat=True))
            if not tickers:
                logger.warning("[TiingoWS] No tickers to subscribe.")
                print("[TiingoWS] Warning: No tickers found in DB to subscribe.")
                return

            subscribe_msg = {
                'eventName': 'subscribe',
                'authorization': self.api_key,
                'eventData': { 
                    'tickers': tickers
                }
            }
            ws.send(json.dumps(subscribe_msg))
            logger.info(f"[TiingoWS] Subscribed to {len(tickers)} tickers.")
            print(f"[TiingoWS] Subscribed to {len(tickers)} tickers.")
            
        except Exception as e:
            logger.error(f"[TiingoWS] Subscription failed: {e}")
            print(f"[TiingoWS] Subscription failed: {e}")

    def db_flusher(self):
        """Background thread to flush buffer to DB"""
        while self.keep_running:
            time.sleep(self.flush_interval)
            
            updates = {}
            with self.lock:
                if not self.buffer:
                    continue
                updates = self.buffer.copy()
                self.buffer.clear()
            
            symbols = list(updates.keys())
            ticker_objs = Ticker.objects.filter(symbol__in=symbols)
            
            to_update = []
            now = timezone.now()
            
            for t in ticker_objs:
                new_price = updates.get(t.symbol)
                if new_price:
                    t.last_price = new_price
                    t.updated_at = now
                    to_update.append(t)
            
            if to_update:
                Ticker.objects.bulk_update(to_update, ['last_price', 'updated_at'])

    def run(self):
        # Start flusher thread
        flusher = threading.Thread(target=self.db_flusher, daemon=True)
        flusher.start()
        
        while self.keep_running:
            try:
                # websocket.enableTrace(True)
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                # Disable SSL verification to avoid "verify failed" errors
                self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            except Exception as e:
                logger.error(f"[TiingoWS] Connection failed: {e}")
                time.sleep(5) # Reconnect delay

def start_stream():
    client = TiingoWebsocketClient()
    client.run()
