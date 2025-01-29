import serial
import threading
import time
import os
import subprocess
import dronekit
import simplekml
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
import RPi.GPIO as GPIO
import shutil
from flask import Flask, send_file
import socket

# Serial Ports
UBX_PORT = "/dev/ttyACM2"
UBX_BAUD = 115200
PIXHAWK_PORT = "/dev/ttyACM0"
PIXHAWK_BAUD = 921600
vehicle = None

# Global Variables
is_armed = False
log_thread = None
current_ubx_file = None

SERVO_PIN = 18
PWM_FREQUENCY = 50  # 50Hz PWM frequency


Mission_download_alt = 8
Shutter_alt = 4

serial_number = 1
image_taken_at = None

generated_image_path = None

destination_dir = "/home/vinlee/Desktop/Emlid_log_files"

Payload_Serial_Port = '/dev/ttyAMA0'
Payload_Baud_Rate = 115200
Payload_connection = None

# Initialize GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
pwm = GPIO.PWM(SERVO_PIN, PWM_FREQUENCY)
pwm.start(0)

if not os.path.exists(destination_dir):
    os.makedirs(destination_dir)

android_ip = "192.168.144.100"
android_port = 14552
listener_port = 14553
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

app = Flask(__name__)
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

def start_flask_server():
    # Retry mechanism to handle hardware disconnection
    while True:
        try:
            app.run(host="192.168.144.20", port=5000, debug=False)
        except Exception as e:
            print(f"Flask server encountered an error: {e}")
            print("Retrying to start Flask server...")

def set_servo(position):
    #set_servo("open")
    #set_servo("close")
    shutter_open = 2550  # Max PWM value in microseconds
    shutter_close = 700  # Min PWM value in microseconds
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

def pendrive__check_and_copy_path():
    # Define the mount point
    mount_point = "/media/vinlee"

    # Check if the mount point exists
    if os.path.exists(mount_point):
        # Get a list of directories in the mount point
        directories = [os.path.join(mount_point, d) for d in os.listdir(mount_point) if os.path.isdir(os.path.join(mount_point, d))]
        if directories:
            for directory in directories:
                emlid_logs_path = os.path.join(directory, "Emlid_Logs")
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

def copy_to_pendrive(log_start_time):
    pendrive_path = pendrive__check_and_copy_path()
    date_folder = os.path.join(destination_dir, log_start_time.strftime("%d-%m-%Y"))
    time_folder = os.path.join(date_folder, log_start_time.strftime("%I-%M-%S %p"))

    if not os.path.exists(time_folder):
        print(f"Source folder does not exist: {time_folder}")
        send_to_pixhawk("Source folder does not exist",3)
        return

    if not pendrive_path:
        print("Pendrive path not detected. Aborting copy process.")
        send_to_pixhawk("Pendrive not attached",3)
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
        send_to_pixhawk("Log saved to Pendrive",5)
    except Exception as e:
        print(f"Error copying files to pendrive: {e}")
        send_to_pixhawk("Error saving to Pendrive",3)

def listen_to_arduino():
    global Payload_connection, destination_dir, vehicle, serial_number, current_ubx_file,image_taken_at
    try:
        while True:
            if Payload_connection and Payload_connection.in_waiting > 0:
                data = Payload_connection.readline().decode('utf-8').strip()
                if data.startswith("Timestamp:"):
                    print(data)
                    # Immediately fetch the heading from Pixhawk
                    heading = None
                    if vehicle is not None:
                        try:
                            heading = vehicle.heading
                        except Exception as e:
                            print(f"Error fetching heading from Pixhawk: {e}")
                    
                    if image_taken_at:
                        print("image Captured")
                        send_to_pixhawk("Image Captured",5)
                        image_taken_at = None

                    if current_ubx_file:
                        # Decode the Arduino message
                        decoded_values = decode_arduino_message(data)
                        if decoded_values:
                            timestamp = decoded_values.get("Timestamp")
                            yaw = decoded_values.get("Yaw")
                            roll = decoded_values.get("Roll")
                            pitch = decoded_values.get("Pitch")
                            
                            # Prepare the file for writing
                            RV_file_path = current_ubx_file.replace(".UBX", "_Rotational_values.txt")

                            # Create file with header if it doesn't exist
                            if not os.path.exists(RV_file_path):
                                with open(RV_file_path, "w") as RV_file:
                                    RV_file.write("Serial Number,Timestamp,Pitch,Roll,Yaw,Heading\n")

                            # Write data to the file
                            with open(RV_file_path, "a") as RV_file:
                                if heading is not None:
                                    # Write with heading
                                    RV_file.write(f"{serial_number},{timestamp},{pitch},{roll},{yaw},{heading:.2f}\n")
                                    print(f"Serial: {serial_number}, Timestamp: {timestamp}, Yaw: {yaw}, Roll: {roll}, Pitch: {pitch}, Heading: {heading:.2f}")
                                    message = f"log_feedback,S: {serial_number}, T: {timestamp}, Y: {yaw}, R: {roll}, P: {pitch},H: {heading:.2f}"
                                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                                else:
                                    # Write without heading (original IMU values)
                                    RV_file.write(f"{serial_number},{timestamp},{pitch},{roll},{yaw}\n")
                                    print(f"Serial: {serial_number}, Timestamp: {timestamp}, Yaw: {yaw}, Roll: {roll}, Pitch: {pitch}")
                                    message = f"log_feedback,S: {serial_number}, T: {timestamp}, Y: {yaw}, R: {roll}, P: {pitch}"
                                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                                serial_number += 1  # Increment serial number
            time.sleep(0.05)  # Reduce CPU usage
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

