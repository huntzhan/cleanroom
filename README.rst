=========
cleanroom
=========


Install::

    pip install cleanroom


Create instance in a new process and proxy all operations:

.. code:: python

    import os
    from cleanroom import create_instance


    class Cal:

        def __init__(self, base):
            self.base = base

        def inc(self):
            self.base += 1
            return self.base

        def pid(self):
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


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
