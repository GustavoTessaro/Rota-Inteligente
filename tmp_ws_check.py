import asyncio
import websockets

async def main():
    async with websockets.connect('ws://127.0.0.1:8000/ws/tracking') as ws:
        print('connected')
        for i in range(3):
            msg = await ws.recv()
            print(i + 1, msg)

asyncio.run(main())
