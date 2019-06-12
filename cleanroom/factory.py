import sys
import os
import logging
import pickle
import traceback
import random
import itertools
from multiprocessing import Process, Manager
import queue
import time
from concurrent.futures import ThreadPoolExecutor

import tblib.pickling_support
tblib.pickling_support.install()

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


class CleanroomArgs:

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class ExceptionWrapper:

    def __init__(self, exception, traceback_obj):
        self.exception = exception
        self.traceback_obj = traceback_obj

    def raise_again(self):
        exception = self.exception
        if self.traceback_obj is not None:
            exception = self.exception.with_traceback(self.traceback_obj)
        raise exception


class TimeoutException(Exception):
    pass


class CleanroomProcess(Process):

    def __init__(self, instance_cls, args, kwargs, in_queue, out_queue):
        super().__init__()

        self.instance_cls = instance_cls
        self.instance = None
        self.args = args
        self.kwargs = kwargs

        self.in_queue = in_queue
        self.out_queue = out_queue

    def _exception_handler(self, action, in_queue_popped):
        try:
            out = action(in_queue_popped)
            self.out_queue.put((True, out))

        except Exception as exception:  # pylint: disable=broad-except
            _, _, traceback_obj = sys.exc_info()
            wrapped = ExceptionWrapper(exception, traceback_obj)

            try:
                pickle.dumps(wrapped)
            except pickle.PickleError:
                # Cannot pickle, mock with Built-in excpetion.
                traceback_lines = ['Traceback (most recent call last):\n']
                traceback_lines.extend(traceback.format_tb(traceback_obj))
                text = ''.join(traceback_lines)
                wrapped = ExceptionWrapper(RuntimeError(text), None)

            self.out_queue.put((False, wrapped))
            sys.exit(-1)

    def _initialize(self, in_queue_popped):  # pylint: disable=unused-argument
        logger.debug('CleanroomProcess._initialize: proc=%s begin', self)
        self.instance = self.instance_cls(*self.args, **self.kwargs)
        logger.debug('CleanroomProcess._initialize: proc=%s end', self)

    def _step(self, in_queue_popped):
        logger.debug('CleanroomProcess._step: proc=%s begin', self)
        method_name, method_args, method_kwargs = in_queue_popped
        method = getattr(self.instance, method_name)
        ret = method(*method_args, **method_kwargs)
        logger.debug('CleanroomProcess._step: proc=%s end', self)
        return ret

    def run(self):
        # Initialization.
        self._exception_handler(self._initialize, self.in_queue.get())

        # Serving.
        while True:
            try:
                logger.debug('CleanroomProcess.run: proc=%s waiting for in_queue.get', self)
                obj = self.in_queue.get()
                logger.debug('CleanroomProcess.run: proc=%s receive in_queue.get', self)
            except EOFError:
                logger.debug('CleanroomProcess.run: proc=%s EOFError & break', self)
                break
            self._exception_handler(self._step, obj)

    def __repr__(self):
        return f'<PID={self.pid}, {super().__repr__()}>'


def create_proc_channel(instance_cls, cleanroom_args=None):
    mgr = Manager()
    in_queue = mgr.Queue(maxsize=1)
    out_queue = mgr.Queue(maxsize=1)
    state = mgr.Value('b', 1)
    lock = mgr.Lock()  # pylint: disable=no-member

    if cleanroom_args is None:
        args = ()
        kwargs = {}
    else:
        args = cleanroom_args.args
        kwargs = cleanroom_args.kwargs

    proc = CleanroomProcess(instance_cls, args, kwargs, in_queue, out_queue)
    proc.daemon = True
    proc.start()
    logger.debug('create_proc_channel: proc=%s started.', proc)

    while not proc.is_alive():
        logger.debug('create_proc_channel: proc=%s not alive, waiting...', proc)
        time.sleep(0.01)

    logger.debug('create_proc_channel: proc=%s is alive.', proc)
    return proc, in_queue, out_queue, state, lock


class ProxyCall:

    def __init__(self, proc_repr, method_name, in_queue, out_queue, timeout, state, lock):
        self.proc_repr = proc_repr
        self.method_name = method_name
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.timeout = timeout
        self.state = state
        self.lock = lock

    def __call__(self, *args, **kwargs):
        logger.debug(
                'ProxyCall.__call__: waiting for lock proc=%s, method_name=%s, args=%s, kwargs=%s',
                self.proc_repr, self.method_name, args, kwargs)
        with self.lock:
            logger.debug(
                    'ProxyCall.__call__: acquire lock proc=%s, method_name=%s, args=%s, kwargs=%s',
                    self.proc_repr, self.method_name, args, kwargs)

            if self.state.value != 1:
                raise RuntimeError('The process is not alive!')

            self.in_queue.put((self.method_name, args, kwargs))
            try:
                good, out = self.out_queue.get(timeout=self.timeout)
            except queue.Empty:
                raise TimeoutException(
                        f'Timeout (timeout={self.timeout}) when calling {self.method_name}.')

            if not good:
                self.state.value = 0
                out.raise_again()
            return out


