from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor
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

    def env(self):
        import os
        return os.getenv('CLEANROOM_ENV_VAR')

    def return_type(self):
        a = {
                'a': 42,
                'b': ['nested'],
        }
        b = set()
        return a, b

    def echo(self, num):
        return num

    def echo_boom(self, num):
        if num > 100:
            raise ValueError('boom!')
        return num


class DummyClassCorruptedInit:

    def __init__(self):
        raise ValueError('something wrong.')


def test_create_proc_channel():
    proc1, in_queue1, out_queue1, _, _ = factory.create_proc_channel(DummyClass)
    in_queue1.put(None)
    assert out_queue1.get()[0]

    proc2, in_queue2, out_queue2, _, _ = factory.create_proc_channel(DummyClass)
    in_queue2.put(None)
    assert out_queue2.get()[0]

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


def test_create_proc_channel_exception():
    proc, in_queue, out_queue, _, _ = factory.create_proc_channel(DummyClass)
    in_queue.put(None)
    assert out_queue.get()[0]

    in_queue.put(('boom', (), {}))
    good, out = out_queue.get()
    assert not good
    assert isinstance(out, factory.ExceptionWrapper)
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


def test_env(monkeypatch):
    monkeypatch.setenv('CLEANROOM_ENV_VAR', '42')

    proxy = factory.create_instance(DummyClass)
    assert proxy.env() == '42'


def test_return_type():
    proxy = factory.create_instance(DummyClass)
    a, b = proxy.return_type()


def test_thread_safe():
    proxy = factory.create_instance(DummyClass)
    assert proxy.echo(42) == 42

    num_list = list(range(1000))
    with Pool(10) as pool:
        assert list(pool.map(proxy.echo, num_list)) == num_list
    with ThreadPoolExecutor(max_workers=10) as pool:
        assert list(pool.map(proxy.echo, num_list)) == num_list


def test_thread_safe_error():
    proxy = factory.create_instance(DummyClass)

    proxy.echo_boom(0)
    with pytest.raises(ValueError):
        proxy.echo_boom(101)
    with pytest.raises(RuntimeError):
        proxy.echo_boom(101)


def test_init_error():
    with pytest.raises(ValueError):
        factory.create_instance(DummyClassCorruptedInit)
