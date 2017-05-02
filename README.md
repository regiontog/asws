# Features
- Asynchronous with python asyncio
- Multiple clients
- Passes autobahn tests 1-10 (11-13 needs compression extension)
- All control frames with status and reason

# Installing
```bash
python3.6 -m venv myproject
source myproject/bin/activate

pip install asws3
```

# Usage
## Basic echo server
```python
loop = asyncio.get_event_loop()
socket = WebSocketServer("localhost", 3001, loop=loop)


@socket.connection
async def on_connection(client: Client):
    logger.info(f'Connection from {client.addr, client.port}')
    logger.info(f'All clients: {socket.clients}')

    @client.message
    async def on_message(reader: WebSocketReader):
        await client.writer.send(await reader.get())

with socket as server:
    print(f'Serving on {server.sockets[0].getsockname()}')
    loop.run_forever()

loop.close()
```

# Documentation
[Link](https://regiontog.github.io/asws-pages/)

# TODO
- Websocket Extentions
- Test with random data