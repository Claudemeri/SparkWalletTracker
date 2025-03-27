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

@routes.get('/')
async def health_check(request):
    return web.Response(text="Bot is running!")

class Transaction:
    def __init__(self, signature: str, timestamp: int, token_address: str, amount: float, price: float, is_buy: bool):
        self.signature = signature
        self.timestamp = timestamp
        self.token_address = token_address
        self.amount = amount
        self.price = price
        self.is_buy = is_buy
        self.total_value = amount * price

class WalletTracker:
    def __init__(self):
        self.wallets = self.load_wallets()
        self.tracked_tokens = self.load_tracked_tokens()
        self.transactions = self.load_transactions()
        self.alerts_enabled = True
        self.multi_buy_threshold = 6  # hours
        self.min_buys_for_alert = 2   # minimum number of wallets that need to buy

    def load_wallets(self):
        if os.path.exists(WALLETS_FILE):
            with open(WALLETS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def load_tracked_tokens(self):
        if os.path.exists(TRACKED_TOKENS_FILE):
            with open(TRACKED_TOKENS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def load_transactions(self):
        if os.path.exists(TRANSACTIONS_FILE):
            with open(TRANSACTIONS_FILE, 'r') as f:
                return json.load(f)
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
        self.transactions[wallet_address].append({
            'signature': transaction.signature,
            'timestamp': transaction.timestamp,
            'token_address': transaction.token_address,
            'amount': transaction.amount,
            'price': transaction.price,
            'is_buy': transaction.is_buy,
            'total_value': transaction.total_value
        })
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

# Initialize wallet tracker
wallet_tracker = WalletTracker()

def start(update, context: CallbackContext):
    # Create menu keyboard
    keyboard = [
        [KeyboardButton("📊 Summary")],
        [KeyboardButton("➕ Add Wallet"), KeyboardButton("➖ Remove Wallet")],
        [KeyboardButton("📝 List Wallets"), KeyboardButton("🔍 Track Token")],
        [KeyboardButton("🔔 Toggle Alerts")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        'Welcome to Solana Wallet Tracker! Choose an option from the menu below:',
        reply_markup=reply_markup
    )

def button_handler(update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == 'add_wallet':
        context.user_data['state'] = 'waiting_for_wallet_address'
        query.message.reply_text(
            'Please send me the wallet address you want to track.'
        )
    elif query.data == 'remove_wallet':
        context.user_data['state'] = 'waiting_for_wallet_to_remove'
        if not wallet_tracker.wallets:
            query.message.reply_text('No wallets are being tracked.')
            context.user_data.clear()
            return
        
        # Create a keyboard with wallet options
        keyboard = []
        for addr, data in wallet_tracker.wallets.items():
            keyboard.append([InlineKeyboardButton(data['name'], callback_data=f'remove_{addr}')])
        keyboard.append([InlineKeyboardButton("Cancel", callback_data='cancel')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.reply_text('Select a wallet to remove:', reply_markup=reply_markup)
    elif query.data == 'list_wallets':
        if not wallet_tracker.wallets:
            query.message.reply_text('No wallets are being tracked.')
        else:
            wallet_list = '\n'.join([f"{data['name']} ({addr})" for addr, data in wallet_tracker.wallets.items()])
            query.message.reply_text(f'Tracked Wallets:\n{wallet_list}')
    elif query.data == 'toggle_alerts':
        wallet_tracker.alerts_enabled = not wallet_tracker.alerts_enabled
        status = 'enabled' if wallet_tracker.alerts_enabled else 'disabled'
        query.message.reply_text(f'Alerts have been {status}')
    elif query.data.startswith('track_sells_'):
        token_address = query.data.replace('track_sells_', '')
        handle_track_sells(update, context, token_address)
    elif query.data.startswith('remove_'):
        address = query.data.replace('remove_', '')
        if wallet_tracker.remove_wallet(address):
            query.message.reply_text(f'Removed wallet {wallet_tracker.get_wallet_name(address)} ({address})')
        else:
            query.message.reply_text('Failed to remove wallet')
        context.user_data.clear()
    elif query.data == 'cancel':
        query.message.reply_text('Operation cancelled.')
        context.user_data.clear()

def handle_message(update, context: CallbackContext):
    text = update.message.text
    
    # Handle menu button clicks
    if text == "📊 Summary":
        summary = get_activity_summary()
        update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)
        return
    elif text == "➕ Add Wallet":
        context.user_data['state'] = 'waiting_for_wallet_address'
        update.message.reply_text('Please send me the wallet address you want to track.')
        return
    elif text == "➖ Remove Wallet":
        if not wallet_tracker.wallets:
            update.message.reply_text('No wallets are being tracked.')
            return
        keyboard = []
        for addr, data in wallet_tracker.wallets.items():
            keyboard.append([InlineKeyboardButton(data['name'], callback_data=f'remove_{addr}')])
        keyboard.append([InlineKeyboardButton("Cancel", callback_data='cancel')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text('Select a wallet to remove:', reply_markup=reply_markup)
        return
    elif text == "📝 List Wallets":
        if not wallet_tracker.wallets:
            update.message.reply_text('No wallets are being tracked.')
        else:
            wallet_list = '\n'.join([f"{data['name']} ({addr})" for addr, data in wallet_tracker.wallets.items()])
            update.message.reply_text(f'Tracked Wallets:\n{wallet_list}')
        return
    elif text == "🔍 Track Token":
        context.user_data['state'] = 'waiting_for_token_address'
        update.message.reply_text('Please send me the token address you want to track.')
        return
    elif text == "🔔 Toggle Alerts":
        wallet_tracker.alerts_enabled = not wallet_tracker.alerts_enabled
        status = 'enabled' if wallet_tracker.alerts_enabled else 'disabled'
        update.message.reply_text(f'Alerts have been {status}')
        return

    # Handle existing message flows
    if context.user_data.get('state') == 'waiting_for_wallet_address':
        context.user_data['wallet_address'] = update.message.text
        context.user_data['state'] = 'waiting_for_wallet_name'
        update.message.reply_text('Please send me a name for this wallet.')
    elif context.user_data.get('state') == 'waiting_for_wallet_name':
        wallet_address = context.user_data['wallet_address']
        wallet_name = update.message.text
        wallet_tracker.add_wallet(wallet_address, wallet_name)
        update.message.reply_text(f'Added wallet {wallet_name} ({wallet_address})')
        context.user_data.clear()
    elif context.user_data.get('state') == 'waiting_for_token_address':
        token_address = update.message.text
        wallet_tracker.add_tracked_token(token_address, list(wallet_tracker.wallets.keys()))
        update.message.reply_text(f'Now tracking token {token_address} for all wallets')
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

async def parse_transaction(signature: str, wallet_address: str) -> Optional[Transaction]:
    try:
        # Get transaction details with max supported version
        tx_response = await solana_client.get_transaction(
            signature,
            max_supported_transaction_version=0  # Support legacy and versioned transactions
        )
        if not tx_response.value:
            return None

        tx = tx_response.value
        timestamp = tx.block_time or int(datetime.now().timestamp())

        # Parse transaction instructions
        for ix in tx.transaction.message.instructions:
            program_id = str(ix.program_id)
            
            # Check if it's a Jupiter or Raydium swap
            if program_id in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID]:
                # Extract token addresses and amounts
                # This is a simplified version - you'll need to implement the actual parsing
                # based on the specific DEX program's instruction format
                token_address = str(ix.accounts[1])  # Example: token account
                amount = float(ix.data[1:9]) / 1e9  # Example: amount in lamports
                price = 1.0  # You'll need to implement price fetching
                
                # Convert wallet address to Pubkey for comparison
                wallet_pubkey = Pubkey.from_string(wallet_address)
                # Determine if it's a buy or sell by comparing the first account with wallet
                is_buy = ix.accounts[0] == wallet_pubkey
                
                return Transaction(
                    signature=signature,
                    timestamp=timestamp,
                    token_address=token_address,
                    amount=amount,
                    price=price,
                    is_buy=is_buy
                )
    except ValueError as e:
        print(f"Error with address format in transaction {signature}: {e}")
    except Exception as e:
        print(f"Error parsing transaction {signature}: {e}")
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
                
                # Get recent transactions
                response = await solana_client.get_signatures_for_address(pubkey)
                if response.value:
                    for sig in response.value:
                        # Parse and store transaction
                        tx = await parse_transaction(sig.signature, address)
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

def get_activity_summary(hours: int = 24) -> str:
    """Generate activity summary for the last n hours"""
    now = datetime.now()
    cutoff_time = int((now - timedelta(hours=hours)).timestamp())
    
    # Track token activity
    token_activity = {}
    wallet_activity = {}
    
    # Process all transactions
    for wallet_addr, transactions in wallet_tracker.transactions.items():
        wallet_name = wallet_tracker.get_wallet_name(wallet_addr)
        wallet_profit = 0
        wallet_tx_count = 0
        
        for tx in transactions:
            if tx['timestamp'] >= cutoff_time:
                token_addr = tx['token_address']
                if token_addr not in token_activity:
                    token_activity[token_addr] = {
                        'volume': 0,
                        'wallets': set(),
                        'tx_count': 0
                    }
                
                # Update token activity
                token_activity[token_addr]['volume'] += tx['total_value']
                token_activity[token_addr]['wallets'].add(wallet_addr)
                token_activity[token_addr]['tx_count'] += 1
                
                # Update wallet activity
                wallet_profit += tx['total_value'] if not tx['is_buy'] else -tx['total_value']
                wallet_tx_count += 1
        
        if wallet_tx_count > 0:
            wallet_activity[wallet_addr] = {
                'name': wallet_name,
                'profit': wallet_profit,
                'tx_count': wallet_tx_count
            }
    
    # Sort tokens by volume
    sorted_tokens = sorted(
        [(addr, data) for addr, data in token_activity.items()],
        key=lambda x: x[1]['volume'],
        reverse=True
    )[:10]  # Top 10 tokens
    
    # Sort wallets by profit
    sorted_wallets = sorted(
        [(addr, data) for addr, data in wallet_activity.items()],
        key=lambda x: x[1]['profit'],
        reverse=True
    )[:4]  # Top 4 wallets
    
    # Build the summary message
    message = f"📊 Activity Summary (Last {hours} Hours)\n\n"
    
    # Most traded tokens section
    message += "🔥 Most Traded Tokens:\n"
    for token_addr, data in sorted_tokens:
        message += (
            f"{token_addr}: {data['volume']:.2f} SOL | "
            f"{len(data['wallets'])} wallets | {data['tx_count']} txs (more)\n"
        )
    
    message += "\n💰 Top Performing Wallets:\n"
    for wallet_addr, data in sorted_wallets:
        profit_str = f"+{data['profit']:.2f}" if data['profit'] >= 0 else f"{data['profit']:.2f}"
        message += f"{data['name']}: 📈 {profit_str} SOL | {data['tx_count']} txs (more)\n"
    
    return message

def show_menu(update, context: CallbackContext):
    keyboard = [
        [KeyboardButton("📊 Summary")],
        [KeyboardButton("➕ Add Wallet"), KeyboardButton("➖ Remove Wallet")],
        [KeyboardButton("📝 List Wallets"), KeyboardButton("🔍 Track Token")],
        [KeyboardButton("🔔 Toggle Alerts")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("Choose an option:", reply_markup=reply_markup)

def summary(update, context: CallbackContext):
    summary_text = get_activity_summary()
    update.message.reply_text(summary_text, parse_mode=ParseMode.MARKDOWN)

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