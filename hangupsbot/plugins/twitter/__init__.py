import datetime
import io
import json
import logging
import os
import re

import aiohttp
import hangups
from TwitterAPI import (
    TwitterAPI,
    TwitterConnectionError,
)
from bs4 import BeautifulSoup

from hangupsbot import plugins
from hangupsbot.commands import Help


logger = logging.getLogger(__name__)

HELP = {
    'twittersecret': _('Set your Twitter API Secret.\n'
                       'Get one from https://apps.twitter.com/app'),

    'twitterkey': _('Set your Twitter API Key.\n'
                    'Get one from https://apps.twitter.com/'),

    'twitterconfig': _('Get your Twitter credentials. Remember that these are '
                       'meant to be kept secret!'),
}


def pretty_date(date):
    diff = datetime.datetime.now(tz=datetime.timezone.utc) - date
    sec = diff.seconds
    output = (date.strftime('%b %d %y') if diff.days > 7 or diff.days < 0 else
              '1 day ago' if diff.days == 1 else
              '{} days ago'.format(diff.days) if diff.days > 1 else
              'just now' if sec <= 1 else
              '{} seconds ago'.format(sec) if sec < 60 else
              '1 minute ago' if sec < 120 else
              '{} minutes ago'.format(round(sec / 60)) if sec < 3600 else
              '1 hour ago' if sec < 7200 else
              '{} hours ago'.format(round(sec / 3600)))
    return output


def _initialise():
    plugins.register_admin_command([
        'twitterkey',
        'twittersecret',
        'twitterconfig',
    ])
    plugins.register_help(HELP)
    plugins.register_sync_handler(_watch_twitter_link, "message_once")


def twittersecret(bot, dummy, *args):
    """Set your Twitter API Secret."""
    if not args:
        raise Help()
    secret = args[0]
    if not bot.memory.get_by_path(['twitter']):
        bot.memory.set_by_path(['twitter'], {})

    bot.memory.set_by_path(['twitter', 'secret'], secret)
    return "Twitter API secret set to <b>{}</b>.".format(secret)


def twitterkey(bot, dummy, *args):
    """Set your Twitter API Key."""
    if not args:
        raise Help()
    key = args[0]
    if not bot.memory.get_by_path(['twitter']):
        bot.memory.set_by_path(['twitter'], {})

    bot.memory.set_by_path(['twitter', 'key'], key)
    return "Twitter API key set to <b>{}</b>.".format(key)


def twitterconfig(bot, *dummys):
    """Get your Twitter credentials."""

    if not bot.memory.exists(['twitter']):
        bot.memory.set_by_path(['twitter'], {})
    if not bot.memory.exists(['twitter', 'key']):
        bot.memory.set_by_path(['twitter', 'key'], "")
    if not bot.memory.exists(['twitter', 'secret']):
        bot.memory.set_by_path(['twitter', 'secret'], "")

    return ("<b>API key:</b> {}<br><b>API secret:</b> {}".format(
        bot.memory.get_by_path(['twitter', 'key']),
        bot.memory.get_by_path(['twitter', 'secret'])))


async def _watch_twitter_link(bot, event):
    if event.user.is_self:
        return

    if " " in event.text:
        return

    if not re.match(
            r"^https?://(www\.)?twitter.com/[a-zA-Z0-9_]{1,15}/status/[0-9]+$",
            event.text, re.IGNORECASE):
        return

    try:
        key = bot.memory.get_by_path(['twitter', 'key'])
        secret = bot.memory.get_by_path(['twitter', 'secret'])
    except KeyError:
        return

    try:
        tweet_id = re.match(r".+/(\d+)", event.text).group(1)
        api = TwitterAPI(key, secret, auth_type="oAuth2")
        tweet = json.loads(
            api.request('statuses/show/:{}'.format(tweet_id)).text)
        text = re.sub(r'(\W)@(\w{1,15})(\W)',
                      r'\1<a href="https://twitter.com/\2">@\2</a>\3',
                      tweet['text'])
        text = re.sub(r'(\W)#(\w{1,15})(\W)',
                      r'\1<a href="https://twitter.com/hashtag/\2">#\2</a>\3',
                      text)
        date = datetime.datetime.strptime(tweet['created_at'],
                                          '%a %b %d %H:%M:%S %z %Y')
        time_ago = pretty_date(date)
        username = tweet['user']['name']
        twitter_handle = tweet['user']['screen_name']
        user_url = "https://twitter.com/intent/user?user_id={}".format(
            tweet['user']['id'])
        message = "<b><u><a href='{}'>@{}</a> ({})</u></b>: {} <i>{}</i>".format(
            user_url, twitter_handle, username, text, time_ago)
        try:
            images = tweet['extended_entities']['media']
            for image in images:
                if image['type'] == 'photo':
                    image = bot.sync.get_sync_image(
                        url=image['media_url'],
                    )
                    await image.download()
                    image_data, filename = image.get_data()
                    image_id = await bot.upload_image(image_data,
                                                      filename=filename)
                    await bot.coro_send_message(event.conv.id_, None,
                                                image_id=image_id)

        except KeyError:
            pass

        await bot.coro_send_message(event.conv, message)
    except (TwitterConnectionError, aiohttp.ClientError, hangups.NetworkError):
        url = event.text.lower()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    body = await response.text()
        except aiohttp.ClientError as err:
            logger.info('get %s: %s', id(url), url)
            logger.error('get %s: failed with %r', id(url), err)
            return

        username = re.match(r".+twitter\.com/([a-zA-Z0-9_]+)/", url).group(1)
        soup = BeautifulSoup(body, "lxml")
        twitter_handle = soup.title.text.split(" on Twitter: ")[0].strip()
        tweet = re.sub(r"#([a-zA-Z0-9]*)",
                       r"<a href='https://twitter.com/hashtag/\1'>#\1</a>",
                       soup.title.text.split(" on Twitter: ")[1].strip())
        message = "<b><a href='{}'>@{}</a> [{}]</b>: {}".format(
            "https://twitter.com/{}".format(username), username, twitter_handle,
            tweet)
        await bot.coro_send_message(event.conv, message)
