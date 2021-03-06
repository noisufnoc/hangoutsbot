"""Sync plugin for the Hangoutsbot with Telegram

rewrite: das7pad@outlook.com
"""
# pylint: disable=wrong-import-position, wrong-import-order

import asyncio
import logging

import telepot.exception

from hangupsbot import (
    commands,
    plugins,
)
from hangupsbot.sync.parser import get_formatted


# reload the other modules
for _path_ in ('user', 'message', 'commands_tg', 'parsers', 'core'):
    plugins.load_module('plugins.telesync.' + _path_)

from .core import (
    TelegramBot,
    POOLS,
    User,
)


HELP = {
    'telesync': _('usage:\n{bot_cmd} telesync add <telegram chat id>\n'
                  '    sync the current chat with the given telegram chat\n'
                  '{bot_cmd} telesync remove <"all"|<telegram chat ids>>\n'
                  '    disable the sync to previously configured telegram chats'
                  ' - "all" may remove all syncs, space separated chat ids may'
                  ' remove only the specified chats\n'
                  '{bot_cmd} telesync show\n    show current sync targets\n'
                  'add "channel" to a request to setup a channel sync, which '
                  'does not sync the senders\' name'),

    'telesync_set_token': _('usage:\n{bot_cmd} telesync_set_token <api_key>\n'
                            'update the api key for the telesync plugin'),
}

logger = logging.getLogger(__name__)


async def _initialise(bot):
    """init bot for telesync, create and start a TelegramBot, register handler

    setup config and memory entries, create TelegramBot and initialise it before
    starting the message loop, add commands to the hangupsbot, register handlers
    for HO-messages and sync tasks

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance

    Raises:
        RuntimeError: can not connect to the Telegram API
    """
    setup_config(bot)

    plugins.register_aiohttp_session(POOLS['default'])
    plugins.register_admin_command([
        'telesync_set_token',
    ])
    if not bot.config.get_by_path(['telesync', 'enabled']):
        return

    plugins.register_admin_command([
        'telesync',
    ])

    bot.tg_bot = TelegramBot(bot)
    if not await bot.tg_bot.can_log_in(retry=False):
        raise RuntimeError('Can not connect to the Telegram API')

    if __name__ in plugins.SENTINELS:
        # cleanup after a pluginreload
        plugins.SENTINELS.pop(__name__, None)

    plugins.register_help(HELP)

    plugins.tracking.current['metadata']['identifier'] = 'Telegram'
    bot.sync.register_profile_sync('telesync', '/syncprofile', label='Telegram')

    setup_memory(bot)

    plugins.register_sync_handler(_handle_message, 'allmessages')
    plugins.register_sync_handler(_handle_membership_change, 'membership')
    plugins.register_sync_handler(_handle_conv_user, 'conv_user')
    plugins.register_sync_handler(_handle_user_kick, 'user_kick')
    plugins.register_sync_handler(_handle_profilesync, 'profilesync')

    plugins.start_asyncio_task(bot.tg_bot.start)


def setup_config(bot):
    """register all attributes in config

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
    """
    default_config = {
        'conversations': {
            'telesync': {
                # images are always displayed in full-width in Telegram
                # resize does not result in a smaller image
                **{'sync_reply_size_%s' % key: 0
                   for key in ('gif', 'photo', 'sticker', 'video')},
                **{'sync_size_%s' % key: 0
                   for key in ('gif', 'photo', 'sticker', 'video')},
            },
        },
        'telesync': {
            # telegram-admin ids
            'admins': [],

            # from botfather
            'api_key': 'PUT_YOUR_TELEGRAM_API_KEY_HERE',

            # no spam from commands if permissions/chat types do not match
            'be_quiet': False,

            # enable the sync
            'enabled': False,

            # number of repeated low level-errors until the message loop dies
            'message_loop_retries': 5,

            # remind the user on the pending sync every n hours
            'profilesync_reminder': 36,

            # interval in hours to update the user profiles
            'profile_update_interval': 5,

            # check the membership data
            'enable_membership_check': 0,

            # interval in hours to check the membership data per chat
            # additionally, this feature must be enabled in the config:
            # - globally:
            #     "telesync"->"enable_membership_check" = 1
            # - or per chat:
            #     for example for the chat with id 123:
            #     "conversations"->"telesync:123"->"enable_membership_check" = 1
            'membership_check_interval': 5,

            # html message a user receives on /start
            # available keys:
            # name (user who triggered /start), botusername, botname
            'start_message': _('Hello {name}! You are talking to @{botusername}'
                               ', known as {botname}.'),

            # id of a chat used to alert mods about important events
            'mod_chat': None,

            # delay between location updates in seconds
            'location_sharing_update_delay': 30,

            # remove the edit-tag from live-locations
            'location_sharing_remove_edit_tag': True,

            # retry request that failed due to a server error n times
            'request_retry_limit': 5,
        },
        # new chat users are unrestricted by default, possible values are:
        # messages, media, sticker, websites, sticker+websites
        'restrict_users': False,
    }
    bot.config.set_defaults(default_config)

    if not bot.config.get_by_path(['telesync', 'api_key']):
        bot.config.set_by_path(['telesync', 'enabled'], False)

    bot.config.save()


