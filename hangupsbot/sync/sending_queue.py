"""keep the sequence for async tasks"""
__author__ = 'das7pad@outlook.com'

import asyncio
import functools
import logging

from hangupsbot.utils.cache import Cache
from . import DEFAULT_CONFIG


logger = logging.getLogger(__name__)

SENDING_BLOCK_RETRY_DELAY = 5  # seconds


class Status:
    """Blocker for scheduled tasks"""
    __slots__ = ('_event', '_status')

    FAILED = False
    SUCCESS = True

    def __init__(self):
        self._event = asyncio.Event()
        self._status = None

    def set(self, status):
        self._status = status
        self._event.set()

    async def wait(self):
        await self._event.wait()
        return self._status

    def __await__(self):
        return self.wait().__await__()


class Queue(list):
    """a queue to schedule synced calls and remain the sequence in processing

    Args:
        group (str): identifier for a platform
        func (callable): will be called with the scheduled args/kwargs
    """
    __slots__ = ('_logger', '_func', '_group', '_lock', '_instance_block')
    _loop = asyncio.get_event_loop()
    _blocks = {'__global__': False}
    _pending_tasks = {}

    def __init__(self, group, func=None):
        super().__init__()
        self._logger = logging.getLogger('%s.%s' % (__name__, group))
        self._func = func
        self._group = group
        self._lock = asyncio.Lock(loop=self._loop)
        self._instance_block = False

        # do not overwrite an active block
        self._blocks.setdefault(group, False)
        # do not reset the counter
        self._pending_tasks.setdefault(group, 0)

    @property
    def _blocked(self):
        """check for a global, local or instance sending block

        Returns:
            bool: True if any block got applied otherwise False
        """
        return (self._instance_block
                or self._blocks['__global__']
                or self._blocks[self._group])

    @property
    def _running(self):
        """check if a queue processor is already running

        Returns:
            bool: True if a queue processor is running, otherwise False
        """
        return self._lock.locked()

    def schedule(self, *args, **kwargs):
        """queue an item with the given args/kwargs for the coroutine

        Returns:
            Status: the scheduled task sets a boolean result after
            being processed in the Status
            `await queue.schedule(...)` returns True on success otherwise False
        """
        self._pending_tasks[self._group] += 1
        status = Status()
        self.append((status, self._blocked, args, kwargs))
        asyncio.ensure_future(self._process(), loop=self._loop)

        self._logger.debug('%s: scheduled args=%r kwargs=%r',
                           id(status), args, kwargs)
        return status

    async def single_stop(self, timeout):
        """apply a submit-block to the instance and wait for pending tasks

        the instance-block is permanent, use with care

        Args:
            timeout (int): time in seconds to wait for pending tasks to complete
        """
        self._instance_block = True
        while timeout > 0:
            if not self and not self._running:
                break
            timeout -= 0.1
            await asyncio.sleep(0.1)
        else:
            self._logger.warning('%s task%s did not finished',
                                 len(self),
                                 ('s' if self._pending_tasks[self._group] > 1
                                  else ''))

    async def local_stop(self, timeout):
        """apply a submit-block to all group members and wait for pending tasks

        stop a group without a reference to an instance of a group member:
        Queue(group).local_stop()

        Args:
            timeout (int): time in seconds to wait for pending tasks to complete
        """
        self._blocks[self._group] = True
        if self._pending_tasks[self._group] > 0:
            self._logger.info('waiting for %s tasks',
                              self._pending_tasks[self._group])
        while timeout > 0:
            if self._pending_tasks[self._group] <= 0:
                break
            timeout -= 0.1
            await asyncio.sleep(0.1)
        else:
            self._logger.warning('%s task%s did not finished',
                                 self._pending_tasks[self._group],
                                 ('s' if self._pending_tasks[self._group] > 1
                                  else ''))

    @classmethod
    async def global_stop(cls, timeout):
        """apply a submit-block to all queues and wait for pending tasks

        Args:
            timeout (int): time in seconds to wait for pending tasks to complete
        """
        cls._blocks['__global__'] = True
        pending = {group: tasks
                   for group, tasks in cls._pending_tasks.items()
                   if tasks > 0}
        if not pending:
            return

        logger.info('global stop: waiting for %s tasks',
                    sum(pending.values()))
        await asyncio.gather(*[Queue(group, None).local_stop(timeout)
                               for group in pending])

    @classmethod
    def release_block(cls, group=None):
        """unset a sending block

        Args:
            group (str): platform identifier or None to release globally
        """
        if group is None:
            cls._blocks.clear()
            cls._blocks['__global__'] = False
            cls._pending_tasks.clear()
        else:
            cls._blocks[group] = False
            cls._pending_tasks[group] = 0

    async def _process(self):
        """process the queue and await the result on each call"""
        if not self:
            # all tasks are handled
            return

        if self._running:
            # only one queue processor is allowed
            return

        async with self._lock:
            try:
                status, blocked, args, kwargs = self.pop(0)
                if blocked:
                    delay = 0
                    while delay < SENDING_BLOCK_RETRY_DELAY:
                        if not self._blocked:
                            # block got released
                            break
                        await asyncio.sleep(.1)
                        delay += .1
                    else:
                        status.set(Status.FAILED)
                        self._log_context(status, args, kwargs)
                        self._logger.warning('%s: block timeout reached',
                                             id(status))
                        return

                self._logger.debug('%s: sending', id(status))
                try:
                    result = await asyncio.shield(self._send(args, kwargs))

                except asyncio.CancelledError:
                    self._logger.debug('%s: cancelled', id(status))
                except Exception:  # pylint: disable=broad-except
                    status.set(Status.FAILED)
                    self._log_context(status, args, kwargs)
                    self._logger.exception('%s: sending failed',
                                           id(status))

                else:
                    # ignore the return value in case it was not set
                    success = True if result is None else result
                    status.set(Status.SUCCESS if success else Status.FAILED)

                self._logger.debug('%s: sent', id(status))
            finally:
                self._pending_tasks[self._group] -= 1
                asyncio.ensure_future(self._process(), loop=self._loop)

    def _log_context(self, status, args, kwargs):
        """Add context to another logging message

        Args:
            status (Status): the status of a queue item
            args (list): queue function args
            kwargs (dict): queue function kwargs
        """
        if self._logger.isEnabledFor(logging.DEBUG):
            # already logged
            return
        self._logger.info('%s: args=%r kwargs=%r',
                          id(status), args, kwargs)

    async def _send(self, args, kwargs):
        """perform the sending of the scheduled content

        Args:
            args (mixed): positional arguments for the func
            kwargs (dict): keyword arguments for the func

        Returns:
            mixed: expect a boolean
        """
        wrapped = functools.partial(self._func, *args, **kwargs)
        return await self._loop.run_in_executor(None, wrapped)


