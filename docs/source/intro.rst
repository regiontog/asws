Getting Started
===============

Asyncio
^^^^^^^
Before trying this library you should understand the basics of python asyncio. You can
read up on python 3 async basics `here <https://snarky.ca/how-the-heck-does-async-await-work-in-python-3-5/>`_.


Creating the socket and server object
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Before we can do anything you need to create the websocket object, we also create the eventloop.
::

   loop = asyncio.get_event_loop()
   socket = WebSocketServer(address, port, loop=loop)


Registering the on_connection callback
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
We can listen for new websocket connections with the :meth:`~websocket.server.WebSocketServer.connection`
`decorator <https://realpython.com/blog/python/primer-on-python-decorators/>`_.
::

    @socket.connection
    async def on_connection(client: Client):
        print("We just got a new connection!")

The parameter to the callback is the :class:`~websocket.client.Client` class, more about that class later.

Starting the server
^^^^^^^^^^^^^^^^^^^
Before the server will accept connections we have to start it. Starting the server is as simple as using the
socket object as a `context manager <http://book.pythontips.com/en/latest/context_managers.html>`_. The server
object yielded by the context manager is a :class:`~asyncio.Server` class.
::

    with socket as server:
        print(f'Serving on {server.sockets[0].getsockname()}')

    print("The server closed")

The server closes as soon as the with block is done. In order to keep the server alive we need to give up control to the event loop.
We can do this with the :meth:`~asyncio.AbstractEventLoop.run_forever` method.
::

    with socket as server:
        loop.run_forever()
        print("The server is going to close!")

    print("The server closed")

The client object
^^^^^^^^^^^^^^^^^
If we look back at :meth:`~websocket.server.WebSocketServer.connection`
`decorator <https://realpython.com/blog/python/primer-on-python-decorators/>`_, we see that the callback accepts the :class:`~asyncio.Server` class.
This class has 3 interesting attributes, :attr:`~websocket.client.Client.addr`, :attr:`~websocket.client.Client.port`, and :attr:`~websocket.client.Client.writer`.
The first two answer to the address and port of the remote socket. We can use these to identify each client.

::

    @socket.connection
    async def on_connection(client: Client):
        print(f"We just got a new connection from {client.addr, client.port}!")

The :attr:`~websocket.client.Client.writer` is used to send messages to the client and we'll look closer at it soon.

We can access all connected clients through :attr:`~websocket.server.WebSocketServer.clients`. This :class:`dict` the key to each client is the tuple `(client.addr, client.port)`.
In particular before the on_connection callback is finished it contains all clients but the newly connected one.
::

    @socket.connection
        async def on_connection(client: Client):
            for other in socket.clients.values():
                print(f"Client {other.addr, other.port} was connected before {client.addr, client.port}")


Registering the on_message callback
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
In the same way we registered a on_connection callback we can register a on_message callback for a specific client, we usually do this at the same time as the client connect.
We do this with :meth:`~websocket.client.Client.message` `decorator <https://realpython.com/blog/python/primer-on-python-decorators/>`_.
The callback parameter is a :class:`~websocket.stream.reader.WebSocketReader` class.
::

    @socket.connection
        async def on_connection(client: Client):
            @client.message
                async def on_message(reader: WebSocketReader):
                    print(f"The client {client.addr, client.port} sent an message.")

Reading from the stream
^^^^^^^^^^^^^^^^^^^^^^^
The :class:`~websocket.stream.reader.WebSocketReader` class inherits some low level read methods from it's superclass :class:`~websocket.stream.buffer.Buffer`,
if you want to read bytes. Otherwise the method :meth:`~websocket.stream.reader.WebSocketReader.get` is useful for reading either :class:`bytes` or :class:`str`.
::

    @client.message
        async def on_message(reader: WebSocketReader):
            msg = await reader.get()
            print(f"The client {client.addr, client.port} sent the message {msg}.")

Sending messages to the client
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
We can send messages to an client though the :attr:`~websocket.client.Client.writer` attribute of type :class:`~websocket.stream.writer.WebSocketWriter`

Data frame
**********
Just like we could receive messages with :meth:`~websocket.stream.reader.WebSocketReader.get` we can send messages with :meth:`~websocket.stream.writer.WebSocketWriter.send`.
:meth:`~websocket.stream.writer.WebSocketWriter.send` will automatically look at the data you give it and send the correct data frame.

::

    @socket.connection
        async def on_connection(client: Client):
            for other in socket.clients.values():
                await other.writer.send('You are a client connected to my server.')

::

    @socket.connection
        async def on_connection(client: Client):
            @client.message
                async def on_message(reader: WebSocketReader):
                msg = await reader.get()
                await client.writer.send('You just send me the following message.')
                await client.writer.send(msg)

Fragments
*********

Coming soon

Other callbacks
^^^^^^^^^^^^^^^
Coming soon