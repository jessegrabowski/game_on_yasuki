#!/usr/bin/env python3
"""
Simple test script to verify the FastAPI backend is working.

Run the server first:
    uvicorn app.api.main:app --reload

Then run this script:
    python test_api.py
"""

import requests
import json

BASE_URL = "http://localhost:8000"


def test_health():
    """Test health endpoint"""
    print("\n=== Testing Health Endpoint ===")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200


def test_list_cards():
    """Test listing cards"""
    print("\n=== Testing List Cards ===")
    response = requests.get(f"{BASE_URL}/api/cards?limit=5")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Found {data['total']} total cards")
    print(f"Returning {len(data['cards'])} cards")
    if data["cards"]:
        print(f"First card: {data['cards'][0].get('name', 'Unknown')}")


def test_search_cards():
    """Test searching cards"""
    print("\n=== Testing Search Cards ===")
    response = requests.get(f"{BASE_URL}/api/cards?search=dragon")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Found {data['total']} cards matching 'dragon'")


def test_create_room():
    """Test creating a game room"""
    print("\n=== Testing Create Room ===")
    response = requests.post(
        f"{BASE_URL}/api/rooms", json={"room_name": "Test Game", "max_players": 2}
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Created room: {data['room_id']}")
    print(f"Room name: {data['room']['name']}")
    print(f"WebSocket URL: {data['websocket_url']}")
    return data["room_id"]


def test_list_rooms():
    """Test listing available rooms"""
    print("\n=== Testing List Rooms ===")
    response = requests.get(f"{BASE_URL}/api/rooms")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Found {data['count']} available rooms")


def test_get_room(room_id):
    """Test getting room details"""
    print(f"\n=== Testing Get Room {room_id} ===")
    response = requests.get(f"{BASE_URL}/api/rooms/{room_id}")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Room: {json.dumps(data['room'], indent=2)}")


def main():
    print("=" * 60)
    print("FastAPI Backend Test Suite")
    print("=" * 60)

    try:
        test_health()
        test_list_cards()
        test_search_cards()
        room_id = test_create_room()
        test_list_rooms()
        test_get_room(room_id)

        print("\n" + "=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Open http://localhost:8000/docs to see interactive API docs")
        print("2. Test WebSocket with app/api/test_websocket.py")
        print("3. Start building the web frontend!")

    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to server")
        print("Make sure the server is running:")
        print("  uvicorn app.api.main:app --reload")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
