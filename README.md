
---

# mqtt-simulations

Synthetic MQTT traffic for UrbanOS, used to stress the subscriber, the geodata pipeline, and the routing loop.
This repo lets you spin up hundreds of virtual clients that publish movement points on the UrbanOS topic format.

**UrbanOS PoC**, [https://github.com/pablo-chacon/UrbanOS-POC](https://github.com/pablo-chacon/UrbanOS-POC)

**Client templates**, [https://github.com/pablo-chacon/mqtt-client-templates](https://github.com/pablo-chacon/mqtt-client-templates)

## What this is

1. A streaming simulation that publishes realistic movement one point at a time.
2. A bulk simulation that pushes points quickly for load tests.
3. Both publish to `client/{client_id}/session/{session_id}/` with QoS 1 and clean session disabled.

### Proven scale in pre release tests

1. Recommended minimum clients 100 to generate enough data.
2. Streaming test 250 clients in 5 minutes.
3. Bulk test 100 clients in 3 minutes.

## Requirements

1. A reachable MQTT broker.
2. Python 3.11 or Python 3.12.
3. Packages, `paho-mqtt` and `locust`.

Install:

```bash
python -m pip install --upgrade pip
pip install paho-mqtt locust
```

## Environment

The simulations read these variables, defaults are safe for local runs.

```bash
export MQTT_BROKER=localhost
export MQTT_PORT=1883
export MQTT_TOPIC_TEMPLATE="client/{client_id}/session/{session_id}/"
export SESSION_HOURS=26
export POINT_INTERVAL_MIN=2        # minutes between synthetic points along a leg
export SEND_INTERVAL_SECONDS=1.5   # wall clock send interval
```

If your broker uses TLS, set the port to 8883 and configure the broker as usual.

## Run the streaming simulation

This publishes one point per send, with realistic speeds and simple POI hops around Stockholm.

```bash
locust -f iot_stream_simulatior.py \
  --headless --users 250 --spawn-rate 50 -t 5m
```

Tune users, spawn rate, and duration for your target.

## Run the bulk simulation

This uses the same generator and timing knobs, it is meant for quick pressure tests.

```bash
locust -f locust_simulation.py \
  --headless --users 100 --spawn-rate 100 -t 3m
```

## Data contract used by the simulations

### Topic

```
client/{client_id}/session/{session_id}/
```

### Payload

The simulations send a compact envelope with one point per message, the subscriber can flatten this into `geodata`.

```json
{
  "client_id": "usr12-1b2c3d4e-...",
  "session_id": 4321,
  "start_time": "2025-08-23T12:00:00Z",
  "end_time": "2025-08-24T14:00:00Z",
  "trajectory": [
    {
      "lat": 59.3293,
      "lon": 18.0686,
      "elevation": 12.3,
      "speed": 1.8,
      "activity": "walking",
      "timestamp": "2025-08-23T12:02:00Z"
    }
  ]
}
```

Notes, QoS is 1, retain is false, client ids are synthetic and session ids are numeric for simplicity, activities include walking, cycling, driving, and public transport, each client moves between four stable POIs and advances time along each leg.

## Endpoint R-T-D examples
1. GET /api/astar_routes
2. GET /api/mapf_routes
3. GET /api/view_eta_accuracy_seconds
4. GET /api/view_routes_astar_mapf_latest   

## Adjusting realism

1. `POINT_INTERVAL_MIN` controls density along a leg.
2. `SEND_INTERVAL_SECONDS` controls how fast messages leave the client.
3. `SESSION_HOURS` controls the window for timestamps, useful when you want data that looks like a finished day.

## Load and capacity modeling

The simulations publish one message every 1.5 seconds per simulated client, this is the send cadence `S = 1.5 s`.

### Instantaneous throughput

This is the live pressure on the broker and the subscriber.

* Streaming test, 250 clients for 5 minutes, about **166.7 messages per second**, total **50,000 messages**.
* Bulk test, 100 clients for 3 minutes, about **66.7 messages per second**, total **12,000 messages**.

Throughput equivalence to real fleets, a real fleet where each device samples every `T_real` seconds creates the same live load as:

```
N_real = N_sim × (T_real / S)
```

| Real sampling T\_real | 250 streaming clients | 100 bulk clients |
| --------------------- | --------------------: | ---------------: |
| 1 s                   |                 166.7 |             66.7 |
| 5 s                   |                 833.3 |            333.3 |
| 10 s                  |               1,666.7 |            666.7 |
| 30 s                  |                 5,000 |            2,000 |
| 60 s                  |                10,000 |            4,000 |

Interpretation, 250 simulated clients at 1.5 seconds represent the same live load as 5,000 real clients at 30 seconds.

### Storage and window equivalence

This is the number of rows written over a time window, useful for migrations and retention.

Messages per real client over a window of `H` hours with sampling `T_real`:

```
messages_per_client = H × 3600 / T_real
```

Total messages produced by a simulation run:

```
messages_sim = N_sim × (t / S)
```

Equivalent number of real clients over a given window:

```
N_real_over_window = messages_sim / (H × 3600 / T_real)
```

Against the 26 hour UrbanOS session window,

* 250 clients for 5 minutes produce 50,000 messages.
* 100 clients for 3 minutes produce 12,000 messages.

| Real sampling T\_real | 250 clients, 5 min → real clients over 26 h | 100 clients, 3 min → real clients over 26 h |
| --------------------- | ------------------------------------------: | ------------------------------------------: |
| 1 s                   |                                        0.53 |                                        0.13 |
| 5 s                   |                                        2.67 |                                        0.64 |
| 10 s                  |                                        5.34 |                                        1.28 |
| 30 s                  |                                       16.03 |                                        3.85 |
| 60 s                  |                                       32.05 |                                        7.69 |

Interpretation, the 250 client, 5 minute run writes as many points as about 16 real clients would write over 26 hours at 30 seconds sampling.

Against a 30 day window, use `H = 720`.

| Real sampling T\_real | 250 clients, 5 min → real clients over 30 days | 100 clients, 3 min → real clients over 30 days |
| --------------------- | ---------------------------------------------: | ---------------------------------------------: |
| 10 s                  |                                           0.19 |                                           0.05 |
| 30 s                  |                                           0.58 |                                           0.14 |
| 60 s                  |                                           1.16 |                                           0.28 |

Short tests are excellent for throughput checks, they do not represent month scale storage unless you extend duration.

### One line recipe

If you want the simulation to emulate a fleet of `N_real` devices at sampling `T_real` over `H` hours, choose `N_sim` and runtime `t` such that:

```
N_sim × (t / S) ≈ N_real × (H × 3600 / T_real)
```

Example, to match 10,000 real clients at 30 seconds over 26 hours with `S = 1.5`,

* Messages to match, `10,000 × (26 × 3600 / 30) = 31,200,000`.
* With `N_sim = 1,000`, runtime `t ≈ 31,200,000 × 1.5 / 1,000 = 46,800 seconds`, about 13 hours.

## Troubleshooting

1. If you see no ingestion, verify broker host and port, then publish a test message with `mosquitto_pub`.
2. If Locust exits early, lower spawn rate or increase `SEND_INTERVAL_SECONDS`.
3. If you use TLS, verify broker certificates and client trust, then test with a single client before scaling up.

## Repository layout

```
.
├── iot_stream_simulatior.py   # streaming user class for Locust
├── locust_simulation.py       # bulk user class for Locust
└── README.md
```

## Disclaimer

This repository generates synthetic movement, it does not include personal data, it is provided “as is” and “as available”, you use it at your own risk, the authors are not liable for any claim or damage.

## Links

UrbanOS PoC, [https://github.com/pablo-chacon/UrbanOS-POC](https://github.com/pablo-chacon/UrbanOS-POC)

Client templates, [https://github.com/pablo-chacon/mqtt-client-templates](https://github.com/pablo-chacon/mqtt-client-templates)

Sovereign, Self-Healing AI, [https://github.com/pablo-chacon/Sovereign-Self-Healing-AI](https://github.com/pablo-chacon/Sovereign-Self-Healing-AI)

---

