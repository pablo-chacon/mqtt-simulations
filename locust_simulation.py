import locust
import json
import time
import paho.mqtt.client as mqtt
import os
import random
import uuid
from datetime import datetime, timedelta

# 🔧 MQTT settings
BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", 1883))
TOPIC_TEMPLATE = "client/{client_id}/session/{session_id}/"

# 🧠 Simulated constants
TRANSIT_ACTIVITIES = ["walking", "cycling", "driving", "public_transport"]
LAT_RANGE = (59.0, 60.0)
LON_RANGE = (17.0, 19.0)


def generate_client_id():
    return f"usr{random.randint(1, 53)}-{uuid.uuid4()}"


def generate_session_id():
    return random.randint(1000, 9999)


def generate_realistic_speed(activity):
    if activity == "walking":
        return round(random.uniform(1, 5), 2)
    elif activity == "cycling":
        return round(random.uniform(8, 25), 2)
    elif activity == "driving":
        return round(random.uniform(30, 120), 2)
    elif activity == "public_transport":
        return round(random.uniform(20, 80), 2)
    return 1.0


def generate_pois_for_client(client_id, seed_offset=0):
    """
    Generate fixed POIs per client. Seeding ensures repeatability.
    """
    random.seed(f"{client_id}_{seed_offset}")
    base_lat = 59.3 + random.uniform(-0.05, 0.05)
    base_lon = 18.0 + random.uniform(-0.05, 0.05)
    return [
        (base_lat, base_lon),                      # Home
        (base_lat + 0.01, base_lon + 0.02),        # Work
        (base_lat + 0.02, base_lon - 0.01),        # Gym
        (base_lat - 0.01, base_lon + 0.03)         # Errands
    ]


def generate_transit_points(start, end, duration_minutes, start_time):
    """
    Generates movement between locations with realistic timestamps and speeds.
    """
    points = []
    activity = random.choice(TRANSIT_ACTIVITIES)

    # Increase time between points to allow POI detection (e.g., 15 min per point)
    interval = 15  # minutes between points
    steps = max(int(duration_minutes / interval), 1)

    lat_step = (end[0] - start[0]) / steps
    lon_step = (end[1] - start[1]) / steps

    current_time = start_time
    lat, lon = start

    for _ in range(steps):
        points.append({
            "lat": lat,
            "lon": lon,
            "elevation": round(random.uniform(0, 50), 2),
            "speed": generate_realistic_speed(activity),
            "activity": activity,
            "timestamp": current_time.isoformat(),
        })
        lat += lat_step
        lon += lon_step
        current_time += timedelta(minutes=interval)

    return points



def generate_client_trajectory(client_id, session_start):
    pois = generate_pois_for_client(client_id)
    schedule = [480, 580, 120, 60]  # Minutes spent at home, work, gym, errands
    trajectory = []
    time = session_start

    for i in range(len(pois)):
        start = pois[i]
        end = pois[(i + 1) % len(pois)]
        commute_time = random.randint(10, 75)
        trajectory += generate_transit_points(start, end, commute_time, time)
        time += timedelta(minutes=commute_time + schedule[i])

    return trajectory


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✅ Client {userdata['client_id']} connected successfully to MQTT broker")
    else:
        print(f"❌ Connection failed for client {userdata['client_id']}, return code {rc}")


def reconnect_client(client):
    if not client.is_connected():
        print("🔄 Reconnecting to MQTT broker...")
        try:
            client.reconnect()
            time.sleep(2)
        except Exception as e:
            print(f"❌ Reconnection failed: {e}")


class MqttUser(locust.User):
    wait_time = locust.between(1, 3)

    def on_start(self):
        self.client_id = generate_client_id()
        self.session_id = generate_session_id()

        # 🕒 Generate session timing
        session_start = datetime.utcnow() - timedelta(hours=26)
        session_end = datetime.utcnow()

        # 🚶‍♂️ Generate realistic daily route
        self.trajectory_data = generate_client_trajectory(self.client_id, session_start)
        self.start_time = session_start.isoformat()
        self.end_time = session_end.isoformat()

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, clean_session=False)
        self.mqtt_client.user_data_set({"client_id": self.client_id})
        self.mqtt_client.on_connect = on_connect

        try:
            self.mqtt_client.connect(BROKER, PORT, keepalive=300)
            self.mqtt_client.loop_start()
            print(f"✅ Client {self.client_id} initiated MQTT connection.")
        except Exception as e:
            print(f"❌ Failed to connect MQTT client {self.client_id}: {e}")

    @locust.task
    def send_trajectory(self):
        if not self.mqtt_client.is_connected():
            reconnect_client(self.mqtt_client)

        if self.mqtt_client.is_connected():
            topic = TOPIC_TEMPLATE.format(client_id=self.client_id, session_id=self.session_id)

            payload = {
                "client_id": self.client_id,
                "session_id": self.session_id,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "trajectory": self.trajectory_data
            }

            result = self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
            result.wait_for_publish()

            if not result.is_published():
                print(f"❌ Failed to publish payload for {self.client_id}")
            else:
                print(f"📤 Published payload to topic {topic}")

    def on_stop(self):
        try:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            print(f"🔌 Client {self.client_id} disconnected.")
        except Exception as e:
            print(f"❌ Failed to disconnect MQTT client {self.client_id}: {e}")
