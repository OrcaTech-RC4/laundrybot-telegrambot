# Laundry Bot for RC4, current telegram handle: @RC4LaundryBot

import os
import csv
import re
import json
import logging
import requests
import threading
from datetime import datetime
import time
from emoji import emojize
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, Filters
from sheets import add_response

from reminders import ReminderList
from data import MockData
from string import Template
import pandas as pd

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR) # Silence oauth2client ImportError

# Initialize global variables
RC_URL = "https://us-central1-rc4laundrybot.cloudfunctions.net/readData/RC4-"
LAUNDRY_LEVELS = [5, 8, 11, 14, 17]
MACHINES_INFO = {
    'washer-coin': 'Washer 1',
    'washer-ezlink': 'Washer 2',
    'dryer-ezlink': 'Dryer 1',
    'dryer-coin': 'Dryer 2'
}
DATA = MockData()
REMINDERS = ReminderList()


# Building menu for every occasion
def build_menu(buttons, n_cols, header_buttons=None, reminder_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, header_buttons)
    if reminder_buttons:
        menu.append(reminder_buttons)
    if footer_buttons:
        menu.append(footer_buttons)
    return InlineKeyboardMarkup(menu)


# Building emojis for every occasion
ebluediamond = emojize(":small_blue_diamond: ", use_aliases=True)
etick = emojize(":white_check_mark: ", use_aliases=True)
ecross = emojize(":x: ", use_aliases=True)
esoon = emojize(":soon: ", use_aliases=True)
ehourglass = emojize(":hourglass:", use_aliases=True)


# start command initializes:
def check_handler(bot, update, user_data):
    # user = update.message.from_user
    if 'pinned_level' in user_data:
        level_status(bot, update, user_data,
                     from_pinned_level=True, new_message=True)
    else:
        ask_level(bot, update)


def ask_level(bot, update):
    level_text = "Heyyo! I am RC4's Laundry Bot. <i>As I am currently in [BETA] mode, "\
        "I can only show details for Ursa floor.</i>\n\n<b>Which laundry level do you wish to check?</b>"
    level_buttons = []
    for level in LAUNDRY_LEVELS:
        label = 'Level {}'.format(level)
        data = 'set_L{}'.format(level)
        buttons = InlineKeyboardButton(text=label, callback_data=data)  # data callback to set_pinned_level
        level_buttons.append(buttons)
    update.message.reply_text(text=level_text,
                              reply_markup=build_menu(level_buttons, 1),
                              parse_mode=ParseMode.HTML)


def set_pinned_level(bot, update, user_data):
    query = update.callback_query
    level = int(re.match('^set_L(5|8|11|14|17)$', query.data).group(1))
    user_data['pinned_level'] = level

    level_status(bot, update, user_data, from_pinned_level=True)


# Generate a Hour Minute Second template
class DeltaTemplate(Template):
    ''' Set a template for input data '''
    delimiter = "%"

