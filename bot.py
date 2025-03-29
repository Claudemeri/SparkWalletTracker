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
    """
    A class to manage wallet tracking, token monitoring, and transaction analysis.
    Handles storage and retrieval of wallet data, token tracking, and transaction monitoring.
    """

    def __init__(self):
        """
        Initialize the WalletTracker with empty data structures.
        Sets up dictionaries for wallets, tracked tokens, and transactions.
        """
        self.wallets = {}  # Dictionary to store wallet addresses and their details
        self.tracked_tokens = {}  # Dictionary to store tracked token information
        self.transactions = {}  # Dictionary to store transaction history
        self.alerts_enabled = True  # Flag to control alert notifications
        self.last_api_calls = {}  # Dictionary to track last API call time for each wallet
        self.load_data()  # Load existing data from files
        logging.info("WalletTracker initialized")

    def load_data(self):
        """
        Load all data from JSON files in the data directory.
        Creates the data directory and files if they don't exist.
        Handles errors gracefully by initializing empty data structures if loading fails.
        """
        try:
            # Create data directory if it doesn't exist
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            
            # Define file paths for data storage
            wallets_file = data_dir / "tracked_wallets.json"
            tokens_file = data_dir / "tracked_tokens.json"
            transactions_file = data_dir / "transactions.json"
            
            # Create files with empty data structures if they don't exist
            if not wallets_file.exists():
                wallets_file.write_text("{}")
            if not tokens_file.exists():
                tokens_file.write_text("{}")
            if not transactions_file.exists():
                transactions_file.write_text("{}")
            
            # Load wallets with error handling
            try:
                with open(wallets_file, 'r') as f:
                    self.wallets = json.load(f)
                logging.info(f"Loaded {len(self.wallets)} wallets")
            except Exception as e:
                logging.error(f"Error loading wallets: {e}")
                self.wallets = {}
            
            # Load tracked tokens with error handling
            try:
                with open(tokens_file, 'r') as f:
                    self.tracked_tokens = json.load(f)
                logging.info(f"Loaded {len(self.tracked_tokens)} tracked tokens")
            except Exception as e:
                logging.error(f"Error loading tracked tokens: {e}")
                self.tracked_tokens = {}
            
            # Load transactions with error handling
            try:
                with open(transactions_file, 'r') as f:
                    self.transactions = json.load(f)
                logging.info(f"Loaded {len(self.transactions)} transaction records")
            except Exception as e:
                logging.error(f"Error loading transactions: {e}")
                self.transactions = {}
                
        except Exception as e:
            logging.error(f"Error in load_data: {e}")
            self.wallets = {}
            self.tracked_tokens = {}
            self.transactions = {}

    def save_data(self):
        """
        Save all data to JSON files in the data directory.
        Creates the data directory if it doesn't exist.
        Handles errors gracefully and logs any issues.
        """
        try:
            # Create data directory if it doesn't exist
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            
            # Save wallets to file
            with open(data_dir / "tracked_wallets.json", 'w') as f:
                json.dump(self.wallets, f)
            logging.info(f"Saved {len(self.wallets)} wallets")
            
            # Save tracked tokens to file
            with open(data_dir / "tracked_tokens.json", 'w') as f:
                json.dump(self.tracked_tokens, f)
            logging.info(f"Saved {len(self.tracked_tokens)} tracked tokens")
            
            # Save transactions to file
            with open(data_dir / "transactions.json", 'w') as f:
                json.dump(self.transactions, f)
            logging.info(f"Saved {len(self.transactions)} transaction records")
                
        except Exception as e:
            logging.error(f"Error in save_data: {e}")

    def add_wallet(self, address, name):
        """
        Add a new wallet to track.
        
        Args:
            address (str): The wallet address to track
            name (str): A friendly name for the wallet
            
        Logs the addition and saves the updated data.
        """
        try:
            # Create data directory if it doesn't exist
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            
            # Create tracked_wallets.json if it doesn't exist
            wallets_file = data_dir / "tracked_wallets.json"
            if not wallets_file.exists():
                wallets_file.write_text("{}")
                logging.info("Created new tracked_wallets.json file")
            
            wallet_logger.info(f"Adding wallet {name} ({address})")
            self.wallets[address] = {
                'name': name,
                'added_at': datetime.now().isoformat()
            }
            self.save_data()
            wallet_logger.info(f"Wallet {name} ({address}) added successfully")
        except Exception as e:
            wallet_logger.error(f"Error adding wallet {name} ({address}): {e}")
            raise

    def remove_wallet(self, address):
        """
        Remove a wallet from tracking.
        
        Args:
            address (str): The wallet address to remove
            
        Returns:
            bool: True if wallet was removed, False if not found
            
        Logs the removal and saves the updated data.
        """
        wallet_logger.info(f"Attempting to remove wallet {address}")
        if address in self.wallets:
            wallet_name = self.wallets[address]['name']
            del self.wallets[address]
            self.save_data()
            wallet_logger.info(f"Wallet {wallet_name} ({address}) removed successfully")
            return True
        wallet_logger.warning(f"Wallet {address} not found")
        return False

    def get_wallet_name(self, address):
        """
        Get the friendly name of a wallet.
        
        Args:
            address (str): The wallet address
            
        Returns:
            str: The wallet's friendly name or address if name not found
        """
        wallet_logger.debug(f"Getting name for wallet {address}")
        name = self.wallets.get(address, {}).get('name', address)
        wallet_logger.debug(f"Wallet {address} name: {name}")
        return name

    def add_tracked_token(self, token_address, wallets):
        """
        Add a new token to track for specified wallets.
        
        Args:
            token_address (str): The token address to track
            wallets (list): List of wallet addresses to track the token for
            
        Logs the addition and saves the updated data.
        """
        token_logger.info(f"Adding tracked token {token_address} for {len(wallets)} wallets")
        self.tracked_tokens[token_address] = {
            'wallets': wallets,
            'added_at': datetime.now().isoformat()
        }
        self.save_data()
        token_logger.info(f"Token {token_address} added successfully")

    def remove_tracked_token(self, token_address):
        """
        Remove a token from tracking.
        
        Args:
            token_address (str): The token address to remove
            
        Returns:
            bool: True if token was removed, False if not found
            
        Logs the removal and saves the updated data.
        """
        token_logger.info(f"Attempting to remove tracked token {token_address}")
        if token_address in self.tracked_tokens:
            del self.tracked_tokens[token_address]
            self.save_data()
            token_logger.info(f"Token {token_address} removed successfully")
            return True
        token_logger.warning(f"Token {token_address} not found")
        return False

    def detect_multi_buys(self, transactions: List[Dict]) -> Optional[Dict]:
        """
        Analyze transactions to detect multiple buys of the same token.
        
        Args:
            transactions (List[Dict]): List of transaction dictionaries
            
        Returns:
            Optional[Dict]: Dictionary containing multi-buy information if detected, None otherwise
            
        Logs the detection process and results.
        """
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
        """
        Analyze transactions to detect multiple sells of the same token.
        
        Args:
            transactions (List[Dict]): List of transaction dictionaries
            
        Returns:
            Optional[Dict]: Dictionary containing multi-sell information if detected, None otherwise
            
        Logs the detection process and results.
        """
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
        """
        Check if a multi-buy has already been alerted to prevent duplicate notifications.
        
        Args:
            token_address (str): The token address to check
            transactions (List[Dict]): List of transactions to check
            
        Returns:
            bool: True if multi-buy was already alerted, False otherwise
            
        Logs the checking process and results.
        """
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
        """
        Check if a multi-sell has already been alerted to prevent duplicate notifications.
        
        Args:
            token_address (str): The token address to check
            transactions (List[Dict]): List of transactions to check
            
        Returns:
            bool: True if multi-sell was already alerted, False otherwise
            
        Logs the checking process and results.
        """
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
        """
        Store multi-buy transactions to prevent duplicate alerts.
        
        Args:
            token_address (str): The token address
            transactions (List[Dict]): List of transactions to store
            
        Logs the storage process and saves the updated data.
        """
        transaction_logger.info(f"Storing multi-buy for token {token_address}")
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_data()
        transaction_logger.info(f"Stored {len(transactions)} transactions for token {token_address}")

    def store_multi_sell(self, token_address: str, transactions: List[Dict]):
        """
        Store multi-sell transactions to prevent duplicate alerts.
        
        Args:
            token_address (str): The token address
            transactions (List[Dict]): List of transactions to store
            
        Logs the storage process and saves the updated data.
        """
        transaction_logger.info(f"Storing multi-sell for token {token_address}")
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_data()
        transaction_logger.info(f"Stored {len(transactions)} transactions for token {token_address}")

    def can_call_api(self, wallet_address: str) -> bool:
        """
        Check if we can make an API call for a specific wallet.
        
        Args:
            wallet_address (str): The wallet address to check
            
        Returns:
            bool: True if we can make an API call, False if we need to wait
        """
        current_time = datetime.now()
        last_call = self.last_api_calls.get(wallet_address)
        
        if last_call is None:
            return True
            
        # Check if at least 60 seconds have passed since last call
        time_diff = (current_time - last_call).total_seconds()
        return time_diff >= 60

    def update_last_api_call(self, wallet_address: str):
        """
        Update the last API call timestamp for a wallet.
        
        Args:
            wallet_address (str): The wallet address to update
        """
        self.last_api_calls[wallet_address] = datetime.now()

