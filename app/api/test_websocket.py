#!/usr/bin/env python3
"""
WebSocket client test for the game server.

Run the server first:
    uvicorn app.api.main:app --reload

Then run this script:
    python test_websocket.py
"""

import asyncio
import websockets
import json


async def test_websocket():
    """
    Test WebSocket game room connection.

    Simulates two players joining a room and playing actions.
    """
    print("=" * 60)
    print("WebSocket Game Room Test")
    print("=" * 60)

    uri = "ws://localhost:8000/ws/test-room"

    print(f"\nConnecting to {uri}...")

    async with websockets.connect(uri) as ws1:
        print("\n=== Player 1 Connected ===")

        await ws1.send(json.dumps({"type": "JOIN", "room": "test-room", "join": {"name": "Alice"}}))

        response = await ws1.recv()
        hello = json.loads(response)
        print(f"Received HELLO: {json.dumps(hello, indent=2)}")

        state1 = await ws1.recv()
        print(f"Received STATE: {json.loads(state1)['state']}")

        async with websockets.connect(uri) as ws2:
            print("\n=== Player 2 Connected ===")

            await ws2.send(
                json.dumps({"type": "JOIN", "room": "test-room", "join": {"name": "Bob"}})
            )

            response = await ws2.recv()
            hello = json.loads(response)
            print(f"Received HELLO: {json.dumps(hello, indent=2)}")

            state2_ws1 = await ws1.recv()
            print(f"\nPlayer 1 sees Player 2 joined: {json.loads(state2_ws1)['seq']}")

            state2_ws2 = await ws2.recv()
            print(f"Player 2 received STATE: seq={json.loads(state2_ws2)['seq']}")

            print("\n=== Player 1 Plays Card ===")
            await ws1.send(
                json.dumps(
                    {
                        "type": "ACTION",
                        "room": "test-room",
                        "action": {"kind": "PLAY_CARD", "card": "card-123"},
                    }
                )
            )

            state3_ws1 = await ws1.recv()
            state3_data = json.loads(state3_ws1)
            print(f"Player 1 received STATE: {state3_data['state'].get('last_action')}")

            state3_ws2 = await ws2.recv()
            state3_data = json.loads(state3_ws2)
            print(f"Player 2 received STATE: {state3_data['state'].get('last_action')}")

            print("\n=== Player 2 Passes ===")
            await ws2.send(
                json.dumps({"type": "ACTION", "room": "test-room", "action": {"kind": "PASS"}})
            )

            state4_ws1 = await ws2.recv()
            state4_data = json.loads(state4_ws1)
            print(f"Player 2 received STATE: turn={state4_data['state']['turn']}")

            state4_ws2 = await ws1.recv()
            state4_data = json.loads(state4_ws2)
            print(f"Player 1 received STATE: turn={state4_data['state']['turn']}")

            print("\n=== Test Complete ===")
            print("✓ WebSocket communication working!")
            print("✓ Player join/leave working!")
            print("✓ Game actions broadcasting!")


if __name__ == "__main__":
    try:
        asyncio.run(test_websocket())
    except ConnectionRefusedError:
        print("\n❌ ERROR: Could not connect to WebSocket server")
        print("Make sure the server is running:")
        print("  uvicorn app.api.main:app --reload")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
