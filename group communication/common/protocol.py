#This file defines the message format sent between components in the group communication
import json 
import sys

"""This defines the message types"""
TYPE_JOIN = 'JOIN'
TYPE_CHAT = 'CHAT'
TYPE_LEAVE = 'LEAVE'  
TYPE_UPDATE = 'UPDATE'  #When there is a new member, send this to update the vector clocks of existing clients


def set_message(msg_type, sender, vector_clock, content):
    """generate the message in json format"""
    message = {
        'type': msg_type,
        'sender': sender, 
        'vector_clock': vector_clock.copy(), 
        'content': content
    }
    return message

def encode_message(message):
    """encode the message to json string"""
    return json.dumps(message).encode('utf-8')

def decode_message(message_str):
    """decode the json string to message dict"""
    return json.loads(message_str.decode('utf-8'))

def safe_print(content):
    """print the message to avoid console conflicts"""
    # ANSI Escape Codes:
    # \r - Move cursor to start of line
    # \033[K - Clear line from cursor to end
    sys.stdout.write('\r\033[K')  
    print(content)
    sys.stdout.write('Enter Message: ')
    sys.stdout.flush() 
    