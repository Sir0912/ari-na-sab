import serial
import requests
import time

# Update COM port if needed
ser = serial.Serial('COM3', 9600, timeout=1)

print("="*50)
print("RFID Scanner Started")
print("Waiting for scans...")
print("="*50)

last_uid = None
last_scan_time = 0
SCAN_DELAY = 3  # seconds to prevent duplicate scans

while True:
    try:
        line = ser.readline().decode(errors='ignore').strip()

        if line.startswith("RFID Tag UID:"):
            uid = line.replace("RFID Tag UID:", "").strip()
            
            # Normalize UID
            uid = uid.replace(" ", "").upper()

            # Anti-duplicate scan
            current_time = time.time()
            if uid == last_uid and (current_time - last_scan_time) < SCAN_DELAY:
                continue
            last_uid = uid
            last_scan_time = current_time

            print("\n" + "="*50)
            print("SCAN DETECTED!")
            print(f"UID: {uid}")
            print(f"Time: {time.strftime('%Y-%m-%d %I:%M:%S %p')}")
            print("="*50)

            try:
                response = requests.post(
                    "http://127.0.0.1:5000/scan",
                    json={"uid": uid},
                    timeout=3
                )
                print("Server Response:", response.json())
            except requests.exceptions.RequestException as err:
                print("Server not reachable:", err)

            print("-"*50)

    except Exception as e:
        print("Error:", e)
        time.sleep(1)