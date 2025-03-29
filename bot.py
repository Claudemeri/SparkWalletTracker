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

# Load environment variables
load_dotenv()

# Store wallet data
WALLETS_FILE = 'wallets.json'
TRACKED_TOKENS_FILE = 'tracked_tokens.json'
TRANSACTIONS_FILE = 'transactions.json'

# API settings
MORALIS_API_KEY = os.getenv('MORALIS_API_KEY')
MORALIS_API_URL = "https://solana-gateway.moralis.io/account/mainnet"

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
            'added_at': datetime.now().isoformat()
        }
        self.save_tracked_tokens()

    def remove_tracked_token(self, token_address):
        if token_address in self.tracked_tokens:
            del self.tracked_tokens[token_address]
            self.save_tracked_tokens()
            return True
        return False

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

    def store_multi_buy(self, token_address: str, transactions: List[Dict]):
        """Store multi-buy transactions"""
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_transactions()

    def store_multi_sell(self, token_address: str, transactions: List[Dict]):
        """Store multi-sell transactions"""
        if token_address not in self.transactions:
            self.transactions[token_address] = []
            
        # Add new transactions
        self.transactions[token_address].extend(transactions)
        self.save_transactions()

# Initialize wallet tracker
wallet_tracker = WalletTracker()

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
                    if not isinstance(data, dict):
                        print(f"Unexpected response format: {data}")
                        return []
                        
                    # Get the result array from the response
                    transactions_data = data.get('result', [])
                    if not isinstance(transactions_data, list):
                        print(f"Unexpected result format: {transactions_data}")
                        return []
                        
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
                        except (ValueError, TypeError) as e:
                            print(f"Error processing transaction: {e}")
                            continue
                            
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