def setup_memory(bot):
    """create all dicts in memory

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
    """
    default_memory = {
        'telesync': {
            # tg-channel -> ho
            'channel2ho': {},

            # ho -> tg
            'ho2tg': {},

            # tg-chat {private, group, supergroup} -> ho
            'tg2ho': {},

            # sub dicts for each chat, store users in each chat
            'chat_data': {},

            # sub dicts for each user, store a Telegram API User and its photo
            'user_data': {},

            # track migration
            'version': 0,
        },
    }
    bot.memory.validate(default_memory)

    def _migrate_20170609():
        """split 1:1 chat-sync, cleanup profilesync"""
        telesync_data = bot.memory['telesync']
        if telesync_data['version'] >= 20170609:
            return
        for sync in ('ho2tg', 'tg2ho', 'channel2ho'):
            for source, target in telesync_data[sync].items():
                telesync_data[sync][source] = [target]

        profilesync = bot.memory['profilesync']
        for user_id, data in profilesync.pop('tg2ho', {}).items():
            if isinstance(data, str):
                # pre v2.8
                profilesync['telesync']['2ho'][user_id] = data
                profilesync['telesync']['ho2'][data] = user_id
                continue
            # v2.8 -> v3.0
            key = 'ho_id' if 'ho_id' in data else 'chat_id'
            profilesync['telesync']['2ho'][user_id] = data[key]
            profilesync['telesync']['ho2'][data[key]] = user_id
        telesync_data['version'] = 20170609

    def _cleanup20180919():
        """drop the fall back user from the users and chats user list"""
        telesync_data = bot.memory['telesync']
        if telesync_data['version'] >= 20180919:
            return

        telesync_data['user_data'].pop('0', None)

        for chat in telesync_data['chat_data'].values():
            if 'user' not in chat:
                continue
            chat['user'].pop('0', None)

        telesync_data['version'] = 20180919

    def _cleanup20181112():
        """drop the last_seen value"""
        telesync_data = bot.memory['telesync']
        if telesync_data['version'] >= 20181112:
            return

        for user in telesync_data['user_data'].values():
            if 'last_seen' not in user:
                continue
            del user['last_seen']

        telesync_data['version'] = 20181112

    def _cleanup20181122():
        """drop the last_update value"""
        telesync_data = bot.memory['telesync']
        if telesync_data['version'] >= 20181122:
            return

        for user in telesync_data['user_data'].values():
            if 'last_update' not in user:
                continue
            del user['last_update']

        telesync_data['version'] = 20181122

    _migrate_20170609()
    _cleanup20180919()
    _cleanup20181112()
    _cleanup20181122()
    bot.memory.save()


