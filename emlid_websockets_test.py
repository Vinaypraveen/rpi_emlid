import websocket
import threading
import socket
import time
import json
import requests

# Define the WebSocket URL
ws_url = "ws://192.168.2.15/socket.io/?EIO=3&transport=websocket"

# Set the IP address and port of the Android device
android_ip = "192.168.144.100"  # Replace with your Android device's IP address
android_port = 14552

# Set the UDP listener port for receiving messages from Android
listener_port = 14553

# Create a UDP socket for sending data to Android
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Define the URL for the POST request endpoint
post_url = "http://192.168.2.15/configuration/logging/logs"

# Define the payload for the POST request
post_payload = {
    "started": False,
    "raw": {
        "enabled": True,
        "format": "RINEX",
        "rinex_options": {
            "logging_interval": 1,
            "preset": "custom",
            "satellite_systems": {
                "gps": True,
                "glonass": True,
                "galileo": True,
                "beidou": True,
                "qzss": True,
                "sbas": True
            },
            "time_adjustments_enabled": True
        },
        "version": "3.04"
    }
}


def perform_post_request(started):
    """
    Send a POST request to update logging status.
    :param started: Boolean indicating whether logging is started or stopped.
    """
    try:
        # Modify the post_payload with the current status
        post_payload["started"] = started
        
        # Send the POST request
        response = requests.post(post_url, json=post_payload)
        if response.status_code == 200:
            status = "started" if started else "stopped"
            print(f"Logging {status} successfully!")
            print("Response:", response.json())
        else:
            print(f"Failed to update logging. HTTP {response.status_code}")
            print("Response:", response.text)
    except requests.exceptions.RequestException as e:
        print("Error:", e)


def listen_for_commands():
    """
    Listen for 'stop' and 'start' messages from Android on a UDP socket.
    """
    listener_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener_sock.bind(("0.0.0.0", listener_port))  # Bind to all interfaces on listener_port
    print(f"Listening for 'stop' and 'start' messages on port {listener_port}...")
    try:
        while True:
            data, addr = listener_sock.recvfrom(1024)  # Buffer size of 1024 bytes
            message = data.decode('utf-8').strip()
            print(f"Received message: '{message}' from {addr}")
            if message == "stop":
                print("Received 'stop' command from Android.")
                perform_post_request(started=False)  # Perform the POST request with "started": False
            elif message == "start":
                print("Received 'start' command from Android.")
                perform_post_request(started=True)  # Perform the POST request with "started": True
    except Exception as e:
        print(f"Error in listener: {e}")
    finally:
        listener_sock.close()


def send_ping(ws, interval=6):
    """
    Send '2' (Socket.IO ping) periodically to keep the connection alive.
    """
    try:
        while True:
            ws.send("2")  # Send Socket.IO ping
            print("Sent ping: 2")
            time.sleep(interval)
    except Exception as e:
        print("Error sending ping:", e)


def on_message(ws, message):
    """
    Handle incoming messages and extract 'active_logs' and 'time_marks' information.
    """
    try:
        # Check if the message starts with '42', which is the Socket.IO event format
        if message.startswith("42"):
            payload = json.loads(message[2:])
            event_name = payload[0]
            data = payload[1]

            if event_name == "broadcast" and data.get("name") == "active_logs":
                payload = data["payload"]
                raw_log = payload.get("raw", {})
                recording_time = raw_log.get("recording_time")
                file_name = payload.get("archive_name")

                if recording_time is not None and file_name:
                    print(f"Recording Time: {recording_time:.2f}s, File Name: {file_name}")

                    # Send the message via UDP to Android
                    message = f"File Name: {file_name}\n Recording Time: {recording_time:.2f}s"
                    try:
                        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                        print(f"Sent to Android: {message.strip()}")
                    except Exception as e:
                        print(f"Error sending to Android: {e}")

            elif event_name == "broadcast" and data.get("name") == "time_marks":
                payload = data["payload"]
                print("Filtered time_marks:")
                for mark in payload:
                    count = mark.get("count", "N/A")
                    last_time = mark.get("last_time", "N/A")
                    print(f"  Count: {count}, Last Time: {last_time}")
                print("-" * 50)

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"Error processing message: {message}, Error: {e}")


def on_open(ws):
    """
    Called when the WebSocket connection is opened.
    Starts the keep-alive thread to send periodic pings.
    """
    print("Connection opened")
    threading.Thread(target=send_ping, args=(ws,), daemon=True).start()


def on_close(ws, close_status_code, close_msg):
    """
    Called when the WebSocket connection is closed.
    """
    print(f"Connection closed: {close_status_code}, {close_msg}")


def on_error(ws, error):
    """
    Called when there is an error in the WebSocket connection.
    """
    print("Error:", error)


def main():
    """
    Main function to establish the WebSocket connection and handle events.
    """
    # Start the UDP listener in a separate thread
    listener_thread = threading.Thread(target=listen_for_commands, daemon=True)
    listener_thread.start()

    # Create the WebSocket connection
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error
    )

    try:
        ws.run_forever()
    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        # Close the UDP socket when the program exits
        udp_sock.close()
        print("UDP socket closed.")


if __name__ == "__main__":
    main()