# Change from timedelta to H M S format without unecessary microsecond
def strfdelta(tdelta, fmt):
    ''' Format timedelta object to the format of string fmt

    Parameter
    ----------
        tdelta: datetime.timedelta
            The datetime.timedelta object that needs to be formatted
        fmt: str
            The format string (eg. %H:%M:%S)
    
    Returns
    -------
        str
            a formmated time string
    '''

    d = {"D": tdelta.days}
    hours, rem = divmod(tdelta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    d["H"] = '{:02d}'.format(hours)
    d["M"] = '{:02d}'.format(minutes)
    d["S"] = '{:02d}'.format(seconds)
    t = DeltaTemplate(fmt)
    return t.substitute(**d)


# Carves the status text for each level
def make_status_text(level_number):
    laundry_data = ''
    floor_url = RC_URL + str(level_number)
    # TODO: This should be the backend server time instead
    current_time = datetime.fromtimestamp(time.time() + 8*3600).strftime('%d %B %Y %H:%M:%S')

    # Get Request to the database backend
    # machine_status = requests.get(floor_url).json()

    # Use mock data (DEPRECATED)
    machine_data = DATA.getStatuses(level_number)

    # Use real data
    machine_data = json.loads(
        requests.get(f"http://188.166.181.174:5000/api/levels/{level_number}/statuses").content
    )

    for machine in machine_data: 
        # Get data from back end - time since request/refresh
        date_time_str = machine["start-time"]
        remaining_time = datetime.fromtimestamp(time.time() + 8*3600) - datetime.strptime(date_time_str, '%Y-%m-%d %H:%M:%S.%f')
        remaining_time_str = strfdelta(remaining_time, '%H:%M:%S')

        if machine["status"] == 0:
            status_emoji = etick
        else:
            status_emoji = f'{ehourglass} {remaining_time_str} |'

        machine_name = machine["type"]
        laundry_data += '{}  {}\n'.format(status_emoji, machine_name)

    return "<b>Showing statuses for Level {}</b>:\n\n" \
           "{}\n" \
           "Last updated: {}\n".format(level_number, laundry_data, current_time)


# Create the status menu which contains the help command, a pinned level number, and refresh button
def make_status_menu(level_number):
    level_buttons = []

    for level in LAUNDRY_LEVELS:
        label = 'L{}'.format(level)
        data = 'check_L{}'.format(level)
        if level == level_number:
            # label = u'\u2022 ' + label + u' \u2022'
            label = ebluediamond + label

        button = InlineKeyboardButton(text=label, callback_data=data)
        level_buttons.append(button)

    refresh_button = [InlineKeyboardButton(
        text='Refresh',
        callback_data='check_L{}'.format(level_number)
    )]

    help_button = [InlineKeyboardButton(
        text='Help',
        callback_data='Help'
    )]

    reminder_button = [InlineKeyboardButton(
        text="Set a reminder",
        callback_data="remind"
    )]

    report_button = [InlineKeyboardButton(
        text='Something wrong?',
        callback_data='Report'
    )]

    header_buttons = help_button + report_button

    return build_menu(level_buttons, 5, footer_buttons=refresh_button, header_buttons=header_buttons, reminder_buttons=reminder_button)


def level_status(bot, update, user_data, from_pinned_level=False, new_message=False):
    query = update.callback_query
    if from_pinned_level:
        level = user_data['pinned_level']
    else:
        level = int(re.match('^check_L(5|8|11|14|17)$', query.data).group(1))

    user_data['check_level'] = level

    if new_message:
        update.message.reply_text(text=make_status_text(level),
                                  reply_markup=make_status_menu(level),
                                  parse_mode=ParseMode.HTML)
    else:
        bot.edit_message_text(
            text=make_status_text(level),
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            reply_markup=make_status_menu(level),
            parse_mode=ParseMode.HTML
            )


def help_menu(bot, update, user_data, from_pinned_level=False, new_message=False):
    query = update.callback_query
    help_text = "<b>Help</b>\n\n" + "Washer 1 and Dryer 2 accept coins\n" \
        + etick + "= Available / Job done\n" + esoon + "= Job finishing soon\n" + ecross + "= In use\n"

    help_text += "\nInformation not accurate or faced a problem? "\
        "Please message @PakornUe or @Cpf05, thank you!"
    help_text += "\n\nThis is a project by RC4Space's Laundry Bot Team. "\
        "We appreciate your feedback as we are currently still beta-testing "\
        "in Ursa before launching the college-wide implementation! :)"

    level = user_data['check_level']

    help_menu_button = [InlineKeyboardButton(
        text='Back',
        callback_data='check_L{}'.format(level)
    )]

    bot.edit_message_text(
        text=help_text,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        reply_markup=build_menu(help_menu_button, 1),
        parse_mode=ParseMode.HTML
        )

def report(bot, update, user_data, from_pinned_level=False, new_message=False):
    query = update.callback_query

    text = 'Is there anything wrong? Tell me in a couple of sentences.\n'
    text += 'Elaborate on any incorrect information!'
    bot.send_message(
        text = text,
        chat_id = query.message.chat_id
    )
    return 1

def get_response_ask_consent(bot, update, user_data):
    user_input = update.message.text
    chat_id = update.message.chat_id
    user_data['user_response'] = user_input
    query = update.callback_query

    yes_button = KeyboardButton(text='Yes', callback_data='Yes')
    no_button = KeyboardButton(text='No', call_back='No')
    consent_button = [yes_button, no_button]

    text = 'Thank you for reporting!\n'
    text += 'Do you consent to give this information along with your telegram use ID to the developer team?'

    bot.send_message(
        text = text,
        chat_id=update.message.chat_id,
        reply_markup=ReplyKeyboardMarkup(keyboard=[consent_button], one_time_keyboard=True)
    )

    return 2

def get_consent_end(bot, update, user_data):
    user_input = update.message.text
    query = update.callback_query
    chat_id = update.message.chat_id

    if user_input == 'Yes':
        text = 'Huge thanks!\n'
        username = update.message.chat.username
        level = user_data['pinned_level']
        response = user_data['user_response']
        add_response(username, level, response)
    else:
        text = 'Okay, your response was not recorded.\n'
    text += 'Enter /start to restart the bot.'

    bot.send_message(
        text = text,
        chat_id = update.message.chat_id
    )

    return ConversationHandler.END

def error(bot, update, error):
    logger.warning('Update "%s" caused error "%s"', update, error)

def remind(bot, update, user_data):
    ''' Set up reminder function interface

        User will be bring to a prompt which show machines that are in used
        and can be set a reminder for (machines that are not in used cannot
        be set a reminder function).

        When machine buttons is clicked:
            data will be sent to add_reminder()
        When back button is clicked:
            user will be sent back to origianl prompt
    '''

    query = update.callback_query
    level = user_data['check_level']
    selection = []
    
    # Mock test (DEPRECATED)
    machine_data = DATA.getStatuses(level)

    # Real data
    machine_data = json.loads(
        requests.get(f"http://188.166.181.174:5000/api/levels/{level}/statuses").content
    )

    
    question = "Which machine on Level {} do you like to set a reminder for?\n".format(level) \
    + "You can only set reminders for busy machines."

    # Put in-use machines in selection list
    for machine in machine_data:
        if machine["status"] != 0:
            label = machine['type']
            data = machine['type']
            button = InlineKeyboardButton(text=label, callback_data=data)
            selection.append(button)

    back_button = [InlineKeyboardButton(
        text='Back',
        callback_data='check_L{}'.format(level)
    )]

    bot.edit_message_text(
        text=question,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        reply_markup=build_menu(selection, len(selection), footer_buttons=back_button),
        parse_mode=ParseMode.HTML
        )

def add_reminder(bot, update, user_data):
    ''' Append current time, username, level and machine to Google sheet

        Append current date, current time, username, level and machine data to Google sheet
        to save reminders. The data is saved in Laundrybot sheet under Reminder tab.
    '''
    query = update.callback_query
    
    # User inputs
    input_data = {
        'current_date': datetime.fromtimestamp(time.time() + 8*3600).strftime('%d %B %Y'),
        'current_time': datetime.fromtimestamp(time.time() + 8*3600).strftime('%H:%M:%S'),
        'username': query['from_user']['username'],
        'level': user_data['check_level'],
        'machine-type': query['data'],
    }

    print(
        requests.get(f"http://188.166.181.174:5000/api/levels/{input_data['level']}/statuses").content
    )
    # Mock data for temporary use (DEPRECATED)
    machine_data = list(
        filter(
            lambda x: x['type'] == input_data['machine-type'], 
            DATA.getStatuses(input_data['level'])
        )).pop()
    
    # Real data
    machine_data = list(
        filter(
            lambda x: x['type'] == input_data['machine-type'], 
            json.loads(
                requests.get(f"http://188.166.181.174:5000/api/levels/{input_data['level']}/statuses").content
            )
        )).pop()

    notice = 'A reminder has been set for Level {} {}'.format(input_data['level'],input_data['machine-type'])

    # The following is the format of reminders logging
    REMINDERS.append({
        'username': query['from_user']['username'],
        'chat_id': query.message.chat_id,
        'input_data': input_data,
        'machine_data': machine_data
    })

    # with open('../reminder.csv', "a",newline='') as file:
    #     file_reader = csv.reader(file,delimiter=',')
    #     fieldsnames = ['current_date','current_time','username','level','machine-type']
    #     writer = csv.DictWriter(file,fieldnames=fieldsnames)
    #     writer.writerow(input_data)

    back_button = [InlineKeyboardButton(
        text='Back',
        callback_data='check_L{}'.format(input_data['level'])
    )]

    bot.edit_message_text(
        text=notice,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        reply_markup=build_menu(back_button, 1),
        parse_mode=ParseMode.HTML,
        )

def run_bot(updater):

    dp = updater.dispatcher

    # dp.add_handler used to receive back querry
    # to call a function using a button, passed in pattern= callback_data
    dp.add_handler(CommandHandler('start', check_handler, pass_user_data=True))
    dp.add_handler(CallbackQueryHandler(set_pinned_level,
                                        pattern='^set_L(5|8|11|14|17)$',
                                        pass_user_data=True))
    dp.add_handler(CallbackQueryHandler(level_status,
                                        pattern='^check_L(5|8|11|14|17)$',
                                        pass_user_data=True))
    dp.add_handler(CallbackQueryHandler(help_menu,
                                        pattern='Help',
                                        pass_user_data=True))
    dp.add_handler(CallbackQueryHandler(remind, 
                                        pattern='remind',
                                        pass_user_data=True))
    dp.add_handler(CallbackQueryHandler(add_reminder, 
                                        pattern='^(washer-coin|washer-ezlink|dryer-ezlink|dryer-coin)$',
                                        pass_user_data=True))                                   
    dp.add_handler(ConversationHandler(
        [CallbackQueryHandler(report, pattern="Report", pass_user_data=True)],
        {
            1: [MessageHandler(Filters.text, get_response_ask_consent, pass_user_data=True)],
            2: [MessageHandler(Filters.text, get_consent_end, pass_user_data=True)]
        },
        []))
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

def main():

    TOKEN = os.environ['RC4LAUNDRYBOT_TOKEN']

    updater = Updater(TOKEN)

    t = threading.Thread(target=REMINDERS.poll, args=(updater.bot,))
    t.start()
    
    run_bot(updater)



if __name__ == '__main__':
    main()