def trigger_camera(vehicle, relay_num=0):
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
    global vehicle  # Ensure 'vehicle' is available globally

    try:
        # Check if the vehicle connection is valid
        if vehicle is None:
            return

        if not (0 <= severity <= 7):
            print("Invalid severity level. Must be between 0 (Emergency) and 7 (Debug).")
            return

        if len(message) > 50:
            print(f"Message is too long. Truncating to 50 characters: {message[:50]}")
            message = message[:50]

        msg = vehicle.message_factory.statustext_encode(
            severity,                # Severity level
            message.encode('utf-8')  # Message string (encoded in UTF-8)
        )
        vehicle.send_mavlink(msg)
        vehicle.flush()  # Ensure the message is sent immediately
        print(f"Message sent: '{message}' with severity {severity}")

    except Exception as e:
        print(f"Error while sending message: {e}")

def get_nmea_time():
    """Extracts UTC time from NMEA messages."""
    try:
        ser = serial.Serial(UBX_PORT, UBX_BAUD, timeout=1)
        while True:  # Keep trying until a valid time is obtained
            line = ser.readline().decode('utf-8', errors='ignore')
            if line.startswith("$GNRMC") or line.startswith("$GPRMC"):
                parts = line.split(',')
                if len(parts) > 9 and parts[1] and parts[9]:
                    try:
                        utc_time = datetime.strptime(parts[1], "%H%M%S.%f")
                        utc_date = datetime.strptime(parts[9], "%d%m%y")
                        combined_time = datetime.combine(utc_date.date(), utc_time.time())
                        print(f"[INFO] Received UTC time from NMEA: {combined_time}")
                        return combined_time
                    except ValueError:
                        pass  # Ignore parsing errors and retry
    except Exception as e:
        print(f"[ERROR] NMEA Time Parsing: {e}")
    return None

def set_rpi_time(utc_time):
    """Sets the Raspberry Pi system time to UTC."""
    try:
        formatted_time = utc_time.strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["sudo", "date", "-s", f"{formatted_time} UTC"], check=True)
        print(f"[INFO] Raspberry Pi time set to {formatted_time} UTC")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to set system time: {e}")

def create_log_filename():
    """Creates UBX log filename in VUT_DDMMYYYY_HHMMSS format using RPi clock."""
    utc_now = datetime.utcnow()  # Get UTC from Raspberry Pi system clock
    ist_now = utc_now + timedelta(hours=5, minutes=30)  # Convert to IST for filename
    #ist_now = ist_now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = ist_now.strftime("%d-%m-%Y")
    time_str = ist_now.strftime("%I%M%S")

    file_name_loc = f"VUT_Rover_{ist_now.strftime('%d%m%Y')}_{time_str}.UBX"

    folder_path = f"{destination_dir}/{date_str}/{ist_now.strftime('%I-%M-%S %p')}"
    os.makedirs(folder_path, exist_ok=True)

    return os.path.join(folder_path, file_name_loc),ist_now

def log_ubx_data(log_filename):
    """Logs only UBX messages in a separate thread."""
    global is_armed
    try:
        ser = serial.Serial(UBX_PORT, UBX_BAUD, timeout=1)
        with open(log_filename, "wb") as file:
            print(f"[INFO] Logging UBX data to {log_filename}")
            buffer = bytearray()

            while is_armed:
                data = ser.read(1024)
                buffer.extend(data)

                while len(buffer) > 2:
                    if buffer[0] == 0xB5 and buffer[1] == 0x62:
                        if len(buffer) < 6:
                            break
                        payload_length = buffer[4] | (buffer[5] << 8)
                        ubx_msg_length = 6 + payload_length + 2

                        if len(buffer) < ubx_msg_length:
                            break

                        ubx_message = buffer[:ubx_msg_length]
                        file.write(ubx_message)
                        file.flush()

                        buffer = buffer[ubx_msg_length:]
                    else:
                        buffer.pop(0)
        print("[INFO] Logging stopped.")
    except Exception as e:
        print(f"[ERROR] UBX Logging: {e}")

