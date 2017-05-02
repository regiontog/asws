# Installing
```bash
python3.6 -m venv myproject
. myproject/bin/activate (linux)
./myproject/Scripts/activate.bat (windows)

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
- websocket extentions
- lazy properties
- make fragment do chunksize
- test with random data
- websocket over https
- use all cores
- http path
- http server