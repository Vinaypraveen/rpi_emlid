import websocket
import threading
import socket
import time
import json
import requests
import os
import zipfile
import subprocess
import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, send_file
import simplekml
from datetime import datetime, timedelta, timezone
import pytz
import shutil
import serial
import RPi.GPIO as GPIO
from dronekit import connect,Command

ws_url = "ws://192.168.2.15/socket.io/?EIO=3&transport=websocket"
android_ip = "192.168.144.100"
android_port = 14552
listener_port = 14553
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
post_url = "http://192.168.2.15/configuration/logging/logs"
base_url = "http://192.168.2.15"
last_time_marks_last_time = None
archive_name_global = None
Compressing_log_name = None
generated_image_path = None
log_start_time = None

# Servo configuration
SERVO_PIN = 18
PWM_FREQUENCY = 50  # 50Hz PWM frequency
shutter_open = 2550  # Max PWM value in microseconds
shutter_close = 700  # Min PWM value in microseconds

# Initialize GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
pwm = GPIO.PWM(SERVO_PIN, PWM_FREQUENCY)
pwm.start(0)

Payload_Serial_Port = '/dev/ttyAMA0'
Payload_Baud_Rate = 115200

Pixhawk_Port = '/dev/ttyACM0'
Pixhawk_Baud_Rate = 115200

Payload_connection = None
connection = None

Mission_download_alt = 8
Shutter_alt = 4

payload_lock = threading.Lock()

serial_number = 1  # Initialize serial number
current_file_name = None  # Track the current file name
image_taken_at = None

app = Flask(__name__)
destination_dir = "/home/vinlee/Desktop/Emlid_log_files"

if not os.path.exists(destination_dir):
    os.makedirs(destination_dir)

post_payload = {
    "started": False,
}

last_sent_times = {
    "navigation": 0,
    "storage_status": 0
}

update_intervals = {
    "navigation": 2,
    "storage_status": 5
}

reboot_payload = [
            "action",
            {
                "name": "reboot"
            }
        ]

def set_servo(position):
    #set_servo("open")
    #set_servo("close")
    try:
        if position == "open":
            duty_cycle = (shutter_open / 20000.0) * 100  # Convert microseconds to duty cycle
        elif position == "close":
            duty_cycle = (shutter_close / 20000.0) * 100  # Convert microseconds to duty cycle
        else:
            print("Invalid position. Use 'open' or 'close'.")
            return
        pwm.ChangeDutyCycle(duty_cycle)
        time.sleep(1)  # Allow servo to stabilize
        pwm.ChangeDutyCycle(0)  # Stop sending PWM to reduce jitter
    except Exception as e:
        print(f"Error: {e}")

def listen_to_arduino():
    global Payload_connection, archive_name_global, destination_dir, connection, serial_number, current_file_name,image_taken_at
    try:
        while True:
            if Payload_connection and Payload_connection.in_waiting > 0:
                data = Payload_connection.readline().decode('utf-8').strip()
                if data.startswith("Timestamp:"):
                    print(data)
                    # Immediately fetch the heading from Pixhawk
                    heading = None
                    if connection is not None:
                        try:
                            heading = connection.heading
                        except Exception as e:
                            print(f"Error fetching heading from Pixhawk: {e}")
                    
                    if image_taken_at:
                        print("image Captured")
                        send_to_pixhawk("Image Captured",5)
                        image_taken_at = None

                    if archive_name_global:
                        # Decode the Arduino message
                        decoded_values = decode_arduino_message(data)
                        if decoded_values:
                            timestamp = decoded_values.get("Timestamp")
                            yaw = decoded_values.get("Yaw")
                            roll = decoded_values.get("Roll")
                            pitch = decoded_values.get("Pitch")
                            
                            # Prepare the file for writing
                            temp_file_name = archive_name_global.replace(".zip", "")
                            temp_file_name = f"{temp_file_name}_rotational_values.txt"
                            temp_file_path = os.path.join(destination_dir, temp_file_name)

                            # Check if the file name has changed
                            if current_file_name != temp_file_name:
                                current_file_name = temp_file_name
                                serial_number = 1  # Reset serial number for the new file

                            # Create file with header if it doesn't exist
                            if not os.path.exists(temp_file_path):
                                with open(temp_file_path, "w") as temp_file:
                                    temp_file.write("Serial Number,Timestamp,Pitch,Roll,Yaw,Heading\n")

                            # Write data to the file
                            with open(temp_file_path, "a") as temp_file:
                                if heading is not None:
                                    # Write with heading
                                    temp_file.write(f"{serial_number},{timestamp},{pitch},{roll},{yaw},{heading:.2f}\n")
                                    print(f"Serial: {serial_number}, Timestamp: {timestamp}, Yaw: {yaw}, Roll: {roll}, Pitch: {pitch}, Heading: {heading:.2f}")
                                else:
                                    # Write without heading (original IMU values)
                                    temp_file.write(f"{serial_number},{timestamp},{pitch},{roll},{yaw}\n")
                                    print(f"Serial: {serial_number}, Timestamp: {timestamp}, Yaw: {yaw}, Roll: {roll}, Pitch: {pitch}")
                                serial_number += 1  # Increment serial number
            time.sleep(0.01)  # Reduce CPU usage
    except Exception as e:
        print(f"Error in listener thread: {e}")