class AsyncQueue(Queue):
    """a queue to schedule async calls and remain the sequence in processing

    Args:
        group (str): identifier for a platform
        func (coroutine): coroutine function, will be called with the scheduled
            args/kwargs
    """
    __slots__ = ()

    async def _send(self, args, kwargs):
        """perform the sending of the scheduled content

        Args:
            args (mixed): positional arguments for the coroutine
            kwargs (dict): keyword arguments for the coroutine

        Returns:
            mixed: expect a boolean
        """
        return await self._func(*args, **kwargs)


class QueueCache(Cache):
    """caches Queues and recreates one if a cache miss happens

    for a custom timeout: specify either `timeout` or provide the `bot` instance
    otherwise the sync.DEFAULT_CONFIG entry for queue caches is used

    Args:
        group (str): identifier for a platform to separate queues for
        func (callable): non-coroutine function, will be called with scheduled
            args/kwargs
        timeout (int): optional, time in seconds for a queue to live in cache
        bot (hangupsbot.core.HangupsBot): the running instance, optional
    """
    __slots__ = ('_default_args',)
    _queue = Queue
    DEFAULT_TIMEOUT = DEFAULT_CONFIG['sync_cache_timeout_sending_queue']

    def __init__(self, group, func, timeout=None, bot=None):
        timeout = timeout or (bot.config['sync_cache_timeout_sending_queue']
                              if bot is not None else self.DEFAULT_TIMEOUT)
        super().__init__(timeout, name='Sending Queues@%s' % group)
        self._default_args = (group, func)
        self._queue.release_block(group)

    def __missing__(self, identifier):
        queue = self._queue(*self._default_args)
        self.add(identifier, queue)
        return queue

    def get(self, identifier):
        """get the message queue of a chat

        Args:
            identifier (mixed): conversation id

        Returns:
            Queue: an instance of ._queue, AsyncQueue or Queue
        """
        # pylint:disable=arguments-differ
        return super().get(identifier, ignore_timeout=True)

    async def stop(self, timeout):
        """stop scheduling of new items and await the sending of recent tasks

        Args:
            timeout (int): timeout in sec to wait for scheduled tasks to finish
        """
        await self._queue(*self._default_args).local_stop(timeout)


class AsyncQueueCache(QueueCache):
    """caches AsyncQueues and recreates one if a cache miss happens

    Args:
        group (str): identifier for a platform to separate queues for
        func: coroutine function, will be called with the scheduled args/kwargs
        timeout: integer, optional, time in seconds for a queue to live in cache
        bot (hangupsbot.core.HangupsBot): the running instance, optional
    """
    __slots__ = ()
    _queue = AsyncQueue