def monitor_arming():
    """Monitors Pixhawk arming status and starts/stops UBX logging."""
    global is_armed, log_thread, current_ubx_file,vehicle,image_taken_at

    shutter_state = "opened"
    log_status = False
    mission_downloaded = False
    retries = 1
    last_206_wp = None

    try:
        vehicle = dronekit.connect(PIXHAWK_PORT, baud=PIXHAWK_BAUD, wait_ready=True,source_system=1,timeout=60)
        print("[INFO] Monitoring Pixhawk arming status...")
        send_to_pixhawk("System Ready" , 5)
        message = f"log_feedback,System Ready"
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))

        while True:
            altitude = max(int(vehicle.location.global_relative_frame.alt), 0)
            current_waypoint = vehicle.commands.next

            if vehicle.armed and not is_armed:
                is_armed = True
                current_ubx_file,log_start_time = create_log_filename()
                if current_ubx_file and not log_status:
                    log_thread = threading.Thread(target=log_ubx_data, args=(current_ubx_file,), daemon=True)
                    log_thread.start()
                    print("[INFO] UBX Logging Started")
                    send_to_pixhawk("Logging Started",4)
                    message = f"log_feedback,Logging started successfully"
                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                    log_status = True
                if shutter_state == "opened":
                    set_servo("close")
                    shutter_state == "closed"

            elif not vehicle.armed and is_armed:
                is_armed = False
                if log_status:
                    if log_thread and log_thread.is_alive():
                        log_thread.join()
                    print("[INFO] UBX Logging Stopped")
                    send_to_pixhawk("Logging Stopped",4)
                    message = f"log_feedback,Logging stopped successfully"
                    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                    log_status == False
                if shutter_state == "closed":
                    time.sleep(3)
                    set_servo("open")
                    shutter_state == "open"

                # Process UBX file with convbin & rnx2rtkp
                if current_ubx_file:
                    process_ubx_file(current_ubx_file,log_start_time)
            
                
            if is_armed:
                if altitude > Mission_download_alt and not mission_downloaded and retries < 3:
                    vehicle.commands.download()
                    vehicle.commands.wait_ready()

                    for index, cmd in enumerate(vehicle.commands):
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

                if last_206_wp and mission_downloaded:
                    if current_waypoint > last_206_wp and log_status == True:
                        if log_thread and log_thread.is_alive():
                            log_thread.join()
                            print("[INFO] UBX Logging Stopped")
                            send_to_pixhawk("Logging Stopped",4)
                            message = f"log_feedback,Logging stopped successfully"
                            udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
                            log_status == False
                        if current_ubx_file:
                            process_ubx_file(current_ubx_file,log_start_time)
                
                if altitude < Shutter_alt - 1 and shutter_state == "opened":
                    print("Camera Shutter Closed")
                    set_servo("close")
                    shutter_state = "closed"
                    time.sleep(1)
                elif altitude >= Shutter_alt + 1 and shutter_state == "closed":
                    print("Camera Shutter Opened")
                    set_servo("open")
                    shutter_state = "opened"
                    time.sleep(2)
                    image_taken_at = int(time.time())
                    trigger_camera(vehicle, relay_num=0)
                    time.sleep(2)
                    trigger_camera(vehicle, relay_num=0)
            
            time.sleep(0.5)

    except Exception as e:
        print(f"[ERROR] Arming Monitor: {e}")

def process_ubx_file(ubx_file,log_start_time):
    """Processes the UBX file with convbin and rnx2rtkp, then deletes temporary files."""
    base_name = os.path.splitext(ubx_file)[0]  # Remove .UBX extension
    output_24o = f"{base_name}.24O"
    output_24p = f"{base_name}.24P"
    output_pos = f"{base_name}.pos"

    try:
        # Convert UBX to RINEX
        subprocess.run(["convbin", ubx_file, "-r", "ubx", "-o", output_24o, "-n", output_24p], check=True)
        print(f"[INFO] Generated .24O file: {output_24o}")
        print(f"[INFO] Generated .24P file: {output_24p}")

        # Process RINEX files with rnx2rtkp
        subprocess.run(["rnx2rtkp", "-k", "/home/vinlee/rpi_emlid/emlid_rpi.conf", "-o", output_pos, output_24o, output_24p], check=True)
        print(f"[INFO] Generated .pos file: {output_pos}")

        # Delete temporary RINEX files
        os.remove(output_24o)
        os.remove(output_24p)
        print(f"[INFO] Deleted temporary RINEX files.")
        events_file_path = output_pos.replace('.pos', '_events.pos')
        process_events_pos(events_file_path,log_start_time,output_pos)

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Processing UBX file: {e}")