def telesync(bot, event, *args):
    """set a telegram chat as sync target for the current ho

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message wrapper
        args (str): additional words passed to the command

    Returns:
        str: a status message

    Raises:
        commands.Help: no sub command such as `remove`, `add` or `show` provided
    """

    def _set_message_format(channel_id, remove_name=True):
        """remove or add the username from a forwarded message to a channel

        Args:
            channel_id (str): target conversation identifier
            remove_name (bool): defaults to True
        """
        channel_tag = 'telesync:' + channel_id
        config_path = ['conversations', channel_tag, 'sync_format_message']
        if remove_name:
            if not channel:
                return
            bot_message_format = bot.config['sync_format_message_bot']
            bot.config.set_by_path(config_path, bot_message_format)
        elif bot.config.exists(config_path):
            bot.config.pop_by_path(config_path)

    def _add():
        """add the given telegram chat ids to the current convs' sync targets"""
        tg_chat_id = args[0]

        ho2tg = bot.memory.get_by_path(['telesync', 'ho2tg'])
        targets = ho2tg.setdefault(ho_chat_id, [])
        if tg_chat_id in targets:
            lines.append(_('HO -> TG: "%s" is already target') % tg_chat_id)
        else:
            targets.append(tg_chat_id)
            _set_message_format(tg_chat_id)
            lines.append(_('HO -> TG: target "%s" added') % tg_chat_id)

        if one_way:
            return

        targets = tg2ho.setdefault(tg_chat_id, [])
        if ho_chat_id in targets:
            lines.append(
                (_('HO <- TG: channel sync from "%s" already set') if channel
                 else _('HO <- TG: sync from "%s" already set')) % tg_chat_id)
        else:
            targets.append(ho_chat_id)
            lines.append(
                (_('HO <- TG: channel sync from "%s" added') if channel
                 else _('HO <- TG: sync from "%s" added')) % tg_chat_id)

    def _remove():
        """remove the given or all chat ids from the current convs' targets"""
        path = ['telesync', 'ho2tg', ho_chat_id]

        tg_chat_ids = (bot.memory.get_by_path(path) if bot.memory.exists(path)
                       else ())
        remove = tuple(tg_chat_ids) if args[0] == _('all') else args
        for tg_chat_id in remove:
            if tg_chat_id in tg_chat_ids:
                tg_chat_ids.remove(tg_chat_id)
                _set_message_format(tg_chat_id, False)
                lines.append(_('HO -> TG: target "%s" removed') % tg_chat_id)
            else:
                lines.append(_('HO -> TG: target "%s" not set') % tg_chat_id)

            if one_way:
                continue

            if tg_chat_id in tg2ho and ho_chat_id in tg2ho[tg_chat_id]:
                tg2ho[tg_chat_id].remove(ho_chat_id)
                lines.append(
                    (_('HO <- TG: channel sync removed from "%s"') if channel
                     else _('HO <- TG: sync removed from "%s"')) % tg_chat_id)
            else:
                lines.append(
                    (_('HO <- TG: channel sync not set from "%s"') if channel
                     else _('HO <- TG: sync not set from "%s"')) % tg_chat_id)

    def _show():
        """list the current convs' sync targets"""
        path = ['telesync', 'ho2tg', ho_chat_id]
        text = ('"%s"' % '", "'.join(bot.memory.get_by_path(path))
                if bot.memory.exists(path) and bot.memory.get_by_path(path)
                else _('no chats'))
        lines.append(_('syncing "{conv_id}" to {tg_ids}').format(
            conv_id=ho_chat_id, tg_ids=text))

    ho_chat_id = event.conv_id
    lines = []
    if args:
        cmd, *args = args
    else:
        cmd = _('show')
    one_way = _('oneway') in args
    channel = _('channel') in args
    args = (tuple(set(args) - {_('oneway'), _('channel')})
            if one_way or channel else args)

    if args:
        tg2ho = bot.memory.get_by_path(['telesync', ('channel2ho' if channel
                                                     else 'tg2ho')])
        if cmd == _('remove'):
            _remove()
        elif cmd == _('add'):
            _add()

        bot.memory.save()
        bot.config.save()

    if cmd == _('show'):
        _show()

    if not lines:
        # no sub-command was specified
        raise commands.Help()
    return '\n'.join(lines)


async def telesync_set_token(bot, event, *args):
    """sets the api key for the telesync bot

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): may contain the api key as first tuple entry

    Returns:
        str: command output

    Raises:
        commands.Help: no api token specified in the args
    """
    if len(args) != 1:
        raise commands.Help('specify your token')

    api_key = (args[0][1:-1]
               if (args[0][0] == args[0][-1] and args[0][0] in ('"', "'"))
               else args[0])

    api_key_path = ['telesync', 'api_key']
    backup = bot.config.get_by_path(api_key_path)
    bot.config.set_by_path(api_key_path, api_key)

    # test the api-key first:
    if not await TelegramBot(bot).can_log_in(retry=False):
        bot.config.set_by_path(api_key_path, backup)
        return 'invalid Telegram API Key'

    bot.config.set_by_path(['telesync', 'enabled'], True)
    bot.config.save()
    asyncio.ensure_future(
        commands.command.run(bot, event, 'pluginreload', __name__))
    return 'Telegram API Key set.'


