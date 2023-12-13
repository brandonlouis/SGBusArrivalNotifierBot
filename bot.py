import os
import telebot
import json
import time
import threading
import math
from utils import get_data
from datetime import datetime
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

# Load tokens from .env file
with open(".env", "r") as env_file:
    for line in env_file:
        if line.startswith("BOT_TOKEN"):
            key, value = line.strip().split("=")
            os.environ[key] = value
        
        if line.startswith("MONGO_URI"):
            key, value = line.strip().split("=", 1)
            os.environ[key] = value

        if line.startswith("DB_NAME"):
            key, value = line.strip().split("=")
            os.environ[key] = value

        if line.startswith("COLLECTION_NAME"):
            key, value = line.strip().split("=")
            os.environ[key] = value

bot = telebot.TeleBot(os.environ.get('BOT_TOKEN'))
client = MongoClient(os.environ.get('MONGO_URI'), server_api=ServerApi('1'))
db = client[os.environ.get('DB_NAME')]
collection = db[os.environ.get('COLLECTION_NAME')]

# Send a ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Successfully connected to MongoDB!")
except Exception as e:
    print(e)

# Load JSON data
with open('stops.json', 'r') as file:
    stop_data = json.load(file)

stopSchedule = False


@bot.message_handler(commands=['start'])
def sendWelcome(message):        
    if not collection.find_one({'chat_id': message.chat.id}):
        collection.insert_one({'chat_id': message.chat.id, 'first_name': message.from_user.first_name, 'last_name': message.from_user.last_name, 'username': message.from_user.username, 'date_last_used': datetime.now(), 'notifiers': []})
    else:
        collection.update_one({'chat_id': message.chat.id}, {'$set': {'date_last_used': datetime.now()}})

    user = message.from_user
    userFirstName = user.first_name if user.first_name else "there"
    bot.send_message(message.chat.id, f'👋 Hello {userFirstName}, welcome to Bus Arrival Notifier Bot!\n\nPlease enter your bus stop code to get started.\ne.g. "67009"')

    bot.register_next_step_handler(message, processBusStopCode)


def processBusStopCode(message):
    busServices_data = None

    if message.text.isdigit() and len(message.text) == 5:
        try:
            busServices_data = get_data(message.text)["services"]
            nos = [service["no"] for service in busServices_data]

            if not nos:
                bot.send_message(message.chat.id, 'No bus services found. Please re-enter your bus stop code.')
                bot.register_next_step_handler(message, processBusStopCode)
            else:
                busStopName = stop_data[message.text][2]
                nos_text = ", ".join(nos)
                bot.send_message(message.chat.id, f'📍 *{busStopName} ({message.text})*\n🚌 *{nos_text}*\n\nPlease enter the bus service number(s) you wish to track.\ne.g. "86, 163, 965"\n\nor send another bus stop code to change bus stop.', parse_mode="Markdown")

                bot.register_next_step_handler(message, processBusService, message.text, busServices_data)
        except Exception as e:
            print(f'API Fetch Error: {e}')
            bot.send_message(message.chat.id, 'Something went wrong. Please try again later.')

    else:
        bot.send_message(message.chat.id, 'Invalid code. Please re-enter your bus stop code.\ne.g. "67009"')
        bot.register_next_step_handler(message, processBusStopCode)


def processBusService(message, busStopCode, busServices_data):
    inputBusServices = None

    if message.text.isdigit() and len(message.text) == 5:
        processBusStopCode(message)
        return

    input_text = message.text.upper().replace(" ", "")
    inputBusServices = input_text.split(",") if "," in input_text else [input_text]
    inputBusServices = list({item: None for item in inputBusServices}.keys())
    inputBusServices.reverse()
    
    inputBusServicesCount = len(inputBusServices)

    valid_services = all(any(service['no'] == num for service in busServices_data) for num in inputBusServices)

    if valid_services:
        showBusArrivalTimes(message, busStopCode, busServices_data, inputBusServices, inputBusServicesCount)
    else:
        inputBusServices = None
        inputBusServicesCount = 0
        bot.send_message(message.chat.id, "Invalid service number(s). Please re-enter service number or send another bus stop code to change bus stop.")
        bot.register_next_step_handler(message, processBusService, busStopCode, busServices_data)


