import sys
import pickle
import traceback
import random
from multiprocessing import Process, Manager

import tblib.pickling_support
tblib.pickling_support.install()


class ExceptionWrapper:

    def __init__(self, exception, traceback_obj):
        self.exception = exception
        self.traceback_obj = traceback_obj

    def raise_again(self):
        exception = self.exception
        if self.traceback_obj is not None:
            exception = self.exception.with_traceback(self.traceback_obj)
        raise exception


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
        self.instance = self.instance_cls(*self.args, **self.kwargs)

    def _step(self, in_queue_popped):
        method_name, method_args, method_kwargs = in_queue_popped
        method = getattr(self.instance, method_name)
        return method(*method_args, **method_kwargs)

    def run(self):
        # Initialization.
        self._exception_handler(self._initialize, self.in_queue.get())

        # Serving.
        while True:
            self._exception_handler(self._step, self.in_queue.get())


def create_proc_channel(instance_cls, *args, **kwargs):
    mgr = Manager()
    in_queue = mgr.Queue()
    out_queue = mgr.Queue()
    state = mgr.Value('b', 1)
    lock = mgr.Lock()  # pylint: disable=no-member

    proc = CleanroomProcess(instance_cls, args, kwargs, in_queue, out_queue)
    proc.daemon = True
    proc.start()
    return proc, in_queue, out_queue, state, lock


class ProxyCall:

    def __init__(self, method_name, in_queue, out_queue, state, lock):
        self.method_name = method_name
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.state = state
        self.lock = lock

    def __call__(self, *args, **kwargs):
        with self.lock:
            if self.state.value != 1:
                raise RuntimeError('The process is not alive!')

            self.in_queue.put((self.method_name, args, kwargs))
            good, out = self.out_queue.get()

            if not good:
                self.state.value = 0
                out.raise_again()
            return out


def _raise_on_invalid_method_name(instance_cls, name):
    if not hasattr(instance_cls, name):
        raise NotImplementedError(f'{name} is not defined in {instance_cls}')
    if not callable(getattr(instance_cls, name)):
        raise AttributeError(f'{name} is not callable in {instance_cls}')


CLEANROOM_PROCESS_PROXY_CRW = {
        '_crw_instance_cls',
        '_crw_proc',
        '_crw_in_queue',
        '_crw_out_queue',
        '_crw_state',
        '_crw_lock',
        '_crw_cached_proxy_call',
}


class CleanroomProcessProxy:

    def __init__(self, instance_cls, proc, in_queue, out_queue, state, lock):
        for name in CLEANROOM_PROCESS_PROXY_CRW:
            if hasattr(instance_cls, name):
                raise AttributeError(f'{instance_cls} contains {name}.')

        self._crw_instance_cls = instance_cls
        self._crw_proc = proc
        self._crw_in_queue = in_queue
        self._crw_out_queue = out_queue
        self._crw_state = state
        self._crw_lock = lock
        self._crw_cached_proxy_call = {}

    def __getattribute__(self, name):
        if name in CLEANROOM_PROCESS_PROXY_CRW:
            return object.__getattribute__(self, name)

        if name not in self._crw_cached_proxy_call:
            _raise_on_invalid_method_name(self._crw_instance_cls, name)

            self._crw_cached_proxy_call[name] = ProxyCall(
                    method_name=name,
                    in_queue=self._crw_in_queue,
                    out_queue=self._crw_out_queue,
                    state=self._crw_state,
                    lock=self._crw_lock,
            )

        return self._crw_cached_proxy_call[name]

    def __del__(self):
        self._crw_proc.terminate()


def create_instance(instance_cls, *args, **kwargs):
    proc, in_queue, out_queue, state, lock = create_proc_channel(
            instance_cls,
            *args,
            **kwargs,
    )
    in_queue.put(None)
    good, out = out_queue.get()
    if not good:
        out.raise_again()

    proxy = CleanroomProcessProxy(instance_cls, proc, in_queue, out_queue, state, lock)
    return proxy


class ProxySchedulerCall:

    def __init__(self, scheduler, method_name):
        self.scheduler = scheduler
        self.method_name = method_name

    def __call__(self, *args, **kwargs):
        proxy = self.scheduler._crw_select_instance(*args, **kwargs)  # pylint: disable=protected-access
        return getattr(proxy, self.method_name)(*args, **kwargs)


CLEANROOM_PROCESS_PROXY_SCHEDULER_CRW = {
        '_crw_processes',
        '_crw_proxies',
        '_crw_create_instances',
        '_crw_instance_cls',
        '_crw_cached_proxy_scheduler_call',
        '_crw_select_instance',
}


class CleanroomProcessProxyScheduler:

    def __init__(self, processes):
        self._crw_processes = processes
        self._crw_proxies = []
        self._crw_instance_cls = None
        self._crw_cached_proxy_scheduler_call = {}

    def _crw_create_instances(self, instance_cls, *args, **kwargs):
        for name in CLEANROOM_PROCESS_PROXY_SCHEDULER_CRW:
            if hasattr(instance_cls, name):
                raise AttributeError(f'{instance_cls} contains {name}.')

        self._crw_instance_cls = instance_cls
        for _ in range(self._crw_processes):
            self._crw_proxies.append(create_instance(instance_cls, *args, **kwargs))

    def _crw_select_instance(self, *args, **kwargs):
        raise NotImplementedError()

    def __getattribute__(self, name):
        if name in CLEANROOM_PROCESS_PROXY_SCHEDULER_CRW:
            return object.__getattribute__(self, name)

        if name not in self._crw_cached_proxy_scheduler_call:
            _raise_on_invalid_method_name(self._crw_instance_cls, name)

            self._crw_cached_proxy_scheduler_call[name] = ProxySchedulerCall(
                    scheduler=self,
                    method_name=name,
            )

        return self._crw_cached_proxy_scheduler_call[name]


class CleanroomProcessProxyRandomAccessScheduler(CleanroomProcessProxyScheduler):

    def _crw_select_instance(self, *args, **kwargs):
        return random.choice(self._crw_proxies)


_REGISTERED_SCHEDULERS = {
        'random_access': CleanroomProcessProxyRandomAccessScheduler,
}


def create_scheduler(processes, scheduler_type='random_access'):
    if scheduler_type not in _REGISTERED_SCHEDULERS:
        raise ValueError(f'Undefined scheduler type: {scheduler_type}')

    scheduler_cls = _REGISTERED_SCHEDULERS[scheduler_type]
    return scheduler_cls(processes)


def create_instances_under_scheduler(scheduler, instance_cls, *args, **kwargs):
    scheduler._crw_create_instances(instance_cls, *args, **kwargs)  # pylint: disable=protected-access