async def _handle_profilesync(bot, platform, remote_user, conv_1on1,
                              split_1on1s):
    """finish profile sync and set a 1on1 sync if requested

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        platform (str): identifier for the platform which started the sync
        remote_user (str): telegram user id
        conv_1on1 (str): users 1on1 chat with the bot
        split_1on1s (bool): toggle to sync the private chats
    """
    if platform != 'telesync':
        return
    tg_chat_id = remote_user

    path_tg2ho = ['telesync', 'tg2ho', tg_chat_id]
    path_ho2tg = ['telesync', 'ho2tg', conv_1on1]
    if split_1on1s:
        try:
            bot.memory.pop_by_path(path_tg2ho)
            bot.memory.pop_by_path(path_ho2tg)
        except KeyError:
            pass
        text = _('<i>Your profiles are connected and you will not receive my '
                 'messages in Telegram</i>')
        bot.tg_bot.send_html(tg_chat_id, text)

    else:
        # chat sync
        bot.memory.set_by_path(path_tg2ho, [conv_1on1])
        bot.memory.set_by_path(path_ho2tg, [tg_chat_id])
        text = _('<i>Your profiles are connected and you will receive my '
                 'messages in Telegram as well.</i>')

    bot.memory.save()
    await bot.coro_send_message(conv_1on1, text)


async def _handle_user_kick(bot, conv_id, user):
    """kick a user from a given conversation

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        conv_id (str): conversation identifier
        user (hangupsbot.sync.user.SyncUser): the user to be kicked

    Returns:
        mixed: None: ignored, False: kick failed, True: kicked, 'whitelisted'
    """
    if not isinstance(user, User):
        # not a telesync user
        return None

    # tracker for log entries
    tracker = object()

    tg_chat_id = user.identifier.split(':', 1)[1]
    logger.info(
        'user kick request %s: user %s, chat %s',
        id(tracker), user.usr_id, tg_chat_id
    )

    if user.usr_id in bot.tg_bot.config('admins'):
        logger.info(
            'user kick request %s: admin is whitelisted',
            id(tracker)
        )
        return 'whitelisted'

    path = ['telesync', 'ho2tg', conv_id]

    kicked = False
    try:
        tg_chat_ids = bot.memory.get_by_path(path)
        tg_chat_ids.index(tg_chat_id)

        resp = await bot.tg_bot.getChat(tg_chat_id)
        if not resp.get('all_members_are_administrators'):
            kicked = await bot.tg_bot.kickChatMember(tg_chat_id, user.usr_id)
        else:
            kicked = False
            logger.info(
                'user kick request %s: failed: all members are administrators',
                id(tracker)
            )
    except (KeyError, ValueError):
        # no sync set for this conversation
        logger.info(
            'user kick request %s: deleted sync: HO %s -> TG %s',
            id(tracker), conv_id, tg_chat_id,
        )

    except telepot.exception.UnauthorizedError:
        logger.warning(
            'user kick request %s: bot is not authorized to kick',
            id(tracker)
        )

    except telepot.exception.TelegramError as err:
        logger.error(
            'user kick request %s: low level error %r',
            id(tracker), err
        )

    if not kicked:
        return False

    # send a membership event as telegram does not broadcast one for bot kicks
    path_chat = ['telesync', 'chat_data', tg_chat_id]
    path_user = ['telesync', 'user_data']
    msg = {
        'chat': bot.memory.get_by_path(path_chat),
        'left_chat_member': bot.memory.get_by_path(path_user + [user.usr_id]),
        'from': bot.memory.get_by_path(path_user + [bot.tg_bot.user.usr_id]),
        'message_id': 0,
    }
    await bot.tg_bot._handle(msg)  # pylint:disable=protected-access
    return True


async def _handle_conv_user(bot, conv_id, profilesync_only):
    """get all telegram user for this conv_id

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        conv_id (str): conversation identifier
        profilesync_only (bool): only include users synced to a G+ profile

    Returns:
        list[user.User]: users participating in this conversation
    """
    path = ['telesync', 'ho2tg', conv_id]
    tg_bot = bot.tg_bot
    if not bot.memory.exists(path):
        # no sync is set
        return []

    requests = []
    for chat_id in bot.memory.get_by_path(path):
        path = ['telesync', 'chat_data', chat_id, 'user']
        if not bot.memory.exists(path):
            continue
        requests.extend((user_id, chat_id)
                        for user_id in bot.memory.get_by_path(path))

    if not requests:
        return []

    all_users = await asyncio.gather(*[tg_bot.get_tg_user(user_id=user_id,
                                                          chat_id=chat_id,
                                                          gpluslink=False)
                                       for user_id, chat_id in requests])

    return [user for user in all_users
            if not profilesync_only or user.id_.chat_id != 'sync']