def decode_arduino_message(message):
    try:
        values = {}
        parts = message.split(",")
        for part in parts:
            key, value = part.split(":")
            key = key.strip()
            value = float(value.strip()) if key != "Timestamp" else int(value.strip())
            values[key] = value
        return values
    except Exception as e:
        print(f"Failed to decode message: {message}. Error: {e}")
        return None

def send_to_pixhawk(message: str, severity: int):
    """
    Sends a message to the Pixhawk via MAVLink with a specified severity.

    Severity levels:
    0: Emergency   - shows pop-up in QGC & voice prompt
    1: Alert       - shows pop-up in QGC & voice prompt
    2: Critical    - shows pop-up in QGC & voice prompt
    3: Error       - shows pop-up in QGC & voice prompt
    4: Warning     - shows pop-up in QGC & voice prompt
    5: Notice      - only voice prompt
    6: Info        - just in logs
    7: Debug       - just in logs
    """
    global connection  # Ensure 'vehicle' is available globally

    try:
        # Check if the vehicle connection is valid
        if connection is None:
            print("Vehicle connection is not established or not ready.")
            establish_connection(retries=10, delay=10)
            send_to_pixhawk(message, severity)
            return

        if not (0 <= severity <= 7):
            print("Invalid severity level. Must be between 0 (Emergency) and 7 (Debug).")
            return

        if len(message) > 50:
            print(f"Message is too long. Truncating to 50 characters: {message[:50]}")
            message = message[:50]

        msg = connection.message_factory.statustext_encode(
            severity,                # Severity level
            message.encode('utf-8')  # Message string (encoded in UTF-8)
        )
        connection.send_mavlink(msg)
        connection.flush()  # Ensure the message is sent immediately
        print(f"Message sent: '{message}' with severity {severity}")

    except Exception as e:
        print(f"Error while sending message: {e}")

def establish_Payload_connection(retries=5, delay=5):
    global Payload_connection, Payload_Serial_Port, Payload_Baud_Rate
    for attempt in range(retries):
        try:
            print(f"Attempt {attempt + 1}/{retries} to connect to payload...")
            Payload_connection = serial.Serial(Payload_Serial_Port, Payload_Baud_Rate, timeout=1)
            if Payload_connection.is_open:
                print(f"Connected to {Payload_Serial_Port} at {Payload_Baud_Rate} baud")
                return Payload_connection
        except Exception as e:
            print(f"Failed to connect on attempt {attempt + 1}: {e}")
        time.sleep(delay)
    print("Reconnection failed after multiple attempts.")
    return None

def establish_connection(retries=5, delay=5):
    global connection
    for attempt in range(1, retries + 1):
        try:
            print(f"Connecting to vehicle on: /dev/ttyACM0, Attempt {attempt}")
            connection = connect('/dev/ttyACM0', wait_ready=True, baud=921600,source_system=1,timeout=60)
            time.sleep(5)
            if connection:
                print("connected")
                return connection
        except Exception as e:
            print(f"Connection attempt {attempt} failed: {e}")
            if attempt < retries:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print("All connection attempts failed.")
    return None

@app.route('/download_image', methods=['GET'])
def download_image():
    global generated_image_path
    
    # Retry mechanism to check for hardware reconnection
    retries = 3  # Number of retries before failing
    retry_delay = 2  # Delay between retries (in seconds)

    while retries > 0:
        if generated_image_path and os.path.exists(generated_image_path):
            # Extract the original filename
            original_filename = os.path.basename(generated_image_path)
            # Add Content-Disposition header to specify the filename
            return send_file(
                generated_image_path,
                as_attachment=True,
                download_name=original_filename  # Ensure filename is passed in the header
            )
        else:
            print("Image not available or path is invalid. Retrying...")
            time.sleep(retry_delay)
            retries -= 1

    # After retries, return an error if the image is still not available
    return "Image not available yet or path is invalid.", 404

def check_logging_status():
    try:
        response = requests.get(post_url)
        if response.status_code == 200:
            data = response.json()
            return data.get("started", False)
        else:
            print(f"Failed to fetch logging status. HTTP {response.status_code}")
    except requests.exceptions.RequestException as e:
        print("Error checking logging status:", e)
    return False

def perform_post_request(started):
    try:
        post_payload["started"] = started
        response = requests.post(post_url, json=post_payload)
        if response.status_code == 200:
            if started:
                log_feedback = "Logging started"
                send_to_pixhawk(log_feedback,5)
            else:
                log_feedback = "Logging stopped"
                send_to_pixhawk(log_feedback,5)
            return f"log_feedback, {log_feedback}"
        
        else:
            print(f"Failed to update logging. HTTP {response.status_code}")
            send_to_pixhawk("Failed to update logging",3)
            return "log_feedback,Failed to update logging"
        
    except requests.exceptions.RequestException as e:
        print("Error performing POST request:", e)
        send_to_pixhawk("Error updating logging status",3)
        return "log_feedback,Error updating logging status"

