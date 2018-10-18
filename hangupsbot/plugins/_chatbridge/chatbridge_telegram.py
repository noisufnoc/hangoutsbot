# pylint: skip-file
import asyncio
import json
import logging
import re

import aiohttp

from hangupsbot import plugins
from hangupsbot.webbridge import (
    WebFramework,
)


logger = logging.getLogger(__name__)


class BridgeInstance(WebFramework):
    def setup_plugin(self):
        self.plugin_name = "telegramBasic"

    async def _send_to_external_chat(self, config, event):
        conv_id = config["trigger"]
        external_ids = config["config.json"][self.configkey]

        user = event.passthru["original_request"]["user"]
        message = event.passthru["original_request"]["message"]

        if not message:
            message = ""

        # XXX: strip html, telegram parser seems buggy and too simplistic
        # only keep bold for emphasis
        # message = re.sub(r"</?b>", "", message)
        message = re.sub(r"</?i>", "", message)
        message = re.sub(r"</?pre>", "", message)

        # https://core.telegram.org/bots/api#html-style
        # prevent replacements on valid <b>...</b> <a href="...">...</a> tags
        message = re.sub(r"&(?!amp;)", "&amp;", message)
        message = re.sub(r"<(?!/b|b|a|/a)", "&lt;", message)
        message = re.sub(r"(?<!b|a|\")>", "&gt;", message)

        for eid in external_ids:
            await self.telegram_api_request(
                config["config.json"],
                "sendMessage",
                {
                    "chat_id": eid,
                    "text": self._format_message(message, user,
                                                 userwrap="HTML_BOLD"),
                    "parse_mode": "HTML",
                })

    def start_listening(self, bot):
        for configuration in self.configuration:
            plugins.start_asyncio_task(self.telegram_longpoll, configuration)

    async def telegram_longpoll(self, bot, configuration, CONNECT_TIMEOUT=90):
        BOT_API_KEY = configuration["bot_api_key"]

        connector = aiohttp.TCPConnector(verify_ssl=True)
        headers = {'content-type': 'application/x-www-form-urlencoded'}

        url = "https://api.telegram.org/bot{}/getUpdates".format(BOT_API_KEY)

        logger.info('Opening new long-polling request')

        max_offset = -1

        session = aiohttp.ClientSession(connector=connector)
        while True:
            try:
                data = {"timeout": 60}
                if max_offset:
                    data["offset"] = int(max_offset) + 1
                async with asyncio.wait_for(
                        session.post(url,
                                     data=data,
                                     headers=headers,
                                     connector=connector),
                        CONNECT_TIMEOUT) as res:
                    chunk = await res.content.read(1024 * 1024)
            except asyncio.TimeoutError:
                raise
            except asyncio.CancelledError:
                await session.close()
                raise

            if chunk:
                response = json.loads(chunk.decode("utf-8"))
                if len(response["result"]) > 0:
                    # results is a list of external chat events
                    for Update in response["result"]:
                        max_offset = Update["update_id"]
                        raw_message = Update["message"]

                        if str(raw_message["chat"]["id"]) in configuration[
                            self.configkey]:
                            for conv_id in configuration["hangouts"]:
                                user = raw_message["from"][
                                           "username"] + "@telegram"
                                image_id = None

                                if "text" in raw_message:
                                    message = raw_message["text"]

                                elif "photo" in raw_message:
                                    photo_path = (
                                        await self.telegram_api_getfilepath(
                                            configuration,
                                            raw_message["photo"][2]['file_id'],
                                        )
                                    )

                                    image_id = await bot.call_shared(
                                        "image_upload_single", photo_path)
                                    message = "sent a photo"

                                elif "sticker" in raw_message:
                                    photo_path = (
                                        await self.telegram_api_getfilepath(
                                            configuration,
                                            raw_message["sticker"]['file_id'],
                                        )
                                    )

                                    image_id = await bot.call_shared(
                                        "image_upload_single", photo_path)
                                    message = "sent {} sticker".format(
                                        raw_message["sticker"]['emoji'])

                                else:
                                    message = ("unrecognised telegram update: {"
                                               "}").format(raw_message)

                                await self._send_to_internal_chat(
                                    conv_id,
                                    message,
                                    {
                                        "source_user": user,
                                        "source_title": False,
                                    })

        logger.critical("long-polling terminated")

    async def telegram_api_request(self, configuration, method, data):
        connector = aiohttp.TCPConnector(verify_ssl=True)
        headers = {'content-type': 'application/x-www-form-urlencoded'}

        BOT_API_KEY = configuration["bot_api_key"]

        url = "https://api.telegram.org/bot{}/{}".format(BOT_API_KEY, method)

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers,
                                    connector=connector) as response:
                results = await response.text()

        return results

    async def telegram_api_getfilepath(self, configuration, file_id):
        results = await self.telegram_api_request(
            configuration,
            "getFile", {
                "file_id": file_id,
            })

        metadata = json.loads(results)

        BOT_API_KEY = configuration["bot_api_key"]
        source_url = "https://api.telegram.org/file/bot{}/{}".format(
            BOT_API_KEY, metadata["result"]["file_path"])

        return source_url


def _initialise(bot):
    BridgeInstance(bot, "telegram")
