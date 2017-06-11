#!/usr/bin/python3
# pylint: skip-file
#TODO(das7pad): refactor globals and split this plugin into two modules
"""
hangoutsbot plugin for integration with surveillance systems that send out notifications
by email (containing webcam snapshots).

See https://github.com/hangoutsbot/hangoutsbot/wiki/Cam-Mail-Intercept-Plugin

The plugin acts as a non-secure email relay on your local network,
intercepts some messages and forwards them to your (hanghoutsbo't accounts) provider's smtp email relay.
Attention, the mail relay works uprotected within your local network, protected over the Internet,
so associate it only with your bot's own email account, not with your personal email account.
This software has only been tested with notifications generated by a synology surveilance station.
Direct video grabbing has been tested with apexis J cams

Please make sure this file gets copied into your hangoutsbot/hangupsbot/plugins directory

infradom
"""



"""
# synology startup script: /etc/init/hangoutsbot.conf
#
# ------------------------------------------
# only start this service after the httpd user process has started
start on started httpd-user

# stop the service gracefully if the runlevel changes to 'reboot'
stop on runlevel [06]

# run the scripts as the 'botty' (or a name of your choice) user. Running as root (the default) is a bad idea.
# you need to create this user first !
setuid botty

# exec the process. Use fully formed path names so that there is no reliance on $PATH
# the 'www' file is a node.js script which starts the foobar application.
exec /usr/bin/python3 /volume1/homes/botty/hangoutsbot/hangupsbot/hangupsbot.py

"""



"""
config.json entries used by this plugin
"extsmtpuser"       : "name_of_mybot@gmail.com"
"extsmtppwd"        : "botsmtppassword" # recommend to use an app password (and 2 factor authentication)
"intsmtpaddress"    : "127.0.0.1"
"intsmtpport"       : "10025"
"cammailcid"        : "Umyconversationid45dsseAQ"
"alarmsysurl"       : "http://10.10.10.32/AlarmLoadedFlag"
"alarmnoturl"       : "http://10.10.10.32/%(location)s/pulse"
"alarmsysusr"       : "camera",
"alarmsyspwd"       : "mypassword",
"alarmsubjectformat": { "regexp": "(.*) (.*)( (.*))*", "locationindex": 2 } # second word of subject is location
"alarmsysoffregexp" : "value=\"0\""
"campwd"            : "myCAMpassword"
"camusr"            : "CAMdmin"
                       # list of direct camera url's for grabbing life jpeg snapshots
"camurls"           : { 'achter' : 'http://10.10.10.31:27116/snapshot.cgi',
                        'zij'    : 'http://10.10.10.33:27118/snapshot.cgi'
                      }
"""


import logging
import plugins
import asyncio
import threading
import socket
import io

logger = logging.getLogger(__name__)

myqueue = asyncio.Queue()
mybot = None


def _initialise(bot):
    global EXTSMTPUSER,EXTSMTPPWD,EXTSMTPSERVER,EXTSMTPPORT,INTSMTPADDRESS,INTSMTPPORT
    global CAMMAILCID
    global ALARMSYSURL,ALARMSYSUSR,ALARMSYSPWD,ALARMNOTURL,ALARMSUBJECTFORMAT,ALARMSYSOFFREGEXP
    global CAMPWD,CAMUSR,CAMURLS
    try:
        EXTSMTPUSER       = bot.config.get_option("extsmtpuser") or None
        EXTSMTPPWD        = bot.config.get_option("extsmtppwd") or None
        EXTSMTPSERVER     = bot.config.get_option("extsmtpserver") or "smtp.gmail.com"
        EXTSMTPPORT       = bot.config.get_option("extsmtpport") or "587"
        INTSMTPADDRESS    = bot.config.get_option("intsmtpaddress") or socket.gethostname()
        INTSMTPPORT       = int(bot.config.get_option("intsmtpport") or "10025")
        CAMMAILCID        = bot.config.get_option("cammailCID") or None
        ALARMSYSURL       = bot.config.get_option("alarmsysurl") or None
        ALARMSYSUSR       = bot.config.get_option("alarmsysusr") or None
        ALARMSYSPWD       = bot.config.get_option("alarmsyspwd") or None
        ALARMNOTURL       = bot.config.get_option("alarmnoturl") or None
        ALARMSYSOFFREGEXP = re.compile(str(bot.config.get_option("alarmsysoffregexp"))) or None
        s = bot.config.get_option("alarmsubjectformat") or { "regexp": r"(.*) (.*)( .*)*", "locationindex": 2 }
        ALARMSUBJECTFORMAT= { "regexp" : re.compile(s["regexp"]), "locationindex": s["locationindex"] }
        CAMPWD            = bot.config.get_option("campwd") or None
        CAMUSR            = bot.config.get_option("camusr") or None
        CAMURLS           = bot.config.get_option("camurls") or {}
    except:
        logger.exception("missing config file entry")
        return
    logger.info("using ALARMSUBJECTFORMAT: " + str(ALARMSUBJECTFORMAT))
    global mybot
    mybot = bot
    # spawn a separate thread for the mail server
    # hoping asyncore and asyncio do not fight
    t = threading.Thread(target = smtpthread)
    t.daemon = True
    t.start()
    plugins.register_user_command(["interceptCamMail"])
    plugins.register_handler(_handle_incoming_message, type="message")