def get_log_by_name(log_name, timeout=30):
    logs_url = f"{base_url}/logs"
    start_time = time.time()
    retry_interval = 1  # Time to wait between retries (in seconds)

    while True:
        try:
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout:
                print(f"Timeout reached: Could not find log '{log_name}' within {timeout} seconds.")
                message = f"log_feedback,Timeout reached: Log '{log_name}' not found."
                send_to_pixhawk(f"Log not found",3)
                udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                return None

            # Make the request to fetch logs
            response = requests.get(logs_url)
            response.raise_for_status()
            logs_data = response.json()

            # Search for the log entry
            for log_entry in logs_data:
                if log_entry['name'] == log_name:
                    message = f"log_feedback,Downloading Log : {log_entry['name']}"
                    send_to_pixhawk(f"Downloading Log",6)
                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                    return log_entry
            time.sleep(0.1)

        except requests.exceptions.RequestException as e:
            print(f"Error fetching logs: {e}. Retrying in {retry_interval} seconds...")
            message = f"log_feedback,Error fetching logs. Retrying..."
            udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))

        # Wait before retrying
        time.sleep(retry_interval)

def process_log(Compressing_log_name):
    print(Compressing_log_name)
    global generated_image_path, log_start_time, destination_dir

    if Compressing_log_name.startswith("Reach_"):
        date_time_str = Compressing_log_name.split("Reach_")[1]
        log_datetime_gmt = datetime.strptime(date_time_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        log_start_time = log_datetime_gmt + timedelta(hours=5, minutes=30)
        print(f"Extracted Date and Time: {log_start_time}")
        date_folder = os.path.join(destination_dir, log_start_time.strftime("%d-%m-%Y"))
        time_folder = os.path.join(date_folder, log_start_time.strftime("%I-%M-%S %p"))  # 12-hour format with AM/PM
        
        # Check and create date folder if not exists
        if not os.path.exists(date_folder):
            os.makedirs(date_folder)
            print(f"Created date folder: {date_folder}")
        
        # Check and create time folder if not exists
        if not os.path.exists(time_folder):
            os.makedirs(time_folder)
            print(f"Created time folder: {time_folder}")
    else:
        print("Invalid log name format.")
        return

    # Handle the temporary file
    temp_file_name = f"{Compressing_log_name}_rotational_values.txt"
    temp_file_path = os.path.join("/home/vinlee/Desktop/Emlid_log_files", temp_file_name)
    
    # Check if the temporary file exists
    if os.path.exists(temp_file_path):
        # Move the file (cut and paste)
        destination_path = os.path.join(time_folder, temp_file_name)
        shutil.move(temp_file_path, destination_path)
        print(f"Moved {temp_file_name} to {destination_path}")
    else:
        print(f"Temporary file {temp_file_name} not found.")

    log_name = Compressing_log_name + ".zip"
    log_entry = get_log_by_name(log_name)
    if not log_entry:
        print("Log not found.")
        return
    extract_to_dir,Log_IST_start_time,Log_recording_time,log_name = download_log_resumable(log_entry, time_folder)
    if not extract_to_dir:
        message = f"log_feedback,Downloaded File is Corrupted"
        send_to_pixhawk("Downloaded File is Corrupted",3)
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
        return

    rinex_files = find_rinex_files(extract_to_dir)
    run_rnx2rtkp_command(rinex_files, extract_to_dir, log_name)
    events_file_path = find_events_pos_file(extract_to_dir, log_name)
    if events_file_path is not None:
        csv_path, image_path = process_positions_and_generate_outputs(events_file_path,Log_IST_start_time,Log_recording_time,log_name)
        if image_path is not None:
            generated_image_path = image_path  # Update the global path
            time.sleep(1)
            message = f"log_feedback,Download the Image"
            send_to_pixhawk("Download the Image",5)
            udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
            print(f"Image path updated to: {generated_image_path}")
            time.sleep(2)
             # Copy processed files to the pendrive
            copy_to_pendrive(log_start_time)
            
def copy_to_pendrive(log_start_time):
    pendrive_path = pendrive__check_and_copy_path()
    date_folder = os.path.join(destination_dir, log_start_time.strftime("%d-%m-%Y"))
    time_folder = os.path.join(date_folder, log_start_time.strftime("%I-%M-%S %p"))

    if not os.path.exists(time_folder):
        print(f"Source folder does not exist: {time_folder}")
        message = f"log_feedback,Source folder does not exist"
        send_to_pixhawk("Source folder does not exist",3)
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
        return

    if not pendrive_path:
        print("Pendrive path not detected. Aborting copy process.")
        message = f"log_feedback,Pendrive not attached"
        send_to_pixhawk("Pendrive not attached",3)
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
        return

    # Derive pendrive_target using relative paths
    pendrive_target = os.path.join(pendrive_path, os.path.relpath(time_folder, destination_dir))

    try:
        for root, dirs, files in os.walk(time_folder):
            for file in files:
                src_file_path = os.path.join(root, file)
                relative_path = os.path.relpath(root, time_folder)
                dest_dir = os.path.join(pendrive_target, relative_path)
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)
                shutil.copy2(src_file_path, os.path.join(dest_dir, file))
                print(f"Copied {file} to {os.path.join(dest_dir, file)}")

        print(f"Files copied to pendrive at: {pendrive_target}")
        message = f"log_feedback,Log saved to Pendrive"
        send_to_pixhawk("Log saved to Pendrive",5)
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
    except Exception as e:
        print(f"Error copying files to pendrive: {e}")
        message = f"log_feedback,Error saving to Pendrive"
        send_to_pixhawk("Error saving to Pendrive",3)
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))