def showBusArrivalTimes(message, busStopCode, busServices_data, inputBusServices, inputBusServicesCount):
    matching_service = next((service for service in busServices_data if service["no"] == inputBusServices[inputBusServicesCount-1]), None)
    
    firstBus = f"*{formatArrivalTime(matching_service['next'])}*"
    secondBus = f"*{formatArrivalTime(matching_service['subsequent'])}*"
    thirdBus = f"*{formatArrivalTime(matching_service['next3'])}*"

    bot.send_message(message.chat.id, f'🚌 *{matching_service["no"]}*\n1st: {firstBus}\n2nd: {secondBus}\n3rd: {thirdBus}\n\nWhich timing(s) would you like me to notify you?\n\ne.g. "5, Arr" would mean that I would notify you as soon as the bus is *5 minutes* away, and when its *Arriving*, in descending order.', parse_mode="Markdown")
    bot.register_next_step_handler(message, processNotifyTime, matching_service["no"], busStopCode, busServices_data, inputBusServices, inputBusServicesCount)


def formatArrivalTime(time):
    if time is None:
        return 'No Information'
    elif math.floor(time['duration_ms'] / (1000 * 60)) <= 0:
        return 'Arriving'
    elif math.floor(time['duration_ms'] / (1000 * 60)) == 1:
        return '1 minute'
    else:
        return f'{math.floor(time["duration_ms"] / (1000 * 60))} minutes'


def processNotifyTime(message, busServiceNo, busStopCode, busServices_data, inputBusServices, inputBusServicesCount):
    notifyDict = {}

    if verifyNotifyTime(message.text) == True:
        userInput = message.text.upper().replace(" ", "").split(",")
        userInputList = []
        for item in userInput:
            item = int(item) if item.isdigit() else item
            if item not in userInputList and item not in ["ARR", "ARRIVING"]:
                userInputList.append(item)

        userInputList.sort(reverse=True)

        if "ARR" in userInput or "ARRIVING" in userInput:
            userInputList.append("ARRIVING")

        notifyDict[busServiceNo] = userInputList

        notifyMessage = f"I will notify you when Bus *{busServiceNo}* is:\n"
        notifyMessageParts = []

        for time in notifyDict[busServiceNo]:
            if time == "ARRIVING":
                notifyMessageParts.append("- *Arriving*")
            else:
                timeString = f"- *{time}min* away" if time == 1 else f"- *{time}mins* away"
                notifyMessageParts.append(f"{timeString}")

        if len(notifyMessageParts) >= 0:
            notifyMessage += "\n".join(notifyMessageParts)
        else:
            notifyMessage += notifyMessageParts[0]

        insertNotifyTimeDB(message.chat.id, busStopCode, busServiceNo, notifyDict[busServiceNo])
        bot.send_message(message.chat.id, notifyMessage, parse_mode="Markdown")
        inputBusServicesCount -= 1

        if inputBusServicesCount > 0:
            showBusArrivalTimes(message, busStopCode, busServices_data, inputBusServices, inputBusServicesCount)
        else:
            bot.send_message(message.chat.id, '/start if you would like to track another bus service!')

    else:
        bot.send_message(message.chat.id, verifyNotifyTime(message.text)[1], parse_mode="Markdown")
        bot.register_next_step_handler(message, processNotifyTime, busServiceNo, busStopCode, busServices_data, inputBusServices, inputBusServicesCount)
        

