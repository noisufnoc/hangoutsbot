import logging

from .exceptions import (
    AlreadySyncingError,
    NotSyncingError,
)
from .storage import (
    SLACKRTMS,
)


logger = logging.getLogger(__name__)


async def slacks(bot, event, *args):
    """list all configured slack teams

       usage: /bot slacks"""

    lines = ["**Configured Slack teams:**"]

    for slackrtm in SLACKRTMS:
        lines.append("* {}".format(slackrtm.name))

    await bot.coro_send_message(event.conv_id, "\n".join(lines))

async def slack_channels(bot, event, *args):
    """list all slack channels available in specified slack team

    usage: /bot slack_channels <teamname>"""

    if len(args) != 1:
        await bot.coro_send_message(event.conv_id, "specify slack team to get list of channels")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    await slackrtm.update_cache('channels')
    await slackrtm.update_cache('groups')

    lines = ['<b>Channels:</b>', '<b>Private groups</b>']

    for channel in slackrtm.conversations:
        if slackrtm.conversations[channel].get('is_archived', True):
            # filter dms and archived channels/groups
            continue
        line = '- %s: %s' % (channel, slackrtm.get_chatname(channel))
        if channel[0] == 'C':
            lines.insert(1, line)
        else:
            lines.append(line)

    await bot.coro_send_message(event.conv_id, "\n".join(lines))


async def slack_users(bot, event, *args):
    """list all slack channels available in specified slack team

        usage: /bot slack_users <team> <channel>"""

    if len(args) != 2:
        await bot.coro_send_message(event.conv_id, "specify slack team and channel")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    await slackrtm.update_cache('channels')
    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    lines = ["**Slack users in channel {}**:".format(channelname)]

    users = await slackrtm.get_channel_users(channelid)
    for username, realname in sorted(users.items()):
        lines.append("* {} {}".format(username, realname))

    await bot.coro_send_message(event.conv_id, "\n".join(lines))


async def slack_listsyncs(bot, event, *args):
    """list current conversations we are syncing

    usage: /bot slack_listsyncs"""

    lines = ["**Currently synced:**"]

    for slackrtm in SLACKRTMS:
        for sync in slackrtm.syncs:
            hangoutname = bot.conversations.get_name(sync.hangoutid, 'unknown')
            lines.append("{} : {} ({})\n  {} ({})\n  {}".format(
                slackrtm.name,
                slackrtm.get_chatname(sync.channelid),
                sync.channelid,
                hangoutname,
                sync.hangoutid,
                sync.get_printable_options()))

    await bot.coro_send_message(event.conv_id, "\n".join(lines))


async def slack_syncto(bot, event, *args):
    """start syncing the current hangout to a given slack team/channel

    usage: /bot slack_syncto <teamname> <channelid>"""

    if len(args) >= 3:
        honame = ' '.join(args[2:])
    else:
        if len(args) != 2:
            await bot.coro_send_message(event.conv_id, "specify slack team and channel")
            return
        honame = bot.conversations.get_name(event.conv)

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    try:
        slackrtm.config_syncto(channelid, event.conv.id_, honame)
    except AlreadySyncingError:
        await bot.coro_send_message(event.conv_id, "hangout already synced with {} : {}".format(slackname, channelname))
        return

    await bot.coro_send_message(event.conv_id, "this hangout synced with {} : {}".format(slackname, channelname))


async def slack_disconnect(bot, event, *args):
    """stop syncing the current hangout with given slack team and channel

    usage: /bot slack_disconnect <teamname> <channelid>"""

    if len(args) != 2:
        await bot.coro_send_message(event.conv_id, "specify slack team and channel")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    try:
        slackrtm.config_disconnect(channelid, event.conv.id_)
    except NotSyncingError:
        await bot.coro_send_message(event.conv_id, "current hangout not previously synced with {} : {}".format(slackname, channelname))
        return

    await bot.coro_send_message(event.conv_id, "this hangout disconnected from {} : {}".format(slackname, channelname))


async def slack_setsyncjoinmsgs(bot, event, *args):
    """enable or disable sending notifications any time someone joins/leaves/adds/invites/kicks

    usage: /bot slack_setsyncjoinmsgs <teamname> <channelid> {true|false}"""

    if len(args) != 3:
        await bot.coro_send_message(event.conv_id, "specify exactly three parameters: slack team, slack channel, and \"true\" or \"false\"")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    flag = args[2]
    if flag.lower() in ['true', 'on', 'y', 'yes']:
        flag = True
    elif flag.lower() in ['false', 'off', 'n', 'no']:
        flag = False
    else:
        await bot.coro_send_message(event.conv_id, "cannot interpret {} as either \"true\" or \"false\"".format(flag))
        return

    try:
        slackrtm.config_setsyncjoinmsgs(channelid, event.conv.id_, flag)
    except NotSyncingError:
        await bot.coro_send_message(event.conv_id, "current hangout not previously synced with {} : {}".format(slackname, channelname))
        return

    if flag:
        await bot.coro_send_message(event.conv_id, "membership changes will be synced with {} : {}".format(slackname, channelname))
    else:
        await bot.coro_send_message(event.conv_id, "membership changes will no longer be synced with {} : {}".format(slackname, channelname))