def pendrive__check_and_copy_path():
    # Define the mount point
    mount_point = "/media/vinlee"

    # Check if the mount point exists
    if os.path.exists(mount_point):
        # Get a list of directories in the mount point
        directories = [os.path.join(mount_point, d) for d in os.listdir(mount_point) if os.path.isdir(os.path.join(mount_point, d))]
        if directories:
            for directory in directories:
                emlid_logs_path = os.path.join(directory, "Emlid Logs")
                if not os.path.exists(emlid_logs_path):
                    # Create the folder if it doesn't exist
                    os.makedirs(emlid_logs_path)
                    print(f"'Emlid Logs' folder created at: {emlid_logs_path}")
                else:
                    print(f"'Emlid Logs' folder already exists at: {emlid_logs_path}")
                return emlid_logs_path
        else:
            print("No directories found in the pendrive.")
            return None
    else:
        print("No pendrive attached.")
        return None

def extract_zip_file(zip_path, extract_to_dir):
    try:
        # If the extraction directory exists, remove it and its contents
        if os.path.exists(extract_to_dir):
            print(f"Directory '{extract_to_dir}' already exists. Deleting it.")
            for root, dirs, files in os.walk(extract_to_dir, topdown=False):
                for file in files:
                    os.remove(os.path.join(root, file))
                for dir in dirs:
                    os.rmdir(os.path.join(root, dir))
            os.rmdir(extract_to_dir)

        # Create a fresh directory for extraction
        os.makedirs(extract_to_dir)

        # Extract the ZIP file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to_dir)
            print(f"Extracted all files to '{extract_to_dir}'.")

    except zipfile.BadZipFile:
        print(f"Error: '{zip_path}' is not a valid ZIP file.")
    except Exception as e:
        print(f"Error during extraction: {e}")

def download_log_resumable(log_entry, destination_dir):
    if log_entry is None:
        print("No log entry provided. Exiting download process.")
        return

    log_id = log_entry['id']
    download_url = f"{base_url}/logs/download/{log_id}"

    # Extract and print the required fields
    log_name = log_entry['name']
    start_time_value = log_entry['start_time']
    total_size = log_entry['size']
    recording_time = log_entry['recording_time']

    utc_time = datetime.fromtimestamp(float(start_time_value), pytz.utc)  # Convert to UTC
    ist_time = utc_time.astimezone(pytz.timezone("Asia/Kolkata"))  # Convert to UTC+5:30
    Log_IST_start_time = ist_time.strftime('%d-%m-%y %H:%M:%S')

    Log_recording_time = str(timedelta(seconds=int(recording_time)))


    print("\nLog Details:")
    print(f"Name: {log_name}")
    print(f"Start Time: {Log_IST_start_time}")
    print(f"Size: {total_size} bytes")
    print(f"Recording Time: {Log_recording_time}\n")

    # Construct the full file path
    destination_path = os.path.join(destination_dir, log_name)

    # Delete the existing file if it exists
    if os.path.exists(destination_path):
        print(f"File '{destination_path}' already exists. Deleting it.")
        os.remove(destination_path)

    try:
        start_time = time.time()  # Start the timer
        total_downloaded = 0

        with requests.get(download_url, stream=True) as response:
            response.raise_for_status()

            with open(destination_path, 'wb') as file:  # Open in write mode to start fresh
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # Filter out keep-alive chunks
                        file.write(chunk)
                        total_downloaded += len(chunk)
                        # Calculate progress
                        progress_percentage = (total_downloaded / total_size) * 100
                        progress_message = (f"Downloaded {total_downloaded / 1048576:.2f} MB "
                                            f"of {total_size / 1048576:.2f} MB "
                                            f"({progress_percentage:.2f}%)")
                        print(progress_message, end='\r')

                        # Send progress message via UDP
                        udp_message = f"log_feedback,{progress_message}"
                        udp_sock.sendto(udp_message.encode('utf-8'), (android_ip, android_port))

        end_time = time.time()  # End the timer
        print(f"\n\nLog file '{log_name}' downloaded successfully")
        print(f"Total download time: {end_time - start_time:.2f} seconds")
        message = f"Total download time: {end_time - start_time:.2f} seconds"
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
        time.sleep(1)
        # Extract the ZIP file
        extract_to_dir = os.path.join(destination_dir, log_name.replace('.zip', ''))
        extract_zip_file(destination_path, extract_to_dir)

        return extract_to_dir,Log_IST_start_time,Log_recording_time,log_name

    except requests.exceptions.RequestException as e:
        print(f"Error downloading log '{log_name}': {e}")
        return None

