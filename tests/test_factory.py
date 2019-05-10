import pytest
from cleanroom import factory


class DummyClass:

    SHOULD_NOT_TOUCH = 42

    def __init__(self):
        self.num = 0

    def get(self):
        return self.num

    def inc(self):
        self.num += 1

    def pid(self):
        import os
        return os.getpid()

    def boom(self):
        raise RuntimeError('something wrong.')


def test_create_proc_and_io_queues():
    proc1, in_queue1, out_queue1 = factory.create_proc_and_io_queues(DummyClass)
    proc2, in_queue2, out_queue2 = factory.create_proc_and_io_queues(DummyClass)

    in_queue1.put(('pid', (), {}))
    in_queue2.put(('pid', (), {}))
    assert out_queue1.get()[1] != out_queue2.get()[1]

    in_queue1.put(('get', (), {}))
    assert out_queue1.get()[1] == 0

    in_queue1.put(('inc', (), {}))
    assert out_queue1.get()[1] is None

    in_queue1.put(('get', (), {}))
    assert out_queue1.get()[1] == 1

    in_queue2.put(('get', (), {}))
    assert out_queue2.get()[1] == 0

    proc1.terminate()
    proc2.terminate()


def test_create_proc_and_io_queues_exception():
    proc, in_queue, out_queue = factory.create_proc_and_io_queues(DummyClass)
    in_queue.put(('boom', (), {}))
    good, out = out_queue.get()
    assert not good
    assert isinstance(out, Exception)
    proc.join()
    assert not proc.is_alive()


def test_create_instance():
    proxy1 = factory.create_instance(DummyClass)
    proxy2 = factory.create_instance(DummyClass)

    assert proxy1.pid() != proxy2.pid()

    assert proxy1.get() == 0
    assert proxy1.inc() == None
    assert proxy1.get() == 1
    with pytest.raises(RuntimeError):
        proxy1.boom()


def test_create_instance_error():
    proxy = factory.create_instance(DummyClass)

    with pytest.raises(NotImplementedError):
        proxy.this_does_not_exists

    with pytest.raises(NotImplementedError):
        proxy.instance_cls

    with pytest.raises(AttributeError):
        proxy.SHOULD_NOT_TOUCH

    with pytest.raises(TypeError):
        proxy.get(42)