async def slack_sethotag(bot, event, *args):
    """sets the identity of current hangout when syncing this conversation
    (default: title of this hangout when sync was set up, use 'none' to disable tagging)

    usage: /bot slack_hotag <teamname> <channelid> {<tag>|none}"""

    if len(args) < 3:
        await bot.coro_send_message(event.conv_id, "specify: slack team, slack channel, and a tag (\"none\" to disable)")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    if len(args) == 3:
        if args[2].lower() == 'none':
            hotag = None
        elif args[2].lower() == "true":
            hotag = True
        else:
            hotag = args[2]
    else:
        hotag = ' '.join(args[2:])

    try:
        slackrtm.config_sethotag(channelid, event.conv.id_, hotag)
    except NotSyncingError:
        await bot.coro_send_message(event.conv_id, "current hangout not previously synced with {} : {}".format(slackname, channelname))
        return

    if hotag is True:
        await bot.coro_send_message(event.conv_id, "messages synced from this hangout will be tagged with chatbridge-compatible channel title")
    elif hotag:
        await bot.coro_send_message(event.conv_id, "messages synced from this hangout will be tagged \"{}\" in {} : {}".format(hotag, slackname, channelname))
    else:
        await bot.coro_send_message(event.conv_id, "messages synced from this hangout will not be tagged in {} : {}".format(slackname, channelname))


async def slack_setslacktag(bot, event, *args):
    """sets the identity of the specified slack conversation synced to the current hangout
    (default: name of the slack team, use 'none' to disable tagging)

    usage: /bot slack_slacktag <teamname> <channelid> {<tag>|none}"""

    if len(args) < 3:
        await bot.coro_send_message(event.conv_id, "specify: slack team, slack channel, and a tag (\"none\" to disable)")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    if len(args) == 3:
        if args[2].lower() == 'none':
            slacktag = None
        elif args[2].lower() == "true":
            slacktag = True
        else:
            slacktag = args[2]
    else:
        slacktag = ' '.join(args[2:])

    try:
        slackrtm.config_setslacktag(channelid, event.conv.id_, slacktag)
    except NotSyncingError:
        await bot.coro_send_message(event.conv_id, "current hangout not previously synced with {} : {}".format(slackname, channelname))
        return

    if slacktag is True:
        await bot.coro_send_message(event.conv_id, "messages from slack {} : {} will be tagged with chatbridge-compatible channel title".format(slackname, channelname))
    elif slacktag:
        await bot.coro_send_message(event.conv_id, "messages from slack {} : {} will be tagged with \"{}\" in this hangout".format(slackname, channelname, slacktag))
    else:
        await bot.coro_send_message(event.conv_id, "messages from slack {} : {} will not be tagged in this hangout".format(slackname, channelname))


async def slack_showslackrealnames(bot, event, *args):
    """enable/disable display of realnames instead of usernames in messages synced from slack (default: disabled)

    usage: /bot slack_showslackrealnames <teamname> <channelid> {true|false}"""

    if len(args) != 3:
        await bot.coro_send_message(event.conv_id, "specify exactly three parameters: slack team, slack channel, and \"true\" or \"false\"")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    flag = args[2]
    if flag.lower() in ['true', 'on', 'y', 'yes']:
        flag = True
    elif flag.lower() in ['false', 'off', 'n', 'no']:
        flag = False
    else:
        await bot.coro_send_message(event.conv_id, "cannot interpret {} as either \"true\" or \"false\"".format(flag))
        return

    try:
        slackrtm.config_showslackrealnames(channelid, event.conv.id_, flag)
    except NotSyncingError:
        await bot.coro_send_message(event.conv_id, "current hangout not previously synced with {} : {}".format(slackname, channelname))
        return

    if flag:
        await bot.coro_send_message(event.conv_id, "real names will be displayed when syncing messages from slack {} : {}".format(slackname, channelname))
    else:
        await bot.coro_send_message(event.conv_id, "user names will be displayed when syncing messages from slack {} : {}".format(slackname, channelname))


async def slack_showhorealnames(bot, event, *args):
    """display real names and/or nicknames in messages synced from hangouts (default: real)

    usage: /bot slack_showhorealnames <teamname> <channelid> {real|nick|both}"""

    if len(args) != 3:
        await bot.coro_send_message(event.conv_id, "specify exactly three parameters: slack team, slack channel, and \"real\"/\"nick\"/\"both\"")
        return

    slackname = args[0]
    slackrtm = None
    for slackrtm in SLACKRTMS:
        if slackrtm.name == slackname:
            break
    if not slackrtm:
        await bot.coro_send_message(event.conv_id, "there is no slack team with name **{}**, use _/bot slacks_ to list all teams".format(slackname))
        return

    channelid = args[1]
    channelname = slackrtm.get_chatname(channelid)
    if not channelname:
        await bot.coro_send_message(
            event.conv_id,
            "there is no channel with name **{0}** in **{1}**, use _/bot slack_channels {1}_ to list all channels".format(channelid, slackname))
        return

    flag = args[2]
    if flag not in ['real', 'nick', 'both']:
        await bot.coro_send_message(event.conv_id, "cannot interpret {} as one of \"real\", \"nick\" or \"both\"".format(flag))
        return

    try:
        slackrtm.config_showhorealnames(channelid, event.conv.id_, flag)
    except NotSyncingError:
        await bot.coro_send_message(event.conv_id, "current hangout not previously synced with {} : {}".format(slackname, channelname))
        return

    await bot.coro_send_message(event.conv_id, "{} names will be displayed when syncing messages from slack {} : {}".format(flag, slackname, channelname))