def find_last_percent_line(file_path):
    with open(file_path, "r") as file:
        lines = file.readlines()

    last_percent_line_number = None

    for i in range(len(lines) - 1, -1, -1):  # Iterate from the end to the beginning
        if lines[i].startswith('%'):
            last_percent_line_number = i + 1  # Convert to 1-based index
            break

    print(f"The last '%' line is at line number: {last_percent_line_number}")
    return last_percent_line_number-1

def calculate_time_difference(file_path):
    with open(file_path, "r") as file:
        lines = file.readlines()

    # Skip lines starting with '%'
    data_lines = [line.strip() for line in lines if not line.startswith('%') and line.strip()]

    # Check if there are no data lines
    if not data_lines:
        print("None")  # Return None if no data lines exist
        return None

    # Extract first and last timestamps
    first_line = data_lines[0].split()
    last_line = data_lines[-1].split()

    # Extract date and time (first two columns)
    first_timestamp = " ".join(first_line[:2])
    last_timestamp = " ".join(last_line[:2])

    # Convert to datetime format
    time_format = "%Y/%m/%d %H:%M:%S.%f"
    first_time = datetime.strptime(first_timestamp, time_format)
    last_time = datetime.strptime(last_timestamp, time_format)

    # Calculate time difference
    time_difference = last_time - first_time

    # Convert timedelta to HH:MM:SS format
    total_seconds = int(time_difference.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    formatted_time_difference = f"{hours:02}:{minutes:02}:{seconds:02}"

    print(f"First Data Timestamp: {first_time}")
    print(f"Last Data Timestamp: {last_time}")
    print(f"Time Difference (HH:MM:SS): {formatted_time_difference}")

    return formatted_time_difference

def process_events_pos(file_path,log_start_time,output_pos):
    """Processes _events.pos to generate CSV, PNG, and KML."""
    global generated_image_path
    
    base_filename = os.path.basename(file_path).replace('_events.pos', '')
    output_csv_path = os.path.join(os.path.dirname(file_path), f"{base_filename}.csv")
    output_image_path = os.path.join(os.path.dirname(file_path), f"{base_filename}.png")
    output_kml_path = os.path.join(os.path.dirname(file_path), f"{base_filename}.kml")

    header_line = find_last_percent_line(file_path)
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
        udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))
        return

    Log_recording_time = calculate_time_difference(output_pos)
    #log_start_time = str(timedelta(seconds=int(log_start_time)))
 
    latitudes = data["Latitude"]
    longitudes = data["Longitude"]

    # Save the cleaned data to a CSV
    locations_df = pd.DataFrame({"Latitude": latitudes, "Longitude": longitudes})
    locations_df.to_csv(output_csv_path, index=False)
    print(f"CSV saved to: {output_csv_path}")

    # Generate and save the scatter plot
    plt.figure(figsize=(14, 10), dpi=300)
    plt.scatter(longitudes, latitudes, s=4, color='red')
    plt.title(f"{base_filename} Position Plot", fontsize=20, weight='bold')
    plt.title(
    f"{base_filename} , IMAGE COUNT : {len(latitudes)}\n"
    f"Date: {log_start_time.strftime('%d-%m-%Y')}, "
    f"Time: {log_start_time.strftime('%I:%M:%S')}   "
    f"Recording Time: {Log_recording_time}",
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
    send_to_pixhawk("Log succesfully processed",5)
    copy_to_pendrive(log_start_time)
    generated_image_path = output_image_path
    message = f"log_feedback,Download the Image"
    udp_sock.sendto(message.encode('utf-8'), (android_ip, android_port))

if __name__ == "__main__":
    print("[INFO] Waiting for valid UTC time from NMEA...")

    # Step 1: Get time from NMEA and synchronize Raspberry Pi time
    while True:
        nmea_time = get_nmea_time()
        if nmea_time:
            print(nmea_time)
            set_rpi_time(nmea_time)
            time.sleep(2)
            utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            print("Current UTC Time:", utc_time)
            break
        time.sleep(1)  # Keep trying until we get valid time

    print("[INFO] Time synchronized. Starting program...")
    Payload_connection = establish_Payload_connection()
    payload_listener_thread = threading.Thread(target=listen_to_arduino, daemon=True)
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    flask_thread.start()
    payload_listener_thread.start()
    time.sleep(1)
    # Step 2: Start monitoring Pixhawk arming status
    monitor_arming()