""" intercept cam mail for this conversation
    replaces previous conversation. Can only support one conversation for now """
def interceptCamMail(bot, event, *args):
    global CAMMAILCID
    print(event.conv_id)
    bot.config.set_by_path(["cammailCID"], event.conv_id)
    CAMMAILCID =  event.conv_id
    return _("<i>This conversation will receive cammail notifications</i>")


async def my_message(item):
    count = 0
    for i in item["img"]:
        image_id = await mybot._client.upload_image(io.BytesIO(i), filename=item["filename"][count])
        await mybot.coro_send_message( CAMMAILCID, None, image_id=image_id)
        count +=1
    await mybot.coro_send_message( CAMMAILCID, item["content"], image_id=None)

async def _handle_incoming_message(bot, event, command):
    txt = event.text.lower().strip()
    logger.info('message received, stiripped: ' + txt)
    camurl = CAMURLS.get(txt, None)
    if camurl:
        image_data = requests.get(camurl, auth=HTTPBasicAuth(CAMUSR, CAMPWD))
        logger.info('image data len: ' + str(len(image_data.content)))
        image_id = await bot._client.upload_image(io.BytesIO(image_data.content), filename=txt+'.jpg')
        await bot.coro_send_message(event.conv.id_, None, image_id=image_id)


"""
mail relay thread section: should be built on asyncio but smtpd uses asyncore internally
So lets run it in a separate thread for the time being.
"""

import smtpd
import asyncore

import os
import re
import sys
import json
import email
import base64
import errno
import mimetypes
import smtplib
import requests
from requests.auth import HTTPBasicAuth
from email.mime.text import MIMEText
from email.header import decode_header



def interceptMail(maildata):
    logger.info("in interceptMail")
    msg = email.message_from_string(maildata)
    subject = msg['Subject']
    if subject: subject = decode_header(subject)[0][0].decode()
    else: subject = ""
    mo = re.match(ALARMSUBJECTFORMAT["regexp"], subject)
    if mo: location= mo.group(ALARMSUBJECTFORMAT["locationindex"])
    else: location = ""
    # notify alarm system in all cases
    if ALARMNOTURL and (location in CAMURLS):
        try: r = requests.get(ALARMNOTURL % {'location': location }, auth=HTTPBasicAuth(ALARMSYSUSR, ALARMSYSPWD))
        except: logger.exception('cannot notify alarm system')
    # do not chat if alarm system is not active
    if ALARMSYSURL:
        try:
            r = requests.get(ALARMSYSURL, auth=HTTPBasicAuth(ALARMSYSUSR, ALARMSYSPWD))
            if ALARMSYSOFFREGEXP and ALARMSYSOFFREGEXP.search(r.text):
                logger.info("ignoring alarm, alarm system not active")
                return True
        except: logger.exception('cannot talk to alarm system url')
    item = {"filename": [], "img": [], "content": subject}
    counter = 0
    for part in msg.walk():
        counter +=1
        # multipart/* are just containers
        if part.get_content_maintype() == 'multipart': continue
        typ = part.get_content_type()
        if part.get_filename("xxx").startswith('=?'): filename = decode_header(part.get_filename())[0][0].decode()
        else: filename = part.get_filename("xxx")
        logger.info('content type: ' + typ + ' filename: ' + filename)
        if (typ == 'text/plain'):
            body = part.get_payload(decode=False)
            item["content"] += '\n' + str(body)
        if (typ == "image/jpeg"):
            img = part.get_payload(decode=True)
            item["filename"].append(filename)
            item["img"].append(img)
            item["content"] = subject # remove body if there is an image - an image says more than 1000 words
            logger.info('feeding image data into bot - size: ' + str(len(img)) )
    try:
        asyncio.ensure_future(my_message(item))
    except:
        logger.exception('cannot post into bot')
    forward = True
    return forward


class CustomSMTPServer(smtpd.SMTPServer):

    def process_message(self, peer, mailfrom, rcpttos, data):
        logger.info("mail received from :" + mailfrom + " to: " + str(rcpttos))
        # analyze and intercept mail
        forward = interceptMail(data)
        # Forward the message to provider SMTP server if required.
        if forward:
            logger.info("forward mail received from :" + mailfrom + " to: " + str(rcpttos))
            s = smtplib.SMTP(EXTSMTPSERVER,EXTSMTPPORT)
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(EXTSMTPUSER,EXTSMTPPWD)
            #s.set_debuglevel(1)
            s.sendmail(mailfrom,rcpttos, data)
            s.close()
        return

def smtpthread():
    logger.info("within smtpd thread")
    server = CustomSMTPServer((INTSMTPADDRESS, INTSMTPPORT), None)
    asyncore.loop()
