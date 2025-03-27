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
from aiohttp import web
import threading
import time
from httpx import HTTPStatusError
from solders.signature import Signature

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

# Web server setup
app = web.Application()
routes = web.RouteTableDef()

# Rate limiting settings
RATE_LIMIT_DELAY = 0.2  # 200ms between requests
MAX_RETRIES = 3
RETRY_DELAY = 1  # 1 second between retries

# Last request timestamp
last_request_time = 0

@routes.get('/')
async def health_check(request):
    return web.Response(text="Bot is running!")

class Transaction:
    def __init__(self, signature: str, timestamp: int, token_address: str, amount: float, price: float, is_buy: bool):
        self.signature = str(signature)  # Ensure signature is a string
        self.timestamp = timestamp
        self.token_address = token_address
        self.amount = amount
        self.price = price
        self.is_buy = is_buy
        self.total_value = amount * price

    def to_dict(self):
        return {
            'signature': self.signature,
            'timestamp': self.timestamp,
            'token_address': self.token_address,
            'amount': self.amount,
            'price': self.price,
            'is_buy': self.is_buy,
            'total_value': self.total_value
        }

class WalletTracker:
    def __init__(self):
        self.wallets = self.load_wallets()
        self.tracked_tokens = self.load_tracked_tokens()
        self.transactions = self.load_transactions()
        self.alerts_enabled = True
        self.multi_buy_threshold = 6  # hours
        self.min_buys_for_alert = 2   # minimum number of wallets that need to buy

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

    def detect_multi_buys(self, token_address: str) -> Optional[Dict]:
        if token_address not in self.tracked_tokens:
            return None

        tracked_wallets = self.tracked_tokens[token_address]['wallets']
        recent_buys = {}

        for wallet in tracked_wallets:
            transactions = self.get_recent_transactions(wallet)
            for tx in transactions:
                if tx.token_address == token_address and tx.is_buy:
                    if wallet not in recent_buys:
                        recent_buys[wallet] = []
                    recent_buys[wallet].append(tx)

        if len(recent_buys) >= self.min_buys_for_alert:
            total_value = sum(
                sum(tx.total_value for tx in wallet_txs)
                for wallet_txs in recent_buys.values()
            )
            return {
                'token_address': token_address,
                'wallets': recent_buys,
                'total_value': total_value
            }
        return None

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

        # Parse transaction instructions
        for ix in message.instructions:
            try:
                # Safely get program ID index and validate it
                if not hasattr(ix, 'program_id_index') or ix.program_id_index >= len(message.account_keys):
                    continue

                # Get program ID from account keys
                program_id = str(message.account_keys[ix.program_id_index])
                
                # Check if it's a Jupiter or Raydium swap
                if program_id in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID]:
                    # Get all account keys for reference
                    all_accounts = [str(key) for key in message.account_keys]
                    
                    # Safely get account indices and validate them
                    if not hasattr(ix, 'accounts') or not ix.accounts:
                        continue

                    # Find the token account (usually the second account, but could be in other positions)
                    token_account = None
                    wallet_found = False
                    wallet_pubkey = str(Pubkey.from_string(wallet_address))
                    
                    # Look through all accounts to find the wallet and token
                    for idx in ix.accounts:
                        if idx >= len(all_accounts):
                            print(f"Skipping invalid account index {idx} in transaction {signature}")
                            continue
                            
                        account = all_accounts[idx]
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
                        signature=str(signature),  # Ensure signature is a string
                        timestamp=timestamp,
                        token_address=token_account,
                        amount=amount,
                        price=price,
                        is_buy=wallet_found  # If wallet is found in accounts, it's likely a buy
                    )
            except (IndexError, ValueError) as e:
                print(f"Error parsing instruction in transaction {signature}: {e}")
                continue

        return None

    except ValueError as e:
        print(f"Error with address format in transaction {signature}: {e}")
    except AttributeError as e:
        print(f"Error accessing transaction attributes for {signature}: {e}")
    except Exception as e:
        print(f"Error parsing transaction {signature}: {e}")
        import traceback
        traceback.print_exc()
    return None

async def check_transactions():
    while True:
        if not wallet_tracker.alerts_enabled:
            await asyncio.sleep(60)
            continue

        for address in wallet_tracker.wallets:
            try:
                # Convert string address to Pubkey
                pubkey = Pubkey.from_string(address)
                
                # Get recent transactions with rate limiting
                response = await rate_limited_request(
                    solana_client.get_signatures_for_address,
                    pubkey
                )
                
                if response and response.value:
                    for sig in response.value:
                        # Parse and store transaction
                        tx = await parse_transaction(str(sig.signature), address)
                        if tx:
                            wallet_tracker.add_transaction(address, tx)
                            
                            # Check for multi-buys
                            multi_buy = wallet_tracker.detect_multi_buys(tx.token_address)
                            if multi_buy and not wallet_tracker.tracked_tokens[tx.token_address].get('multi_buy_detected'):
                                # Send multi-buy notification
                                message = f"🚨 Multi-Buy Alert!\n\n"
                                message += f"Token: {tx.token_address}\n"
                                message += f"Total Value: {multi_buy['total_value']:.2f} SOL\n\n"
                                message += "Wallets that bought:\n"
                                
                                for wallet, transactions in multi_buy['wallets'].items():
                                    wallet_name = wallet_tracker.get_wallet_name(wallet)
                                    total = sum(tx.total_value for tx in transactions)
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
                                        await context.bot.send_message(
                                            chat_id=wallet,
                                            text=message,
                                            reply_markup=reply_markup
                                        )
                                    except Exception as e:
                                        print(f"Error sending notification to {wallet}: {e}")
                                
                                # Mark multi-buy as detected
                                wallet_tracker.tracked_tokens[tx.token_address]['multi_buy_detected'] = True
                                wallet_tracker.save_tracked_tokens()
                                
            except ValueError as e:
                print(f"Error with wallet address format {address}: {e}")
            except Exception as e:
                print(f"Error checking transactions for {address}: {e}")

            # Add a small delay between checking different wallets
            await asyncio.sleep(RATE_LIMIT_DELAY)

        await asyncio.sleep(60)  # Check every minute

async def start_web_server():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', '8080')))
    await site.start()
    print(f"Web server started on port {os.getenv('PORT', '8080')}")

def run_async_tasks():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_web_server())
    loop.run_until_complete(check_transactions())
    loop.run_forever()

def summary(update, context: CallbackContext):
    summary_text = get_activity_summary()
    keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data='show_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(summary_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

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

    # Add web routes
    app.add_routes(routes)

    # Start async tasks in a separate thread
    async_thread = threading.Thread(target=run_async_tasks, daemon=True)
    async_thread.start()

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main() 