# Initialize wallet tracker
wallet_tracker = WalletTracker()

async def get_recent_transactions(wallet_address: str) -> List[Dict]:
    """
    Fetch recent transactions for a wallet using the Moralis API.
    
    Args:
        wallet_address (str): The wallet address to fetch transactions for
        
    Returns:
        List[Dict]: List of transaction dictionaries
        
    Logs the API request process and any errors encountered.
    """
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
    """
    Continuously check for recent transactions and detect multi-buys/sells.
    Runs in a loop with a 60-second delay between checks.
    Logs detailed information about transactions and alerts.
    """
    while True:
        if not wallet_tracker.alerts_enabled:
            logging.info("Alerts are disabled, skipping transaction check")
            await asyncio.sleep(60)
            continue

        try:
            # Skip if no wallets are being tracked
            if not wallet_tracker.wallets:
                logging.info("No wallets are being tracked, skipping transaction check")
                await asyncio.sleep(60)
                continue

            logging.info("Starting transaction check")
            # Get transactions for all wallets
            all_transactions = []
            for address in wallet_tracker.wallets:
                # Check if we can make an API call for this wallet
                if not wallet_tracker.can_call_api(address):
                    logging.info(f"Skipping API call for wallet {address} - too soon since last call")
                    continue
                    
                logging.info(f"Checking transactions for wallet {address}")
                transactions = await get_recent_transactions(address)
                if transactions:  # Only update timestamp if we got transactions
                    wallet_tracker.update_last_api_call(address)
                all_transactions.extend(transactions)
            
            # If no transactions were fetched (all wallets were skipped), wait before next check
            if not all_transactions:
                logging.info("No transactions fetched in this cycle, waiting before next check")
                await asyncio.sleep(60)
                continue
                
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
    """
    Handle the /start command.
    Displays the main menu with available options.
    """
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
    """
    Display the main menu with available options.
    Can be called from both message and callback query handlers.
    """
    keyboard = [
        [InlineKeyboardButton("➕ Add Wallet", callback_data='add_wallet')],
        [InlineKeyboardButton("➖ Remove Wallet", callback_data='remove_wallet')],
        [InlineKeyboardButton("✏️ Modify Wallet", callback_data='modify_wallet')],
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
    """
    Handle button callbacks from the inline keyboard.
    Manages all menu options and user interactions.
    """
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
    elif query.data == 'modify_wallet':
        if not wallet_tracker.wallets:
            keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.message.edit_text('No wallets are being tracked.', reply_markup=reply_markup)
            return
        
        keyboard = []
        for addr, data in wallet_tracker.wallets.items():
            keyboard.append([InlineKeyboardButton(data['name'], callback_data=f'modify_{addr}')])
        keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text('Select a wallet to modify:', reply_markup=reply_markup)
    elif query.data.startswith('modify_'):
        address = query.data.replace('modify_', '')
        context.user_data['modify_address'] = address
        keyboard = [
            [InlineKeyboardButton("✏️ Change Name", callback_data='change_name')],
            [InlineKeyboardButton("🔄 Change Address", callback_data='change_address')],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(
            f'What would you like to modify for {wallet_tracker.get_wallet_name(address)}?',
            reply_markup=reply_markup
        )
    elif query.data == 'change_name':
        context.user_data['state'] = 'waiting_for_new_name'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(
            'Please send me the new name for this wallet.',
            reply_markup=reply_markup
        )
    elif query.data == 'change_address':
        context.user_data['state'] = 'waiting_for_new_address'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(
            'Please send me the new address for this wallet.',
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
        for addr, data in wallet_tracker.wallets.items():
            keyboard.append([InlineKeyboardButton(data['name'], callback_data=f'remove_{addr}')])
        keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text('Select a wallet to remove:', reply_markup=reply_markup)
    elif query.data == 'list_wallets':
        if not wallet_tracker.wallets:
            text = '📭 No wallets are being tracked.'
        else:
            text = '📋 *Tracked Wallets*\n\n'
            for addr, data in wallet_tracker.wallets.items():
                # Add a separator line between wallets
                text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                # Add wallet name and address with emojis
                text += f"👤 *Name:* {data['name']}\n"
                text += f"🔑 *Address:* `{addr}`\n"
                # Add when the wallet was added
                added_at = datetime.fromisoformat(data['added_at'])
                text += f"📅 *Added:* {added_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                text += "\n"  # Add extra line for spacing
            
            # Add a summary at the top
            text = f"📊 *Total Wallets:* {len(wallet_tracker.wallets)}\n\n" + text
            
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif query.data == 'toggle_alerts':
        wallet_tracker.alerts_enabled = not wallet_tracker.alerts_enabled
        status = 'enabled' if wallet_tracker.alerts_enabled else 'disabled'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(f'Alerts have been {status}', reply_markup=reply_markup)
    elif query.data.startswith('remove_'):
        address = query.data.replace('remove_', '')
        if wallet_tracker.remove_wallet(address):
            text = f'Removed wallet {wallet_tracker.get_wallet_name(address)} ({address})'
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
    """
    Handle text messages from users.
    Manages the wallet and token addition process.
    """
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
        wallet_tracker.add_tracked_token(token_address, list(wallet_tracker.wallets.keys()))
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            f'Now tracking token {token_address} for all wallets',
            reply_markup=reply_markup
        )
        context.user_data.clear()
    elif context.user_data.get('state') == 'waiting_for_new_name':
        old_address = context.user_data['modify_address']
        old_name = wallet_tracker.get_wallet_name(old_address)
        new_name = text
        
        # Update the wallet name
        wallet_tracker.wallets[old_address]['name'] = new_name
        wallet_tracker.save_data()
        
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            f'Updated wallet name from {old_name} to {new_name}',
            reply_markup=reply_markup
        )
        context.user_data.clear()
    elif context.user_data.get('state') == 'waiting_for_new_address':
        old_address = context.user_data['modify_address']
        old_name = wallet_tracker.get_wallet_name(old_address)
        new_address = text
        
        # Update the wallet address
        wallet_tracker.wallets[new_address] = wallet_tracker.wallets.pop(old_address)
        wallet_tracker.save_data()
        
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            f'Updated wallet address for {old_name} from {old_address} to {new_address}',
            reply_markup=reply_markup
        )
        context.user_data.clear()

def main():
    """
    Main function to start the bot.
    Sets up logging, handlers, and starts the bot.
    """
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
    """
    Run async tasks in a separate thread.
    Currently runs the transaction checking loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_transactions())
    loop.run_forever()

if __name__ == '__main__':
    main() 