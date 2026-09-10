import os
import psycopg2
from psycopg2 import Error
# pyrefly: ignore [missing-import]
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
# pyrefly: ignore [missing-import]
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
# pyrefly: ignore [missing-import]
from telegram import BotCommand
from dotenv import load_dotenv

load_dotenv()

# Retrieve sensitive credentials from environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in the environment or .env file.")

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS'),
    'port': os.getenv('DB_PORT', '5432')
}


def get_db_connection():
    """Helper function to create and return a PostgreSQL database connection."""
    return psycopg2.connect(**DB_CONFIG)


# Reusable keyboard markup layouts
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("1: database_data")],
        [KeyboardButton("2: mail_content")],
        [KeyboardButton("🔙 Exit")]
    ]
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)


def get_db_keyboard():
    db_keyboard = [
        [KeyboardButton("1: Detailed Newspaper Status")],
        [KeyboardButton("2: Total Count of Newspapers")],
        [KeyboardButton("3: Newspaper Regions List")],
        [KeyboardButton("4: Newspaper Regions List (Dup)")],
        [KeyboardButton("5: Queue Totals")],
        [KeyboardButton("6: Today's Article Counts")],
        [KeyboardButton("🔙 Exit")]
    ]
    return ReplyKeyboardMarkup(db_keyboard, one_time_keyboard=True, resize_keyboard=True)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reset state on /start
    context.user_data['waiting_for_db_choice'] = False

    welcome_message = (
        "👋 *Welcome to the Spokesperson Bot!*\n\n"
        "👇 *Please choose an option below to get started:*"
    )

    await update.message.reply_text(
        welcome_message,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()

    # ----------------------------------------------------
    # STEP 2: Handle the database menu choices (1 to 6)
    # ----------------------------------------------------
    if context.user_data.get('waiting_for_db_choice'):
        
        # Handle Exit button — go back to the main menu
        if user_text == "🔙 Exit":
            context.user_data['waiting_for_db_choice'] = False
            await update.message.reply_text(
                "↩️ Returned to main menu. What do you need?", 
                reply_markup=get_main_keyboard()
            )
            return

        # Extract the number from the clicked button (e.g., "1" from "1: Detailed Newspaper Status")
        try:
            user_number = int(user_text.split(":")[0])
        except (ValueError, IndexError):
            await update.message.reply_text(
                "Invalid entry. Please use the menu buttons.", 
                reply_markup=get_db_keyboard()
            )
            return

        query = ""
        if user_number == 1:
            query = """
            SELECT
                n.name AS name,
                n.alexa_local_region AS region,
                CASE
                    WHEN n.isactive = 1 THEN 'in-process'
                    ELSE 'not process'
                END AS status,
                cs.passed_count AS passed_count,
                cs.failed_count AS failed_count,
                cs.in_queue_count AS n_queue_count
            FROM (
                SELECT
                    m.newspaper_id,
                    SUM(CASE WHEN b.fid IS NOT NULL THEN 1 ELSE 0 END) AS passed_count,
                    SUM(CASE WHEN b.fid IS NULL AND f.article_id IS NOT NULL THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN b.fid IS NULL AND f.article_id IS NULL THEN 1 ELSE 0 END) AS in_queue_count
                FROM articles.article_main_metadata m
                LEFT JOIN articles.article_body_master b
                    ON b.fid = m.fid
                   AND b.newspaperid = m.newspaper_id
                LEFT JOIN monitoring.failed_articles f
                    ON f.article_id = m.fid
                   AND f.newspaper_id = m.newspaper_id
                GROUP BY m.newspaper_id
            ) cs
            JOIN conf.newspapers n
                ON n.id = cs.newspaper_id
            ORDER BY n.name;
            """
        elif user_number == 2:
            query = "SELECT count(*) AS total_count FROM conf.newspapers;"
        elif user_number == 3:
            query = """
            SELECT n.alexa_local_region AS region FROM conf.newspapers AS n
            ORDER BY n.alexa_local_region;
            """
        elif user_number == 4:
            query = """
            SELECT n.alexa_local_region AS region FROM conf.newspapers AS n
            ORDER BY n.alexa_local_region;
            """
        elif user_number == 5:
            query = """
            SELECT
                m.newspaper_id,
                'in_queue' AS status,
                COUNT(*) AS total
            FROM articles.article_main_metadata m
            LEFT JOIN articles.article_body_master b
                ON b.fid = m.fid
               AND b.newspaperid = m.newspaper_id
            LEFT JOIN monitoring.failed_articles f
                ON f.article_id = m.fid
               AND f.newspaper_id = m.newspaper_id
            WHERE m.newspaper_id IN (1,9,10,18,25,38,44,50,52,63,69,114,132,135,141,153,191,202)
              AND b.fid IS NULL        
              AND f.article_id IS NULL
            GROUP BY m.newspaper_id
            ORDER BY m.newspaper_id;
            """
        elif user_number == 6:
            query = """
            SELECT
                ns.name AS name,
                abm.newspaperid AS newspaper_id,
                COUNT(*) AS article_count
            FROM articles.article_body_master abm, conf.newspapers ns
            WHERE abm.adddate::date = CURRENT_DATE
              AND abm.newspaperid IN (69,135,52,18,44,132,10,25,114,9,69,191,1,202)
              AND ns.id = abm.newspaperid
            GROUP BY ns.name, abm.newspaperid;
            """
        else:
            await update.message.reply_text(
                "Please enter a valid option (1-6)", 
                reply_markup=get_db_keyboard()
            )
            return

        # Execute selected query
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(query)
            records = cursor.fetchall()

            if records:
                headers = [desc[0] for desc in cursor.description]
                header_line = " | ".join(headers)
                divider_line = "-" * len(header_line)

                response = f"📊 *Results for Option {user_number}:*\n\n"
                response += f"`{header_line}`\n"
                response += f"`{divider_line}`\n"

                for row in records[:40]:  
                    row_line = " | ".join(str(val) if val is not None else "NULL" for val in row)
                    response += f"`{row_line}`\n"
                    
                if len(records) > 40:
                    response += "\n_...and more rows (output truncated)_"
            else:
                response = "Database connected successfully, but no records were found."

            # Send result AND show the db keyboard again so they can query more or exit
            await update.message.reply_text(
                response, 
                reply_markup=get_db_keyboard(), 
                parse_mode="Markdown"
            )

        except Error as err:
            await update.message.reply_text(
                f"❌ PostgreSQL Database Error:\n`{err}`", 
                reply_markup=get_db_keyboard(), 
                parse_mode="Markdown"
            )
        
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ----------------------------------------------------
    # STEP 1: Process initial menu selection
    # ----------------------------------------------------
    elif user_text == "1: database_data":
        context.user_data['waiting_for_db_choice'] = True
        
        db_menu_message = (
            "📊 *Database Data Options*\n"
            "Please select an option below:"
        )
        await update.message.reply_text(db_menu_message, reply_markup=get_db_keyboard(), parse_mode="Markdown")

    elif user_text == "2: mail_content":
        await update.message.reply_text("Mail content logic goes here.", reply_markup=get_main_keyboard())

    elif user_text == "🔙 Exit":
        # Dismiss the keyboard and say goodbye
        await update.message.reply_text(
            "👋 Session closed. Type /start anytime to begin again.",
            reply_markup=ReplyKeyboardRemove()
        )

    else:
        await update.message.reply_text(
            "Please enter a valid command or use `/start` to reset.", 
            reply_markup=get_main_keyboard()
        )


async def post_init(application: Application) -> None:
    """Register bot commands so they appear in the Telegram '/' menu."""
    await application.bot.set_my_commands([
        BotCommand("start", "🚀 Start the bot & see the main menu"),
    ])


def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is starting...")
    app.run_polling()


if __name__ == '__main__':
    main()