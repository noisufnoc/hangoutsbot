"""trigger popular reddit meme images
based on the word/image list for the image linker bot on reddit
sauce: http://www.reddit.com/r/image_linker_bot/comments/2znbrg
/image_suggestion_thread_20/
"""
import io
import logging
import os
import random
import re

import aiohttp

from hangupsbot import plugins


logger = logging.getLogger(__name__)

HELP = {
    'redditmemeword': _("trigger popular reddit meme images (eg. type "
                        "'slowclap.gif').\nFull list at http://goo.gl/ORmisN"),
}

_LOOKUP = {}


def _initialise():
    _load_all_the_things()
    plugins.register_admin_command([
        "redditmemeword",
    ])
    plugins.register_sync_handler(_scan_for_triggers, "message_once")
    plugins.register_help(HELP)


async def redditmemeword(dummy0, dummy1, *args):
    """trigger popular reddit meme images (eg. type 'slowclap.gif')."""
    if len(args) == 1:
        image_link = await _get_a_link(args[0])
        return "this one? {}".format(image_link)


async def _scan_for_triggers(bot, event):
    limit = 3
    count = 0
    text = event.text.lower()
    image_links = set()
    for trigger in _LOOKUP:
        pattern = r'\\b' + trigger + r'\.(jpg|png|gif|bmp)\\b'
        if re.search(pattern, text):
            image_links.add(_get_a_link(trigger))
            count += 1
            if count >= limit:
                break

    if image_links:
        for image_link in image_links:
            try:
                image_id = await bot.call_shared(
                    'image_validate_and_upload_single', image_link)
            except KeyError:
                logger.warning('image plugin not loaded - using legacy code')
                if re.match(r'^https?://gfycat.com', image_link):
                    image_link = re.sub(r'^https?://gfycat.com/',
                                        'https://thumbs.gfycat.com/',
                                        image_link) + '-size_restricted.gif'
                elif "imgur.com" in image_link:
                    image_link = image_link.replace(".gifv", ".gif")
                    image_link = image_link.replace(".webm", ".gif")
                image = bot.sync.get_sync_image(
                    url=image_link,
                )
                await image.download()
                image_data, filename = image.get_data()
                logger.debug("uploading: %s", filename)
                image_id = await bot.upload_image(image_data, filename=filename)
            await bot.coro_send_message(event.conv.id_, "", image_id=image_id)


def _load_all_the_things():
    plugin_dir = os.path.dirname(os.path.realpath(__file__))
    source_file = os.path.join(plugin_dir, "sauce.txt")
    with open(source_file) as file:
        content = file.read().splitlines()
    for line in content:
        parts = line.strip("|").split('|')
        if len(parts) == 2:
            triggers, images = parts
            triggers = [x.strip() for x in triggers.split(',')]
            images = [re.search(r'\((.*?)\)$', x).group(1)
                      for x in images.split(' ')]
            for trigger in triggers:
                if trigger in _LOOKUP:
                    _LOOKUP[trigger].extend(images)
                else:
                    _LOOKUP[trigger] = images
    logger.debug("%s trigger(s) loaded", len(_LOOKUP))


def _get_a_link(trigger):
    if trigger in _LOOKUP:
        return random.choice(_LOOKUP[trigger])
    return False