def run_rnx2rtkp_command(rinex_files, output_dir, log_name):
    if not rinex_files["24O"] or not rinex_files["24P"]:
        print("Required RINEX files (.24O or .24P) not found. Cannot run rnx2rtkp.")
        return

    # Define the output file path dynamically based on the log name
    output_file = os.path.join(output_dir, log_name.replace('.zip', '.pos'))

    # Build the command
    command = [
        "rnx2rtkp",
        "-k", "/home/vinlee/rpi_emlid/emlid_rpi.conf",
        "-o", output_file,
        rinex_files["24O"],
        rinex_files["24P"]
    ]

    #print(f"Running command: {' '.join(command)}")
    print("Running rnx2rtkp")

    try:
        # Run the command
        subprocess.run(command, check=True)
        print(f"rnx2rtkp done at '{output_file}'.")
        message = f"log_feedback,Log Processed Succesfully"
        send_to_pixhawk("Log Processed",6)
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
    except subprocess.CalledProcessError as e:
        print(f"Error running rnx2rtkp: {e}")
    except FileNotFoundError:
        print("Error: rnx2rtkp command not found. Ensure it is installed and in your PATH.")

def find_rinex_files(directory):
    rinex_files = {"24O": None, "24P": None}
    ubx_file = None

    # Look for .ubx file first
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".UBX"):
                ubx_file = os.path.join(root, file)
                break  # Only process the first .ubx file found

    if ubx_file:
        print(f"Found .ubx file: {ubx_file}")
        base_name = os.path.splitext(ubx_file)[0]  # Remove .ubx extension
        output_24o = f"{base_name}.24O"
        output_24p = f"{base_name}.24P"

        # Run convbin command
        try:
            subprocess.run([
                "convbin", ubx_file,
                "-r", "ubx",
                "-o", output_24o,
                "-n", output_24p
            ], check=True)

            rinex_files["24O"] = output_24o
            rinex_files["24P"] = output_24p
            print(f"Generated .24O file: {output_24o}")
            print(f"Generated .24P file: {output_24p}")
        except subprocess.CalledProcessError as e:
            print(f"Error during conversion with convbin: {e}")
    else:
        # If no .ubx file is found, search for .24O and .24P files
        print("No .ubx file found. Searching for .24O and .24P files.")
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".24O"):
                    rinex_files["24O"] = os.path.join(root, file)
                elif file.endswith(".24P"):
                    rinex_files["24P"] = os.path.join(root, file)
    #Delete UBX File
    if ubx_file:
        if os.path.exists(ubx_file):
            # Delete the file
            os.remove(ubx_file)
            print(f"File {ubx_file} has been deleted.")
        else:
            print(f"The file {ubx_file} does not exist.")

    if rinex_files["24O"]:
        print(f"Found .24O file: {rinex_files['24O']}")
    else:
        print("No .24O file found.")

    if rinex_files["24P"]:
        print(f"Found .24P file: {rinex_files['24P']}")
    else:
        print("No .24P file found.")

    return rinex_files

def find_events_pos_file(directory, log_name):
    expected_file_name = log_name.replace('.zip', '_events.pos')

    for root, _, files in os.walk(directory):
        for file in files:
            if file == expected_file_name:
                file_path = os.path.join(root, file)
                print(f"Found events file: {file_path}")
                return file_path

    print(f"Events file '{expected_file_name}' not found.")
    message = f"Events file not found"
    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
    return None

def process_positions_and_generate_outputs(file_path,Log_IST_start_time,Log_recording_time,log_name):
    base_filename = os.path.basename(file_path).replace('_events.pos', '')
    output_csv_path = os.path.join(os.path.dirname(file_path), f"{base_filename}.csv")
    output_image_path = os.path.join(os.path.dirname(file_path), f"{base_filename}.png")
    output_kml_path = os.path.join(os.path.dirname(file_path), f"{base_filename}.kml")
    
    header_line = 13
    columns = [
        "GPST", "Latitude", "Longitude", "Height", "Q", "ns", "sdn", "sde",
        "sdu", "sdne", "sdeu", "sdun", "age", "ratio"
    ]

    try:
        # Load the data, skipping bad lines
        data = pd.read_csv(
            file_path,
            delim_whitespace=True,
            skiprows=header_line + 1,
            names=columns,
            engine="python",
            on_bad_lines="skip",
        )
    except Exception as e:
        print(f"Error reading data: {e}")
        return

    # Clean and validate the data
    data = data.dropna(subset=["Latitude", "Longitude"])  # Drop rows with NaN values in Latitude or Longitude
    data["Latitude"] = pd.to_numeric(data["Latitude"], errors="coerce")  # Convert to numeric, invalid entries become NaN
    data["Longitude"] = pd.to_numeric(data["Longitude"], errors="coerce")  # Convert to numeric, invalid entries become NaN
    data = data.dropna(subset=["Latitude", "Longitude"])  # Drop rows with NaN after conversion

    if data.empty:
        print("No valid data to plot.")
        message = f"log_feedback,No valid data to plot"
        send_to_pixhawk("No valid data to plot",3)
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))

        return None,None

    latitudes = data["Latitude"]
    longitudes = data["Longitude"]

    # Save the cleaned data to a CSV
    locations_df = pd.DataFrame({"Latitude": latitudes, "Longitude": longitudes})
    locations_df.to_csv(output_csv_path, index=False)
    print(f"CSV saved to: {output_csv_path}")

    # Generate and save the scatter plot
    plt.figure(figsize=(14, 10), dpi=300)
    plt.scatter(longitudes, latitudes, s=4, color='red')
    plt.title(
        f"{log_name} , IMAGE COUNT : {len(latitudes)}\nDate & Time: {Log_IST_start_time}   Recording Time: {Log_recording_time}",
        fontsize=20,
        weight='bold'
    )
    plt.xlabel("Longitude", fontsize=12)
    plt.ylabel("Latitude", fontsize=12)
    plt.grid(True, which='both', linestyle='--', linewidth=0.2)
    plt.axis('equal')  # Enforce equal scaling for lat/lon
    plt.tight_layout()  # Ensure all elements fit properly
    plt.savefig(output_image_path, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"Image saved to: {output_image_path}")
    
    # Generate and save the KML file with the specified icon and color
    kml = simplekml.Kml()
    point_style = simplekml.Style()
    point_style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/pal2/icon18.png"  # Custom icon
    point_style.iconstyle.color = "ff0000ff"  # Correct ABGR format for #ffaa00
    point_style.iconstyle.scale = 0.3  # Smaller icon size

    for lat, lon in zip(latitudes, longitudes):
        pnt = kml.newpoint(coords=[(lon, lat)])  # Add each point to the KML file
        pnt.style = point_style  # Apply the custom style

    kml.save(output_kml_path)
    print(f"KML saved to: {output_kml_path}")

    return output_csv_path, output_image_path

