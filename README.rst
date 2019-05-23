=========
cleanroom
=========


Install::

    pip install cleanroom


Create instance in a new process and proxy all operations:

.. code:: python

    import os
    import time
    from cleanroom import create_instance


    class Cal:

        def __init__(self, base):
            self.base = base

        def inc(self):
            self.base += 1
            return self.base

        def pid(self, sleep=None):
            if sleep:
                time.sleep(sleep)

            return os.getpid()


    cal = create_instance(Cal, 0)

    print('Parent PID: ', os.getpid())
    print('Cal PID: ', cal.pid())

    print('inc: ', cal.inc())
    print('inc: ', cal.inc())


Output::

    Parent PID:  22239
    Cal PID:  22272
    inc:  1
    inc:  2


Create multiple instances under the `random_access` scheduler:

.. code:: python

    from cleanroom import create_scheduler, create_instances_under_scheduler


    scheduler = create_scheduler(instances=5, scheduler_type='random_access')
    create_instances_under_scheduler(scheduler, Cal, 0)

    print('Parent PID: ', os.getpid())

    for _ in range(20):
        pid = scheduler.pid(sleep=1)
        print(time.ctime(), 'Cal PID:', pid)


Output::

    Parent PID:  4376
    Thu May 23 14:00:59 2019 Cal PID: 4399
    Thu May 23 14:01:00 2019 Cal PID: 4403
    Thu May 23 14:01:01 2019 Cal PID: 4397
    Thu May 23 14:01:02 2019 Cal PID: 4397
    Thu May 23 14:01:03 2019 Cal PID: 4403
    Thu May 23 14:01:04 2019 Cal PID: 4399
    Thu May 23 14:01:05 2019 Cal PID: 4395
    Thu May 23 14:01:06 2019 Cal PID: 4401
    Thu May 23 14:01:07 2019 Cal PID: 4399
    Thu May 23 14:01:08 2019 Cal PID: 4395
    Thu May 23 14:01:09 2019 Cal PID: 4401
    Thu May 23 14:01:10 2019 Cal PID: 4401
    Thu May 23 14:01:11 2019 Cal PID: 4403
    Thu May 23 14:01:12 2019 Cal PID: 4395
    Thu May 23 14:01:13 2019 Cal PID: 4397
    Thu May 23 14:01:14 2019 Cal PID: 4403
    Thu May 23 14:01:15 2019 Cal PID: 4401
    Thu May 23 14:01:16 2019 Cal PID: 4395
    Thu May 23 14:01:17 2019 Cal PID: 4395
    Thu May 23 14:01:18 2019 Cal PID: 4397


Create multiple instances under the `batch_random_access` scheduler:

.. code:: python

    from cleanroom import BatchCall

    scheduler = create_scheduler(instances=5, scheduler_type='batch_random_access')
    create_instances_under_scheduler(scheduler, Cal, 0)

    print('Parent PID: ', os.getpid())

    for pid in scheduler.pid(BatchCall(sleep=1) for _ in range(20)):
        print(time.ctime(), 'Cal PID:', pid)


Output::

    Parent PID:  4376
    Thu May 23 14:04:47 2019 Cal PID: 4429
    Thu May 23 14:04:47 2019 Cal PID: 4433
    Thu May 23 14:04:47 2019 Cal PID: 4435
    Thu May 23 14:04:48 2019 Cal PID: 4433
    Thu May 23 14:04:48 2019 Cal PID: 4437
    Thu May 23 14:04:49 2019 Cal PID: 4429
    Thu May 23 14:04:49 2019 Cal PID: 4433
    Thu May 23 14:04:49 2019 Cal PID: 4437
    Thu May 23 14:04:49 2019 Cal PID: 4431
    Thu May 23 14:04:49 2019 Cal PID: 4435
    Thu May 23 14:04:50 2019 Cal PID: 4429
    Thu May 23 14:04:51 2019 Cal PID: 4431
    Thu May 23 14:04:51 2019 Cal PID: 4435
    Thu May 23 14:04:51 2019 Cal PID: 4431
    Thu May 23 14:04:51 2019 Cal PID: 4437
    Thu May 23 14:04:53 2019 Cal PID: 4429
    Thu May 23 14:04:53 2019 Cal PID: 4431
    Thu May 23 14:04:53 2019 Cal PID: 4429
    Thu May 23 14:04:53 2019 Cal PID: 4437
    Thu May 23 14:04:53 2019 Cal PID: 4437


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
