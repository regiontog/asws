#!/usr/bin/env python

from setuptools import setup

setup(name='asws3',
      version='1.0.1',
      description='Asynchronous websockets in python 3.6',
      author='Erlend Tobiassen',
      author_email='erlentob@stud.ntnu.no',
      url='https://github.com/regiontog/asws',
      keywords=['websocket', 'python3.6', 'asynchronous', 'asyncio', 'async'],
      packages=["websocket", "websocket.stream", "websocket.http"],
      classifiers=[],
)