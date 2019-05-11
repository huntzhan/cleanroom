import sys
import traceback
from multiprocessing import Process, Manager


class CleanroomProcess(Process):

    def __init__(self, instance_cls, args, kwargs, in_queue, out_queue):
        super().__init__()

        self.instance_cls = instance_cls
        self.args = args
        self.kwargs = kwargs

        self.in_queue = in_queue
        self.out_queue = out_queue

    def run(self):
        instance = self.instance_cls(*self.args, **self.kwargs)
        while True:
            method_name, method_args, method_kwargs = self.in_queue.get()
            method = getattr(instance, method_name)

            try:
                out = method(*method_args, **method_kwargs)
                self.out_queue.put((True, out))

            except:  # pylint: disable=bare-except
                exc_type, exc_value, exc_traceback = sys.exc_info()
                traceback.print_exception(exc_type, exc_value, exc_traceback)
                self.out_queue.put((False, exc_value))
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
                raise out
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
        in_queue = object.__getattribute__(self, 'in_queue')
        out_queue = object.__getattribute__(self, 'out_queue')
        state = object.__getattribute__(self, 'state')
        lock = object.__getattribute__(self, 'lock')

        if not hasattr(instance_cls, method_name):
            raise NotImplementedError(f'{method_name} is not defined in {instance_cls}')
        if not callable(getattr(instance_cls, method_name)):
            raise AttributeError(f'{method_name} is not callable in {instance_cls}')

        cached_proxy_call = object.__getattribute__(self, 'cached_proxy_call')
        if method_name not in cached_proxy_call:
            cached_proxy_call[method_name] = ProxyCall(
                    method_name=method_name,
                    in_queue=in_queue,
                    out_queue=out_queue,
                    state=state,
                    lock=lock,
            )

        return cached_proxy_call[method_name]


def create_instance(instance_cls, *args, **kwargs):
    proc, in_queue, out_queue, state, lock = create_proc_channel(
            instance_cls,
            *args,
            **kwargs,
    )
    proxy = CleanroomProcessProxy(instance_cls, proc, in_queue, out_queue, state, lock)
    return proxy