def listen_for_commands():
    global archive_name_global
    global log_start_time
    listener_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener_sock.bind(("0.0.0.0", listener_port))
    print(f"Listening for 'stop' and 'start' messages on port {listener_port}...")

    try:
        while True:
            data, addr = listener_sock.recvfrom(1024)  # Buffer size of 1024 bytes
            message = data.decode('utf-8').strip()
            print(f"Received message: '{message}' from {addr}")

            if message in ["start", "stop", "reboot", "copy"]:
                is_running = check_logging_status()
                if message == "start":
                    if is_running:
                        feedback = "log_feedback,Log is already running"
                        send_to_pixhawk("Log is already running",5)
                        udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
                        print(feedback)
                    else:
                        feedback = perform_post_request(started=True)
                        udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
                        print(feedback)
                elif message == "stop":
                    if not is_running:
                        feedback = "log_feedback,Log is not running"
                        send_to_pixhawk("Log is not running",5)
                        udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
                        print(feedback)
                    else:
                        feedback = perform_post_request(started=False)
                        udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
                        print(feedback)
                elif message == "reboot":
                    try:
                        json_payload = json.dumps(reboot_payload) 
                        json_payload = f"42{json_payload}"       
                        ws.send(json_payload)
                        print("Reboot command sent:", json_payload)
                        feedback = "log_feedback,Emlid is rebooting"
                        send_to_pixhawk("Emlid is rebooting",5)
                        udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
                    except Exception as e:
                        print("Error sending reboot command:", e)
                elif message == "copy":
                    if log_start_time == None:
                        feedback = "log_feedback,Log is not available for copy"
                        send_to_pixhawk("Log is not available for copy",5)
                        udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
                        print(feedback)
                    else:
                        copy_to_pendrive(log_start_time)
            time.sleep(0.01)

    except Exception as e:
        print(f"Error in listener: {e}")
    finally:
        listener_sock.close()

def on_message(ws, message):
    global last_sent_times, last_time_marks_last_time,archive_name_global,Compressing_log_name
    try:
        if message.startswith("42"):
            payload = json.loads(message[2:])
            event_name = payload[0]
            data = payload[1]
            current_time = time.time()

            if event_name == "broadcast" and data.get("name") == "active_logs" and  len(message) > 100:
                payload = data["payload"]
                raw_log = payload.get("raw", {})
                archive_name = payload.get("archive_name")
                archive_name_global = archive_name + ".zip"
                recording_time = raw_log.get("recording_time")
                remaining_time = raw_log.get("remaining_time")
                size = raw_log.get("size")
                size = round(size/1024/1024,1)
                file_format = raw_log.get("format")
                message = f"active_logs,{archive_name},{recording_time:.2f},{remaining_time:.2f},{size:.1f} MB,{file_format}"
                udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                #print(message)

            elif event_name == "broadcast" and data.get("name") == "time_marks":
                payload = data["payload"]
                first_object = payload[0]
                count = first_object.get("count")
                last_time = first_object.get("last_time")
                if last_time != last_time_marks_last_time:
                    message = f"time_marks,{count},{last_time}"
                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                    #print(message)
                    last_time_marks_last_time = last_time

            elif event_name == "broadcast" and data.get("name") == "navigation":
                if current_time - last_sent_times["navigation"] >= update_intervals["navigation"]:
                    payload = data["payload"]
                    dop = payload.get("dop", {})
                    rover_position = payload.get("rover_position", {})
                    coordinates = rover_position.get("coordinates", {})
                    lat = round(coordinates.get("lat" ,0),9)
                    lon = round(coordinates.get("lon",0),9)
                    height = round(coordinates.get("h",0),2)
                    satellites = payload.get("satellites", {})
                    g = round(dop.get("g"),2)
                    p = round(dop.get("p"),2)
                    h = round(dop.get("h"),2)
                    v = round(dop.get("v"),2)
                    rover = satellites.get("rover")
                    valid = satellites.get("valid")
                    positioning_mode = payload.get("positioning_mode", "unknown")
                    solution = payload.get("solution", "unknown")

                    message = f"navigation,{g:.2f},{p:.2f},{h:.2f},{v:.2f},{rover},{valid},{positioning_mode},{solution},{lat},{lon},{height}"

                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                    #print(message)
                    last_sent_times["navigation"] = current_time

            elif event_name == "broadcast" and data.get("name") == "storage_status":
                if current_time - last_sent_times["storage_status"] >= update_intervals["storage_status"]:
                    payload = data["payload"]
                    free = payload.get("free")
                    total = payload.get("total")
                    message = f"storage_status,{total} MB,{free} MB"
                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                    #print(message)
                    last_sent_times["storage_status"] = current_time

            elif event_name == "broadcast" and data.get("name") == "compressing_logs":
                global Compressing_log_name
                payload = data.get("payload", [])
                if not payload:
                    # If payload is empty, log is ready to download
                    if Compressing_log_name != None:
                        print(f"{Compressing_log_name} is ready to download")
                        message = f"log_feedback,compressing {Compressing_log_name} completed"
                        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                        process_log(Compressing_log_name)
                    else:
                        print("Compressing_log_name is None")
                        return
                else:
                    # If payload is not empty, print name and progress
                    for item in payload:
                        Compressing_log_name = item.get("name", "unknown")
                        progress = item.get("progress", 0)
                        print(f"Name: {Compressing_log_name}, Progress: {progress}")
                        message = f"log_feedback,Compressing log : {Compressing_log_name}, Progress: {progress} %"
                        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
        time.sleep(0.1)

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        pass
        #print(f"Error processing message: {message}, Error: {e}")

