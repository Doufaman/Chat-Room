#This file defines the message format sent between components in the group communication
import json 
import sys
import os

"""This defines the message types for group communication"""
TYPE_JOIN = 'JOIN'
TYPE_CHAT = 'CHAT'
TYPE_LEAVE = 'LEAVE'  
TYPE_UPDATE = 'UPDATE'  #When there is a new member, send this to update the vector clocks of existing clients


"""This defines the message types for server communication"""
TYPE_HEARTBEAT = 'HEARTBEAT'
TYPE_ELECTION = 'ELECTION'
TYPE_ANSWER = 'ANSWER'
TYPE_COORDINATOR = 'COORDINATOR'

def set_server_message(msg_type, sender, content):
    """generate the server message in json format"""
    message = {
        'type': msg_type,
        'sender': sender, 
        'content': content if content else {}
    }
    return message

#For client and server communication:
def set_client_message(msg_type, sender, vector_clock, content):
    """generate the message in json format"""
    message = {
        'type': msg_type,
        'sender': sender, 
        'vector_clock': vector_clock.copy(), 
        'content': content if content else {}
    }
    return message

def encode_message(message):
    """encode the message to json string"""
    return json.dumps(message).encode('utf-8')

def decode_message(message_str):
    """decode the json string to message dict"""
    return json.loads(message_str.decode('utf-8'))

def safe_print(content):
    """
    Safely print a message to the console without disrupting the user's input line.
    Works on Windows and Unix-like systems.
    """
    # 1. Clear the current line (where "Your message: " might be)
    if os.name == 'nt':
        # Windows: Move to start (\r), overwrite with spaces, move back to start
        sys.stdout.write('\r' + ' ' * 80 + '\r')
    else:
        # macOS/Linux: Move to start (\r), clear line (\033[K)
        sys.stdout.write('\r\033[K')

    # 2. Print the actual message (new line)
    print(content)

    # 3. Restore the input prompt
    sys.stdout.write("Your message: ")
    sys.stdout.flush()