def _raise_on_invalid_method_name(instance_cls, name):
    if not hasattr(instance_cls, name):
        raise NotImplementedError(f'[name:{name}] is not defined in [cls:{instance_cls}]')
    if not callable(getattr(instance_cls, name)):
        raise AttributeError(f'[name:{name}] is not callable in [cls:{instance_cls}]')


CLEANROOM_PROCESS_PROXY_CRW = {
        '_crw_instance_cls',
        '_crw_proc',
        '_crw_in_queue',
        '_crw_out_queue',
        '_crw_timeout',
        '_crw_state',
        '_crw_lock',
        '_crw_cached_proxy_call',
        '_crw_check_instance_cls_methods',
}


class CleanroomProcessProxy:

    @staticmethod
    def _crw_check_instance_cls_methods(instance_cls):
        for name in CLEANROOM_PROCESS_PROXY_CRW:
            if hasattr(instance_cls, name):
                raise AttributeError(f'{instance_cls} contains {name}.')

    def __init__(
            self,
            instance_cls,
            proc,
            in_queue,
            out_queue,
            timeout,
            state,
            lock,
    ):
        self._crw_instance_cls = instance_cls
        self._crw_proc = proc
        self._crw_in_queue = in_queue
        self._crw_out_queue = out_queue
        self._crw_timeout = timeout
        self._crw_state = state
        self._crw_lock = lock
        self._crw_cached_proxy_call = {}

    def __getattribute__(self, name):
        if name in CLEANROOM_PROCESS_PROXY_CRW:
            return object.__getattribute__(self, name)

        if name not in self._crw_cached_proxy_call:
            _raise_on_invalid_method_name(self._crw_instance_cls, name)

            self._crw_cached_proxy_call[name] = ProxyCall(
                    proc_repr=repr(self._crw_proc),
                    method_name=name,
                    in_queue=self._crw_in_queue,
                    out_queue=self._crw_out_queue,
                    timeout=self._crw_timeout,
                    state=self._crw_state,
                    lock=self._crw_lock,
            )

        return self._crw_cached_proxy_call[name]

    def __del__(self):
        # Remove process in GC.
        if self._crw_proc._parent_pid != os.getpid():  # pylint: disable=protected-access
            logger.debug('CleanroomProcessProxy.__del__: killing unknown proc=%s', self._crw_proc)
            if hasattr(self._crw_proc, 'kill'):
                # New in 3.7.
                getattr(self._crw_proc, 'kill')()
            return

        # Normal termination.
        logger.debug('CleanroomProcessProxy.__del__: terminating proc=%s', self._crw_proc)
        self._crw_proc.terminate()

        # Default timeout: 30s.
        timeout = self._crw_timeout or 30
        self._crw_proc.join(timeout)
        if self._crw_proc.exitcode is None:
            logger.debug('CleanroomProcessProxy.__del__: timeout & force killing proc=%s',
                         self._crw_proc)
            self._crw_proc.kill()
        else:
            logger.debug('CleanroomProcessProxy.__del__: proc=%s is terminated', self._crw_proc)


def create_instance(
        instance_cls,
        cleanroom_args=None,
        timeout=None,
):
    logger.debug('create_instance: instance_cls=%s, cleanroom_args=%s, timeout=%s', instance_cls,
                 cleanroom_args, timeout)

    CleanroomProcessProxy._crw_check_instance_cls_methods(instance_cls)  # pylint: disable=protected-access

    proc, in_queue, out_queue, state, lock = create_proc_channel(
            instance_cls,
            cleanroom_args,
    )

    logger.debug('create_instance: proc=%s, trigger initialization', proc)
    in_queue.put(None)
    try:
        logger.debug('create_instance: proc=%s, waiting for initialization...', proc)
        good, out = out_queue.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutException(f'Timeout (timeout={timeout}) during initialization')

    if not good:
        out.raise_again()

    logger.debug('create_instance: proc=%s, initialization done', proc)
    proxy = CleanroomProcessProxy(
            instance_cls,
            proc,
            in_queue,
            out_queue,
            timeout,
            state,
            lock,
    )
    logger.debug('create_instance: proxy=%s has been created for proc=%s', proxy, proc)
    return proxy