def verifyNotifyTime(timeList):
    userInput = timeList.upper().replace(" ", "").split(",")
    for item in userInput:
        if item.isdigit() and int(item) > 30:
            return [False,'I can only notify you up to *30 minutes* before the bus arrives. Please try again.']
        elif not (item.isdigit() or item == "ARR" or item == "ARRIVING"):
            return [False, 'Invalid input. Please try again.\n\ne.g. "Arr", "Arriving" (case-insensitive)']
        elif item.isdigit() and int(item) <= 0:
            return [False, 'Invalid input. Timing should be more than 0 minutes. Try again with "Arr" or "Arriving" instead.']
    
    return True


def insertNotifyTimeDB(chat_id, busStopCode, busServiceNo, notifyTime):
    query = {
        'chat_id': chat_id,
        'notifiers': {
            '$elemMatch': {busStopCode: {"$exists": True}}
        }
    }

    if collection.find_one(query) is None: # If bus stop code does not exist, create new + first bus service number
        update_data = {
            "$push": {
                "notifiers": {
                    busStopCode: [{
                        busServiceNo: notifyTime
                    }]
                }
            }
        }
        collection.update_one({'chat_id': chat_id}, update_data, upsert=True)

    else: # If bus stop code exists, check if bus service number exists
        query = {
            'chat_id': chat_id,
            f'notifiers.{busStopCode}': {
                '$elemMatch': {busServiceNo: {"$exists": True}}
            }
        }

        if collection.find_one(query) is None: # If bus service number does not exist, create new
            update_data = {
                "$push": {
                    f"notifiers.$[code].{busStopCode}": {
                        busServiceNo: notifyTime
                    }
                }
            }
            array_filters = [{f"code.{busStopCode}": {"$exists": True}}]
            collection.update_one({'chat_id': chat_id}, update_data, array_filters=array_filters)

        else: # If bus service number exists, update existing
            update_data = {
                "$set": {
                    f"notifiers.$[code].{busStopCode}.$[service].{busServiceNo}": notifyTime
                }
            }
            array_filters = [
                {f"code.{busStopCode}": {"$exists": True}},
                {f"service.{busServiceNo}": {"$exists": True}}
            ]
            collection.update_one({'chat_id': chat_id}, update_data, array_filters=array_filters)
    
    global stopSchedule
    if stopSchedule == True: # If scheduleThread is stopped, start it again
        stopSchedule = False
        thread = threading.Thread(target=refreshAPI)
        thread.start()