def start_flask_server():
    # Retry mechanism to handle hardware disconnection
    while True:
        try:
            app.run(host="192.168.144.20", port=5000, debug=False)
            #time.sleep(0.2)
        except Exception as e:
            print(f"Flask server encountered an error: {e}")
            print("Retrying to start Flask server...")
            time.sleep(2)  # Wait before retrying

def send_ping(ws, interval=6):
    try:
        while True:
            ws.send("2")
            time.sleep(interval)
    except Exception as e:
        print("Error sending ping:", e)

def on_open(ws):
    print("Connection opened")
    message = "log_feedback,Emlid Connected"
    send_to_pixhawk("Emlid Connected",5)
    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
    threading.Thread(target=send_ping, args=(ws,), daemon=True).start()

def on_close(ws, close_status_code, close_msg):
    print(f"Connection closed: {close_status_code}, {close_msg}")
    message = "log_feedback,Connection lost, retrying..."
    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
    print("Connection lost, retrying...")
    retry_connection()

def on_error(ws, error):
    print("Error:", error)
    message = "log_feedback,Connection lost, retrying..."
    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
    print("Connection lost, retrying...")
    retry_connection()

def retry_connection():
    global ws
    time.sleep(3)
    while True:
        try:
            # Attempt to reconnect
            print("Retrying connection to Reach...")
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_close=on_close,
                on_error=on_error
            )
            time.sleep(1)
            ws.run_forever()
            print("Reconnected successfully!")
            return  # Exit retry loop if connection is successful
        except Exception as e:
            print("Retry failed, waiting before next attempt:")
            time.sleep(5)  # Wait 5 seconds before retrying

