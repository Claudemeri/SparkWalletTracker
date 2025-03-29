import os
import json
import asyncio
import base58
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv
from telegram import ParseMode, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from solders.message import Message
import threading
import time
from httpx import HTTPStatusError
from solders.signature import Signature
from flask import Flask, request, jsonify
import hmac
import hashlib
import requests
import aiohttp

# Load environment variables
load_dotenv()

# Initialize Solana client
solana_client = AsyncClient(os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com'))

# Store wallet data
WALLETS_FILE = 'wallets.json'
TRACKED_TOKENS_FILE = 'tracked_tokens.json'
TRANSACTIONS_FILE = 'transactions.json'

# Known DEX program IDs
JUPITER_PROGRAM_ID = "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB"
RAYDIUM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

# Rate limiting settings
RATE_LIMIT_DELAY = 0.2  # 200ms between requests
MAX_RETRIES = 3
RETRY_DELAY = 1  # 1 second between retries

# Last request timestamp
last_request_time = 0

# Initialize Flask app
app = Flask(__name__)

# Helius webhook secret (you'll need to set this in your environment)
HELIUS_WEBHOOK_SECRET = os.getenv('HELIUS_WEBHOOK_SECRET')

# API settings
API_URL = os.getenv('API_URL', 'https://api.example.com')  # Replace with your API URL
API_KEY = os.getenv('API_KEY')  # Your API key
MORALIS_API_KEY = os.getenv('MORALIS_API_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6IjcyMGU0ZmI0LTk3Y2QtNGU4ZS04NGUwLTQyZTVmZmY2Y2JiNCIsIm9yZ0lkIjoiNDM4Njc4IiwidXNlcklkIjoiNDUxMzA5IiwidHlwZUlkIjoiYjhlNGZlMDktMzUzNi00YTZkLTkwNjktY2YyYzQxYTQ0MmJhIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NDMyNTQ4MzUsImV4cCI6NDg5OTAxNDgzNX0.2zIfKFA3TsR-ufg5FrLjpVpQIijEKyqbfiYfgDbbJZI')
MORALIS_API_URL = "https://solana-gateway.moralis.io/account/mainnet"

@app.route('/')
def health_check():
    return "Bot is running!"

class Transaction:
    def __init__(self, signature: str, timestamp: int, token_address: str, amount: float, price: float, is_buy: bool, description: str = ''):
        self.signature = signature
        self.timestamp = timestamp
        self.token_address = token_address
        self.amount = amount
        self.price = price
        self.is_buy = is_buy
        self.description = description
        self.total_value = amount * price

    def to_dict(self):
        return {
            'signature': self.signature,
            'timestamp': self.timestamp,
            'token_address': self.token_address,
            'amount': self.amount,
            'price': self.price,
            'is_buy': self.is_buy,
            'description': self.description,
            'total_value': self.total_value
        }

class WalletTracker:
    def __init__(self):
        self.wallets = self.load_wallets()
        self.tracked_tokens = self.load_tracked_tokens()
        self.transactions = self.load_transactions()
        self.alerts_enabled = True
        self.multi_buy_threshold = 6  # hours
        self.min_buys_for_alert = 3   # minimum number of wallets that need to buy
        self.min_sells_for_alert = 3  # minimum number of wallets that need to sell

    def load_wallets(self):
        try:
            if os.path.exists(WALLETS_FILE):
                with open(WALLETS_FILE, 'r') as f:
                    return json.load(f)
            return {}
        except json.JSONDecodeError:
            print(f"Warning: {WALLETS_FILE} contains invalid JSON. Creating new file.")
            with open(WALLETS_FILE, 'w') as f:
                json.dump({}, f)
            return {}

    def load_tracked_tokens(self):
        try:
            if os.path.exists(TRACKED_TOKENS_FILE):
                with open(TRACKED_TOKENS_FILE, 'r') as f:
                    return json.load(f)
            return {}
        except json.JSONDecodeError:
            print(f"Warning: {TRACKED_TOKENS_FILE} contains invalid JSON. Creating new file.")
            with open(TRACKED_TOKENS_FILE, 'w') as f:
                json.dump({}, f)
            return {}

    def load_transactions(self):
        try:
            if os.path.exists(TRANSACTIONS_FILE):
                with open(TRANSACTIONS_FILE, 'r') as f:
                    return json.load(f)
            return {}
        except json.JSONDecodeError:
            print(f"Warning: {TRANSACTIONS_FILE} contains invalid JSON. Creating new file.")
            with open(TRANSACTIONS_FILE, 'w') as f:
                json.dump({}, f)
            return {}

    def save_wallets(self):
        with open(WALLETS_FILE, 'w') as f:
            json.dump(self.wallets, f)

    def save_tracked_tokens(self):
        with open(TRACKED_TOKENS_FILE, 'w') as f:
            json.dump(self.tracked_tokens, f)

    def save_transactions(self):
        with open(TRANSACTIONS_FILE, 'w') as f:
            json.dump(self.transactions, f)

    def add_wallet(self, address, name):
        self.wallets[address] = {
            'name': name,
            'added_at': datetime.now().isoformat()
        }
        self.save_wallets()

    def remove_wallet(self, address):
        if address in self.wallets:
            del self.wallets[address]
            self.save_wallets()
            return True
        return False

    def get_wallet_name(self, address):
        return self.wallets.get(address, {}).get('name', address)

    def add_tracked_token(self, token_address, wallets):
        self.tracked_tokens[token_address] = {
            'wallets': wallets,
            'added_at': datetime.now().isoformat(),
            'multi_buy_detected': False
        }
        self.save_tracked_tokens()

    def remove_tracked_token(self, token_address):
        if token_address in self.tracked_tokens:
            del self.tracked_tokens[token_address]
            self.save_tracked_tokens()
            return True
        return False

    def add_transaction(self, wallet_address: str, transaction: Transaction):
        if wallet_address not in self.transactions:
            self.transactions[wallet_address] = []
        # Convert Transaction object to dictionary before storing
        self.transactions[wallet_address].append(transaction.to_dict())
        self.save_transactions()

    def get_recent_transactions(self, wallet_address: str, hours: int = 6) -> List[Transaction]:
        if wallet_address not in self.transactions:
            return []
        
        cutoff_time = int((datetime.now() - timedelta(hours=hours)).timestamp())
        return [
            Transaction(**tx) for tx in self.transactions[wallet_address]
            if tx['timestamp'] >= cutoff_time
        ]

    def detect_multi_buys(self, transactions: List[Dict]) -> Optional[Dict]:
        """Detect multi-buys from a list of transactions"""
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
                # Check if this multi-buy was already alerted
                if not self.is_multi_buy_already_alerted(token_address, data['transactions']):
                    return {
                        'token_address': token_address,
                        'token_symbol': data['token_symbol'],
                        'wallet_count': len(data['wallets']),
                        'total_amount': data['total_amount'],
                        'transactions': data['transactions']
                    }
        return None

    def is_multi_buy_already_alerted(self, token_address: str, transactions: List[Dict]) -> bool:
        """Check if this multi-buy was already alerted"""
        if token_address not in self.transactions:
            return False
            
        # Get the signatures of the current transactions
        current_signatures = {tx.get('signature') for tx in transactions}
        
        # Check if any of these transactions were already stored
        for stored_tx in self.transactions[token_address]:
            if stored_tx.get('signature') in current_signatures:
                return True
                
        return False

    def store_multi_buy(self, token_address: str, transactions: List[Dict]):
        """Store multi-buy transactions"""
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_transactions()

    def detect_multi_sells(self, transactions: List[Dict]) -> Optional[Dict]:
        """Detect multi-sells from a list of transactions"""
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
                # Check if this multi-sell was already alerted
                if not self.is_multi_sell_already_alerted(token_address, data['transactions']):
                    return {
                        'token_address': token_address,
                        'token_symbol': data['token_symbol'],
                        'wallet_count': len(data['wallets']),
                        'total_amount': data['total_amount'],
                        'transactions': data['transactions']
                    }
        return None

    def is_multi_sell_already_alerted(self, token_address: str, transactions: List[Dict]) -> bool:
        """Check if this multi-sell was already alerted"""
        if token_address not in self.transactions:
            return False
            
        # Get the signatures of the current transactions
        current_signatures = {tx.get('signature') for tx in transactions}
        
        # Check if any of these transactions were already stored
        for stored_tx in self.transactions[token_address]:
            if stored_tx.get('signature') in current_signatures:
                return True
                
        return False

    def store_multi_sell(self, token_address: str, transactions: List[Dict]):
        """Store multi-sell transactions"""
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_transactions()

    def get_activity_summary(self, wallet_address):
        try:
            # Get transactions for the wallet
            transactions = self.transactions.get(wallet_address, [])
            if not transactions:
                return "No transactions found for this wallet."

            # Group transactions by token
            token_activity = {}
            for tx in transactions:
                token_account = tx.get('token_account')
                if not token_account:
                    continue

                if token_account not in token_activity:
                    token_activity[token_account] = {
                        'buys': 0,
                        'sells': 0,
                        'total_bought': 0,
                        'total_sold': 0,
                        'last_activity': 0
                    }

                activity = token_activity[token_account]
                amount = tx.get('amount', 0)
                timestamp = tx.get('timestamp', 0)

                if tx.get('type') == 'buy':
                    activity['buys'] += 1
                    activity['total_bought'] += amount
                else:
                    activity['sells'] += 1
                    activity['total_sold'] += amount

                activity['last_activity'] = max(activity['last_activity'], timestamp)

            # Format the summary
            summary = f"📊 *Activity Summary for {wallet_address[:8]}...{wallet_address[-8:]}*\n\n"
            
            for token_account, activity in token_activity.items():
                # Get token name from tracked tokens if available
                token_name = self.tracked_tokens.get(token_account, {}).get('name', 'Unknown Token')
                short_token = f"{token_account[:8]}...{token_account[-8:]}"
                
                summary += f"*{token_name}* (`{short_token}`)\n"
                summary += f"• Buys: {activity['buys']}\n"
                summary += f"• Sells: {activity['sells']}\n"
                summary += f"• Total Bought: {activity['total_bought'] / 1e9:.2f}\n"
                summary += f"• Total Sold: {activity['total_sold'] / 1e9:.2f}\n"
                summary += f"• Last Activity: {datetime.fromtimestamp(activity['last_activity']).strftime('%Y-%m-%d %H:%M:%S')}\n\n"

            return summary

        except Exception as e:
            print(f"Error generating summary: {e}")
            return "Error generating summary. Please try again."

# Initialize wallet tracker
wallet_tracker = WalletTracker()

def start(update, context: CallbackContext):
    # Create inline keyboard
    keyboard = [
        [InlineKeyboardButton("📊 Summary", callback_data='show_summary')],
        [
            InlineKeyboardButton("➕ Add Wallet", callback_data='add_wallet'),
            InlineKeyboardButton("➖ Remove Wallet", callback_data='remove_wallet')
        ],
        [
            InlineKeyboardButton("📝 List Wallets", callback_data='list_wallets'),
            InlineKeyboardButton("🔍 Track Token", callback_data='track_token')
        ],
        [InlineKeyboardButton("🔔 Toggle Alerts", callback_data='toggle_alerts')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        'Welcome to Solana Wallet Tracker! Choose an option:',
        reply_markup=reply_markup
    )

def show_menu(update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("📊 Summary", callback_data='show_summary')],
        [
            InlineKeyboardButton("➕ Add Wallet", callback_data='add_wallet'),
            InlineKeyboardButton("➖ Remove Wallet", callback_data='remove_wallet')
        ],
        [
            InlineKeyboardButton("📝 List Wallets", callback_data='list_wallets'),
            InlineKeyboardButton("🔍 Track Token", callback_data='track_token')
        ],
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

    if query.data == 'show_summary':
        # Get the first wallet address for summary
        if wallet_tracker.wallets:
            first_wallet = list(wallet_tracker.wallets.keys())[0]
            summary_text = wallet_tracker.get_activity_summary(first_wallet)
        else:
            summary_text = "No wallets are being tracked. Add a wallet first!"
        
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(summary_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    elif query.data == 'show_menu':
        keyboard = [
            [InlineKeyboardButton("📊 Summary", callback_data='show_summary')],
            [
                InlineKeyboardButton("➕ Add Wallet", callback_data='add_wallet'),
                InlineKeyboardButton("➖ Remove Wallet", callback_data='remove_wallet')
            ],
            [
                InlineKeyboardButton("📝 List Wallets", callback_data='list_wallets'),
                InlineKeyboardButton("🔍 Track Token", callback_data='track_token')
            ],
            [InlineKeyboardButton("🔔 Toggle Alerts", callback_data='toggle_alerts')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text("Choose an option:", reply_markup=reply_markup)
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
        
        # Create a keyboard with wallet options
        keyboard = []
        for addr, data in wallet_tracker.wallets.items():
            keyboard.append([InlineKeyboardButton(data['name'], callback_data=f'remove_{addr}')])
        keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text('Select a wallet to remove:', reply_markup=reply_markup)
    elif query.data == 'list_wallets':
        if not wallet_tracker.wallets:
            text = 'No wallets are being tracked.'
        else:
            text = 'Tracked Wallets:\n' + '\n'.join([f"{data['name']} ({addr})" for addr, data in wallet_tracker.wallets.items()])
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(text, reply_markup=reply_markup)
    elif query.data == 'toggle_alerts':
        wallet_tracker.alerts_enabled = not wallet_tracker.alerts_enabled
        status = 'enabled' if wallet_tracker.alerts_enabled else 'disabled'
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.edit_text(f'Alerts have been {status}', reply_markup=reply_markup)
    elif query.data.startswith('track_sells_'):
        token_address = query.data.replace('track_sells_', '')
        handle_track_sells(update, context, token_address)
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
    text = update.message.text
    
    # Handle message flows
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

def handle_track_sells(update, context: CallbackContext, token_address: str):
    keyboard = [
        [InlineKeyboardButton("Track Multi-Sells Only", callback_data=f'multi_sells_{token_address}')],
        [InlineKeyboardButton("Track All Sells", callback_data=f'all_sells_{token_address}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.callback_query.message.reply_text(
        'Choose how to track sells:',
        reply_markup=reply_markup
    )

async def rate_limited_request(func, *args, **kwargs):
    """Execute a rate-limited RPC request with retries"""
    global last_request_time
    
    for attempt in range(MAX_RETRIES):
        try:
            # Ensure minimum delay between requests
            current_time = time.time()
            time_since_last = current_time - last_request_time
            if time_since_last < RATE_LIMIT_DELAY:
                await asyncio.sleep(RATE_LIMIT_DELAY - time_since_last)
            
            # Make the request
            last_request_time = time.time()
            return await func(*args, **kwargs)
            
        except Exception as e:
            if isinstance(e, HTTPStatusError) and e.response.status_code == 429:
                if attempt < MAX_RETRIES - 1:  # Don't sleep on the last attempt
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
                    continue
            raise e
    
    return None

async def parse_transaction(signature: str, wallet_address: str) -> Optional[Transaction]:
    try:
        # Convert string signature to Signature object
        sig = Signature.from_string(signature)
        
        # Get transaction details with rate limiting
        tx_response = await rate_limited_request(
            solana_client.get_transaction,
            sig,
            max_supported_transaction_version=0
        )
        if not tx_response or not tx_response.value:
            return None

        tx = tx_response.value
        timestamp = tx.block_time or int(datetime.now().timestamp())

        # Get the transaction message from the correct structure
        if hasattr(tx.transaction, 'transaction'):
            # Handle versioned transaction
            message = tx.transaction.transaction.message
        elif hasattr(tx.transaction, 'message'):
            # Handle legacy transaction
            message = tx.transaction.message
        else:
            print(f"Unexpected transaction structure for {signature}")
            return None

        # Get all account keys as strings
        all_accounts = [str(key) for key in message.account_keys]
        account_keys_count = len(all_accounts)

        # Parse transaction instructions
        for ix in message.instructions:
            try:
                # Validate program ID index
                if not hasattr(ix, 'program_id_index') or ix.program_id_index >= account_keys_count:
                    continue

                # Get program ID from account keys
                program_id = all_accounts[ix.program_id_index]
                
                # Check if it's a Jupiter or Raydium swap
                if program_id in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID]:
                    # Validate and filter account indices
                    valid_accounts = [
                        all_accounts[idx] 
                        for idx in (ix.accounts or []) 
                        if 0 <= idx < account_keys_count
                    ]

                    # Look for wallet and token accounts
                    wallet_found = False
                    token_account = None
                    wallet_pubkey = str(Pubkey.from_string(wallet_address))
                    
                    for account in valid_accounts:
                        if account == wallet_pubkey:
                            wallet_found = True
                        elif account != program_id:  # Potential token account
                            token_account = account

                    if not wallet_found or not token_account:
                        continue

                    # Safely parse data
                    try:
                        data_bytes = base58.b58decode(ix.data) if hasattr(ix, 'data') and ix.data else None
                        amount = float(int.from_bytes(data_bytes[1:9], 'little')) / 1e9 if data_bytes and len(data_bytes) >= 9 else 0
                    except (ValueError, IndexError) as e:
                        print(f"Error parsing data in transaction {signature}: {e}")
                        amount = 0
                        
                    price = 1.0  # You'll need to implement price fetching
                    
                    return Transaction(
                        signature=str(signature),
                        timestamp=timestamp,
                        token_address=token_account,
                        amount=amount,
                        price=price,
                        is_buy=wallet_found,
                        description=message.get_instruction_data(ix)
                    )
            except Exception as e:
                print(f"Error processing instruction in transaction {signature}: {e}")
                continue

        return None

    except Exception as e:
        print(f"Comprehensive error parsing transaction {signature}: {e}")
        import traceback
        traceback.print_exc()
    return None

async def get_recent_transactions(wallet_address: str) -> List[Dict]:
    """Get recent transactions for a wallet using the Moralis API"""
    try:
        headers = {
            "Accept": "application/json",
            "X-API-Key": MORALIS_API_KEY
        }
        
        url = f"{MORALIS_API_URL}/{wallet_address}/swaps?order=DESC"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # Transform Moralis data to our format
                    transactions = []
                    for tx in data:
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
                            
                            # Get timestamp in seconds (Moralis returns milliseconds)
                            timestamp = int(tx.get('blockTimestamp', 0)) // 1000
                            
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
                    return transactions
                else:
                    print(f"Error fetching transactions: {response.status}")
                    return []
    except Exception as e:
        print(f"Error in get_recent_transactions: {e}")
        return []

async def check_transactions():
    """Check recent transactions for all tracked wallets"""
    while True:
        if not wallet_tracker.alerts_enabled:
            await asyncio.sleep(60)
            continue

        try:
            # Get transactions for all wallets
            all_transactions = []
            for address in wallet_tracker.wallets:
                transactions = await get_recent_transactions(address)
                all_transactions.extend(transactions)
            
            # Filter transactions from the last 6 hours
            cutoff_time = int((datetime.now() - timedelta(hours=6)).timestamp())
            recent_transactions = [
                tx for tx in all_transactions 
                if tx.get('timestamp', 0) >= cutoff_time
            ]
            
            # Detect multi-buys
            multi_buy = wallet_tracker.detect_multi_buys(recent_transactions)
            if multi_buy:
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
                    except Exception as e:
                        print(f"Error sending notification to {wallet}: {e}")

            # Detect multi-sells
            multi_sell = wallet_tracker.detect_multi_sells(recent_transactions)
            if multi_sell:
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
                    except Exception as e:
                        print(f"Error sending notification to {wallet}: {e}")
                        
        except Exception as e:
            print(f"Error checking transactions: {e}")

        await asyncio.sleep(60)  # Check every minute

def run_async_tasks():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_transactions())
    loop.run_forever()

def summary(update, context: CallbackContext):
    # Get the first wallet address for summary
    if wallet_tracker.wallets:
        first_wallet = list(wallet_tracker.wallets.keys())[0]
        summary_text = wallet_tracker.get_activity_summary(first_wallet)
    else:
        summary_text = "No wallets are being tracked. Add a wallet first!"
    
    keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(summary_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

def verify_webhook_signature(request_body, signature):
    """Verify the webhook signature from Helius"""
    if not HELIUS_WEBHOOK_SECRET:
        return False
    
    expected_signature = hmac.new(
        HELIUS_WEBHOOK_SECRET.encode(),
        request_body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    """Handle incoming webhooks from Helius"""
    try:
        # Get the signature from headers
        signature = request.headers.get('X-Helius-Signature')
        if not signature:
            return jsonify({'error': 'No signature provided'}), 401

        # Verify the signature
        if not verify_webhook_signature(request.get_data(), signature):
            return jsonify({'error': 'Invalid signature'}), 401

        # Parse the webhook data
        data = request.get_json()
        
        # Process the transaction
        if data.get('type') == 'TRANSACTION':
            transaction = data.get('transaction', {})
            signature = transaction.get('signature')
            
            # Get transaction description
            description = transaction.get('description', '')
            
            # Get the accounts involved
            accounts = transaction.get('accounts', [])
            
            # Check if any of our tracked wallets are involved
            involved_wallets = [acc for acc in accounts if acc in wallet_tracker.wallets]
            
            if involved_wallets:
                # Create an event loop for async operations
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Parse and store the transaction
                    tx = loop.run_until_complete(parse_transaction(signature, involved_wallets[0]))
                    if tx:
                        # Store transaction for each involved wallet
                        for wallet in involved_wallets:
                            wallet_tracker.add_transaction(wallet, tx)
                        
                        # Check for multi-buy pattern
                        if len(involved_wallets) >= 3:  # If 3 or more tracked wallets are involved
                            # Get all recent transactions with the same description
                            recent_txs = []
                            for wallet in wallet_tracker.wallets:
                                wallet_txs = wallet_tracker.transactions.get(wallet, [])
                                for t in wallet_txs:
                                    if (t.get('description') == description and 
                                        t.get('timestamp') > int(datetime.now().timestamp()) - 3600):  # Last hour
                                        recent_txs.append(t)
                            
                            # If we have 3 or more recent transactions with the same description
                            if len(recent_txs) >= 3:
                                # Send multi-buy notification
                                message = f"🚨 Multi-Buy Alert!\n\n"
                                message += f"Description: {description}\n"
                                message += f"Total Value: {sum(tx.get('amount', 0) for tx in recent_txs):.2f} SOL\n\n"
                                message += "Wallets that participated:\n"
                                
                                # Group transactions by wallet
                                wallet_txs = {}
                                for tx in recent_txs:
                                    wallet = tx.get('wallet_address')
                                    if wallet not in wallet_txs:
                                        wallet_txs[wallet] = []
                                    wallet_txs[wallet].append(tx)
                                
                                # Add wallet details to message
                                for wallet, transactions in wallet_txs.items():
                                    wallet_name = wallet_tracker.get_wallet_name(wallet)
                                    total = sum(tx.get('amount', 0) for tx in transactions)
                                    message += f"- {wallet_name}: {total:.2f} SOL\n"
                                
                                # Add tracking options
                                keyboard = [[
                                    InlineKeyboardButton(
                                        "Track Sells",
                                        callback_data=f'track_sells_{tx.token_address}'
                                    )
                                ]]
                                reply_markup = InlineKeyboardMarkup(keyboard)
                                
                                # Send notification to all tracked wallets
                                for wallet in wallet_tracker.wallets:
                                    try:
                                        loop.run_until_complete(
                                            context.bot.send_message(
                                                chat_id=wallet,
                                                text=message,
                                                reply_markup=reply_markup
                                            )
                                        )
                                    except Exception as e:
                                        print(f"Error sending notification to {wallet}: {e}")
                finally:
                    loop.close()

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        print(f"Error processing webhook: {e}")
        return jsonify({'error': str(e)}), 500

def main():
    # Create the Updater and pass it your bot's token
    updater = Updater(os.getenv('TELEGRAM_BOT_TOKEN'), use_context=True)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("menu", show_menu))
    dispatcher.add_handler(CommandHandler("summary", summary))
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

if __name__ == '__main__':
    main() 