# -*- coding: utf-8 -*-
"""Top-level package for cleanroom."""

__author__ = """Hunt Zhan"""
__email__ = 'huntzhan.dev@gmail.com'
__version__ = '0.3.1'

from cleanroom.factory import (
        create_instance,
        create_scheduler,
        create_instances_under_scheduler,
        get_instances_under_scheduler,
        BatchCall,
)