def ping_ip(ip):
    """
    Ping a given IP address to check if it is reachable.
    Returns True if the ping is successful, False otherwise.
    """
    try:
        response = subprocess.run(
            ["ping", "-c", "1", ip] if os.name != "nt" else ["ping", "-n", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return response.returncode == 0
    except Exception as e:
        print(f"Error pinging IP {ip}: {e}")
        return False

def check_http_status(url):
    """
    Check if a given URL returns a 200 status code.
    Returns True if status code is 200, False otherwise.
    """
    try:
        response = requests.get(url)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Error checking HTTP status for {url}: {e}")
        return False

def wait_for_conditions(ip_list, url, retry_interval=3):
    while True:
        # Check ping for all IPs
        all_ips_success = all(ping_ip(ip) for ip in ip_list)

        # Check HTTP status for the specified URL
        url_success = check_http_status(url)

        if all_ips_success and url_success:
            print("All IPs are reachable, and the webpage is available. Proceeding with the program...")
            return

        if not all_ips_success:
            print(f"Ping check failed for one or more IPs. Retrying in {retry_interval} seconds...")

        if not url_success:
            print(f"Webpage check for {url} failed. Retrying in {retry_interval} seconds...")

        time.sleep(retry_interval)

def start_or_stop_logging(message):
    is_running = check_logging_status()
    if message == "start":
        if is_running:
            feedback = "log_feedback,Log is already running"
            send_to_pixhawk("Log is already running", 5)
            udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
            print(feedback)
        else:
            feedback = perform_post_request(started=True)
            udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
            print(feedback)
    elif message == "stop":
        if not is_running:
            feedback = "log_feedback,Log is not running"
            send_to_pixhawk("Log is not running", 5)
            udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
            print(feedback)
        else:
            feedback = perform_post_request(started=False)
            udp_sock.sendto(feedback.encode('utf-8'), (android_ip, android_port))
            print(feedback)

def trigger_camera(vehicle, relay_num=0):
    global image_taken_at
    image_taken_at = int(time.time())
    
    # Turn the relay ON
    print(f"Activating relay {relay_num}...")
    vehicle.message_factory.command_long_send(
        vehicle._master.target_system,  # Target system
        vehicle._master.target_component,  # Target component
        181,  # MAV_CMD_DO_SET_RELAY
        0,    # Confirmation
        relay_num,  # Relay number
        1,    # Relay state (1 = ON)
        0, 0, 0, 0, 0  # Unused parameters
    )
    print(f"Relay {relay_num} activated.")
    
    # Wait a short time
    time.sleep(0.1)
    
    # Turn the relay OFF
    print(f"Deactivating relay {relay_num}...")
    vehicle.message_factory.command_long_send(
        vehicle._master.target_system,  # Target system
        vehicle._master.target_component,  # Target component
        181,  # MAV_CMD_DO_SET_RELAY
        0,    # Confirmation
        relay_num,  # Relay number
        0,    # Relay state (0 = OFF)
        0, 0, 0, 0, 0  # Unused parameters
    )
    print(f"Image Captured.")

def start_websocket():
    global ws
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error
    )
    while True:
        try:
            ws.run_forever()
            time.sleep(0.5)
        except Exception as e:
            print(f"WebSocket error: {e}")
            time.sleep(5)  # Retry after delay

def monitor_drone():
    global Mission_download_alt, Shutter_alt, connection

    connection = establish_connection(retries=5, delay=5)

    print("Starting drone monitoring...")
    mission_downloaded = False
    logging_stopped = not check_logging_status()
    last_206_wp = None
    armed = False
    last_armed = True
    shutter_state = "opened"
    retries = 1

    while True:
        try:
            if connection:
                armed = connection.armed
                altitude = max(int(connection.location.global_relative_frame.alt), 0)
                current_waypoint = connection.commands.next
                #print(f"Armed: {armed}, altitude: {altitude}")
                time.sleep(0.1)
                
                if armed:
                    if altitude < Shutter_alt - 1 and shutter_state != "closed":
                        print("Camera Shutter Closed")
                        set_servo("close")
                        shutter_state = "closed"
                        time.sleep(1)
                    elif altitude >= Shutter_alt + 1 and shutter_state != "opened":
                        print("Camera Shutter Opened")
                        set_servo("open")
                        shutter_state = "opened"
                        time.sleep(2)
                        trigger_camera()

                    if altitude > Mission_download_alt and not mission_downloaded and retries < 3:
                        connection.commands.download()
                        connection.commands.wait_ready()

                        for index, cmd in enumerate(connection.commands):
                            if cmd.command == 206:  # MAV_CMD_DO_DIGICAM_CONTROL (or similar camera trigger command)
                                last_206_wp = index + 1  # Index is 0-based, waypoints are typically 1-based
                        if last_206_wp is not None:
                            print(f"Last waypoint with command 206: {last_206_wp-1}")
                            send_to_pixhawk(f"last camera waypoint is {last_206_wp-1}",4)
                            mission_downloaded = True
                            retries = 3
                        else:
                            print("No waypoint with command 206 found.")
                            retries += 1             

                    if last_206_wp:
                        if current_waypoint > last_206_wp and logging_stopped == False:
                            start_or_stop_logging("stop")
                            print("Logging Stopped")
                            logging_stopped = True

                if armed != last_armed:
                    print("Hellooooooo")
                    if armed:
                        print("Drone armed. Closing shutter and starting logging...")
                        set_servo("close")                                   
                        shutter_state = "closed"
                        if logging_stopped:                             
                            start_or_stop_logging("start")
                            logging_stopped = False
                            print("Logging Started")
                    else:
                        print("Drone disarmed. Opening shutter and stopping logging...")
                        if logging_stopped == False:
                            start_or_stop_logging("stop")
                            print("Logging Stopped")
                            logging_stopped = True
                        print("Camera Shutter Opened")
                        shutter_state = "opened"
                        time.sleep(5)
                        set_servo("open")
                    last_armed = armed
            time.sleep(0.1)

        except Exception as e:
            # Log the exception and continue the loop
            print(f"Error in monitor_drone: {type(e).__name__}: {e}")
            time.sleep(1)  # Prevent tight loops in case of repeated errors

def main():
    global Payload_connection,connection
    ip_addresses = ["192.168.144.20","192.168.2.15"]
    print("Checking connectivity to required IPs...")
    wait_for_conditions(ip_addresses, post_url)

    Payload_connection = establish_Payload_connection()

    listener_thread = threading.Thread(target=listen_for_commands, daemon=True)
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    websocket_thread = threading.Thread(target=start_websocket, daemon=True)
    drone_monitor_thread = threading.Thread(target=monitor_drone, daemon=True)
    payload_listener_thread = threading.Thread(target=listen_to_arduino, daemon=True)

    drone_monitor_thread.start()
    time.sleep(3)
    listener_thread.start()
    flask_thread.start()
    websocket_thread.start()
    payload_listener_thread.start()
    time.sleep(3)

    print("Main thread is now running")

    while True:
        time.sleep(10)


if __name__ == "__main__":
    main()