class ProxySchedulerCall:

    def __init__(self, scheduler, method_name):
        self.scheduler = scheduler
        self.method_name = method_name

    def __call__(self, *args, **kwargs):
        proxy = self.scheduler._crw_select_instance(*args, **kwargs)  # pylint: disable=protected-access
        return getattr(proxy, self.method_name)(*args, **kwargs)


CLEANROOM_PROCESS_PROXY_SCHEDULER_CRW = {
        '_crw_instances',
        '_crw_chunksize',
        '_crw_proxies',
        '_crw_create_instances',
        '_crw_instance_cls',
        '_crw_cached_proxy_scheduler_call',
        '_crw_select_instance',
        'PROXY_SCHEDULER_CALL_CLS',
}


class CleanroomProcessProxyScheduler:

    PROXY_SCHEDULER_CALL_CLS = ProxySchedulerCall

    def __init__(self, instances):
        self._crw_instances = instances
        self._crw_proxies = []
        self._crw_instance_cls = None
        self._crw_cached_proxy_scheduler_call = {}

    def _crw_create_instances(
            self,
            instance_cls,
            cleanroom_args=None,
            timeout=None,
    ):
        for name in CLEANROOM_PROCESS_PROXY_SCHEDULER_CRW:
            if hasattr(instance_cls, name):
                raise AttributeError(f'{instance_cls} contains {name}.')

        self._crw_instance_cls = instance_cls
        for _ in range(self._crw_instances):
            self._crw_proxies.append(create_instance(instance_cls, cleanroom_args, timeout))

    def _crw_select_instance(self, *args, **kwargs):
        raise NotImplementedError()

    def __getattribute__(self, name):
        if name in CLEANROOM_PROCESS_PROXY_SCHEDULER_CRW:
            return object.__getattribute__(self, name)

        if name not in self._crw_cached_proxy_scheduler_call:
            _raise_on_invalid_method_name(self._crw_instance_cls, name)

            self._crw_cached_proxy_scheduler_call[name] = self.PROXY_SCHEDULER_CALL_CLS(
                    scheduler=self,
                    method_name=name,
            )

        return self._crw_cached_proxy_scheduler_call[name]


class CleanroomProcessProxyRandomAccessScheduler(CleanroomProcessProxyScheduler):

    def _crw_select_instance(self, *args, **kwargs):
        return random.choice(self._crw_proxies)


class _ZIP_LONGEST_FILL_VALUE:  # pylint: disable=invalid-name
    pass


def _on_batch_call(proxy_call, batch_call):
    return proxy_call(*batch_call.args, **batch_call.kwargs)


class ProxySchedulerBatchCall(ProxySchedulerCall):

    def __call__(self, batch_calls):  # pylint: disable=arguments-differ
        groups = itertools.zip_longest(
                *([iter(batch_calls)] * self.scheduler._crw_instances),  # pylint: disable=protected-access
                fillvalue=_ZIP_LONGEST_FILL_VALUE,
        )
        for group in groups:
            proxy_calls = [
                    getattr(
                            self.scheduler._crw_select_instance(  # pylint: disable=protected-access
                                    *batch_call.args,
                                    **batch_call.kwargs,
                            ),
                            self.method_name,
                    ) for batch_call in group if batch_call is not _ZIP_LONGEST_FILL_VALUE
            ]
            with ThreadPoolExecutor(max_workers=len(proxy_calls)) as pool:
                yield from pool.map(lambda p: _on_batch_call(*p), zip(proxy_calls, group))


class CleanroomProcessProxyBatchScheduler(CleanroomProcessProxyScheduler):  # pylint: disable=abstract-method

    PROXY_SCHEDULER_CALL_CLS = ProxySchedulerBatchCall


class CleanroomProcessProxyBatchRandomAccessScheduler(CleanroomProcessProxyBatchScheduler):

    def _crw_select_instance(self, *args, **kwargs):
        return random.choice(self._crw_proxies)


_REGISTERED_SCHEDULERS = {
        'random_access': CleanroomProcessProxyRandomAccessScheduler,
        'batch_random_access': CleanroomProcessProxyBatchRandomAccessScheduler,
}


def create_scheduler(instances, scheduler_type='random_access'):
    if scheduler_type not in _REGISTERED_SCHEDULERS:
        raise ValueError(f'Undefined scheduler type: {scheduler_type}')

    scheduler_cls = _REGISTERED_SCHEDULERS[scheduler_type]
    return scheduler_cls(instances)


def create_instances_under_scheduler(
        scheduler,
        instance_cls,
        cleanroom_args=None,
        timeout=None,
):
    scheduler._crw_create_instances(  # pylint: disable=protected-access
            instance_cls,
            cleanroom_args,
            timeout,
    )


def get_instances_under_scheduler(scheduler):
    return scheduler._crw_proxies  # pylint: disable=protected-access