async def _send_media(*, tg_bot, event, tg_chat_id, chat_tag,
                      image, image_data, filename):
    """send the resized image/video of an event to a given telegram chat

    Args:
        tg_bot (TelegramBot): the running instance
        event (hangupsbot.sync.event.SyncEvent): a message wrapper
        tg_chat_id (str): telegram chat identifier
        chat_tag (str): identifier to receive config entries of the chat
        image (hangupsbot.sync.image.SyncImage): media data wrapper
        image_data (io.BytesIO): the resized image data
        filename (str): file name of the image

    Returns:
        tuple[bool, str]: True if the image sending failed, otherwise False
                          and additional text that did not fit into the
                           caption
    """
    caption = event.get_formatted_text(
        style='html_flat', add_photo_tag=True, conv_id=chat_tag,
    )
    if len(caption) > 4095:
        # we got to parse the text once again
        raw_caption = event.get_formatted_text(
            style='internal', add_photo_tag=True, conv_id=chat_tag,
        )
        caption, next_part = raw_caption[:4095].rsplit('\n', 1)
        caption = get_formatted(caption, 'html_flat', internal_source=True)
    else:
        next_part = None

    logger.info(
        'sending media %s: org size: %s',
        id(image), len(image_data.getbuffer())
    )
    try:
        if filename.endswith(('gif', 'mp4', 'avi')):
            # handle animated
            await tg_bot.sendDocument(tg_chat_id, (filename, image_data),
                                      caption=caption,
                                      parse_mode='HTML')
        else:
            await tg_bot.sendPhoto(tg_chat_id, (filename, image_data),
                                   caption=caption,
                                   parse_mode='HTML')
    except telepot.exception.TelegramError as err:
        if 'PHOTO_SAVE_FILE_INVALID' in repr(err):
            # probably to big image
            image_data.close()
            image_data, filename = image.get_data(limit=500)
            try:
                await tg_bot.sendPhoto(tg_chat_id,
                                       (filename, image_data),
                                       caption=caption)
            except telepot.exception.TelegramError as err:
                logger.error(
                    'sending media %s: error sending in 500px: %r',
                    id(image), err
                )
            else:
                # force no tag as we already send it
                return False, next_part
        else:
            logger.error(
                'sending media %s: low level error: %r',
                id(image), err
            )

        # force a tag as we could not send it
        return True, next_part
    finally:
        image_data.close()

    # force no tag as we already send it
    return False, next_part


async def _handle_message(bot, event):
    """forward message/photos from any platform to Telegram

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.sync.event.SyncEvent): a message wrapper
    """
    if not bot.memory.exists(['telesync', 'ho2tg', event.conv_id]):
        # no sync is set
        return

    tg_bot = bot.tg_bot

    tg_chat_ids = bot.memory.get_by_path(['telesync', 'ho2tg', event.conv_id])
    for tg_chat_id in tg_chat_ids:
        chat_tag = 'telesync:%s' % tg_chat_id

        if chat_tag in event.previous_targets:
            # event from telesync
            continue
        event.previous_targets.add(chat_tag)

        image, image_data, filename = await event.get_image(chat_tag)

        has_text = (len(event.conv_event.segments) or event.reply is not None or
                    event.edited or image_data is None)

        logger.debug(
            'Forwarding %s%s%s from HO: %s to TG: %s',
            'Text' if has_text else '',
            ' and ' if has_text and image_data is not None else '',
            'Media' if image_data is not None else '',
            event.conv_id, tg_chat_id)

        if image_data is not None:
            add_tag, text = await _send_media(
                tg_bot=tg_bot, event=event, tg_chat_id=tg_chat_id,
                chat_tag=chat_tag, image=image, image_data=image_data,
                filename=filename)
            has_text = text
        else:
            # let the event decide whether it is necessary to add a tag
            add_tag, text = None, None

        if has_text:
            text = event.get_formatted_text(
                style='internal', add_photo_tag=add_tag, conv_id=chat_tag,
                text=text)
            tg_bot.send_html(tg_chat_id, text)


async def _handle_membership_change(bot, event):
    """notify a configured tg-chat about a membership change

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.sync.event.SyncEventMembership): a data wrapper
    """
    if not bot.memory.exists(['telesync', 'ho2tg', event.conv_id]):
        # no sync is set
        return

    tg_chat_ids = bot.memory.get_by_path(['telesync', 'ho2tg', event.conv_id])
    for tg_chat_id in tg_chat_ids:
        chat_tag = 'telesync:%s' % tg_chat_id

        if chat_tag in event.previous_targets:
            # event from telesync
            return
        event.previous_targets.add(chat_tag)

        text = event.get_formatted_text(style='internal', conv_id=chat_tag)
        if text is None:
            return

        bot.tg_bot.send_html(tg_chat_id, text)
