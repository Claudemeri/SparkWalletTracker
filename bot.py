import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv
from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
import asyncio
import aiohttp
import threading
import logging
from pathlib import Path

# Load environment variables
load_dotenv()

# Set up logging
LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)

# Configure logging with multiple handlers
def setup_logger(name, log_file, level=logging.INFO):
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = logging.FileHandler(LOG_DIR / log_file)
    handler.setFormatter(formatter)
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger

# Create loggers for different components
wallet_logger = setup_logger('wallet', 'wallet_operations.log')
token_logger = setup_logger('token', 'token_operations.log')
transaction_logger = setup_logger('transaction', 'transaction_operations.log')
api_logger = setup_logger('api', 'api_operations.log')

# Configure main logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'bot.log'),
        logging.StreamHandler()
    ]
)

# Store wallet data
WALLETS_FILE = 'wallets.json'
TRACKED_TOKENS_FILE = 'tracked_tokens.json'
TRANSACTIONS_FILE = 'transactions.json'

# API settings
MORALIS_API_KEY = os.getenv('MORALIS_API_KEY')
MORALIS_API_URL = "https://solana-gateway.moralis.io/account/mainnet"

class WalletTracker:
    def __init__(self):
        self.wallets = set()
        self.tracked_tokens = {}
        self.transactions = {}
        self.alerts_enabled = True
        self.load_data()
        logging.info("WalletTracker initialized")

    def load_data(self):
        """Load wallets, tracked tokens, and transactions from JSON files"""
        try:
            # Create data directory if it doesn't exist
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            
            # Define file paths
            wallets_file = data_dir / "tracked_wallets.json"
            tokens_file = data_dir / "tracked_tokens.json"
            transactions_file = data_dir / "transactions.json"
            
            # Create files if they don't exist
            if not wallets_file.exists():
                wallets_file.write_text("[]")
            if not tokens_file.exists():
                tokens_file.write_text("{}")
            if not transactions_file.exists():
                transactions_file.write_text("{}")
            
            # Load wallets
            try:
                with open(wallets_file, 'r') as f:
                    self.wallets = set(json.load(f))
                logging.info(f"Loaded {len(self.wallets)} wallets")
            except Exception as e:
                logging.error(f"Error loading wallets: {e}")
                self.wallets = set()
            
            # Load tracked tokens
            try:
                with open(tokens_file, 'r') as f:
                    self.tracked_tokens = json.load(f)
                logging.info(f"Loaded {len(self.tracked_tokens)} tracked tokens")
            except Exception as e:
                logging.error(f"Error loading tracked tokens: {e}")
                self.tracked_tokens = {}
            
            # Load transactions
            try:
                with open(transactions_file, 'r') as f:
                    self.transactions = json.load(f)
                logging.info(f"Loaded {len(self.transactions)} transaction records")
            except Exception as e:
                logging.error(f"Error loading transactions: {e}")
                self.transactions = {}
                
        except Exception as e:
            logging.error(f"Error in load_data: {e}")
            self.wallets = set()
            self.tracked_tokens = {}
            self.transactions = {}

    def save_data(self):
        """Save wallets, tracked tokens, and transactions to JSON files"""
        try:
            # Create data directory if it doesn't exist
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            
            # Save wallets
            with open(data_dir / "tracked_wallets.json", 'w') as f:
                json.dump(list(self.wallets), f)
            logging.info(f"Saved {len(self.wallets)} wallets")
            
            # Save tracked tokens
            with open(data_dir / "tracked_tokens.json", 'w') as f:
                json.dump(self.tracked_tokens, f)
            logging.info(f"Saved {len(self.tracked_tokens)} tracked tokens")
            
            # Save transactions
            with open(data_dir / "transactions.json", 'w') as f:
                json.dump(self.transactions, f)
            logging.info(f"Saved {len(self.transactions)} transaction records")
                
        except Exception as e:
            logging.error(f"Error in save_data: {e}")

    def add_wallet(self, address, name):
        wallet_logger.info(f"Adding wallet {name} ({address})")
        self.wallets.add(address)
        self.save_data()
        wallet_logger.info(f"Wallet {name} ({address}) added successfully")

    def remove_wallet(self, address):
        wallet_logger.info(f"Attempting to remove wallet {address}")
        if address in self.wallets:
            self.wallets.remove(address)
            self.save_data()
            wallet_logger.info(f"Wallet {address} removed successfully")
            return True
        wallet_logger.warning(f"Wallet {address} not found")
        return False

    def get_wallet_name(self, address):
        wallet_logger.debug(f"Getting name for wallet {address}")
        name = self.wallets.get(address, address)
        wallet_logger.debug(f"Wallet {address} name: {name}")
        return name

    def add_tracked_token(self, token_address, wallets):
        token_logger.info(f"Adding tracked token {token_address} for {len(wallets)} wallets")
        self.tracked_tokens[token_address] = {
            'wallets': wallets,
            'added_at': datetime.now().isoformat()
        }
        self.save_data()
        token_logger.info(f"Token {token_address} added successfully")

    def remove_tracked_token(self, token_address):
        token_logger.info(f"Attempting to remove tracked token {token_address}")
        if token_address in self.tracked_tokens:
            del self.tracked_tokens[token_address]
            self.save_data()
            token_logger.info(f"Token {token_address} removed successfully")
            return True
        token_logger.warning(f"Token {token_address} not found")
        return False

    def detect_multi_buys(self, transactions: List[Dict]) -> Optional[Dict]:
        transaction_logger.info(f"Detecting multi-buys from {len(transactions)} transactions")
        # Group transactions by token
        token_buys = {}
        
        for tx in transactions:
            if not tx.get('is_buy'):
                continue
                
            token_address = tx.get('token_address')
            if not token_address:
                continue
                
            if token_address not in token_buys:
                token_buys[token_address] = {
                    'wallets': set(),
                    'total_amount': 0,
                    'token_symbol': tx.get('token_symbol', ''),
                    'transactions': []
                }
            
            token_buys[token_address]['wallets'].add(tx.get('wallet_address'))
            token_buys[token_address]['total_amount'] += float(tx.get('amount', 0))
            token_buys[token_address]['transactions'].append(tx)
        
        # Check for multi-buys
        for token_address, data in token_buys.items():
            if len(data['wallets']) >= self.min_buys_for_alert:
                transaction_logger.info(f"Found potential multi-buy for token {data['token_symbol']} ({token_address})")
                # Check if this multi-buy was already alerted
                if not self.is_multi_buy_already_alerted(token_address, data['transactions']):
                    transaction_logger.info(f"New multi-buy detected: {len(data['wallets'])} wallets bought {data['token_symbol']}")
                    return {
                        'token_address': token_address,
                        'token_symbol': data['token_symbol'],
                        'wallet_count': len(data['wallets']),
                        'total_amount': data['total_amount'],
                        'transactions': data['transactions']
                    }
                else:
                    transaction_logger.info(f"Multi-buy already alerted for token {data['token_symbol']}")
        transaction_logger.info("No new multi-buys detected")
        return None

    def detect_multi_sells(self, transactions: List[Dict]) -> Optional[Dict]:
        transaction_logger.info(f"Detecting multi-sells from {len(transactions)} transactions")
        # Group transactions by token
        token_sells = {}
        
        for tx in transactions:
            if not tx.get('is_sell'):
                continue
                
            token_address = tx.get('token_address')
            if not token_address:
                continue
                
            if token_address not in token_sells:
                token_sells[token_address] = {
                    'wallets': set(),
                    'total_amount': 0,
                    'token_symbol': tx.get('token_symbol', ''),
                    'transactions': []
                }
            
            token_sells[token_address]['wallets'].add(tx.get('wallet_address'))
            token_sells[token_address]['total_amount'] += float(tx.get('amount', 0))
            token_sells[token_address]['transactions'].append(tx)
        
        # Check for multi-sells
        for token_address, data in token_sells.items():
            if len(data['wallets']) >= self.min_sells_for_alert:
                transaction_logger.info(f"Found potential multi-sell for token {data['token_symbol']} ({token_address})")
                # Check if this multi-sell was already alerted
                if not self.is_multi_sell_already_alerted(token_address, data['transactions']):
                    transaction_logger.info(f"New multi-sell detected: {len(data['wallets'])} wallets sold {data['token_symbol']}")
                    return {
                        'token_address': token_address,
                        'token_symbol': data['token_symbol'],
                        'wallet_count': len(data['wallets']),
                        'total_amount': data['total_amount'],
                        'transactions': data['transactions']
                    }
                else:
                    transaction_logger.info(f"Multi-sell already alerted for token {data['token_symbol']}")
        transaction_logger.info("No new multi-sells detected")
        return None

    def is_multi_buy_already_alerted(self, token_address: str, transactions: List[Dict]) -> bool:
        transaction_logger.debug(f"Checking if multi-buy for token {token_address} was already alerted")
        if token_address not in self.transactions:
            transaction_logger.debug(f"No previous transactions found for token {token_address}")
            return False
            
        # Get the signatures of the current transactions
        current_signatures = {tx.get('signature') for tx in transactions}
        
        # Check if any of these transactions were already stored
        for stored_tx in self.transactions[token_address]:
            if stored_tx.get('signature') in current_signatures:
                transaction_logger.debug(f"Found matching signature for token {token_address}")
                return True
                
        transaction_logger.debug(f"No matching signatures found for token {token_address}")
        return False

    def is_multi_sell_already_alerted(self, token_address: str, transactions: List[Dict]) -> bool:
        transaction_logger.debug(f"Checking if multi-sell for token {token_address} was already alerted")
        if token_address not in self.transactions:
            transaction_logger.debug(f"No previous transactions found for token {token_address}")
            return False
            
        # Get the signatures of the current transactions
        current_signatures = {tx.get('signature') for tx in transactions}
        
        # Check if any of these transactions were already stored
        for stored_tx in self.transactions[token_address]:
            if stored_tx.get('signature') in current_signatures:
                transaction_logger.debug(f"Found matching signature for token {token_address}")
                return True
                
        transaction_logger.debug(f"No matching signatures found for token {token_address}")
        return False

    def store_multi_buy(self, token_address: str, transactions: List[Dict]):
        transaction_logger.info(f"Storing multi-buy for token {token_address}")
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_data()
        transaction_logger.info(f"Stored {len(transactions)} transactions for token {token_address}")

    def store_multi_sell(self, token_address: str, transactions: List[Dict]):
        transaction_logger.info(f"Storing multi-sell for token {token_address}")
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_data()
        transaction_logger.info(f"Stored {len(transactions)} transactions for token {token_address}")

