import sys
from multiprocessing import Process, Manager

import tblib.pickling_support
tblib.pickling_support.install()


class ExceptionWrapper:

    def __init__(self, exception, traceback):
        self.exception = exception
        self.traceback = traceback

    def raise_again(self):
        raise self.exception.with_traceback(self.traceback)


class CleanroomProcess(Process):

    def __init__(self, instance_cls, args, kwargs, in_queue, out_queue):
        super().__init__()

        self.instance_cls = instance_cls
        self.args = args
        self.kwargs = kwargs

        self.in_queue = in_queue
        self.out_queue = out_queue

    def run(self):
        # Initialization.
        self.in_queue.get()
        try:
            instance = self.instance_cls(*self.args, **self.kwargs)
            self.out_queue.put((True, None))

        except Exception as exception:  # pylint: disable=broad-except
            _, _, traceback = sys.exc_info()
            self.out_queue.put((False, ExceptionWrapper(exception, traceback)))
            sys.exit(-1)

        # Serving.
        while True:
            method_name, method_args, method_kwargs = self.in_queue.get()
            method = getattr(instance, method_name)

            try:
                out = method(*method_args, **method_kwargs)
                self.out_queue.put((True, out))

            except Exception as exception:  # pylint: disable=broad-except
                _, _, traceback = sys.exc_info()
                self.out_queue.put((False, ExceptionWrapper(exception, traceback)))
                sys.exit(-1)


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


class CleanroomProcessProxy:

    def __init__(self, instance_cls, proc, in_queue, out_queue, state, lock):
        self.instance_cls = instance_cls
        self.proc = proc
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.state = state
        self.lock = lock

        self.cached_proxy_call = {}

    def __getattribute__(self, method_name):
        instance_cls = object.__getattribute__(self, 'instance_cls')
        cached_proxy_call = object.__getattribute__(self, 'cached_proxy_call')

        if method_name not in cached_proxy_call:
            if not hasattr(instance_cls, method_name):
                raise NotImplementedError(f'{method_name} is not defined in {instance_cls}')
            if not callable(getattr(instance_cls, method_name)):
                raise AttributeError(f'{method_name} is not callable in {instance_cls}')

            cached_proxy_call[method_name] = ProxyCall(
                    method_name=method_name,
                    in_queue=object.__getattribute__(self, 'in_queue'),
                    out_queue=object.__getattribute__(self, 'out_queue'),
                    state=object.__getattribute__(self, 'state'),
                    lock=object.__getattribute__(self, 'lock'),
            )

        return cached_proxy_call[method_name]

    def __del__(self):
        proc = object.__getattribute__(self, 'proc')
        proc.terminate()


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