# Your fetchAPI function
def fetchAPITiming():
    global stopSchedule
    if collection.count_documents({'notifiers': {'$exists': True, '$not': {'$size': 0}}}) == 0 and stopSchedule == False: # If notifiers array is empty, stop scheduleThread
        stopSchedule = True
        thread = threading.Thread(target=refreshAPI)
        thread.start()
        thread.join()

    for document in collection.find({'notifiers.0': {'$exists': True}}): # If notifiers array is not empty
        for i in range(len(document['notifiers'])):
            for busStopCode in document['notifiers'][i]:
                apiBusInfo = get_data(busStopCode)["services"] # Retrieve bus stop data through API

                for busServiceNo in document['notifiers'][i][busStopCode]:
                    for service in apiBusInfo:
                        for key in busServiceNo:
                            
                            for j in range(len(busServiceNo[key])): # Change ARRIVING to 0
                                if busServiceNo[key][j] == 'ARRIVING':
                                    busServiceNo[key][j] = 0
                                
                            if service['no'] == key: # If bus service number matches
                                timings = ['next', 'subsequent', 'next3']
                                defaultTiming = 1000
                                busTimings = {}

                                for timing in timings:
                                    if service[timing] is not None:
                                        busTimings[timing] = math.floor(service[timing]['duration_ms'] / (1000 * 60)) # Convert to minutes
                                    else:
                                        busTimings[timing] = defaultTiming # If no timing, set to 1000 minutes
                                

                                if busTimings['next'] == busServiceNo[key][0] or busTimings['subsequent'] == busServiceNo[key][0] or busTimings['next3'] == busServiceNo[key][0]:
                                    if busServiceNo[key][0] <= 0:
                                        bot.send_message(document['chat_id'], f"📍{stop_data[busStopCode][2]}\n🚌 {key} is now *Arriving*", parse_mode="Markdown")
                                    elif busServiceNo[key][0] == 1:
                                        bot.send_message(document['chat_id'], f"📍{stop_data[busStopCode][2]}\n🚌 {key} is now *1 minute* away", parse_mode="Markdown")
                                    else:
                                        bot.send_message(document['chat_id'], f"📍{stop_data[busStopCode][2]}\n🚌 {key} is now *{int(busServiceNo[key][0])} minutes* away", parse_mode="Markdown")

                                    removeNotifierTime = {
                                        "$pop": {
                                            f"notifiers.$[code].{busStopCode}.$[service].{key}": -1
                                        }
                                    }
                                    array_filters = [
                                        {f"code.{busStopCode}": {"$exists": True}},
                                        {f"service.{key}": {"$exists": True}}
                                    ]
                                    collection.update_one({'chat_id': document['chat_id']}, removeNotifierTime, array_filters=array_filters)

                                    
                                    collection.update_one({'chat_id': document['chat_id']}, # Remove empty bus service numbers arrays
                                        {
                                            "$pull": {
                                                f"notifiers.$[elem].{busStopCode}": {
                                                    f'{key}': {'$eq': []}
                                                }
                                            }
                                        },
                                        array_filters=[{"elem": {"$exists": True}}]
                                    )
                                    collection.update_one({'chat_id': document['chat_id']}, # Remove empty bus stop codes arrays
                                        {
                                            "$pull": {
                                                f"notifiers": {
                                                    f'{busStopCode}': {'$eq': []}
                                                }
                                            }
                                        }
                                    )





@bot.message_handler(commands=['notifiers'])
def sendNotifiers(message):
    for document in collection.find({'chat_id': {'$eq': message.chat.id}}): # If notifiers array is not empty
        if len(document['notifiers']) == 0:
            bot.send_message(message.chat.id, 'You have no active notifiers. Use /start to begin!')
        else:
            resString = ''

            for i in range(len(document['notifiers'])):
                for busStopCode in document['notifiers'][i]:
                    if i > 0:
                        resString += '\n' # Add a new line if it's not the first bus stop code

                    resString += f"📍 {stop_data[busStopCode][2]} ({busStopCode}):\n" 

                    for busServiceNo in document['notifiers'][i][busStopCode]:
                        for key in busServiceNo:
                            timings = ''

                            for j in range(len(busServiceNo[key])):
                                if busServiceNo[key][j] == 'ARRIVING':
                                    timings += 'Arriving'
                                else:
                                    timings += str(busServiceNo[key][j])

                                    if busServiceNo[key][j] > 1:
                                        timings += 'mins'
                                    elif busServiceNo[key][j] == 1:
                                        timings += 'min'

                                # Add a comma if it's not the last item
                                if j < len(busServiceNo[key]) - 1:
                                    timings += ', '

                            resString += f"🚌 {key}: {timings}\n"

            bot.send_message(message.chat.id, resString)





@bot.message_handler(commands=['clearall'])
def clearNotifiers(message):
    filter = {}
    update = {"$set": {"notifiers": []}}

    # Update the documents in the collection
    collection.update_many(filter, update)
    
    bot.send_message(message.chat.id, "Successfully cleared all notifiers! Use /start to begin!")





# Fetch API every 15 seconds
def refreshAPI():
    global stopSchedule
    while not stopSchedule:
        print("Fetched")
        fetchAPITiming()
        time.sleep(15)

# Start the scheduleThread in a separate thread
thread = threading.Thread(target=refreshAPI)
thread.start()

# Start the bot's polling loop in the main thread
bot.infinity_polling()