# Initialize wallet tracker
wallet_tracker = WalletTracker()

async def get_recent_transactions(wallet_address: str) -> List[Dict]:
    """Get recent transactions for a wallet using the Moralis API"""
    try:
        headers = {
            "Accept": "application/json",
            "X-API-Key": MORALIS_API_KEY,
            "Content-Type": "application/json"
        }
        
        # Update the endpoint to use the correct path
        url = f"{MORALIS_API_URL}/{wallet_address}/swaps"
        
        # Add query parameters
        params = {
            "order": "DESC",
            "limit": 100  # Limit the number of transactions to avoid overwhelming the API
        }
        
        logging.info(f"Making API request for wallet {wallet_address}")
        logging.debug(f"Request URL: {url}")
        logging.debug(f"Request params: {params}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                response_text = await response.text()
                logging.info(f"API Response status: {response.status}")
                logging.debug(f"API Response headers: {response.headers}")
                logging.debug(f"API Response body: {response_text[:1000]}...")  # Log first 1000 chars of response
                
                if response.status == 200:
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logging.error(f"Failed to parse API response: {e}")
                        return []
                        
                    if not isinstance(data, dict):
                        logging.error(f"Unexpected response format: {data}")
                        return []
                        
                    # Get the result array from the response
                    transactions_data = data.get('result', [])
                    if not isinstance(transactions_data, list):
                        logging.error(f"Unexpected result format: {transactions_data}")
                        return []
                        
                    logging.info(f"Found {len(transactions_data)} transactions for wallet {wallet_address}")
                    
                    # Transform Moralis data to our format
                    transactions = []
                    for tx in transactions_data:
                        if not isinstance(tx, dict):
                            continue
                            
                        try:
                            # Get transaction type and subcategory
                            tx_type = tx.get('transactionType', '')
                            sub_category = tx.get('subCategory', '')
                            
                            # Get wallet and token addresses
                            wallet_address = tx.get('walletAddress', '')
                            pair_address = tx.get('pairAddress', '')
                            
                            # Get transaction details
                            bought = tx.get('bought', {})
                            sold = tx.get('sold', {})
                            
                            # Determine if it's a buy or sell
                            is_buy = sub_category == 'newPosition'
                            is_sell = sub_category == 'sellAll'
                            
                            # Only include transactions we want to track
                            if is_buy or is_sell:
                                # Get the correct token symbol and amount based on transaction type
                                token_symbol = bought.get('symbol', '') if is_buy else sold.get('symbol', '')
                                amount = float(bought.get('amount', 0)) if is_buy else float(sold.get('amount', 0))
                                
                                # Parse ISO 8601 timestamp
                                timestamp_str = tx.get('blockTimestamp', '')
                                try:
                                    # Convert ISO 8601 to datetime
                                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                    timestamp = int(dt.timestamp())
                                except (ValueError, TypeError) as e:
                                    logging.error(f"Error parsing timestamp {timestamp_str}: {e}")
                                    continue
                                
                                transaction_data = {
                                    'wallet_address': wallet_address,
                                    'token_address': pair_address,
                                    'token_symbol': token_symbol,
                                    'amount': amount,
                                    'is_buy': is_buy,
                                    'is_sell': is_sell,
                                    'timestamp': timestamp,
                                    'signature': tx.get('signature', ''),
                                    'price': float(tx.get('price', 0)),
                                    'transaction_type': tx_type,
                                    'sub_category': sub_category
                                }
                                transactions.append(transaction_data)
                        except (ValueError, TypeError) as e:
                            logging.error(f"Error processing transaction: {e}")
                            continue
                            
                    logging.info(f"Successfully processed {len(transactions)} transactions for wallet {wallet_address}")
                    return transactions
                else:
                    logging.error(f"API request failed with status {response.status}")
                    logging.error(f"Response: {response_text}")
                    return []
    except Exception as e:
        logging.error(f"Error in get_recent_transactions: {e}", exc_info=True)
        return []

async def check_transactions():
    """Check recent transactions for all tracked wallets"""
    while True:
        if not wallet_tracker.alerts_enabled:
            logging.info("Alerts are disabled, skipping transaction check")
            await asyncio.sleep(60)
            continue

        try:
            logging.info("Starting transaction check")
            # Get transactions for all wallets
            all_transactions = []
            for address in wallet_tracker.wallets:
                logging.info(f"Checking transactions for wallet {address}")
                transactions = await get_recent_transactions(address)
                all_transactions.extend(transactions)
            
            logging.info(f"Total transactions found: {len(all_transactions)}")
            
            # Filter transactions from the last 6 hours
            cutoff_time = int((datetime.now() - timedelta(hours=6)).timestamp())
            recent_transactions = [
                tx for tx in all_transactions 
                if tx.get('timestamp', 0) >= cutoff_time
            ]
            
            # Enhanced logging for recent transactions
            logging.info(f"Recent transactions (last 6 hours): {len(recent_transactions)}")
            if recent_transactions:
                # Group transactions by type (buy/sell)
                buys = [tx for tx in recent_transactions if tx.get('is_buy')]
                sells = [tx for tx in recent_transactions if tx.get('is_sell')]
                
                # Group transactions by token
                token_transactions = {}
                for tx in recent_transactions:
                    token = tx.get('token_symbol', 'Unknown')
                    if token not in token_transactions:
                        token_transactions[token] = {'buys': 0, 'sells': 0, 'total_buy_amount': 0, 'total_sell_amount': 0}
                    if tx.get('is_buy'):
                        token_transactions[token]['buys'] += 1
                        token_transactions[token]['total_buy_amount'] += tx.get('amount', 0)
                    else:
                        token_transactions[token]['sells'] += 1
                        token_transactions[token]['total_sell_amount'] += tx.get('amount', 0)
                
                # Log detailed transaction summary
                logging.info("Transaction Summary:")
                logging.info(f"- Total Buys: {len(buys)}")
                logging.info(f"- Total Sells: {len(sells)}")
                logging.info("\nPer Token Summary:")
                for token, data in token_transactions.items():
                    logging.info(f"\nToken: {token}")
                    logging.info(f"- Buys: {data['buys']}")
                    logging.info(f"- Sells: {data['sells']}")
                    logging.info(f"- Total Buy Amount: {data['total_buy_amount']:.2f} SOL")
                    logging.info(f"- Total Sell Amount: {data['total_sell_amount']:.2f} SOL")
                
                # Log unique wallets involved
                unique_wallets = set(tx.get('wallet_address') for tx in recent_transactions)
                logging.info(f"\nUnique Wallets Involved: {len(unique_wallets)}")
                
                # Log transaction timestamps
                timestamps = [tx.get('timestamp', 0) for tx in recent_transactions]
                if timestamps:
                    latest = max(timestamps)
                    earliest = min(timestamps)
                    latest_time = datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M:%S')
                    earliest_time = datetime.fromtimestamp(earliest).strftime('%Y-%m-%d %H:%M:%S')
                    logging.info(f"\nTime Range:")
                    logging.info(f"- Latest Transaction: {latest_time}")
                    logging.info(f"- Earliest Transaction: {earliest_time}")
            else:
                logging.info("No recent transactions found in the last 6 hours")
            
            # Detect multi-buys
            multi_buy = wallet_tracker.detect_multi_buys(recent_transactions)
            if multi_buy:
                logging.info(f"Multi-buy detected for token {multi_buy['token_symbol']}")
                # Store the multi-buy
                wallet_tracker.store_multi_buy(
                    multi_buy['token_address'],
                    multi_buy['transactions']
                )
                
                # Format and send alert
                message = f"🟢 Multi Buy Alert!\n\n"
                message += f"{multi_buy['wallet_count']} wallets bought {multi_buy['token_symbol']} in the last 6 hours!\n"
                message += f"Total: {multi_buy['total_amount']:.2f} SOL\n\n"
                message += f"{multi_buy['token_address']}"
                
                # Send to all tracked wallets
                for wallet in wallet_tracker.wallets:
                    try:
                        await context.bot.send_message(
                            chat_id=wallet,
                            text=message
                        )
                        logging.info(f"Sent multi-buy alert to wallet {wallet}")
                    except Exception as e:
                        logging.error(f"Error sending notification to {wallet}: {e}")

            # Detect multi-sells
            multi_sell = wallet_tracker.detect_multi_sells(recent_transactions)
            if multi_sell:
                logging.info(f"Multi-sell detected for token {multi_sell['token_symbol']}")
                # Store the multi-sell
                wallet_tracker.store_multi_sell(
                    multi_sell['token_address'],
                    multi_sell['transactions']
                )
                
                # Format and send alert
                message = f"🔴 Multi Sell Alert!\n\n"
                message += f"{multi_sell['wallet_count']} wallets sold {multi_sell['token_symbol']} in the last 6 hours!\n"
                message += f"Total: {multi_sell['total_amount']:.2f} SOL\n\n"
                message += f"{multi_sell['token_address']}"
                
                # Send to all tracked wallets
                for wallet in wallet_tracker.wallets:
                    try:
                        await context.bot.send_message(
                            chat_id=wallet,
                            text=message
                        )
                        logging.info(f"Sent multi-sell alert to wallet {wallet}")
                    except Exception as e:
                        logging.error(f"Error sending notification to {wallet}: {e}")
                        
        except Exception as e:
            logging.error(f"Error checking transactions: {e}", exc_info=True)

        await asyncio.sleep(60)  # Check every minute

def start(update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("➕ Add Wallet", callback_data='add_wallet')],
        [InlineKeyboardButton("➖ Remove Wallet", callback_data='remove_wallet')],
        [InlineKeyboardButton("📝 List Wallets", callback_data='list_wallets')],
        [InlineKeyboardButton("🔍 Track Token", callback_data='track_token')],
        [InlineKeyboardButton("🔔 Toggle Alerts", callback_data='toggle_alerts')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        'Welcome to Solana Wallet Tracker! Choose an option:',
        reply_markup=reply_markup
    )

def show_menu(update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("➕ Add Wallet", callback_data='add_wallet')],
        [InlineKeyboardButton("➖ Remove Wallet", callback_data='remove_wallet')],
        [InlineKeyboardButton("📝 List Wallets", callback_data='list_wallets')],
        [InlineKeyboardButton("🔍 Track Token", callback_data='track_token')],
        [InlineKeyboardButton("🔔 Toggle Alerts", callback_data='toggle_alerts')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        update.message.reply_text("Choose an option:", reply_markup=reply_markup)
    else:
        update.callback_query.message.reply_text("Choose an option:", reply_markup=reply_markup)

def button_handler(update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == 'show_menu':
        show_menu(update, context)
    elif query.data == 'add_wallet':
        context.user_data['state'] = 'waiting_for_wallet_address'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(
            'Please send me the wallet address you want to track.',
            reply_markup=reply_markup
        )
    elif query.data == 'track_token':
        context.user_data['state'] = 'waiting_for_token_address'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(
            'Please send me the token address you want to track.',
            reply_markup=reply_markup
        )
    elif query.data == 'remove_wallet':
        if not wallet_tracker.wallets:
            keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.message.edit_text('No wallets are being tracked.', reply_markup=reply_markup)
            return
        
        keyboard = []
        for addr in wallet_tracker.wallets:
            keyboard.append([InlineKeyboardButton(addr, callback_data=f'remove_{addr}')])
        keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text('Select a wallet to remove:', reply_markup=reply_markup)
    elif query.data == 'list_wallets':
        if not wallet_tracker.wallets:
            text = 'No wallets are being tracked.'
        else:
            text = 'Tracked Wallets:\n' + '\n'.join(wallet_tracker.wallets)
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(text, reply_markup=reply_markup)
    elif query.data == 'toggle_alerts':
        wallet_tracker.alerts_enabled = not wallet_tracker.alerts_enabled
        status = 'enabled' if wallet_tracker.alerts_enabled else 'disabled'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(f'Alerts have been {status}', reply_markup=reply_markup)
    elif query.data.startswith('remove_'):
        address = query.data.replace('remove_', '')
        if wallet_tracker.remove_wallet(address):
            text = f'Removed wallet {address}'
        else:
            text = 'Failed to remove wallet'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(text, reply_markup=reply_markup)
    elif query.data == 'cancel':
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text('Operation cancelled.', reply_markup=reply_markup)
        context.user_data.clear()

def handle_message(update, context: CallbackContext):
    text = update.message.text
    
    if context.user_data.get('state') == 'waiting_for_wallet_address':
        context.user_data['wallet_address'] = text
        context.user_data['state'] = 'waiting_for_wallet_name'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text('Please send me a name for this wallet.', reply_markup=reply_markup)
    elif context.user_data.get('state') == 'waiting_for_wallet_name':
        wallet_address = context.user_data['wallet_address']
        wallet_name = text
        wallet_tracker.add_wallet(wallet_address, wallet_name)
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            f'Added wallet {wallet_name} ({wallet_address})',
            reply_markup=reply_markup
        )
        context.user_data.clear()
    elif context.user_data.get('state') == 'waiting_for_token_address':
        token_address = text
        wallet_tracker.add_tracked_token(token_address, list(wallet_tracker.wallets))
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            f'Now tracking token {token_address} for all wallets',
            reply_markup=reply_markup
        )
        context.user_data.clear()

def main():
    # Create the Updater and pass it your bot's token
    updater = Updater(os.getenv('TELEGRAM_BOT_TOKEN'), use_context=True)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("menu", show_menu))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # Start async tasks in a separate thread
    async_thread = threading.Thread(target=run_async_tasks, daemon=True)
    async_thread.start()

    # Start keep_alive
    from keep_alive import keep_alive
    keep_alive()

    # Start the bot
    updater.start_polling()
    updater.idle()

def run_async_tasks():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_transactions())
    loop.run_forever()

if __name__ == '__main__':
    main() 